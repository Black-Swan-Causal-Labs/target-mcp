import json
from pathlib import Path

import pytest

from target_mcp.spec import load_spec, floor_leaves, SpecError
from target_mcp.ingest import parse_text, parse_pdf
from target_mcp.assess import build_judge_request, finalize_assessment, VerdictValidationError
from target_mcp.governance import check_critical_floor

REPO_PARENT = Path(__file__).resolve().parents[2]
BMJ_PDF = REPO_PARENT / "bmj-2025-087179.full.pdf"

FAKE_PAPER = """Emulating a target trial of drug A versus drug B

Abstract
We emulated a target trial using observational claims data to estimate the
effect of initiating drug A versus drug B on mortality. Hazard ratio 0.85
(95% CI 0.7 to 1.0) under the assumption of no unmeasured confounding.

Introduction
Prior evidence is limited. We summarize the causal question: among adults
with condition X, what is the effect of initiating drug A versus drug B on
5-year mortality?

Methods
Eligibility criteria required age over 40 and a new diagnosis of condition X.
Follow-up started at treatment assignment (time zero) and ended at death,
disenrollment, or five years. We adjusted for baseline confounders using
inverse probability weighting.

Results
Of 120000 individuals assessed for eligibility, 45000 were eligible and
assigned: 20000 to drug A and 25000 to drug B. The hazard ratio was 0.85
(95% CI 0.7 to 1.0).

Discussion
Findings are compatible with a protective effect under our identifying
assumptions. Residual confounding remains possible.
"""


def test_spec_loads_and_counts():
    spec = load_spec()
    assert len(spec["items"]) == 39
    assert {i["item_no"] for i in spec["items"]} == set(range(1, 22))
    assert floor_leaves() == ["6d", "7d", "6f", "7f", "6g", "7g.i"]
    # pairing symmetry is enforced at load; check one pair explicitly
    by_id = {i["id"]: i for i in spec["items"]}
    assert by_id["6g"]["paired_with"] == ["7g.i", "7g.ii"]
    assert by_id["7g.i"]["paired_with"] == ["6g"]


def test_unknown_version_raises():
    with pytest.raises(SpecError):
        load_spec("target-9.9.9")


def test_parse_text_sections_and_locate():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    names = [s.name for s in sm.sections]
    for required in ("abstract", "introduction", "methods", "results", "discussion"):
        assert required in names
    span = sm.locate("Follow-up started at treatment assignment (time zero)")
    assert span is not None
    assert sm.section_at(span[0]) == "methods"
    # whitespace-insensitive matching across the collapsed form
    assert sm.locate("effect of initiating   drug A\nversus drug B") is not None
    assert sm.locate("this text does not exist anywhere") is None


@pytest.mark.skipif(not BMJ_PDF.exists(), reason="reference PDF not present")
def test_parse_real_pdf():
    sm = parse_pdf(BMJ_PDF)
    assert sm.n_pages == 10
    assert {s.name for s in sm.sections} >= {"abstract", "introduction", "methods"}
    assert sm.protocol_table_detected
    q = sm.locate("immortal time bias and other self-inflicted injuries")
    assert q is not None


def _full_verdicts(request, sm):
    """Synthetic verdict set: floor leaves reported with real quotes,
    everything else not_reported."""
    quote_by_leaf = {
        "6d": "Follow-up started at treatment assignment (time zero)",
        "7d": "ended at death,\ndisenrollment, or five years",
        "6f": "effect of initiating drug A versus drug B on mortality",
        "7f": "The hazard ratio was 0.85",
        "6g": "assumption of no unmeasured confounding",
        "7g.i": "adjusted for baseline confounders using\ninverse probability weighting",
    }
    items = []
    for lid in request["leaf_ids"]:
        if lid in quote_by_leaf:
            items.append({"id": lid, "verdict": "reported", "confidence": 0.9,
                          "rationale": "stated", "evidence_quotes": [quote_by_leaf[lid]]})
        else:
            items.append({"id": lid, "verdict": "not_reported", "confidence": 0.8,
                          "rationale": "absent"})
    return items


def test_finalize_and_floor_pass():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    assert len(request["leaf_ids"]) == 39 and not request["excluded_leaves"]
    result = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")
    assert result["full_text_available"] is True
    assert result["unresolved_evidence_leaves"] == []
    ev = next(i for i in result["items"] if i["id"] == "6d")["evidence"][0]
    assert ev["resolved"] and ev["section"] == "methods"
    floor = check_critical_floor(result)
    assert floor["status"] == "pass" and floor["pass"]


def test_floor_fails_on_partial():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    verdicts = _full_verdicts(request, sm)
    for v in verdicts:
        if v["id"] == "7g.i":
            v["verdict"] = "partial"
    result = finalize_assessment(sm, verdicts, request, mode="judge")
    floor = check_critical_floor(result)
    assert floor["status"] == "fail"
    assert [f["id"] for f in floor["failed_leaves"]] == ["7g.i"]


def test_evidence_required_for_reported():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    verdicts = _full_verdicts(request, sm)
    verdicts[0]["verdict"] = "reported"
    verdicts[0].pop("evidence_quotes", None)
    with pytest.raises(VerdictValidationError):
        finalize_assessment(sm, verdicts, request, mode="judge")


def test_not_applicable_only_on_conditional_leaves():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    verdicts = _full_verdicts(request, sm)
    for v in verdicts:
        if v["id"] == "12":  # always-applicable leaf
            v["verdict"] = "not_applicable"
    with pytest.raises(VerdictValidationError):
        finalize_assessment(sm, verdicts, request, mode="judge")


def test_coverage_mismatch_raises():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    with pytest.raises(VerdictValidationError):
        finalize_assessment(sm, _full_verdicts(request, sm)[:-1], request, mode="judge")


def test_abstract_only_gating():
    abstract_only = FAKE_PAPER.split("Introduction")[0]
    sm = parse_text(abstract_only, manuscript_id="fake-abs")
    request = build_judge_request(sm)
    assert set(request["leaf_ids"]) == {"1a", "1b", "1c"}
    assert len(request["excluded_leaves"]) == 36
    items = [{"id": lid, "verdict": "not_reported", "confidence": 0.7, "rationale": "x"}
             for lid in request["leaf_ids"]]
    result = finalize_assessment(sm, items, request, mode="judge")
    assert result["full_text_available"] is False
    floor = check_critical_floor(result)
    assert floor["status"] == "indeterminate"


def test_prompt_hash_stable():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    r1 = build_judge_request(sm)
    r2 = build_judge_request(sm)
    assert r1["prompt_hash"] == r2["prompt_hash"]
    assert r1["prompt_hash"].startswith("sha256:")
