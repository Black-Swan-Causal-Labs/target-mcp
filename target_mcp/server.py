"""MCP composition layer: the TARGET tool surface.

Vertical-slice tools: get_checklist, parse_manuscript, assess_manuscript,
check_critical_floor. Parsed manuscripts are cached in-process by text hash
so assess/check calls can reference a prior parse instead of re-supplying
the document.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import assess as _assess
from . import corpus as _corpus
from . import governance as _gov
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
        "publication: parse_manuscript (the paper you were given, with its "
        "supplement) -> assess_manuscript (mode='scaffold' default: it returns "
        "the assessment prompt for YOU to run) -> submit_scaffold_verdicts (to "
        "validate your verdicts and resolve evidence to spans) -> "
        "check_critical_floor. Supplements matter: TTE methods (estimand, "
        "identifying assumptions) often live in supplementary material, so pass "
        "the supplement to parse_manuscript when you have it — a floor failure "
        "without a supplement in hand is reported as indeterminate, not fail. "
        "get_checklist introspects the encoded spec. (parse_pmcid and "
        "assess_manuscript mode='judge' exist for headless corpus/batch runs, "
        "not the interactive review case.)"
    ),
)

_parsed: dict[str, SectionMap] = {}          # text_sha256 -> SectionMap
_assessments: dict[str, dict[str, Any]] = {} # manuscript_id -> latest assessment


@mcp.tool()
def get_checklist(version: str = DEFAULT_VERSION) -> dict[str, Any]:
    """Return the encoded TARGET checklist spec: 39 scoreable leaf subitems
    (grouped into the 21 published items) with intent, assessor notes,
    signal terms, pairing links, applicability rules, and the critical-floor
    overlay. Pass a version id to pin; omit for the current default."""
    spec = load_spec(version)
    return {
        "spec_version": spec["spec_version"],
        "available_versions": available_versions(),
        "guideline_scope": spec["guideline_scope"],
        "e_e_status": spec["e_e_status"],
        "verdict_vocabulary": spec["verdict_vocabulary"],
        "evidence_policy": spec["evidence_policy"],
        "critical_floor": spec["critical_floor"],
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
) -> dict[str, Any]:
    """PRIMARY entry point: parse a manuscript you were given (and its
    supplements) into a SectionMap with character-offset, source-tagged section
    spans. This is the usual door — most of the time you have the paper as a
    file, not a PMCID. `document` is a path to a PDF/text/docx file or the raw
    manuscript text. `supplements` is a list of file paths (PDF/docx/text) to
    merge as supplementary material — PASS IT WHEN YOU HAVE IT: TTE methods
    (estimand, identifying assumptions) frequently live in a supplementary
    protocol table, and without a supplement the floor verdicts on those leaves
    come back indeterminate rather than fail. When supplements are provided,
    supplement_status defaults to 'user_provided'. Pass supplement_status=
    'none_exists' to assert the article has no supplement (enables a confident
    floor verdict). Returns source-tagged section boundaries, protocol-table and
    flow-diagram detection over the combined text, supplement_status, and the
    text hash used to key later calls."""
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
def parse_pmcid(pmcid: str, include_supplements: bool = True) -> dict[str, Any]:
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
    provenance, ready for check_critical_floor).

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


@mcp.tool()
def submit_scaffold_verdicts(
    text_sha256: str,
    items_json: str,
    spec_version: str = DEFAULT_VERSION,
    model: str = "unspecified",
) -> dict[str, Any]:
    """Scaffold-mode completion: validate verdicts produced by the calling
    agent against the same rules judge mode enforces (leaf coverage, verdict
    vocabulary, mandatory verbatim evidence quotes resolved to spans) and
    return the stamped assessment. `items_json` is the JSON array from the
    forced tool call. `model` should identify the model that produced them."""
    sm = _parsed.get(text_sha256)
    if sm is None:
        raise ValueError(
            f"No parsed manuscript with text_sha256 {text_sha256!r}; call "
            "parse_manuscript or assess_manuscript(mode='scaffold') first."
        )
    request = _assess.build_judge_request(sm, spec_version=spec_version, model=model)
    raw_items = json.loads(items_json)
    result = _assess.finalize_assessment(sm, raw_items, request, mode="scaffold")
    _assessments[result["manuscript_id"]] = result
    return result


@mcp.tool()
def check_critical_floor(
    assessment_json: str = "",
    manuscript_id: str = "",
) -> dict[str, Any]:
    """Hard pass/fail gate over the non-waivable critical-floor leaves
    (time zero 6d/7d, causal estimand 6f/7f, identifying assumptions 6g/7g.i).
    This floor is a Black Swan Causal Labs governance overlay, not a tiering
    the published guideline defines. Pass either a full assessment JSON or
    the manuscript_id of an assessment produced earlier in this session."""
    if assessment_json:
        assessment = json.loads(assessment_json)
    elif manuscript_id and manuscript_id in _assessments:
        assessment = _assessments[manuscript_id]
    else:
        raise ValueError(
            "Provide assessment_json, or a manuscript_id assessed this session."
        )
    return _gov.check_critical_floor(assessment)


@mcp.tool()
def aggregate_corpus(
    assessments_json: str = "",
    use_session: bool = False,
) -> dict[str, Any]:
    """Roll up many assessments into per-item completeness rates plus coverage
    denominators (supplement-retrieval status, full-text availability, evidence-
    resolution rate) and the critical-floor distribution. Pass a JSON array of
    assessment objects as `assessments_json`, or use_session=true to aggregate
    every assessment produced this session. The completeness rates are only as
    valid as the sample and are not yet gold-standard calibrated."""
    if assessments_json:
        assessments = json.loads(assessments_json)
    elif use_session:
        assessments = list(_assessments.values())
    else:
        raise ValueError("Provide assessments_json, or set use_session=true.")
    if not assessments:
        raise ValueError("No assessments to aggregate.")
    floors = [_gov.check_critical_floor(a) for a in assessments]
    return _corpus.aggregate_corpus(assessments, floors)


@mcp.tool()
def build_coding_sheet(
    assessments_json: str = "",
    use_session: bool = False,
    blind: bool = True,
) -> list[dict[str, Any]]:
    """Emit blank per-paper coding sheets for human gold-standard coding: one
    row per applicable leaf with its intent and verdict boundaries and empty
    verdict/evidence/note fields. blind=true (default) withholds the
    instrument's verdict so coders are not anchored — use blind coding for the
    primary reference standard. Pass assessments_json or use_session=true."""
    if assessments_json:
        assessments = json.loads(assessments_json)
    elif use_session:
        assessments = list(_assessments.values())
    else:
        raise ValueError("Provide assessments_json, or set use_session=true.")
    return _validate.build_coding_sheet(assessments, blind=blind)


@mcp.tool()
def validate_against_gold(
    instrument_json: str,
    human_codings_json: str,
) -> dict[str, Any]:
    """Compute per-leaf agreement between instrument assessments and human
    gold-standard codings: raw agreement, Cohen's kappa, Gwet's AC1, and binary
    (reported-vs-rest) sensitivity/specificity with the human coding as the
    reference standard, plus a span-keyed disagreement list for adjudication.
    Agreement is reported PER LEAF; the pooled figure is orientation only. Both
    arguments are JSON arrays of assessment/coding objects sharing manuscript
    ids and spec version."""
    instrument = json.loads(instrument_json)
    human = json.loads(human_codings_json)
    return _validate.compare(instrument, human)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
