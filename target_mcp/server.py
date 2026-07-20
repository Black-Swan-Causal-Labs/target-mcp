"""MCP composition layer: the TARGET tool surface.

Eleven tools. The interactive review flow is parse_manuscript ->
assess_manuscript (scaffold, default) -> submit_scaffold_verdicts, which returns
the finished, provenance-stamped deliverable inline (HTML by default; opt into
markdown/docx via report_formats) in its `report` — that stamped render is the
artifact of record. render_checklist / render_checklist_docx /
render_checklist_html re-render the same stamped artifact on demand (different
view, logo, format). Parsed manuscripts are cached
in-process by text hash so downstream calls can reference a prior parse by hash
instead of re-supplying the document.

Tools take structured inputs (arrays/objects) and declare structured output
schemas. Output TypedDicts are `total=False` so they document the result shape
without forcing every optional field to be present on every return path.
"""

from __future__ import annotations

from typing import Any, TypedDict

from mcp.server.fastmcp import FastMCP

from . import assess as _assess
from . import corpus as _corpus
from . import render as _render
from . import render_docx as _render_docx
from . import render_html as _render_html
from . import retrieve as _retrieve
from . import validate as _validate
from .ingest import (
    SUPPLEMENT_STATES,
    SectionMap,
    build_bundle,
    extract_file,
    parse_document,
    parse_text,
)
from .spec import DEFAULT_VERSION, available_versions, load_spec

mcp = FastMCP(
    "target-checklist",
    instructions=(
        "Operationalized TARGET reporting guideline (Cashin et al., JAMA/BMJ "
        "2025) for reviewing whether an observational target-trial-emulation "
        "study reports what the checklist requires. Primary flow to review a "
        "publication: parse_manuscript (pass the manuscript TEXT, or a PMCID via "
        "parse_pmcid; file paths must be readable on THIS server's host, not the "
        "agent's) -> assess_manuscript (mode='scaffold' default: it returns "
        "the assessment prompt for YOU to run) -> submit_scaffold_verdicts (to "
        "validate your verdicts; it returns the finished, provenance-STAMPED "
        "deliverable inline in `report` — HTML by default; other formats via "
        "report_formats or the render tools. That stamped "
        "render is the ARTIFACT OF RECORD: present it as the completed checklist. "
        "Do NOT hand-build your own checklist document — it lacks the stamp and "
        "cannot be verified. render_checklist / render_checklist_docx / "
        "render_checklist_html re-render the same stamped artifact on demand.) "
        "Supplements matter: TTE methods (estimand, "
        "identifying assumptions) often live in supplementary material, so pass "
        "the supplement to parse_manuscript when you have it, or those leaves "
        "read not_reported when they were merely in an un-ingested appendix. "
        "get_checklist introspects the encoded spec but is OPTIONAL in the review "
        "flow — assess_manuscript already embeds the rubric, so don't fetch both. "
        "render_checklist_docx returns the .docx bytes as base64 for retrieval "
        "(its server-side file path is not the caller's filesystem). (parse_pmcid "
        "and "
        "assess_manuscript mode='judge' exist for headless corpus/batch runs, "
        "not the interactive review case.)"
    ),
)

_parsed: dict[str, SectionMap] = {}          # text_sha256 -> SectionMap
_assessments: dict[str, dict[str, Any]] = {} # manuscript_id -> latest assessment


# --- Output schemas (total=False: document the shape, tolerate optional keys) ---

class ChecklistDoc(TypedDict, total=False):
    spec_version: str
    available_versions: list
    guideline_scope: str
    e_e_status: str
    verdict_vocabulary: list
    evidence_policy: str
    leaf_count: int
    items: list


class SectionMapSummary(TypedDict, total=False):
    source: str
    manuscript_id: str
    extractor_version: str
    text_sha256: str
    full_text: str
    sections: list
    n_pages: int | None
    protocol_table_detected: bool
    flow_diagram_detected: bool
    warnings: list
    supplement_status: str
    documents: list


class AssessmentResult(TypedDict, total=False):
    manuscript_id: str
    spec_version: str
    mode: str
    model: str
    temperature: float | None
    prompt_hash: str
    prompt_template_version: str
    extractor_version: str
    text_sha256: str
    assessed_at: str
    full_text_available: bool
    excluded_leaves: list
    supplement_status: str
    documents: list
    items: list
    section_rollups: dict
    unresolved_evidence_leaves: list
    # usage is present only in judge mode. total=False makes every field emit a
    # `default: null` in the generated schema; for a plain `dict` that null is
    # invalid against `type: object`, so a validator that fills defaults crashes
    # scaffold returns (which omit usage) with "None is not of type 'object'".
    # Typing it dict | None makes the null-default valid. See DECISIONS 2026-07-20.
    usage: dict | None
    # The finished, stamped deliverable rendered inline so the canonical artifact
    # falls out of validation — no separate render step to forget or skip.
    report: dict | None


class ChecklistReport(TypedDict, total=False):
    manuscript_id: str
    spec_version: str
    view: str
    generated_from: dict
    supplement_status: str
    provenance: dict
    completeness: dict
    rows: list
    markdown: str
    html: str
    attribution: dict


class ChecklistHtml(TypedDict, total=False):
    manuscript_id: str
    view: str
    html: str
    content_base64: str
    content_type: str
    filename: str
    provenance: dict


class ChecklistDocx(TypedDict, total=False):
    path: str
    view: str
    n_rows: int
    bytes: int
    logo_applied: bool
    content_base64: str
    content_type: str
    filename: str


class CorpusSummary(TypedDict, total=False):
    spec_version: str
    n_papers: int
    coverage: dict
    per_leaf: list
    lowest_reported_leaves: list
    note: str


class ValidationResult(TypedDict, total=False):
    spec_version: str
    papers_compared: list
    n_papers: int
    leaves_with_data: int
    per_leaf: list
    pooled_binary_reported: dict | None
    pooled_raw_agreement: float | None
    disagreements: list
    n_disagreements: int


@mcp.tool()
def get_checklist(version: str = DEFAULT_VERSION) -> ChecklistDoc:
    """Return the encoded TARGET checklist spec: 39 scoreable leaf subitems
    (grouped into the 21 published items) with intent, assessor notes,
    signal terms, pairing links, and applicability rules. Pass a version id to
    pin; omit for the current default.

    OPTIONAL in the review flow — introspection only. assess_manuscript already
    embeds the full per-leaf rubric (intents + verdict boundaries) in the prompt
    it returns, so calling both get_checklist and assess_manuscript for the same
    review duplicates the rubric payload. Use this when you want to inspect the
    spec on its own, not as a required step before assessing."""
    spec = load_spec(version)
    return {
        "spec_version": spec["spec_version"],
        "available_versions": available_versions(),
        "guideline_scope": spec["guideline_scope"],
        "e_e_status": spec["e_e_status"],
        "verdict_vocabulary": spec["verdict_vocabulary"],
        "evidence_policy": spec["evidence_policy"],
        "leaf_count": len(spec["items"]),
        "items": spec["items"],
    }


def _summarize(sm: SectionMap) -> dict[str, Any]:
    out = sm.to_dict(include_text=False)
    out["sections"] = [
        {"name": s.name, "heading": s.heading, "source": s.source,
         "start": s.start, "end": s.end, "chars": s.end - s.start}
        for s in sm.sections
    ]
    return out


@mcp.tool()
def parse_manuscript(
    document: str,
    manuscript_id: str = "",
    supplements: list[str] | None = None,
    supplement_status: str = "",
) -> SectionMapSummary:
    """PRIMARY entry point: parse a manuscript into a SectionMap with
    character-offset, source-tagged section spans.

    `document` is EITHER the raw manuscript text OR a file path — but the path
    must be readable on the SERVER host. If you are an agent whose uploaded files
    live on your own filesystem (a mounted upload dir, a sandbox), the server
    cannot see them: paste the manuscript TEXT instead, or use parse_pmcid for an
    open-access PMCID. Reach for a file path only when the file is on the same
    host as this server (server-local/batch use). A path-looking string that the
    server can't find raises rather than being silently ingested as its own text.

    `supplements` is a list of server-readable file paths (PDF/docx/text) to
    merge as supplementary material — PASS IT WHEN YOU HAVE IT: TTE methods
    (estimand, identifying assumptions) frequently live in a supplementary
    protocol table, and without a supplement the verdicts on those leaves come
    back not_reported when the content was merely in an un-ingested appendix.
    When supplements are provided, supplement_status defaults to 'user_provided'.
    Pass supplement_status='none_exists' to assert the article has no supplement.
    Returns source-tagged section boundaries, protocol-table and flow-diagram
    detection over the combined text, supplement_status, and the text hash used
    to key later calls."""
    main = parse_document(document, manuscript_id or None)
    if supplements:
        docs = []
        for path in supplements:
            text, n_pages = extract_file(path)
            docs.append((_path_name(path), text, n_pages))
        status = supplement_status or "user_provided"
        sm = build_bundle(main, docs, supplement_status=status)
    else:
        if supplement_status:
            if supplement_status not in SUPPLEMENT_STATES:
                raise ValueError(f"Unknown supplement_status {supplement_status!r}")
            main.supplement_status = supplement_status
        sm = main
    _parsed[sm.text_sha256] = sm
    return _summarize(sm)


@mcp.tool()
def parse_pmcid(pmcid: str, include_supplements: bool = True) -> SectionMapSummary:
    """CONVENIENCE / BATCH entry point: retrieve an open-access article from
    Europe PMC by PMCID and parse it. Reach for this in the corpus/batch case
    (no file in hand) or to auto-fetch an open-access paper's supplement; for a
    single manuscript you were given, use parse_manuscript instead. Fetches JATS
    main text plus (if available) PMC-hosted supplementary files, merged into
    one source-tagged SectionMap. supplement_status is 'retrieved' when a
    supplement was obtained, else 'not_retrieved' (a supplement may still exist
    on the publisher site; absence of retrieval is not proof of absence).
    Raises if no open-access full text is available. Returns the same summary
    as parse_manuscript, including the text hash for assess_manuscript."""
    sm = _retrieve.retrieve_bundle(pmcid, include_supplements=include_supplements)
    _parsed[sm.text_sha256] = sm
    return _summarize(sm)


def _path_name(path: str) -> str:
    from pathlib import Path
    return Path(path).name


def _resolve_section_map(document: str, manuscript_id: str) -> SectionMap:
    if document in _parsed:  # caller passed a text_sha256 from parse_manuscript
        return _parsed[document]
    sm = parse_document(document, manuscript_id or None)
    return _parsed.setdefault(sm.text_sha256, sm)


@mcp.tool()
def assess_manuscript(
    document: str,
    manuscript_id: str = "",
    spec_version: str = DEFAULT_VERSION,
    mode: str = "scaffold",
    model: str = _assess.DEFAULT_JUDGE_MODEL,
) -> dict[str, Any]:
    """Assess a manuscript against all applicable TARGET leaves in one batched
    pass. `document` is a path, raw text, or a text_sha256 returned by
    parse_manuscript.

    mode='scaffold' (default) is the path for reviewing a publication: you are
    the LLM in the loop, so the server returns the exact assessment prompt, the
    tool schema, and a prompt hash for YOU to execute — read the manuscript
    against the rubric, produce the verdicts, then call submit_scaffold_verdicts
    to validate them and get the stamped result (evidence resolved to spans,
    provenance, ready for render_checklist).

    mode='judge' is for the headless/batch case where no LLM is in the loop
    (e.g. a corpus run). The server makes its own pinned-model API call
    (requires ANTHROPIC_API_KEY) so scoring is reproducible and caller-
    independent, and returns the full verdict matrix directly. Overkill when an
    agent is already reviewing the paper interactively."""
    sm = _resolve_section_map(document, manuscript_id)
    if mode == "scaffold":
        request = _assess.build_judge_request(sm, spec_version=spec_version, model=model)
        return {
            "mode": "scaffold",
            "text_sha256": sm.text_sha256,
            "instructions": (
                "Run the system prompt against user_content with the given "
                "tool forced. Then call submit_scaffold_verdicts with the "
                "tool-call `items` array and this text_sha256."
            ),
            **{k: request[k] for k in (
                "model", "temperature", "max_tokens", "system", "tool",
                "user_content", "prompt_hash", "spec_version", "leaf_ids",
                "excluded_leaves",
            )},
        }
    if mode != "judge":
        raise ValueError(f"Unknown mode {mode!r}; use 'judge' or 'scaffold'.")
    result = _assess.run_judge(sm, spec_version=spec_version, model=model)
    _assessments[result["manuscript_id"]] = result
    return result


def _render_bundle(assessment: dict[str, Any], view: str = "enriched",
                   formats: tuple[str, ...] | list[str] = ("html",)) -> dict[str, Any]:
    """The finished, stamped deliverable rendered inline. Defaults to HTML only:
    every extra format returned here transits the caller's conversation context
    (a triple-format bundle caused a real client timeout under Claude Desktop),
    and markdown/docx remain one render_checklist / render_checklist_docx call
    away from the same stamped artifact."""
    known = {"html", "markdown", "docx"}
    unknown = set(formats) - known
    if unknown:
        raise ValueError(f"Unknown report format(s) {sorted(unknown)}; use {sorted(known)}.")
    report = _render.render_checklist(assessment, view=view)
    bundle: dict[str, Any] = {
        "view": view,
        "provenance": report["provenance"],
        "completeness": report["completeness"],
    }
    if "markdown" in formats:
        bundle["markdown"] = report["markdown"]
    if "html" in formats:
        bundle["html"] = _render_html.render_html(report)
    if "docx" in formats:
        import os
        import tempfile
        stem = (report.get("manuscript_id") or "assessment").replace("/", "_")
        meta = _render_docx.write_checklist_docx(
            report, os.path.join(tempfile.gettempdir(), f"{stem}_TARGET_checklist.docx"))
        bundle["docx_base64"] = meta["content_base64"]
        bundle["docx_filename"] = meta["filename"]
    return bundle


@mcp.tool()
def submit_scaffold_verdicts(
    text_sha256: str,
    items: list[dict[str, Any]],
    spec_version: str = DEFAULT_VERSION,
    model: str = "unspecified",
    document: str = "",
    render: bool = True,
    report_formats: list[str] | None = None,
) -> AssessmentResult:
    """Scaffold-mode completion: validate verdicts produced by the calling
    agent (leaf coverage, verdict vocabulary, mandatory verbatim evidence quotes
    resolved to spans) and return the stamped assessment TOGETHER WITH the
    finished, rendered deliverable. `items` is the verdict array from the forced
    tool call — one object per leaf with `id`, `verdict`, `confidence`,
    `rationale`, and (for reported/partial) `evidence_quotes`.

    THE ARTIFACT OF RECORD is in the returned `report` (by default the HTML
    form), carrying a provenance `stamp` bound to the ingested text and prompt.
    That stamped render is the ONLY canonical output — present it as the
    completed checklist. Need another format? Do NOT hand-assemble one: call
    render_checklist (markdown) or render_checklist_docx (.docx bytes) to
    re-render the same stamped artifact, or pass report_formats (any of
    'html', 'markdown', 'docx') to include them here. The default is HTML only
    because every extra format flows through your context window. The `items`
    verdicts are an intermediate object; do NOT hand-assemble your own checklist
    document and present it as the assessment, because it will lack the stamp
    and cannot be verified. You MAY additionally write an analytic memo
    (prioritized gaps, an estimand-first reading), but label it as commentary
    and cite the stamp — never let it stand in for, or inherit the authority
    of, the stamped form.

    Set render=false to skip rendering (verdicts only). The parse cache does not
    survive a server restart; if `text_sha256` is no longer cached, pass
    `document` (the same path or text) to re-parse transparently."""
    sm = _parsed.get(text_sha256)
    if sm is None and document:
        sm = _resolve_section_map(document, "")
    if sm is None:
        raise ValueError(
            f"No parsed manuscript with text_sha256 {text_sha256!r} — the parse "
            "cache does not survive a server restart. Re-run parse_manuscript, "
            "or pass document= (the same path or text) to this call to re-parse "
            "and resolve your verdicts in one step."
        )
    request = _assess.build_judge_request(sm, spec_version=spec_version, model=model)
    result = _assess.finalize_assessment(sm, items, request, mode="scaffold")
    _assessments[result["manuscript_id"]] = result
    if render:
        result["report"] = _render_bundle(result, formats=report_formats or ["html"])
    return result


@mcp.tool()
def render_checklist(
    assessment: dict[str, Any] | None = None,
    manuscript_id: str = "",
    view: str = "enriched",
) -> ChecklistReport:
    """Render a finalized assessment as the completed TARGET checklist form: the
    21 published items (39 leaf rows, in checklist order) with the published
    item wording and a Location-reported column derived from the resolved
    evidence spans. The default enriched view adds, per leaf, the instrument's
    verdict and the verbatim evidence quote that justifies the location;
    view='official' strips to the published form's columns (Item / Checklist
    item / Location reported). Returns structured rows, a completeness tally, and
    a ready-to-display Markdown table. Pass either a full `assessment` object or
    the `manuscript_id` of one assessed earlier this session. This is a pure
    projection — no re-scoring."""
    if assessment is None:
        if manuscript_id and manuscript_id in _assessments:
            assessment = _assessments[manuscript_id]
        else:
            raise ValueError(
                "Provide an assessment object, or a manuscript_id assessed this session."
            )
    return _render.render_checklist(assessment, view=view)


@mcp.tool()
def render_checklist_docx(
    path: str = "",
    assessment: dict[str, Any] | None = None,
    manuscript_id: str = "",
    view: str = "enriched",
    logo: bool = False,
) -> ChecklistDocx:
    """Write the completed TARGET checklist to a Word (.docx) file and return it.
    Same content as render_checklist (published item wording + a Location-reported
    column from the resolved evidence spans; enriched view adds verdict and
    evidence), serialized as a submission-ready landscape table, one per
    manuscript section. Pass a full `assessment` object or the `manuscript_id` of
    one assessed this session. view='official' strips to the published form's
    three columns.

    RETRIEVING THE FILE: the return carries the document bytes as base64 in
    `content_base64` (with `content_type` and `filename`) — decode and save these
    to get the deliverable. The file is ALSO written to `path` on the server host,
    but that filesystem is not the caller's: if you are an agent whose files live
    elsewhere, use `content_base64`, not `path`. `path` defaults to a writable
    temp dir and is only directly useful for server-local/batch runs.

    logo=True heads the document with the published TARGET banner, but ONLY on
    view='official' (the author's self-report form); on the enriched view it is
    ignored and the returned `logo_applied` is False, because the official mark on
    a machine-generated assessment would imply an endorsement the instrument does
    not carry. Default off."""
    if assessment is None:
        if manuscript_id and manuscript_id in _assessments:
            assessment = _assessments[manuscript_id]
        else:
            raise ValueError(
                "Provide an assessment object, or a manuscript_id assessed this session."
            )
    report = _render.render_checklist(assessment, view=view)
    if not path:
        import os
        import tempfile
        stem = (report.get("manuscript_id") or "assessment").replace("/", "_")
        # Default into a writable temp dir. A bare relative name resolves against
        # the server's working directory, which under Claude Desktop is often the
        # filesystem root '/', where the write fails.
        path = os.path.join(tempfile.gettempdir(), f"{stem}_TARGET_checklist.docx")
    return _render_docx.write_checklist_docx(report, path, logo=logo)


@mcp.tool()
def render_checklist_html(
    assessment: dict[str, Any] | None = None,
    manuscript_id: str = "",
    view: str = "enriched",
) -> ChecklistHtml:
    """Render the completed TARGET checklist as a self-contained HTML page —
    same content as render_checklist, styled to the Black Swan Causal Labs
    identity (canvas ground, one aligned table, verdict pills), viewable in any
    browser on any host. Returns the HTML string in `html` (show it inline or
    publish it as an artifact) and the same bytes as base64 in `content_base64`
    (decode and save as an .html file). Carries the provenance `stamp`. Pass a
    full `assessment` object or the `manuscript_id` of one assessed this session;
    view='official' strips to the published form's three columns."""
    if assessment is None:
        if manuscript_id and manuscript_id in _assessments:
            assessment = _assessments[manuscript_id]
        else:
            raise ValueError(
                "Provide an assessment object, or a manuscript_id assessed this session."
            )
    import base64
    report = _render.render_checklist(assessment, view=view)
    html = _render_html.render_html(report)
    raw = html.encode("utf-8")
    stem = (report.get("manuscript_id") or "assessment").replace("/", "_")
    return {
        "manuscript_id": report.get("manuscript_id", ""),
        "view": view,
        "html": html,
        "content_base64": base64.b64encode(raw).decode("ascii"),
        "content_type": "text/html; charset=utf-8",
        "filename": f"{stem}_TARGET_checklist.html",
        "provenance": report["provenance"],
    }


@mcp.tool()
def aggregate_corpus(
    assessments: list[dict[str, Any]] | None = None,
    use_session: bool = False,
) -> CorpusSummary:
    """Roll up many assessments into per-item completeness rates plus coverage
    denominators (supplement-retrieval status, full-text availability, evidence-
    resolution rate). Pass an array of assessment objects as `assessments`, or
    use_session=true to aggregate every assessment produced this session. The
    completeness rates are only as valid as the sample and are not yet
    gold-standard calibrated."""
    if not assessments:
        if use_session:
            assessments = list(_assessments.values())
        else:
            raise ValueError("Provide assessments, or set use_session=true.")
    if not assessments:
        raise ValueError("No assessments to aggregate.")
    return _corpus.aggregate_corpus(assessments)


@mcp.tool()
def build_coding_sheet(
    assessments: list[dict[str, Any]] | None = None,
    use_session: bool = False,
    blind: bool = True,
) -> list[dict[str, Any]]:
    """Emit blank per-paper coding sheets for human gold-standard coding: one
    row per applicable leaf with its intent and verdict boundaries and empty
    verdict/evidence/note fields. blind=true (default) withholds the
    instrument's verdict so coders are not anchored — use blind coding for the
    primary reference standard. Pass `assessments` or use_session=true."""
    if not assessments:
        if use_session:
            assessments = list(_assessments.values())
        else:
            raise ValueError("Provide assessments, or set use_session=true.")
    return _validate.build_coding_sheet(assessments, blind=blind)


@mcp.tool()
def validate_against_gold(
    instrument: list[dict[str, Any]],
    human_codings: list[dict[str, Any]],
) -> ValidationResult:
    """Compute per-leaf agreement between instrument assessments and human
    gold-standard codings: raw agreement, Cohen's kappa, Gwet's AC1, and binary
    (reported-vs-rest) sensitivity/specificity with the human coding as the
    reference standard, plus a span-keyed disagreement list for adjudication.
    Agreement is reported PER LEAF; the pooled figure is orientation only. Both
    arguments are arrays of assessment/coding objects sharing manuscript ids and
    spec version."""
    return _validate.compare(instrument, human_codings)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
