# TARGET Checklist MCP Server

An MCP server that operationalizes the **TARGET** reporting guideline
(TrAnsparent ReportinG of observational studies Emulating a Target trial;
Cashin et al., JAMA/BMJ, September 2025) as a deterministic, provenanced
scoring engine for target trial emulation (TTE) studies.

This is the *executable* TARGET: not a manuscript auditor that renders an
opinion, but a measurement instrument that produces a structured,
item-by-item, evidence-linked matrix with fixed model provenance, so a
corpus-scale result is reproducible.

See `../target-mcp-server-design.md` for the full design rationale.

## Status — vertical slice

Built and proven end-to-end:

- **Spec layer** — the 21 published items decomposed into **39 scoreable leaf
  subitems**, encoded as versioned YAML (`target_mcp/specs/target-0.1.0.yaml`)
  with own-words intent, verdict boundaries, signal terms, the 6x↔7x
  specification/emulation pairing, applicability rules, and a critical-floor
  overlay. Structurally validated on load (`spec.py`).
- **Ingestion layer** — PDF/text → `SectionMap` with character-offset section
  spans, protocol-table and flow-diagram detection, extractor version + text
  hash stamps, and whitespace-insensitive quote→span resolution (`ingest.py`).
- **Assessment layer** — batched, single-pass judging of all applicable
  leaves. **Judge mode** makes the pinned model call server-side (temperature
  0, prompt hash stamped); **scaffold mode** returns the exact prompt for a
  calling agent and validates the verdicts it produces. Both share one
  validation path that enforces leaf coverage, verdict vocabulary, and
  mandatory verbatim evidence resolved to spans (`assess.py`).
- **Governance layer** — `check_critical_floor`, a pure-logic pass/fail gate
  over the non-waivable leaves (`governance.py`).
- **Composition layer** — FastMCP server exposing `get_checklist`,
  `parse_manuscript`, `assess_manuscript`, `submit_scaffold_verdicts`, and
  `check_critical_floor` (`server.py`).

Not yet built (see design doc §4): `assess_item`, `check_emulation_coherence`,
`export_identifiability_spec`, `aggregate_corpus`, and the identifier-based
(PMCID/DOI) ingestion path.

### Provenance stamped on every assessment

`spec_version`, resolved `model` id, `temperature`, `prompt_hash`,
`prompt_template_version`, `extractor_version`, `text_sha256`, `assessed_at`,
and `full_text_available`. An evidence span is only meaningful alongside the
extractor version and text hash, so all three travel together.

## Critical floor is a governance overlay, not the published guideline

TARGET presents all 21 items as essential minimum items with **no tiering**.
The non-waivable floor (`6d/7d` time zero, `6f/7f` causal estimand, `6g/7g.i`
identifying assumptions) is a **Black Swan Causal Labs** overlay for the
governed lane, stamped `provenance: bscl_overlay` and kept separable from the
encoded guideline. Do not present it as TARGET's own definition.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Run as an MCP server

```bash
.venv/bin/target-mcp          # stdio transport
```

Judge mode needs `ANTHROPIC_API_KEY` in the environment. The pinned model is
`claude-sonnet-5` by default; override with `TARGET_JUDGE_MODEL`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Covers spec validation, section mapping and quote resolution, the full
finalize + floor path, evidence-required and coverage-mismatch guards,
applicability rules, abstract-only full-text gating, and prompt-hash
stability.

## Licensing / commons hygiene

The encoded checklist is a re-encoding of item *intent* in own words plus
assessor notes; it does not reproduce the TARGET checklist wording verbatim.
The original checklist is © the TARGET group under CC BY-ND 4.0. When the
Explanation & Elaboration document is released, leaves flagged
`e_e_pending: true` should be re-checked and the spec bumped to a clean minor
release. Do not copy E&E text verbatim.
