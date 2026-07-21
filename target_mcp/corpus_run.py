"""Concurrent corpus runner: fetch + judge many papers in parallel, then roll up.

Judge mode is one blocking API call per paper (`assess.run_judge`) and retrieval
is one blocking HTTP round-trip (`retrieve.retrieve_bundle`); both build their own
client per call, so they are thread-safe. This module pipelines a list of PMCIDs
through fetch→judge on a bounded thread pool, isolates per-paper failures (one bad
paper never sinks the batch), retries transient errors with backoff, and hands the
successful assessments to `corpus.aggregate_corpus`.

A full corpus run takes minutes-to-hours, so it is a HEADLESS entry point (the
`target-mcp-corpus` CLI), not an interactive MCP tool — a multi-hour tool call
would blow the client's request timeout. Use the CLI for batch runs and the
existing `aggregate_corpus` MCP tool to re-roll-up saved assessments.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from . import assess as _assess
from . import retrieve as _retrieve
from .corpus import aggregate_corpus
from .spec import DEFAULT_VERSION


def _is_retryable(exc: Exception) -> bool:
    """Transient errors worth a retry (rate limit, overload, network blip) vs
    permanent ones (paper not open-access, bad PMCID) that would only waste time."""
    import httpx
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    # Anthropic SDK error surface — matched by name so anthropic stays an optional
    # import and a version bump doesn't break the isinstance chain.
    name = type(exc).__name__
    if name in {"RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError"}:
        return True
    status = getattr(exc, "status_code", None)
    return status in (408, 409, 429, 500, 502, 503, 529)


def _run_one(
    pmcid: str,
    fetch_fn: Callable[..., Any],
    judge_fn: Callable[..., Any],
    *,
    spec_version: str,
    model: str | None,
    include_supplements: bool,
    max_retries: int,
) -> dict[str, Any]:
    """Fetch + judge one paper with bounded retries on transient failures.

    Returns {"pmcid", "assessment"} on success or {"pmcid", "error"} on failure —
    never raises, so a single bad paper cannot abort the pool."""
    attempt = 0
    while True:
        try:
            sm = fetch_fn(pmcid, include_supplements=include_supplements)
            kwargs = {"spec_version": spec_version}
            if model:
                kwargs["model"] = model
            assessment = judge_fn(sm, **kwargs)
            return {"pmcid": pmcid, "assessment": assessment}
        except Exception as exc:  # noqa: BLE001 — isolate per-paper failure
            if attempt < max_retries and _is_retryable(exc):
                time.sleep(min(2 ** attempt, 30))  # 1s, 2s, 4s, … capped
                attempt += 1
                continue
            return {"pmcid": pmcid, "error": f"{type(exc).__name__}: {exc}"}


def run_corpus(
    pmcids: list[str],
    *,
    spec_version: str = DEFAULT_VERSION,
    model: str | None = None,
    include_supplements: bool = True,
    max_workers: int = 8,
    max_retries: int = 2,
    out_dir: str | None = None,
    progress: Callable[[int, int, str, str], None] | None = None,
    fetch_fn: Callable[..., Any] | None = None,
    judge_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch + judge `pmcids` concurrently, then aggregate.

    `max_workers` bounds concurrency (raise it to your API rate limit's comfort;
    it also throttles Europe PMC politeness). `out_dir`, if given, receives one
    JSON per successful assessment plus aggregate/summary/failures files.
    `fetch_fn`/`judge_fn` are injectable for testing or to swap in a different
    scorer (e.g. a future Batch-API judge); they default to the real retrieval
    and judge calls. Returns the aggregate, per-paper summaries, and failures —
    plus the full assessments under `assessments` for programmatic use."""
    fetch_fn = fetch_fn or _retrieve.retrieve_bundle
    judge_fn = judge_fn or _assess.run_judge
    # Dedupe while preserving order; a repeated PMCID is almost always a mistake.
    seen: set[str] = set()
    todo = [p for p in (s.strip() for s in pmcids) if p and not (p in seen or seen.add(p))]

    assessments: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    done = 0
    total = len(todo)
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futs = {
            pool.submit(
                _run_one, pmcid, fetch_fn, judge_fn,
                spec_version=spec_version, model=model,
                include_supplements=include_supplements, max_retries=max_retries,
            ): pmcid
            for pmcid in todo
        }
        for fut in as_completed(futs):
            res = fut.result()
            done += 1
            if "assessment" in res:
                assessments.append(res["assessment"])
                status = "ok"
            else:
                failures.append({"pmcid": res["pmcid"], "error": res["error"]})
                status = "FAILED"
            if progress:
                progress(done, total, res["pmcid"], status)

    elapsed = round(time.perf_counter() - started, 1)
    aggregate = aggregate_corpus(assessments) if assessments else {"n_papers": 0}
    per_paper = [
        {
            "manuscript_id": a.get("manuscript_id"),
            "stamp": _stamp(a),
            "supplement_status": a.get("supplement_status"),
            "model": a.get("model"),
            "verdicts": _tally(a),
        }
        for a in assessments
    ]
    summary = {
        "n_requested": total,
        "n_succeeded": len(assessments),
        "n_failed": len(failures),
        "elapsed_seconds": elapsed,
        "max_workers": max_workers,
        "failures": failures,
        "per_paper": per_paper,
        "aggregate": aggregate,
    }
    if out_dir:
        _write_out(out_dir, assessments, summary)
    return {**summary, "assessments": assessments}


def _tally(assessment: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in assessment.get("items", []):
        out[it["verdict"]] = out.get(it["verdict"], 0) + 1
    return out


def _stamp(assessment: dict[str, Any]) -> str:
    from . import render as _render
    return _render.provenance(assessment)["stamp"]


def _write_out(out_dir: str, assessments: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    adir = os.path.join(out_dir, "assessments")
    os.makedirs(adir, exist_ok=True)
    for a in assessments:
        stem = str(a.get("manuscript_id") or "assessment").replace("/", "_")
        with open(os.path.join(adir, f"{stem}.json"), "w") as f:
            json.dump(a, f, indent=1, default=str)
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, default=str)
    with open(os.path.join(out_dir, "aggregate.json"), "w") as f:
        json.dump(summary["aggregate"], f, indent=1, default=str)


def _read_pmcids(path: str) -> list[str]:
    """One PMCID per line; blank lines and #-comments ignored."""
    out: list[str] = []
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(line)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        prog="target-mcp-corpus",
        description="Concurrently fetch + judge a list of PMCIDs and roll up the "
                    "TARGET completeness aggregate. Judge mode: needs ANTHROPIC_API_KEY.",
    )
    ap.add_argument("input", help="File with one PMCID per line (#-comments ok)")
    ap.add_argument("-o", "--out-dir", help="Write assessments + aggregate here")
    ap.add_argument("-j", "--workers", type=int, default=8,
                    help="Max concurrent papers (default 8; raise to your rate limit)")
    ap.add_argument("--model", default=None, help="Override the pinned judge model")
    ap.add_argument("--no-supplements", action="store_true",
                    help="Skip supplement retrieval")
    args = ap.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: judge mode needs ANTHROPIC_API_KEY in the environment.", file=sys.stderr)
        return 2

    pmcids = _read_pmcids(args.input)
    if not pmcids:
        print(f"error: no PMCIDs found in {args.input}", file=sys.stderr)
        return 2
    print(f"Running {len(pmcids)} papers, {args.workers} concurrent…", file=sys.stderr)

    def _progress(done: int, total: int, pmcid: str, status: str) -> None:
        print(f"[{done}/{total}] {pmcid}: {status}", file=sys.stderr)

    result = run_corpus(
        pmcids, model=args.model, include_supplements=not args.no_supplements,
        max_workers=args.workers, out_dir=args.out_dir, progress=_progress,
    )
    print(
        f"\nDone: {result['n_succeeded']}/{result['n_requested']} ok, "
        f"{result['n_failed']} failed, {result['elapsed_seconds']}s.",
        file=sys.stderr,
    )
    if args.out_dir:
        print(f"Wrote assessments + aggregate to {args.out_dir}", file=sys.stderr)
    else:
        json.dump(result["aggregate"], sys.stdout, indent=1, default=str)
        print()
    return 1 if result["n_failed"] and not result["n_succeeded"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
