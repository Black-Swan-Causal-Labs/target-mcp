"""Server-level integration tests: the MCP tool surface, structured I/O, and
the interactive review round-trip through call_tool()."""

import asyncio

import pytest

from target_mcp.server import mcp

FAKE = """Emulating a target trial of drug A vs B
Abstract
We emulated a target trial using claims data. Hazard ratio 0.85 under no unmeasured confounding.
Methods
Eligibility required age over 40. Follow-up started at treatment assignment (time zero) and ended at death.
We adjusted for baseline confounders using inverse probability weighting.
Results
Of 120000 assessed, 45000 eligible. The hazard ratio was 0.85.
Discussion
Residual confounding remains possible.
"""

EXPECTED_TOOLS = {
    "get_checklist", "parse_manuscript", "parse_pmcid", "assess_manuscript",
    "submit_scaffold_verdicts", "check_critical_floor", "aggregate_corpus",
    "build_coding_sheet", "validate_against_gold",
}


def _call(name, args):
    # call_tool returns (content_blocks, structured_content)
    return asyncio.run(mcp.call_tool(name, args))[1]


def test_tool_surface_and_output_schemas():
    tools = asyncio.run(mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    # every tool declares a structured output schema
    for t in tools:
        assert getattr(t, "outputSchema", None) is not None, t.name
    # submit_scaffold_verdicts takes a structured array, not a JSON string
    sub = next(t for t in tools if t.name == "submit_scaffold_verdicts")
    assert sub.inputSchema["properties"]["items"]["type"] == "array"


def test_review_round_trip_structured_io():
    parsed = _call("parse_manuscript", {"document": FAKE, "manuscript_id": "rt-1"})
    sha = parsed["text_sha256"]
    assert parsed["n_pages"] is None  # text input -> nullable field tolerated
    assert {"methods", "results"} <= {s["name"] for s in parsed["sections"]}

    scaf = _call("assess_manuscript", {"document": sha, "mode": "scaffold"})
    assert scaf["mode"] == "scaffold" and len(scaf["leaf_ids"]) == 39

    items = [
        {"id": lid,
         "verdict": "reported" if lid == "6d" else "not_reported",
         "confidence": 0.8, "rationale": "x",
         **({"evidence_quotes": ["Follow-up started at treatment assignment (time zero)"]}
            if lid == "6d" else {})}
        for lid in scaf["leaf_ids"]
    ]
    res = _call("submit_scaffold_verdicts", {"text_sha256": sha, "items": items, "model": "test"})
    assert res["mode"] == "scaffold" and len(res["items"]) == 39
    r6d = next(i for i in res["items"] if i["id"] == "6d")
    assert r6d["evidence"][0]["resolved"] and r6d["evidence"][0]["source_document"] == "main"

    # no supplement checked -> floor failure on assumptions is indeterminate, not fail
    floor = _call("check_critical_floor", {"manuscript_id": "rt-1"})
    assert floor["status"] == "indeterminate"

    agg = _call("aggregate_corpus", {"use_session": True})
    assert agg["n_papers"] >= 1


def test_check_floor_accepts_structured_assessment():
    parsed = _call("parse_manuscript", {"document": FAKE, "manuscript_id": "rt-2",
                                        "supplement_status": "none_exists"})
    sha = parsed["text_sha256"]
    scaf = _call("assess_manuscript", {"document": sha, "mode": "scaffold"})
    items = [{"id": lid, "verdict": "not_reported", "confidence": 0.7, "rationale": "x"}
             for lid in scaf["leaf_ids"]]
    assessment = _call("submit_scaffold_verdicts", {"text_sha256": sha, "items": items})
    # pass the assessment object straight in (structured input, not a JSON string)
    floor = _call("check_critical_floor", {"assessment": assessment})
    assert floor["status"] == "fail"  # none_exists => confident verdict
