"""Render layer: project a finalized assessment onto the published TARGET
checklist form.

The official TARGET checklist (Cashin et al., JAMA/BMJ 2025) is an author-facing
table whose one fill-in column is *Location reported* — where in the paper each
item appears. This module turns an instrument assessment into that same form,
enriched: alongside each item's location it carries the instrument's verdict
(reported/partial/not_reported/N/A) and the verbatim evidence quote that
justifies the location.

No scoring happens here. `render_checklist` is a pure projection of an
assessment object into rows + Markdown.

The published item wording is reproduced verbatim under the checklist's
CC BY-ND 4.0 license (redistribution permitted unchanged, in whole, with
credit); see CITATION / LICENSE below. This differs from the spec YAML, which
deliberately re-words item intent and is not a substitute for the checklist.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .spec import SECTIONS, load_spec

INSTRUMENT = "TARGET MCP (Black Swan Causal Labs)"


def provenance(assessment: dict[str, Any]) -> dict[str, Any]:
    """A self-attesting provenance block binding this record to its inputs.

    `stamp` is a short code deterministically derived from the spec version, the
    hash of the exact ingested text, and the prompt hash — so a document that
    was NOT produced by this renderer cannot carry the correct stamp, and a
    consumer can detect a hand-assembled report masquerading as instrument
    output. Every rendered artifact (Markdown, HTML, .docx) carries it."""
    spec = str(assessment.get("spec_version", ""))
    text_sha = str(assessment.get("text_sha256", ""))
    prompt_hash = str(assessment.get("prompt_hash", ""))
    basis = f"{spec}|{text_sha}|{prompt_hash}|{INSTRUMENT}"
    stamp = "TGT-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12].upper()
    return {
        "instrument": INSTRUMENT,
        "spec_version": spec,
        "text_sha256": text_sha,
        "prompt_hash": prompt_hash,
        "prompt_template_version": str(assessment.get("prompt_template_version", "")),
        "extractor_version": str(assessment.get("extractor_version", "")),
        "assessed_at": str(assessment.get("assessed_at", "")),
        "mode": str(assessment.get("mode", "")),
        "model": str(assessment.get("model", "")).removeprefix("external:"),
        "stamp": stamp,
    }


def provenance_line(prov: dict[str, Any]) -> str:
    """One-line stamp for artifact footers — the value of record for detecting
    unstamped (hand-built) documents."""
    sha = prov.get("text_sha256", "") or ""
    ph = prov.get("prompt_hash", "").removeprefix("sha256:") if prov.get("prompt_hash") else ""
    return (f"Provenance — {prov.get('instrument', INSTRUMENT)} · "
            f"stamp {prov.get('stamp', '?')} · "
            f"text sha256:{sha[:12]} · spec {prov.get('spec_version', '?')}"
            + (f" · prompt {ph[:12]}" if ph else ""))

CITATION = (
    "Cashin AG, Hansford HJ, Hernán MA, Swanson SA, Lee H, Jones MD, et al. "
    "Transparent Reporting of Observational Studies Emulating a Target Trial: "
    "The TARGET Statement. JAMA 2025. doi:10.1001/jama.2025.13350 "
    "(co-published BMJ 2025;390:e087179)."
)
LICENSE = (
    "Checklist item wording © 2025 Cashin et al., reproduced verbatim under "
    "CC BY-ND 4.0."
)
TITLE = ("Transparent Reporting of Observational Studies Emulating a Target "
         "Trial (TARGET) Checklist")
SUBTITLE = "Black Swan Causal Labs — Completeness Assessment"


def instrument_line(src: dict[str, Any]) -> str:
    """One-line provenance: instrument, spec, mode, model, date, supplement.

    Accepts either a render `report` (provenance under `generated_from`) or a raw
    `assessment` (provenance at top level)."""
    gen = src.get("generated_from") or src
    model = str(gen.get("model") or "?").removeprefix("external:")
    parts = [
        f"spec {src.get('spec_version', '?')}",
        f"{gen.get('mode', '?')} mode",
        f"model {model}",
    ]
    assessed = gen.get("assessed_at")
    if assessed:
        parts.append(f"assessed {str(assessed)[:10]}")
    suppl = str(src.get("supplement_status", "not_checked")).replace("_", "-")
    parts.append(f"supplement: {suppl}")
    return "Instrument: TARGET MCP (Black Swan Causal Labs), " + " · ".join(parts)


def completeness_line(completeness: dict[str, int]) -> str:
    segs = [
        f"{completeness['reported']} Reported",
        f"{completeness['partial']} Partial",
        f"{completeness['not_reported']} Not reported",
        f"{completeness['not_applicable']} N/A",
    ]
    if completeness.get("not_assessed"):
        segs.append(f"{completeness['not_assessed']} Not assessed")
    return "Completeness: " + " · ".join(segs)

# Published checklist item wording, keyed by encoded leaf id (verbatim, CC BY-ND).
OFFICIAL_TEXT: dict[str, str] = {
    "1a": ("Identify that the study attempts to emulate a target trial using "
           "observational data. State the study objectives and briefly summarize "
           "the specified target trial."),
    "1b": "Report the data sources used for emulation.",
    "1c": "Summarize key assumptions, statistical methods, findings and conclusions.",
    "2": "Describe the scientific background of the study and the gap in knowledge.",
    "3": "Summarize the causal question.",
    "4": ("Describe the rationale for emulating a target trial with the available "
          "data. Cite randomized trials informing the design of the target trial "
          "if applicable."),
    "5": ("Cite the data sources contributing to the analyses and for each one "
          "describe the following: original purpose, type, the geographic "
          "locations, setting and time-period. If relevant, describe how the data "
          "were linked or pooled."),
    "6a": "Describe the eligibility criteria.",
    "7a": "Describe how the eligibility criteria were operationalized with the data.",
    "6b": "Describe the treatment strategies that would be compared.",
    "7b": "Describe how the treatment strategies were operationalized with the data.",
    "6c": ("Report that eligible individuals would be randomly assigned to "
           "treatment strategies and may be aware of their treatment allocation."),
    "7c": "Describe how assignment to treatment strategies was operationalized with the data.",
    "6d": ("Clarify that follow-up would start at time of assignment to the "
           "treatment strategies. Specify when follow-up would end."),
    "7d": ("Clarify that follow-up starts at the time individuals were assigned to "
           "the treatment strategies. Describe how the end of follow-up was "
           "operationalized with the data."),
    "6e": "Describe the outcomes.",
    "7e": "Describe how the outcomes were operationalized with the data.",
    "6f": "Describe the causal contrasts of interest, including effect measures.",
    "7f": ("Describe how the causal contrasts were operationalized with the data, "
           "including effect measures."),
    "6g": ("Describe assumptions that would be made to identify each causal "
           "estimand. Describe the variables, if any, related to these assumptions."),
    "7g.i": ("For each causal estimand, describe assumptions made to identify it, "
             "including assumptions regarding baseline confounding due to lack of "
             "randomization."),
    "7g.ii": ("Describe how the variables related to these assumptions were "
              "operationalized with the data."),
    "6h": ("For each causal estimand, describe the data analysis procedures and "
           "any associated statistical modelling assumptions, including approaches "
           "for handling missing data."),
    "7h.i": ("For each causal estimand, describe the data analysis procedures and "
             "any associated statistical modelling assumptions, including "
             "approaches for handling missing data."),
    "7h.ii": ("For each causal estimand, describe any additional analyses "
              "conducted to assess the sensitivity of the results to the choice of "
              "operationalizations, assumptions and analysis."),
    "8": ("Report numbers of individuals assessed for eligibility, eligible, and "
          "assigned to each treatment strategy. A flow diagram is strongly "
          "recommended."),
    "9": ("Describe the distribution of characteristics of individuals at "
          "baseline, by treatment strategy."),
    "10": ("Summarize length of follow-up and describe reasons for end of "
           "follow-up for each treatment strategy and causal contrast."),
    "11": ("Describe the frequency of missing data in all variables, by treatment "
           "strategy when applicable."),
    "12": "Describe the frequency or distribution of each outcome, by treatment strategy.",
    "13": ("Report the effect estimates for each causal contrast with "
           "corresponding measures of precision, including both absolute and "
           "relative measures of effect, when applicable."),
    "14": ("Report results of all analyses to assess the sensitivity of the "
           "estimates to choices in operationalizations, assumptions and analysis."),
    "15": "Provide an interpretation of the key findings.",
    "16": ("Discuss the limitations of the study considering differences between "
           "the target trial and its emulation and the plausibility of "
           "assumptions, including assumptions regarding baseline confounding due "
           "to lack of randomization."),
    "17": ("Provide the institutional research board or ethics committee that "
           "approved the study and approval numbers, if relevant."),
    "18": "State whether, when and where the study protocol was registered.",
    "19": ("Provide information on whether data, analytic code and/or other "
           "materials are accessible, and where and how they can be accessed."),
    "20": ("Provide the sources of funding and detail the role of the funders in "
           "the design, conduct and reporting of the study."),
    "21": "State any conflicts of interest and financial disclosures for all authors.",
}

SECTION_TITLE = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "methods": "Methods",
    "results": "Results",
    "discussion": "Discussion",
    "other": "Other information",
}

_GROUP_LABEL = {
    "eligibility_criteria": "Eligibility criteria",
    "treatment_strategies": "Treatment strategies",
    "assignment_procedures": "Assignment procedures",
    "follow_up": "Follow-up",
    "outcomes": "Outcomes",
    "causal_contrasts": "Causal contrasts",
    "identifying_assumptions": "Identifying assumptions",
    "analysis_plan": "Data analysis plan",
}

_VERDICT_DISPLAY = {
    "reported": "✓ Reported",
    "partial": "◑ Partial",
    "not_reported": "✗ Not reported",
    "not_applicable": "— N/A",
    "not_assessed": "· Not assessed",
}


def _fmt_location(section: str | None, source: str | None) -> str:
    if source and source.startswith("supplement:"):
        return f"Supplement — {source.split(':', 1)[1]}"
    title = SECTION_TITLE.get(section or "", (section or "Unknown").title())
    if source and source not in ("main", ""):
        return f"{title} ({source})"
    return title


def _location_for(item: dict[str, Any], verdict: str) -> str:
    if verdict in ("reported", "partial"):
        evidence = item.get("evidence", [])
        locs: list[str] = []
        for ev in evidence:
            if ev.get("resolved"):
                loc = _fmt_location(ev.get("section"), ev.get("source_document"))
                if loc not in locs:
                    locs.append(loc)
        if locs:
            text = "; ".join(locs)
            if any(not ev.get("resolved") for ev in evidence):
                text += " (+ unresolved quote)"
            return text
        return "Quoted; location not resolved"
    if verdict == "not_reported":
        return "Not reported"
    if verdict == "not_applicable":
        cond = (item.get("not_applicable_condition") or "").strip()
        return f"N/A — {cond}" if cond else "Not applicable"
    return "—"


def build_rows(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per encoded leaf (all 39, in checklist order), whether or not the
    leaf was scored. Excluded leaves carry verdict `not_assessed`."""
    spec = load_spec(assessment["spec_version"])
    by_leaf = {i["id"]: i for i in spec["items"]}
    scored = {i["id"]: i for i in assessment.get("items", [])}
    excluded = {e["id"]: e.get("reason", "") for e in assessment.get("excluded_leaves", [])}

    rows: list[dict[str, Any]] = []
    for leaf in spec["items"]:
        lid = leaf["id"]
        item = scored.get(lid)
        if item is not None:
            verdict = item["verdict"]
            location = _location_for(item, verdict)
            rationale = item.get("rationale", "")
            confidence = item.get("confidence")
            evidence = [
                {
                    "quote": ev.get("quote", ""),
                    "location": (_fmt_location(ev.get("section"), ev.get("source_document"))
                                 if ev.get("resolved") else "unresolved"),
                    "resolved": bool(ev.get("resolved")),
                }
                for ev in item.get("evidence", [])
            ]
        else:
            verdict = "not_assessed"
            location = excluded.get(lid, "not assessed")
            rationale = excluded.get(lid, "")
            confidence = None
            evidence = []
        rows.append({
            "id": lid,
            "item_no": leaf["item_no"],
            "role": leaf.get("role"),
            "section": leaf["section"],
            "group": _GROUP_LABEL.get(leaf.get("element", "")) if leaf.get("role") else None,
            "official_text": OFFICIAL_TEXT.get(lid, leaf["label"]),
            "verdict": verdict,
            "verdict_display": _VERDICT_DISPLAY[verdict],
            "location": location,
            "evidence": evidence,
            "rationale": rationale,
            "confidence": confidence,
        })
    return rows


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _evidence_cell(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for ev in row["evidence"]:
        q = ev["quote"].strip()
        if not q:
            continue
        mark = "" if ev["resolved"] else " *(unresolved)*"
        parts.append(f"“{q}”{mark}")
    quote_txt = " / ".join(parts)
    rationale = (row.get("rationale") or "").strip()
    if quote_txt and rationale:
        return f"{quote_txt} — {rationale}"
    return quote_txt or rationale or ""


def _item_cell(row: dict[str, Any], view: str) -> str:
    text = row["official_text"]
    if row["group"] and view == "enriched":
        role = "specification" if row["role"] == "specification" else "emulation"
        return f"**{row['group']}** _({role})_ — {text}"
    return text


def _id_cell(row: dict[str, Any]) -> str:
    return row["id"]


def render_markdown(
    assessment: dict[str, Any],
    rows: list[dict[str, Any]],
    completeness: dict[str, int],
    view: str,
    prov: dict[str, Any],
) -> str:
    mid = assessment.get("manuscript_id", "(unnamed)")
    # Full bibliographic reference of the assessed publication when supplied;
    # the short manuscript_id is only the fallback.
    manuscript_ref = assessment.get("citation") or mid

    lines = [
        f"# {TITLE}",
        f"### {SUBTITLE}",
        "",
        f"*{CITATION}*",
        "",
        f"**Manuscript assessed:** {manuscript_ref}  ",
        instrument_line(assessment),
        "",
        f"**{completeness_line(completeness)}**",
        "",
    ]

    header = (["Item", "Checklist item", "Location reported"] if view == "official"
              else ["Item", "Checklist item", "Verdict", "Location reported",
                    "Evidence & rationale"])
    rows_by_section: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_section.setdefault(row["section"], []).append(row)

    for section in SECTIONS:
        section_rows = rows_by_section.get(section)
        if not section_rows:
            continue
        lines.append(f"## {SECTION_TITLE[section]}")
        lines.append("")
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for row in section_rows:
            if view == "official":
                cells = [_id_cell(row), _cell(_item_cell(row, view)), _cell(row["location"])]
            else:
                cells = [
                    _id_cell(row),
                    _cell(_item_cell(row, view)),
                    row["verdict_display"],
                    _cell(row["location"]),
                    _cell(_evidence_cell(row)),
                ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("---")
    lines.append(f"*{provenance_line(prov)}*")
    lines.append("")
    lines.append(f"*{LICENSE}*")
    return "\n".join(lines)


def render_checklist(
    assessment: dict[str, Any],
    view: str = "enriched",
) -> dict[str, Any]:
    """Project a finalized assessment onto the TARGET checklist form.

    `view='enriched'` (default) carries verdict + evidence alongside the location
    column; `view='official'` strips to the published form's columns (Item /
    Checklist item / Location reported).
    """
    if view not in ("enriched", "official"):
        raise ValueError(f"Unknown view {view!r}; use 'enriched' or 'official'.")

    rows = build_rows(assessment)
    completeness = {v: 0 for v in
                    ("reported", "partial", "not_reported", "not_applicable", "not_assessed")}
    for row in rows:
        completeness[row["verdict"]] += 1
    completeness["total_leaves"] = len(rows)
    completeness["scored"] = len(rows) - completeness["not_assessed"]

    prov = provenance(assessment)
    markdown = render_markdown(assessment, rows, completeness, view, prov)

    return {
        "manuscript_id": assessment.get("manuscript_id", ""),
        "citation": assessment.get("citation", ""),
        "spec_version": assessment.get("spec_version", ""),
        "view": view,
        "generated_from": {
            "mode": assessment.get("mode"),
            "model": assessment.get("model"),
            "assessed_at": assessment.get("assessed_at"),
            "text_sha256": assessment.get("text_sha256"),
            "extractor_version": assessment.get("extractor_version"),
        },
        "supplement_status": assessment.get("supplement_status", "not_checked"),
        "provenance": prov,
        "completeness": completeness,
        "rows": rows,
        "markdown": markdown,
        "attribution": {
            "citation": CITATION,
            "license": LICENSE,
        },
    }
