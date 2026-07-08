"""Corpus layer: roll up many assessments into completeness rates and coverage.

Pure aggregation over finalized assessments (as produced by assess.finalize_
assessment) plus their floor results (governance.check_critical_floor). No model
calls, no network. This is the measurement-instrument output: per-item
completeness across a corpus, with the coverage denominators that make the
numbers honest (how many papers had full text, how many had a supplement
retrieved, how much evidence resolved).
"""

from __future__ import annotations

from typing import Any

from .spec import load_spec, VERDICTS


def aggregate_corpus(
    assessments: list[dict[str, Any]],
    floors: list[dict[str, Any]] | None = None,
    spec_version: str | None = None,
) -> dict[str, Any]:
    """Roll up a list of assessments. `floors` (optional, aligned by index or by
    manuscript_id) supplies critical-floor results for the floor distribution.
    """
    if not assessments:
        return {"n_papers": 0, "note": "no assessments supplied"}

    spec_version = spec_version or assessments[0]["spec_version"]
    spec = load_spec(spec_version)
    leaves = [it["id"] for it in spec["items"]]
    leaf_meta = {it["id"]: it for it in spec["items"]}
    floor_leaves = set(spec["critical_floor"]["leaves"])

    # --- per-leaf tallies ---
    per_leaf: dict[str, dict[str, Any]] = {
        lid: {v: 0 for v in VERDICTS} | {"excluded": 0} for lid in leaves
    }
    for a in assessments:
        excluded = {e["id"] for e in a.get("excluded_leaves", [])}
        seen = {i["id"]: i["verdict"] for i in a["items"]}
        for lid in leaves:
            if lid in excluded:
                per_leaf[lid]["excluded"] += 1
            elif lid in seen:
                per_leaf[lid][seen[lid]] += 1

    def leaf_row(lid: str) -> dict[str, Any]:
        t = per_leaf[lid]
        # denominator for "reported rate": scored and applicable (exclude
        # excluded + not_applicable)
        scored = t["reported"] + t["partial"] + t["not_reported"]
        rate = round(t["reported"] / scored, 3) if scored else None
        return {
            "id": lid,
            "item_no": leaf_meta[lid]["item_no"],
            "section": leaf_meta[lid]["section"],
            "label": leaf_meta[lid]["label"],
            "critical_floor": lid in floor_leaves,
            "reported": t["reported"], "partial": t["partial"],
            "not_reported": t["not_reported"], "not_applicable": t["not_applicable"],
            "excluded": t["excluded"],
            "reported_rate": rate,
        }

    leaf_rows = [leaf_row(lid) for lid in leaves]

    # --- coverage denominators ---
    suppl = _counter(a.get("supplement_status", "not_checked") for a in assessments)
    full_text = _counter("full_text" if a.get("full_text_available") else "abstract_only"
                         for a in assessments)

    total_ev = resolved_ev = 0
    papers_with_unresolved = 0
    for a in assessments:
        if a.get("unresolved_evidence_leaves"):
            papers_with_unresolved += 1
        for it in a["items"]:
            for ev in it.get("evidence", []):
                total_ev += 1
                if ev.get("resolved"):
                    resolved_ev += 1

    # --- floor distribution ---
    floor_dist = None
    if floors:
        by_id = {f.get("manuscript_id"): f for f in floors}
        aligned = []
        for i, a in enumerate(assessments):
            aligned.append(by_id.get(a["manuscript_id"], floors[i] if i < len(floors) else None))
        floor_dist = _counter(f["status"] for f in aligned if f)

    # --- worst-reported leaves (lowest reported_rate among scored leaves) ---
    scored_rows = [r for r in leaf_rows if r["reported_rate"] is not None]
    worst = sorted(scored_rows, key=lambda r: r["reported_rate"])[:8]

    return {
        "spec_version": spec_version,
        "n_papers": len(assessments),
        "coverage": {
            "supplement_status": suppl,
            "full_text": full_text,
            "evidence_resolution_rate": round(resolved_ev / total_ev, 3) if total_ev else None,
            "evidence_total": total_ev, "evidence_resolved": resolved_ev,
            "papers_with_unresolved_evidence": papers_with_unresolved,
        },
        "critical_floor_distribution": floor_dist,
        "per_leaf": leaf_rows,
        "lowest_reported_leaves": [
            {"id": r["id"], "label": r["label"], "reported_rate": r["reported_rate"],
             "critical_floor": r["critical_floor"]}
            for r in worst
        ],
    }


def _counter(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))
