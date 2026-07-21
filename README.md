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
  specification/emulation pairing, and applicability rules. Structurally
  validated on load (`spec.py`).
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
- **Assessment layer** — batched, single-pass scoring of all applicable leaves.
  **Scaffold mode (default)** is the path for reviewing a publication: the agent
  already in the loop is the scorer, so the server returns the exact prompt +
  schema for it to run, then validates the verdicts it submits. **Judge mode**
  is for the headless/batch case (no LLM in the loop) — the server makes its own
  pinned model call so a corpus run is reproducible and caller-independent. Both
  share one validation path that enforces leaf coverage, verdict vocabulary, and
  mandatory verbatim evidence resolved to spans with a `source_document` tag
  (`assess.py`).
- **Rendering layer** — `render_checklist` projects a finalized assessment onto
  the published TARGET checklist form (all 39 rows, verbatim item wording under
  CC BY-ND, a Location-reported column from the resolved evidence spans; the
  enriched view adds verdict + evidence). `render_checklist_docx` writes the
  same as a submission-ready Word file (`render.py`, `render_docx.py`).
- **Corpus & validation layers** — `aggregate_corpus` rolls many assessments
  into per-item completeness rates with coverage denominators (`corpus.py`);
  `validate.py` provides blind human coding-sheet generation and per-leaf
  agreement (raw, Cohen's κ, Gwet's AC1, sensitivity/specificity) against a
  gold standard.
- **Composition layer** — FastMCP server (`server.py`) exposing eleven tools.
  The primary manuscript flow is **`parse_manuscript`** (parse the file you
  were given, with `supplements=` when available) → **`assess_manuscript`** →
  **`submit_scaffold_verdicts`** → **`render_checklist`** (or
  `render_checklist_docx`). Supporting tools: `parse_pmcid` (corpus/batch or
  OA-supplement fetch), `get_checklist` (introspect the spec),
  `aggregate_corpus`, `build_coding_sheet`, and `validate_against_gold`.

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

## Reporting completeness, not a pass/fail verdict

The instrument scores how *completely* a manuscript reports what the checklist
requires — not study quality, and it issues **no pass/fail judgment**. TARGET
presents all 21 items as essential minimum items with **no tiering**, and this
tool follows suit: the output is the 39 per-leaf verdicts with evidence and a
completeness tally. (An earlier "critical floor" — a BSCL pass/fail overlay over
six leaves — was removed in 2026-07-19 as off-message and confusing; see
`docs/DECISIONS.md`.) Do not present a verdict matrix as TARGET compliance.

## Install

The server and the optional orchestration skill ship together in this repo, but
they **activate through two separate mechanisms** — installing one does not
enable the other. Getting the files (clone/download) gives you both; then do the
two activation steps below.

### 1. Install the server

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Run it standalone (stdio transport) to smoke-test:

```bash
.venv/bin/target-mcp
```

### 2. Register the server with your MCP client

Add it to the client's MCP config with an **absolute** path. For Claude Desktop
that file is `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS); for a Claude Code project use `.mcp.json`:

```json
{
  "mcpServers": {
    "target-checklist": {
      "command": "/ABSOLUTE/PATH/TO/target-mcp/.venv/bin/python",
      "args": ["-m", "target_mcp.server"]
    }
  }
}
```

Restart / reconnect the client. Confirm it exposes **11 tools** (a stale process
may show fewer — respawn it). The server is now fully usable on its own: any MCP
client can run parse → assess → submit → render in a single scaffold pass.

### 3. (Optional, Claude Code only) Activate the fan-out skill

`.claude/skills/target-checklist-fanout/` encodes the parallel-subagent
orchestration that scores the 39 leaves concurrently (~2 min vs ~20 min). It is
**an accelerator, not a dependency** — it only works in clients that can spawn
subagents (the Claude Code CLI, or the Claude Desktop **Code/Cowork** tabs; the
plain **Chat** tab cannot, and non-Claude clients like Codex ignore it). Without
it, everything still works via the single-pass fallback.

A Claude Code session discovers the skill when its working directory is this
repo. To make it available in **every** session regardless of directory, copy it
to the user scope:

```bash
mkdir -p ~/.claude/skills
cp -R .claude/skills/target-checklist-fanout ~/.claude/skills/
```

For the skill to actually run, all three must be present: the **server**
(step 2), the **skill** (this step), and a **subagent-capable client**.

### Judge mode (headless/batch, optional)

Judge mode needs `ANTHROPIC_API_KEY` in the environment. The pinned model is
`claude-sonnet-5` by default; override with `TARGET_JUDGE_MODEL`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Covers spec validation, section mapping and quote resolution, the finalize +
evidence-resolution path, evidence-required and coverage-mismatch guards,
applicability rules, abstract-only full-text gating, corpus aggregation,
the validation harness, checklist rendering (Markdown + .docx), and prompt-hash
stability.

## Licensing / commons hygiene

The encoded checklist is a re-encoding of item *intent* in own words plus
assessor notes; it does not reproduce the TARGET checklist wording verbatim.
The original checklist is © the TARGET group under CC BY-ND 4.0. When the
Explanation & Elaboration document is released, leaves flagged
`e_e_pending: true` should be re-checked and the spec bumped to a clean minor
release. Do not copy E&E text verbatim.
