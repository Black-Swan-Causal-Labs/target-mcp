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
- **Ingestion layer** — PDF/text/docx → `SectionMap` with character-offset,
  **source-tagged** section spans (main vs `supplement:<file>`), protocol-table
  and flow-diagram detection, extractor version + text hash stamps, and
  whitespace-insensitive quote→span resolution. Supports **multi-document
  bundles** (main text + supplements) via `build_bundle` (`ingest.py`).
- **Retrieval layer** — the corpus/batch and convenience path: fetch
  open-access articles by PMCID from Europe PMC (JATS main text plus PMC-hosted
  supplementary files, merged into one bundle). Use this when there is no file
  in hand or to auto-fetch an OA paper's supplement; for a manuscript you were
  given, ingest the file directly (`retrieve.py`).
- **Assessment layer** — batched, single-pass judging of all applicable
  leaves. **Judge mode** makes the pinned model call server-side (prompt hash
  stamped; temperature omitted for models that deprecate it); **scaffold mode**
  returns the exact prompt for a calling agent and validates the verdicts it
  produces. Both share one validation path that enforces leaf coverage, verdict
  vocabulary, and mandatory verbatim evidence resolved to spans with a
  `source_document` tag (`assess.py`).
- **Governance layer** — `check_critical_floor`, a pure-logic gate over the
  non-waivable leaves. A floor failure is reported as **`indeterminate — check
  supplement`** rather than `fail` when no supplement was ingested
  (`supplement_status` not in the confident set), because floor-critical
  content routinely lives in supplements (`governance.py`).
- **Corpus & validation layers** — `aggregate_corpus` rolls many assessments
  into per-item completeness rates with coverage denominators (`corpus.py`);
  `validate.py` provides blind human coding-sheet generation and per-leaf
  agreement (raw, Cohen's κ, Gwet's AC1, sensitivity/specificity) against a
  gold standard.
- **Composition layer** — FastMCP server (`server.py`) exposing nine tools.
  The primary manuscript flow is **`parse_manuscript`** (parse the file you
  were given, with `supplements=` when available) → **`assess_manuscript`** →
  **`check_critical_floor`**. Supporting tools: `parse_pmcid` (corpus/batch or
  OA-supplement fetch), `submit_scaffold_verdicts` (scaffold-mode completion),
  `get_checklist` (introspect the spec), `aggregate_corpus`,
  `build_coding_sheet`, and `validate_against_gold`.

Not yet built (see design doc): `assess_item`, `check_emulation_coherence`,
`export_identifiability_spec`, publisher-site supplement retrieval (beyond the
PMC-OA tier), better table extraction, and the separate materiality/design-risk
layer.

### Provenance stamped on every assessment

`spec_version`, resolved `model` id, `temperature`, `prompt_hash`,
`prompt_template_version`, `extractor_version`, `text_sha256`, `assessed_at`,
`full_text_available`, `supplement_status`, and a per-source `documents` list;
each evidence item carries its resolved span, section, and `source_document`.
A span is only meaningful alongside the extractor version and text hash, so
they travel together.

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
