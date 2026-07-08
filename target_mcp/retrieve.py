"""Retrieval layer: fetch main text (JATS) and supplements for a PMC article.

v1 covers the open-access PMC tier via Europe PMC:
  - main text as JATS XML  -> clean sectioned plain text
  - supplements via the supplementaryFiles endpoint (returned as a ZIP)

Honest about coverage: if no PMC-hosted supplement is found we report
supplement_status="not_retrieved" (a supplement may still exist on the
publisher site), never "none_exists". Only a human assertion yields none_exists.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import httpx

from .ingest import (
    SectionMap,
    build_bundle,
    extract_file,
    parse_text,
)

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_TIMEOUT = 60.0
_SUPPL_EXT_ORDER = {".pdf": 0, ".docx": 1, ".doc": 2, ".xlsx": 3, ".txt": 4}


def normalize_pmcid(pmcid: str) -> str:
    s = str(pmcid).strip().upper()
    if s.startswith("PMC"):
        return s
    if s.isdigit():
        return f"PMC{s}"
    raise ValueError(f"Not a PMCID: {pmcid!r}")


def jats_to_text(xml_bytes: bytes) -> str:
    """Render JATS XML to sectioned plain text (title, abstract, body sections)."""
    root = ET.fromstring(xml_bytes)

    def strip(el: ET.Element) -> str:
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip()

    out: list[str] = []
    title = root.find(".//article-meta//article-title")
    if title is not None:
        out += [strip(title), ""]
    abstract = root.find(".//article-meta//abstract")
    if abstract is not None:
        out += ["Abstract", strip(abstract), ""]

    def walk(sec: ET.Element) -> None:
        t = sec.find("title")
        if t is not None:
            out.append(strip(t))
        for child in sec:
            if child.tag == "sec":
                walk(child)
            elif child.tag in ("p", "list"):
                out.append(strip(child))
        out.append("")

    body = root.find(".//body")
    if body is not None:
        for sec in body.findall("sec"):
            walk(sec)
    return "\n".join(out)


def fetch_jats(pmcid: str, client: httpx.Client | None = None) -> str | None:
    pmcid = normalize_pmcid(pmcid)
    owns = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        r = client.get(f"{EPMC}/{pmcid}/fullTextXML")
        if r.status_code != 200 or b"<body" not in r.content:
            return None
        return jats_to_text(r.content)
    finally:
        if owns:
            client.close()


def fetch_supplements(pmcid: str, client: httpx.Client | None = None) -> list[tuple[str, bytes]]:
    """Return [(filename, raw_bytes)] from the Europe PMC supplementaryFiles ZIP.
    Empty list if none are hosted (which does NOT prove none exist)."""
    pmcid = normalize_pmcid(pmcid)
    owns = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        r = client.get(f"{EPMC}/{pmcid}/supplementaryFiles")
        if r.status_code != 200 or not r.content:
            return []
        try:
            zf = zipfile.ZipFile(io.BytesIO(r.content))
        except zipfile.BadZipFile:
            return []
        files: list[tuple[str, bytes]] = []
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            files.append((name, zf.read(name)))
        # deterministic order, preferred file types first
        files.sort(key=lambda kv: (_SUPPL_EXT_ORDER.get(
            "." + kv[0].rsplit(".", 1)[-1].lower(), 9), kv[0]))
        return files
    finally:
        if owns:
            client.close()


def _bytes_to_text(filename: str, data: bytes) -> tuple[str, int | None]:
    """Extract text from an in-memory supplement file by writing through
    ingest.extract_file semantics without touching disk where possible."""
    import tempfile
    from pathlib import Path

    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in (".txt", ".csv", ".tsv", ".xml", ".html", ".htm"):
        return data.decode("utf-8", errors="replace"), None
    # pypdf / python-docx need a filesystem path
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return extract_file(Path(tmp.name))


def retrieve_bundle(
    pmcid: str,
    include_supplements: bool = True,
    supplement_types: tuple[str, ...] = (".pdf", ".docx", ".doc", ".txt", ".xml", ".htm", ".html"),
) -> SectionMap:
    """Fetch main text + supplements for a PMCID and return a merged SectionMap.

    Raises if the main text cannot be retrieved (no point assessing without it).
    """
    pmcid = normalize_pmcid(pmcid)
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        main_text = fetch_jats(pmcid, client=client)
        if not main_text:
            raise RuntimeError(
                f"No JATS full text available for {pmcid} from Europe PMC "
                "(article may not be open access). Supply the document directly."
            )
        main = parse_text(main_text, source=f"europepmc:{pmcid}", manuscript_id=pmcid)

        if not include_supplements:
            main.supplement_status = "not_checked"
            return main

        raw = fetch_supplements(pmcid, client=client)

    supplements: list[tuple[str, str, int | None]] = []
    skipped: list[str] = []
    for filename, data in raw:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in supplement_types:
            skipped.append(filename)
            continue
        try:
            text, n_pages = _bytes_to_text(filename, data)
        except Exception as e:  # noqa: BLE001 - one bad file shouldn't sink the bundle
            skipped.append(f"{filename} (extract failed: {e})")
            continue
        if text.strip():
            supplements.append((filename, text, n_pages))

    if supplements:
        status = "retrieved"
    else:
        # No PMC-hosted supplement obtained; cannot confirm none exists.
        status = "not_retrieved"
    bundle = build_bundle(main, supplements, supplement_status=status)
    if skipped:
        bundle.warnings.append(f"Supplement files skipped: {skipped}")
    return bundle
