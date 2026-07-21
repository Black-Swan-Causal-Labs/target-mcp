"""Concurrent corpus runner: mechanics via injected fetch/judge (no net, no API)."""

import json

from target_mcp.corpus_run import run_corpus, _read_pmcids, _is_retryable
from target_mcp.spec import load_spec

LEAVES = [it["id"] for it in load_spec()["items"]]


def _fake_fetch(pmcid, include_supplements=True):
    return {"pmcid": pmcid}  # judge_fn is also fake, so the type is irrelevant


def _make_judge(fail_on=(), transient_once=()):
    calls = {}

    def judge(sm, spec_version="target-0.1.0", model=None):
        pmcid = sm["pmcid"]
        if pmcid in fail_on:
            raise RuntimeError("No JATS full text available")  # permanent
        if pmcid in transient_once and calls.get(pmcid, 0) == 0:
            calls[pmcid] = 1
            raise _RateLimit("slow down")  # retryable by type name
        return {
            "manuscript_id": pmcid, "spec_version": spec_version,
            "text_sha256": f"sha-{pmcid}", "prompt_hash": "sha256:deadbeef",
            "supplement_status": "retrieved", "model": model or "claude-sonnet-5",
            "excluded_leaves": [],
            "items": [{"id": lid, "verdict": "reported", "evidence": []} for lid in LEAVES],
        }
    return judge


class _RateLimit(Exception):
    pass


# _is_retryable matches on the exception CLASS name; give the class the name the
# real Anthropic SDK uses so the retry path is exercised without importing it.
_RateLimit.__name__ = "RateLimitError"


def test_all_succeed_and_aggregate():
    ids = [f"PMC{i}" for i in range(5)]
    res = run_corpus(ids, fetch_fn=_fake_fetch, judge_fn=_make_judge(), max_workers=4)
    assert res["n_requested"] == 5 and res["n_succeeded"] == 5 and res["n_failed"] == 0
    assert len(res["assessments"]) == 5
    assert res["aggregate"]["n_papers"] == 5
    # per-paper summaries carry a provenance stamp + verdict tally
    assert all(p["stamp"].startswith("TGT-") for p in res["per_paper"])
    assert res["per_paper"][0]["verdicts"]["reported"] == 39


def test_failure_is_isolated_not_fatal():
    ids = ["PMC1", "PMC2", "PMCBAD", "PMC3"]
    res = run_corpus(ids, fetch_fn=_fake_fetch,
                     judge_fn=_make_judge(fail_on={"PMCBAD"}), max_workers=4)
    assert res["n_succeeded"] == 3 and res["n_failed"] == 1
    assert res["failures"][0]["pmcid"] == "PMCBAD"
    assert "No JATS" in res["failures"][0]["error"]
    # the batch still aggregated the 3 good papers
    assert res["aggregate"]["n_papers"] == 3


def test_transient_error_is_retried():
    res = run_corpus(["PMCFLAKY"], fetch_fn=_fake_fetch,
                     judge_fn=_make_judge(transient_once={"PMCFLAKY"}),
                     max_workers=1, max_retries=2)
    assert res["n_succeeded"] == 1 and res["n_failed"] == 0


def test_permanent_error_not_retried_quickly():
    # a RuntimeError is not retryable → recorded immediately, no wasted attempts
    assert _is_retryable(RuntimeError("nope")) is False
    assert _is_retryable(_RateLimit("x")) is True


def test_duplicate_pmcids_deduped():
    res = run_corpus(["PMC1", "PMC1", "PMC2"], fetch_fn=_fake_fetch,
                     judge_fn=_make_judge(), max_workers=2)
    assert res["n_requested"] == 2 and res["n_succeeded"] == 2


def test_out_dir_written(tmp_path):
    ids = ["PMC1", "PMC2"]
    res = run_corpus(ids, fetch_fn=_fake_fetch, judge_fn=_make_judge(),
                     out_dir=str(tmp_path), max_workers=2)
    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "aggregate.json").exists()
    assert (tmp_path / "assessments" / "PMC1.json").exists()
    saved = json.loads((tmp_path / "assessments" / "PMC2.json").read_text())
    assert saved["manuscript_id"] == "PMC2" and len(saved["items"]) == 39
    # summary.json omits the heavy full assessments (those live in assessments/)
    summ = json.loads((tmp_path / "summary.json").read_text())
    assert "assessments" not in summ and summ["n_succeeded"] == 2


def test_read_pmcids_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / "ids.txt"
    p.write_text("PMC1\n\n# a comment\nPMC2  # trailing\n   \nPMC3\n")
    assert _read_pmcids(str(p)) == ["PMC1", "PMC2", "PMC3"]
