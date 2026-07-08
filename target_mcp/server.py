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
from . import governance as _gov
from .ingest import SectionMap, parse_document
from .spec import DEFAULT_VERSION, available_versions, load_spec

mcp = FastMCP(
    "target-checklist",
    instructions=(
        "Operationalized TARGET reporting guideline (Cashin et al., JAMA/BMJ "
        "2025) for observational studies emulating a target trial. Typical "
        "flow: parse_manuscript -> assess_manuscript -> check_critical_floor. "
        "get_checklist introspects the encoded spec."
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


@mcp.tool()
def parse_manuscript(document: str, manuscript_id: str = "") -> dict[str, Any]:
    """Parse a manuscript into a SectionMap with character-offset section
    spans. `document` is a path to a PDF or text file, or the raw manuscript
    text itself. Returns section boundaries, protocol-table and flow-diagram
    detection, extractor version, and the text hash used to key later calls."""
    sm = parse_document(document, manuscript_id or None)
    _parsed[sm.text_sha256] = sm
    out = sm.to_dict(include_text=False)
    out["sections"] = [
        {"name": s.name, "heading": s.heading, "start": s.start, "end": s.end,
         "chars": s.end - s.start}
        for s in sm.sections
    ]
    return out


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
    mode: str = "judge",
    model: str = _assess.DEFAULT_JUDGE_MODEL,
) -> dict[str, Any]:
    """Assess a manuscript against all applicable TARGET leaves in one batched
    pass. `document` is a path, raw text, or a text_sha256 returned by
    parse_manuscript. mode='judge' (default) makes the pinned-model call
    server-side (requires ANTHROPIC_API_KEY) and returns the full verdict
    matrix with resolved evidence spans and provenance stamps.
    mode='scaffold' returns the exact judge prompt, tool schema, and prompt
    hash for the calling agent to execute; submit the verdicts via
    submit_scaffold_verdicts to get the same validated, stamped result."""
    sm = _resolve_section_map(document, manuscript_id)
    if mode == "scaffold":
        request = _assess.build_judge_request(sm, spec_version=spec_version, model=model)
        return {
            "mode": "scaffold",
            "text_sha256": sm.text_sha256,
            "instructions": (
                "Run the system prompt against user_content with the given "
                "tool forced, temperature and model as specified. Then call "
                "submit_scaffold_verdicts with the tool-call `items` array "
                "and this text_sha256."
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
