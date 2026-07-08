"""Assessment layer: pinned-model judging of a SectionMap against the spec.

Judge mode (default): this module makes the model call itself, with a fixed
model id, temperature 0.0, and a prompt hash stamped on the result, so a
corpus run is reproducible and does not depend on the calling agent.

Scaffold mode: `build_judge_request` returns the exact prompt + schema for a
calling agent to execute; `finalize_assessment` validates and provenance-
stamps verdicts produced either way. Both modes share one validation path.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from typing import Any

from .ingest import SectionMap
from .spec import load_spec, DEFAULT_VERSION, VERDICTS

DEFAULT_JUDGE_MODEL = os.environ.get("TARGET_JUDGE_MODEL", "claude-sonnet-5")
JUDGE_TEMPERATURE = 0.0
MAX_OUTPUT_TOKENS = 16000
PROMPT_TEMPLATE_VERSION = "judge-prompt/0.1.0"

_SUBMIT_TOOL_NAME = "submit_target_assessment"


# --------------------------------------------------------------- prompt build

def _render_leaf(leaf: dict[str, Any]) -> str:
    lines = [
        f"### Leaf {leaf['id']} — {leaf['label']}",
        f"Section where evidence typically lives: {leaf['section']}",
        f"Intent: {leaf['intent'].strip()}",
        f"Verdict boundaries: {leaf['assessor_notes'].strip()}",
    ]
    if leaf.get("applicability") == "conditional":
        lines.append(f"Applicability: {leaf['applicability_rule'].strip()}")
    if leaf.get("paired_with"):
        lines.append(
            f"Paired leaf/leaves: {', '.join(leaf['paired_with'])} — score THIS leaf "
            "independently; do not credit content that only satisfies the pair."
        )
    return "\n".join(lines)


def _system_prompt(spec: dict[str, Any], leaf_ids: list[str]) -> str:
    leaves = [it for it in spec["items"] if it["id"] in set(leaf_ids)]
    rendered = "\n\n".join(_render_leaf(l) for l in leaves)
    return f"""You are a reporting-completeness assessor implementing the TARGET \
guideline (Cashin et al., JAMA/BMJ 2025) as a measurement instrument. You will \
receive a manuscript of an observational study emulating a target trial, split \
into sections. Assess each checklist leaf below against the manuscript.

Rules:
1. Verdict vocabulary: reported | partial | not_reported | not_applicable.
2. For `reported` or `partial`, you MUST supply 1-3 evidence quotes copied \
VERBATIM from the manuscript text (short spans, <=300 characters each). Do not \
paraphrase inside quotes. Quotes are machine-resolved to character offsets; a \
quote that cannot be found in the text invalidates the evidence.
3. `not_applicable` requires naming the applicability condition invoked; only \
leaves whose entry lists conditional applicability can be not_applicable.
4. Judge reporting completeness, not methodological quality: a clearly \
reported but questionable choice is still `reported`.
5. Supplementary material counts as reported only if it appears in the text \
you were given; otherwise judge on what is present.
6. confidence is your calibrated probability (0-1) that a careful human \
assessor applying the same boundaries would give the same verdict.
7. rationale: one to three sentences, grounded in the verdict boundaries.
8. Assess every leaf listed; return them in the same order.

Checklist leaves to assess ({len(leaves)} of {len(spec['items'])}; spec {spec['spec_version']}):

{rendered}"""


def _submit_tool(leaf_ids: list[str]) -> dict[str, Any]:
    return {
        "name": _SUBMIT_TOOL_NAME,
        "description": "Submit the completed TARGET assessment matrix.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "enum": leaf_ids},
                            "verdict": {"type": "string", "enum": list(VERDICTS)},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "evidence_quotes": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 3,
                            },
                            "rationale": {"type": "string"},
                            "not_applicable_condition": {"type": "string"},
                        },
                        "required": ["id", "verdict", "confidence", "rationale"],
                    },
                },
            },
            "required": ["items"],
        },
    }


def _manuscript_block(sm: SectionMap) -> str:
    parts = [f"MANUSCRIPT {sm.manuscript_id} (sections as extracted; "
             f"extractor {sm.extractor_version})"]
    for s in sm.sections:
        parts.append(f"\n<<SECTION {s.name}{' — ' + s.heading if s.heading else ''}>>\n"
                     f"{sm.full_text[s.start:s.end]}")
    return "\n".join(parts)


def select_leaves(sm: SectionMap, spec: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Full-text gating: with no methods/results sections, only
    abstract-supportable leaves are assessable."""
    present = {s.name for s in sm.sections}
    full_text = "methods" in present and "results" in present
    if full_text:
        return [it["id"] for it in spec["items"]], []
    scored = [it["id"] for it in spec["items"] if it.get("abstract_supportable")]
    excluded = [
        {"id": it["id"], "reason": "full text unavailable; leaf not abstract-supportable"}
        for it in spec["items"] if not it.get("abstract_supportable")
    ]
    return scored, excluded


def build_judge_request(
    sm: SectionMap,
    spec_version: str = DEFAULT_VERSION,
    model: str = DEFAULT_JUDGE_MODEL,
) -> dict[str, Any]:
    """The exact request judge mode sends. Also the scaffold-mode payload."""
    spec = load_spec(spec_version)
    leaf_ids, excluded = select_leaves(sm, spec)
    system = _system_prompt(spec, leaf_ids)
    tool = _submit_tool(leaf_ids)
    prompt_hash = hashlib.sha256(
        json.dumps(
            {"template": PROMPT_TEMPLATE_VERSION, "system": system, "tool": tool},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "model": model,
        "temperature": JUDGE_TEMPERATURE,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": system,
        "tool": tool,
        "user_content": _manuscript_block(sm),
        "prompt_hash": f"sha256:{prompt_hash}",
        "spec_version": spec_version,
        "leaf_ids": leaf_ids,
        "excluded_leaves": excluded,
    }


# ---------------------------------------------------------------- validation

class VerdictValidationError(ValueError):
    pass


def finalize_assessment(
    sm: SectionMap,
    raw_items: list[dict[str, Any]],
    request: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    """Validate raw verdicts, resolve evidence quotes to spans, stamp provenance."""
    spec = load_spec(request["spec_version"])
    by_id = {it["id"]: it for it in spec["items"]}
    expected = list(request["leaf_ids"])
    got = [i.get("id") for i in raw_items]
    if sorted(got) != sorted(expected):
        missing = set(expected) - set(got)
        extra = set(got) - set(expected)
        raise VerdictValidationError(
            f"Leaf coverage mismatch. missing={sorted(missing)} extra={sorted(extra)}"
        )

    items: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for raw in raw_items:
        leaf = by_id[raw["id"]]
        verdict = raw["verdict"]
        if verdict not in VERDICTS:
            raise VerdictValidationError(f"Leaf {raw['id']}: bad verdict {verdict!r}")
        if verdict == "not_applicable" and leaf.get("applicability") != "conditional":
            raise VerdictValidationError(
                f"Leaf {raw['id']}: not_applicable on an always-applicable leaf"
            )
        item: dict[str, Any] = {
            "id": raw["id"],
            "verdict": verdict,
            "confidence": float(raw.get("confidence", 0.0)),
            "rationale": str(raw.get("rationale", "")).strip(),
            "evidence": [],
        }
        if verdict == "not_applicable":
            item["not_applicable_condition"] = str(
                raw.get("not_applicable_condition", "")
            ).strip()
        if verdict in ("reported", "partial"):
            quotes = [q for q in raw.get("evidence_quotes", []) if q and q.strip()]
            if not quotes:
                raise VerdictValidationError(
                    f"Leaf {raw['id']}: verdict {verdict!r} without evidence quotes"
                )
            for q in quotes:
                span = sm.locate(q)
                if span is None:
                    item["evidence"].append(
                        {"quote": q, "span": None, "section": None, "resolved": False}
                    )
                    unresolved.append(raw["id"])
                else:
                    item["evidence"].append({
                        "quote": q,
                        "span": list(span),
                        "section": sm.section_at(span[0]),
                        "resolved": True,
                    })
        items.append(item)

    order = {lid: i for i, lid in enumerate(expected)}
    items.sort(key=lambda x: order[x["id"]])

    rollups: dict[str, dict[str, int]] = {}
    for item in items:
        sec = by_id[item["id"]]["section"]
        rollups.setdefault(sec, {v: 0 for v in VERDICTS})
        rollups[sec][item["verdict"]] += 1

    return {
        "manuscript_id": sm.manuscript_id,
        "spec_version": request["spec_version"],
        "mode": mode,
        "model": request["model"] if mode == "judge" else f"external:{request['model']}",
        "temperature": request["temperature"],
        "prompt_hash": request["prompt_hash"],
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "extractor_version": sm.extractor_version,
        "text_sha256": sm.text_sha256,
        "assessed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "full_text_available": not request["excluded_leaves"],
        "excluded_leaves": request["excluded_leaves"],
        "items": items,
        "section_rollups": rollups,
        "unresolved_evidence_leaves": sorted(set(unresolved)),
    }


# ---------------------------------------------------------------- judge mode

def run_judge(sm: SectionMap, spec_version: str = DEFAULT_VERSION,
              model: str = DEFAULT_JUDGE_MODEL) -> dict[str, Any]:
    """Judge mode: build request, call the pinned model, validate, stamp."""
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Judge mode needs ANTHROPIC_API_KEY in the environment. "
            "Alternatively use scaffold mode (build_judge_request + finalize_assessment)."
        )
    request = build_judge_request(sm, spec_version=spec_version, model=model)
    client = anthropic.Anthropic()
    call = dict(
        model=request["model"],
        max_tokens=request["max_tokens"],
        system=request["system"],
        tools=[request["tool"]],
        tool_choice={"type": "tool", "name": _SUBMIT_TOOL_NAME},
        messages=[{"role": "user", "content": request["user_content"]}],
    )
    # Newer models (e.g. claude-sonnet-5) deprecate the temperature knob and are
    # deterministic without it; older ones honor temperature=0. Send it, and on
    # the deprecation error retry without — recording which path was taken so the
    # provenance stamp stays truthful.
    temperature_applied: float | None = request["temperature"]
    try:
        response = client.messages.create(temperature=request["temperature"], **call)
    except anthropic.BadRequestError as e:
        if "temperature" not in str(e).lower():
            raise
        temperature_applied = None
        response = client.messages.create(**call)
    tool_use = next(b for b in response.content if b.type == "tool_use")
    result = finalize_assessment(sm, tool_use.input["items"], request, mode="judge")
    result["temperature"] = temperature_applied  # None => model is deterministic without the knob
    result["model"] = response.model  # resolved model id from the API, not the alias
    result["usage"] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return result
