"""Governance layer: pure logic over assessment output. No model calls."""

from __future__ import annotations

from typing import Any

from .spec import load_spec


def check_critical_floor(assessment: dict[str, Any]) -> dict[str, Any]:
    """Binary gate over the non-waivable leaves (BSCL overlay, not TARGET itself).

    Pass rule per spec: every floor leaf must be `reported`; `partial` fails.
    Floor leaves excluded from scoring (e.g. abstract-only ingestion) make the
    gate indeterminate rather than failed.
    """
    spec = load_spec(assessment["spec_version"])
    floor = spec["critical_floor"]
    floor_ids = list(floor["leaves"])
    verdicts = {i["id"]: i for i in assessment["items"]}
    excluded = {e["id"] for e in assessment.get("excluded_leaves", [])}

    failed, unassessed = [], []
    for lid in floor_ids:
        if lid in excluded:
            unassessed.append(lid)
        elif verdicts.get(lid, {}).get("verdict") != "reported":
            failed.append({
                "id": lid,
                "verdict": verdicts.get(lid, {}).get("verdict", "missing"),
                "rationale": verdicts.get(lid, {}).get("rationale", ""),
            })

    status = "indeterminate" if unassessed else ("fail" if failed else "pass")
    return {
        "manuscript_id": assessment["manuscript_id"],
        "spec_version": assessment["spec_version"],
        "floor_provenance": floor["provenance"],
        "floor_leaves": floor_ids,
        "status": status,
        "pass": status == "pass",
        "failed_leaves": failed,
        "unassessed_leaves": unassessed,
    }
