import json
from pathlib import Path

import pytest

from target_mcp.spec import load_spec, SpecError
from target_mcp.ingest import parse_text, parse_pdf, build_bundle
from target_mcp.assess import build_judge_request, finalize_assessment, VerdictValidationError

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
    """Synthetic verdict set: a handful of leaves reported with real quotes,
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


def test_finalize_resolves_evidence_and_rolls_up():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    assert len(request["leaf_ids"]) == 39 and not request["excluded_leaves"]
    result = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")
    assert result["full_text_available"] is True
    assert result["unresolved_evidence_leaves"] == []
    ev = next(i for i in result["items"] if i["id"] == "6d")["evidence"][0]
    assert ev["resolved"] and ev["section"] == "methods"
    # section rollups tally verdicts per section
    assert result["section_rollups"]["methods"]["reported"] >= 1


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
    # the 36 non-abstract leaves are excluded, not scored
    assert len(result["excluded_leaves"]) == 36


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


def test_supplement_supplies_leaf_and_source_tagged_evidence():
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
    # paper A: 6g reported; paper B: 6g not_reported
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
    summ = aggregate_corpus([a, b])
    assert summ["n_papers"] == 2
    g6 = next(r for r in summ["per_leaf"] if r["id"] == "6g")
    assert g6["reported"] == 1 and g6["not_reported"] == 1
    assert g6["reported_rate"] == 0.5
    assert summ["coverage"]["evidence_resolution_rate"] == 1.0


def test_validation_harness():
    from target_mcp.validate import build_coding_sheet, compare
    sm = parse_text(FAKE_PAPER, manuscript_id="P1")
    request = build_judge_request(sm)
    instr = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")
    instr["manuscript_id"] = "P1"

    # blind coding sheet: no instrument verdicts leaked, one row per scored leaf
    sheet = build_coding_sheet([instr], blind=True)
    assert len(sheet) == 1 and sheet[0]["manuscript_id"] == "P1"
    assert all("_instrument_verdict" not in r for r in sheet[0]["items"])
    assert {r["id"] for r in sheet[0]["items"]} == set(request["leaf_ids"])

    # a human coding that agrees on everything except 6f (human: partial)
    human_items = []
    for i in instr["items"]:
        v = i["verdict"]
        if i["id"] == "6f":
            v = "partial"
        human_items.append({"id": i["id"], "verdict": v, "note": "coded"})
    human = {"manuscript_id": "P1", "spec_version": instr["spec_version"], "items": human_items}

    result = compare([instr], [human])
    assert result["n_papers"] == 1
    assert result["n_disagreements"] == 1
    d = result["disagreements"][0]
    assert d["id"] == "6f" and d["instrument_verdict"] == "reported" and d["human_verdict"] == "partial"
    # disagreement carries the instrument's evidence span for adjudication
    assert d["instrument_evidence"] and d["instrument_evidence"][0]["resolved"]
    # 6f leaf: instrument=reported, human=partial -> a false positive for "reported"
    row6f = next(r for r in result["per_leaf"] if r["id"] == "6f")
    assert row6f["binary_reported"]["fp"] == 1
    assert row6f["raw_agreement"] == 0.0
    # a leaf both coded 'reported' shows perfect agreement
    row6d = next(r for r in result["per_leaf"] if r["id"] == "6d")
    assert row6d["raw_agreement"] == 1.0


def test_render_checklist_enriched():
    from target_mcp.render import render_checklist, OFFICIAL_TEXT
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    request = build_judge_request(sm)
    result = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")

    report = render_checklist(result)
    # one row per encoded leaf, in checklist order, all officially worded
    assert len(report["rows"]) == 39
    assert [r["id"] for r in report["rows"]] == request["leaf_ids"]
    assert all(r["official_text"] == OFFICIAL_TEXT[r["id"]] for r in report["rows"])

    # a reported leaf carries its resolved location, not "Not reported"
    row6d = next(r for r in report["rows"] if r["id"] == "6d")
    assert row6d["verdict"] == "reported"
    assert row6d["location"] == "Methods"
    # a not_reported leaf reads "Not reported"
    row2 = next(r for r in report["rows"] if r["id"] == "2")
    assert row2["verdict"] == "not_reported" and row2["location"] == "Not reported"

    assert report["completeness"]["reported"] == 6
    assert "floor" not in report  # the critical floor was removed
    assert "(TARGET) Checklist" in report["markdown"]
    assert "Black Swan Causal Labs — Completeness Assessment" in report["markdown"]
    assert "third-party" not in report["markdown"].lower()  # framing removed
    assert "Location reported" in report["markdown"]


def test_render_checklist_official_view_and_supplement_location():
    from target_mcp.render import render_checklist
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
            verdicts.append({"id": lid, "verdict": "not_reported", "confidence": 0.8,
                             "rationale": "absent"})
    result = finalize_assessment(bundle, verdicts, request, mode="scaffold")

    # supplement-sourced evidence surfaces as a Supplement location
    report = render_checklist(result)
    row6f = next(r for r in report["rows"] if r["id"] == "6f")
    assert row6f["location"] == "Supplement — s1.pdf"

    # official view drops the verdict/evidence columns from the table header
    official = render_checklist(result, view="official")
    assert "| Verdict |" not in official["markdown"]
    assert "Evidence & rationale" not in official["markdown"]
    assert "| Verdict |" in render_checklist(result)["markdown"]  # present in enriched
    assert "Location reported" in official["markdown"]


def test_path_like_but_missing_raises_not_silently_ingested():
    from target_mcp.ingest import parse_document
    # a path that doesn't resolve must RAISE, not become a 30-char "manuscript"
    with pytest.raises(FileNotFoundError):
        parse_document("other pubs/Nonexistent Paper 2024.pdf")
    with pytest.raises(FileNotFoundError):
        parse_document("/absolute/missing/paper.docx")
    # genuine inline text is still parsed as text, not mistaken for a path
    sm = parse_document(FAKE_PAPER)
    assert len(sm.full_text) > 500
    assert "methods" in {s.name for s in sm.sections}


def test_extraction_guards():
    from target_mcp.ingest import (_assert_plausible, ExtractionError,
                                   _too_sparse, _looks_like_path)
    # a paged doc that resolves to near-nothing fails loudly
    with pytest.raises(ExtractionError):
        _assert_plausible("   ", 12, "scan.pdf")
    _assert_plausible("x" * 300, 3, "ok.pdf")  # plausible -> no raise
    _assert_plausible("short but no page count", None, "text")  # non-paged -> no raise
    assert _too_sparse([""] * 10) is True
    assert _too_sparse(["word " * 60]) is False
    assert _looks_like_path("/abs/paper.pdf") and _looks_like_path("folder/p.docx")
    assert not _looks_like_path("We emulated a target trial of drug A versus B in adults.")


def test_out_of_order_layout_still_fully_assessed():
    # Methods printed AFTER Discussion (accepted-manuscript proof): the sectioner
    # drops the out-of-order Methods heading, but a substantial body still unlocks
    # the full checklist rather than excluding 36 leaves.
    body = ("Discussion\n" + "We interpret the findings in context. " * 300
            + "\nMethods\n" + "Eligibility required age over 40 and a diagnosis. " * 40)
    sm = parse_text("Title line\nAbstract\nWe emulated a target trial.\n" + body,
                    manuscript_id="ooo")
    request = build_judge_request(sm)
    assert len(request["leaf_ids"]) == 39 and request["excluded_leaves"] == []


def test_unresolved_quote_carries_actionable_reason():
    sm = parse_text(FAKE_PAPER, manuscript_id="ur")
    request = build_judge_request(sm)
    verds = _full_verdicts(request, sm)
    for v in verds:
        if v["id"] == "6a":
            v["verdict"] = "reported"
            v["evidence_quotes"] = ["this exact phrase appears nowhere in the manuscript"]
    res = finalize_assessment(sm, verds, request, mode="judge")
    ev = next(i for i in res["items"] if i["id"] == "6a")["evidence"][0]
    assert ev["resolved"] is False
    assert ev.get("reason")  # opaque None replaced by an actionable explanation
    assert "6a" in res["unresolved_evidence_leaves"]


def test_provenance_stamp_binds_to_inputs():
    from target_mcp.render import provenance, render_checklist
    sm = parse_text(FAKE_PAPER, manuscript_id="prov")
    request = build_judge_request(sm)
    res = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")
    p = provenance(res)
    assert p["stamp"].startswith("TGT-") and len(p["stamp"]) == 16
    assert p["text_sha256"] == res["text_sha256"]
    # stamp changes if the ingested text changes (different manuscript => different sha)
    sm2 = parse_text(FAKE_PAPER + "\nExtra sentence.", manuscript_id="prov2")
    r2 = build_judge_request(sm2)
    res2 = finalize_assessment(sm2, _full_verdicts(r2, sm2), r2, mode="judge")
    assert provenance(res2)["stamp"] != p["stamp"]
    # the render carries the stamp in its footer and structured block
    report = render_checklist(res)
    assert report["provenance"]["stamp"] == p["stamp"]
    assert p["stamp"] in report["markdown"]


def test_render_html_is_self_contained_and_stamped():
    from target_mcp.render import render_checklist
    from target_mcp.render_html import render_html
    sm = parse_text(FAKE_PAPER, manuscript_id="html-1")
    request = build_judge_request(sm)
    res = finalize_assessment(sm, _full_verdicts(request, sm), request, mode="judge")
    html = render_html(render_checklist(res))
    assert html.startswith("<!doctype html>")
    assert "<style>" in html and "http://" not in html and "https://" not in html  # no external assets
    assert "(TARGET) Checklist" in html
    assert "Black Swan Causal Labs — Completeness Assessment" in html
    # all 39 leaf ids present; provenance stamp embedded
    for lid in ("1a", "6d", "7g.i", "21"):
        assert f'class="col-id">{lid}<' in html
    assert render_checklist(res)["provenance"]["stamp"] in html
    assert 'name="target-mcp:stamp"' in html


def test_protocol_table_detected_from_delimited_header():
    from target_mcp.ingest import _detect_protocol_table
    # pipe- or tab-delimited protocol table (the text-path form) with no literal
    # word "table" is still detected via the column-header fallback
    piped = "Component | Hypothetical target trial | Emulation using cohort data"
    tabbed = "Protocol component\tTarget trial\tEmulated trial"
    assert _detect_protocol_table(piped)
    assert _detect_protocol_table(tabbed)
    # prose mentioning both terms (no column separator) does not false-positive
    assert not _detect_protocol_table(
        "We emulated a hypothetical target trial using observational data.")


def test_prompt_hash_stable():
    sm = parse_text(FAKE_PAPER, manuscript_id="fake-1")
    r1 = build_judge_request(sm)
    r2 = build_judge_request(sm)
    assert r1["prompt_hash"] == r2["prompt_hash"]
    assert r1["prompt_hash"].startswith("sha256:")
