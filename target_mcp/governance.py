"""Governance layer: pure logic over assessment output. No model calls."""

from __future__ import annotations

from typing import Any

from .ingest import SUPPLEMENT_CONFIDENT
from .spec import load_spec


def check_critical_floor(assessment: dict[str, Any]) -> dict[str, Any]:
    """Binary gate over the non-waivable leaves (BSCL overlay, not TARGET itself).

    Pass rule per spec: every floor leaf must be `reported`; `partial` fails.

    Two ways a floor failure becomes indeterminate rather than a confident fail:
      1. The leaf was excluded from scoring (e.g. abstract-only ingestion).
      2. The leaf failed but no supplement was ingested to check
         (supplement_status not in the confident set). Floor-critical content
         (estimand, identifying assumptions) routinely lives in supplements, so
         a failure without one cannot be asserted. See design note sec 1.4.
    """
    spec = load_spec(assessment["spec_version"])
    floor = spec["critical_floor"]
    floor_ids = list(floor["leaves"])
    verdicts = {i["id"]: i for i in assessment["items"]}
    excluded = {e["id"] for e in assessment.get("excluded_leaves", [])}
    suppl_status = assessment.get("supplement_status", "not_checked")
    supplement_confident = suppl_status in SUPPLEMENT_CONFIDENT

    failed, unassessed, pending_supplement = [], [], []
    for lid in floor_ids:
        if lid in excluded:
            unassessed.append(lid)
            continue
        verdict = verdicts.get(lid, {}).get("verdict", "missing")
        if verdict == "reported":
            continue
        entry = {
            "id": lid,
            "verdict": verdict,
            "rationale": verdicts.get(lid, {}).get("rationale", ""),
        }
        if supplement_confident:
            failed.append(entry)
        else:
            pending_supplement.append(entry)

    if unassessed or pending_supplement:
        status = "indeterminate"
    elif failed:
        status = "fail"
    else:
        status = "pass"

    return {
        "manuscript_id": assessment["manuscript_id"],
        "spec_version": assessment["spec_version"],
        "floor_provenance": floor["provenance"],
        "floor_leaves": floor_ids,
        "status": status,
        "pass": status == "pass",
        "supplement_status": suppl_status,
        "failed_leaves": failed,
        "unassessed_leaves": unassessed,
        "pending_supplement_leaves": pending_supplement,
    }
