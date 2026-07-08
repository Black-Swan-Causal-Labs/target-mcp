import json
from pathlib import Path

import pytest

from target_mcp.spec import load_spec, floor_leaves, SpecError
from target_mcp.ingest import parse_text, parse_pdf, build_bundle
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


def _partial_floor_result(supplement_status):
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    sm.supplement_status = supplement_status
    request = build_judge_request(sm)
    verdicts = _full_verdicts(request, sm)
    for v in verdicts:
        if v["id"] == "7g.i":
            v["verdict"] = "partial"
    return finalize_assessment(sm, verdicts, request, mode="judge")


def test_floor_fails_on_partial_when_supplement_confident():
    # A confident supplement state (here: none_exists) permits a real fail.
    result = _partial_floor_result("none_exists")
    floor = check_critical_floor(result)
    assert floor["status"] == "fail"
    assert [f["id"] for f in floor["failed_leaves"]] == ["7g.i"]
    assert floor["pending_supplement_leaves"] == []


def test_floor_indeterminate_when_supplement_not_retrieved():
    # Same verdicts, but no supplement checked -> cannot assert a failure.
    for status in ("not_checked", "not_retrieved"):
        result = _partial_floor_result(status)
        floor = check_critical_floor(result)
        assert floor["status"] == "indeterminate", status
        assert [f["id"] for f in floor["pending_supplement_leaves"]] == ["7g.i"]
        assert floor["failed_leaves"] == []


def test_floor_pass_regardless_of_supplement_status():
    # All floor leaves reported -> pass even if no supplement was checked.
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    result = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")
    assert result["supplement_status"] == "not_checked"
    assert check_critical_floor(result)["status"] == "pass"


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


def test_build_bundle_source_tagging_and_resolution():
    main = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    suppl_text = ("Supplementary Table S1. Target trial specification.\n"
                  "Causal contrasts: intention-to-treat effect and per-protocol effect.\n"
                  "Identifying assumption: conditional exchangeability given baseline covariates.")
    bundle = build_bundle(main, [("suppl.pdf", suppl_text, 2)], supplement_status="user_provided")

    assert bundle.supplement_status == "user_provided"
    assert any(s.source == "supplement:suppl.pdf" for s in bundle.sections)
    assert {d["kind"] for d in bundle.documents} == {"main", "supplement"}
    # a quote unique to the supplement resolves and is tagged to its source
    span = bundle.locate("intention-to-treat effect and per-protocol effect")
    assert span is not None
    assert bundle.source_at(span[0]) == "supplement:suppl.pdf"
    # a quote from the main text still resolves and is tagged main
    mspan = bundle.locate("adjusted for baseline confounders")
    assert mspan is not None and bundle.source_at(mspan[0]) == "main"


def test_supplement_flips_floor_leaf_and_source_tagged_evidence():
    # Main text lacks the estimand statement; supplement supplies it.
    main = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    suppl = "Causal contrasts of interest: the intention-to-treat effect of drug A versus drug B."
    bundle = build_bundle(main, [("s1.pdf", suppl, 1)], supplement_status="user_provided")
    request = build_judge_request(bundle)
    verdicts = []
    for lid in request["leaf_ids"]:
        if lid == "6f":
            verdicts.append({"id": lid, "verdict": "reported", "confidence": 0.9,
                             "rationale": "estimand named in supplement",
                             "evidence_quotes": ["the intention-to-treat effect of drug A versus drug B"]})
        else:
            verdicts.append({"id": lid, "verdict": "reported", "confidence": 0.8,
                             "rationale": "x", "evidence_quotes": ["effect of initiating drug A versus drug B"]})
    result = finalize_assessment(bundle, verdicts, request, mode="scaffold")
    ev = next(i for i in result["items"] if i["id"] == "6f")["evidence"][0]
    assert ev["resolved"] and ev["source_document"] == "supplement:s1.pdf"
    assert result["supplement_status"] == "user_provided"


def test_aggregate_corpus():
    from target_mcp.corpus import aggregate_corpus
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    # paper A: all floor reported (pass); paper B: 7g.i partial
    a = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")
    a["manuscript_id"] = "A"
    vb = _full_verdicts(request, sm)
    for v in vb:
        if v["id"] == "6g":
            v["verdict"] = "not_reported"
            v.pop("evidence_quotes", None)
    b = finalize_assessment(sm, vb, request, mode="judge")
    b["manuscript_id"] = "B"
    for x in (a, b):
        x["supplement_status"] = "none_exists"
    floors = [check_critical_floor(a), check_critical_floor(b)]
    summ = aggregate_corpus([a, b], floors)
    assert summ["n_papers"] == 2
    assert summ["critical_floor_distribution"] == {"fail": 1, "pass": 1}
    g6 = next(r for r in summ["per_leaf"] if r["id"] == "6g")
    assert g6["reported"] == 1 and g6["not_reported"] == 1
    assert g6["reported_rate"] == 0.5
    assert summ["coverage"]["evidence_resolution_rate"] == 1.0


def test_prompt_hash_stable():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    r1 = build_judge_request(sm)
    r2 = build_judge_request(sm)
    assert r1["prompt_hash"] == r2["prompt_hash"]
    assert r1["prompt_hash"].startswith("sha256:")
