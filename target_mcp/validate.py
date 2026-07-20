"""Validation layer: agreement of the instrument against human gold-standard coding.

The instrument produces a scientific claim ("X% of TTE studies report item Y"),
so it must be validated as a measurement instrument before a corpus run. Per the
design, agreement is reported PER ITEM, never as a single aggregate — objective
leaves (time zero defined) will agree highly, judgment leaves (causal question
adequately summarized) will be noisy, and one aggregate kappa hides that split.

This module is pure computation over:
  - instrument assessments  (assess.finalize_assessment output)
  - human codings           (same shape, minimally: manuscript_id + items[{id,verdict}])

Workflow:
  1. build_coding_sheet(assessments) -> blank, BLIND per-leaf sheets for coders.
  2. humans fill verdicts (optionally an evidence quote + note).
  3. compare(instrument, human) -> per-leaf agreement, binary sensitivity/
     specificity, and a span-keyed disagreement list for adjudication.

No model calls, no network.
"""

from __future__ import annotations

from typing import Any

from .spec import load_spec, VERDICTS

# Binarization for sensitivity/specificity: the instrument is treated as a
# detector of *adequate* reporting. Positive = "reported"; partial and
# not_reported are negative (the item was not fully reported).
POSITIVE = "reported"


def build_coding_sheet(
    assessments: list[dict[str, Any]],
    blind: bool = True,
    spec_version: str | None = None,
) -> list[dict[str, Any]]:
    """Emit blank per-paper coding sheets for human coders.

    blind=True (default) withholds the instrument's verdict and evidence so the
    coder is not anchored — the scientifically correct default. blind=False
    includes them (for adjudication or training, not primary coding).
    """
    if not assessments:
        return []
    spec_version = spec_version or assessments[0]["spec_version"]
    spec = load_spec(spec_version)
    meta = {it["id"]: it for it in spec["items"]}
    order = [it["id"] for it in spec["items"]]

    sheets = []
    for a in assessments:
        instr = {i["id"]: i for i in a["items"]}
        excluded = {e["id"] for e in a.get("excluded_leaves", [])}
        items = []
        for lid in order:
            if lid in excluded:
                continue
            leaf = meta[lid]
            row = {
                "id": lid,
                "item_no": leaf["item_no"],
                "section": leaf["section"],
                "label": leaf["label"],
                "intent": leaf["intent"].strip(),
                "verdict_boundaries": leaf["assessor_notes"].strip(),
                "verdict": None,          # coder fills: one of VERDICTS
                "evidence_quote": None,   # coder fills (optional)
                "note": None,             # coder fills (optional)
            }
            if not blind and lid in instr:
                row["_instrument_verdict"] = instr[lid]["verdict"]
                row["_instrument_evidence"] = instr[lid].get("evidence", [])
            items.append(row)
        sheets.append({
            "manuscript_id": a["manuscript_id"],
            "spec_version": spec_version,
            "coder": None,
            "blind": blind,
            "items": items,
        })
    return sheets


# ------------------------------------------------------------- agreement math

def _cohen_kappa(pairs: list[tuple[str, str]], categories: list[str]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    pa = {c: 0 for c in categories}
    pb = {c: 0 for c in categories}
    for a, b in pairs:
        pa[a] += 1
        pb[b] += 1
    pe = sum((pa[c] / n) * (pb[c] / n) for c in categories)
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else None
    return round((po - pe) / (1 - pe), 3)


def _gwet_ac1(pairs: list[tuple[str, str]], categories: list[str]) -> float | None:
    """Gwet's AC1 — robust where one category dominates (kappa's paradox)."""
    n = len(pairs)
    k = len(categories)
    if n == 0 or k < 2:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    pi = {}
    for c in categories:
        na = sum(1 for a, b in pairs if a == c)
        nb = sum(1 for a, b in pairs if b == c)
        pi[c] = (na + nb) / (2 * n)
    pe = sum(pi[c] * (1 - pi[c]) for c in categories) / (k - 1)
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else None
    return round((po - pe) / (1 - pe), 3)


def _binary_sens_spec(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """pairs are (instrument_verdict, human_verdict). Positive = reported.
    Human is the reference standard."""
    tp = fp = tn = fn = 0
    for instr, human in pairs:
        ip = instr == POSITIVE
        hp = human == POSITIVE
        if hp and ip:
            tp += 1
        elif hp and not ip:
            fn += 1
        elif not hp and ip:
            fp += 1
        else:
            tn += 1
    sens = round(tp / (tp + fn), 3) if (tp + fn) else None
    spec = round(tn / (tn + fp), 3) if (tn + fp) else None
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "sensitivity": sens, "specificity": spec}


# ------------------------------------------------------------------- compare

def compare(
    instrument_assessments: list[dict[str, Any]],
    human_codings: list[dict[str, Any]],
    spec_version: str | None = None,
) -> dict[str, Any]:
    """Per-leaf agreement between instrument and human codings.

    Only paper+leaf cells present and verdict-bearing on BOTH sides are
    compared. `not_applicable` on either side is excluded from a leaf's
    agreement (it is not a reporting-completeness judgment).
    """
    if not instrument_assessments or not human_codings:
        raise ValueError("Need both instrument assessments and human codings.")
    spec_version = spec_version or instrument_assessments[0]["spec_version"]
    spec = load_spec(spec_version)
    order = [it["id"] for it in spec["items"]]
    meta = {it["id"]: it for it in spec["items"]}

    instr_by_mid = {a["manuscript_id"]: {i["id"]: i for i in a["items"]}
                    for a in instrument_assessments}
    human_by_mid = {h["manuscript_id"]: {i["id"]: i for i in h["items"]}
                    for h in human_codings}
    shared_mids = sorted(set(instr_by_mid) & set(human_by_mid))

    # collect (instrument, human) verdict pairs per leaf
    per_leaf_pairs: dict[str, list[tuple[str, str]]] = {lid: [] for lid in order}
    disagreements: list[dict[str, Any]] = []
    for mid in shared_mids:
        iv = instr_by_mid[mid]
        hv = human_by_mid[mid]
        for lid in order:
            if lid not in iv or lid not in hv:
                continue
            a = iv[lid]["verdict"]
            b = hv[lid].get("verdict")
            if b is None or "not_applicable" in (a, b):
                continue
            per_leaf_pairs[lid].append((a, b))
            if a != b:
                disagreements.append({
                    "manuscript_id": mid, "id": lid,
                    "instrument_verdict": a, "human_verdict": b,
                    # span-keyed adjudication: point the human at the exact quote
                    "instrument_evidence": iv[lid].get("evidence", []),
                    "instrument_rationale": iv[lid].get("rationale", ""),
                    "human_note": hv[lid].get("note"),
                })

    per_leaf = []
    for lid in order:
        pairs = per_leaf_pairs[lid]
        n = len(pairs)
        if n == 0:
            continue
        raw = round(sum(1 for a, b in pairs if a == b) / n, 3)
        per_leaf.append({
            "id": lid,
            "item_no": meta[lid]["item_no"],
            "section": meta[lid]["section"],
            "label": meta[lid]["label"],
            "n": n,
            "raw_agreement": raw,
            "cohen_kappa": _cohen_kappa(pairs, list(VERDICTS)),
            "gwet_ac1": _gwet_ac1(pairs, list(VERDICTS)),
            "binary_reported": _binary_sens_spec(pairs),
        })

    all_pairs = [p for lid in order for p in per_leaf_pairs[lid]]
    corpus_binary = _binary_sens_spec(all_pairs) if all_pairs else None
    scored = [r for r in per_leaf]

    return {
        "spec_version": spec_version,
        "papers_compared": shared_mids,
        "n_papers": len(shared_mids),
        "leaves_with_data": len(scored),
        "per_leaf": per_leaf,
        # A pooled figure is provided for orientation only; per_leaf is the
        # scientifically meaningful unit (design sec 9).
        "pooled_binary_reported": corpus_binary,
        "pooled_raw_agreement": (
            round(sum(1 for a, b in all_pairs if a == b) / len(all_pairs), 3)
            if all_pairs else None
        ),
        "disagreements": sorted(disagreements, key=lambda d: (d["id"], d["manuscript_id"])),
        "n_disagreements": len(disagreements),
    }
