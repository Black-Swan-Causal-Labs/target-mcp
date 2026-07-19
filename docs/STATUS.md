# Status & handoff

Snapshot for picking the project back up cold. Last updated 2026-07-19.

## What this is

An MCP server that operationalizes the **TARGET reporting guideline** (Cashin
et al., JAMA/BMJ 2025) as a deterministic, provenanced, executable scoring
engine for target-trial-emulation (TTE) studies. It scores how *completely* a
finished manuscript reports what the checklist requires — not study quality.
Built by Black Swan Causal Labs. See `README.md` for the layered architecture,
`docs/METHODS.md` for the full method, `docs/DECISIONS.md` for why things are
the way they are.

## State: functionally complete, end-to-end, not yet gold-standard calibrated

All six layers work and are exercised: spec → ingestion (supplement-aware) →
retrieval (Europe PMC) → assessment (scaffold + judge) → governance (critical
floor) → corpus aggregation, plus a validation harness. **20 tests pass**
(`.venv/bin/python -m pytest tests/ -q`).

## The nine tools

Primary interactive flow (reviewing one paper you were given):
`parse_manuscript` (+ `supplements=`) → `assess_manuscript` (scaffold, default)
→ `submit_scaffold_verdicts` → `check_critical_floor`.

Supporting: `get_checklist`, `parse_pmcid` (corpus/batch or OA-supplement fetch),
`aggregate_corpus`, `build_coding_sheet`, `validate_against_gold`. All take
structured inputs and declare output schemas.

Two assessment modes: **scaffold** (default; the agent in the loop scores, the
server validates) and **judge** (server makes its own pinned model call — for
headless/batch runs; needs `ANTHROPIC_API_KEY`).

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m pytest tests/ -q          # 20 tests
.venv/bin/target-mcp                           # stdio MCP server
```
Judge mode needs `ANTHROPIC_API_KEY` in the env (kept in a git-ignored
`.keyfile` locally; never committed). Pinned model `claude-sonnet-5`
(override `TARGET_JUDGE_MODEL`); note this model deprecates the temperature
parameter, which `run_judge` omits.

## Key files

| File | Role |
|------|------|
| `target_mcp/specs/target-0.1.0.yaml` | The 39-leaf encoded checklist (single source of truth) |
| `target_mcp/spec.py` | Load + structural validation |
| `target_mcp/ingest.py` | SectionMap, multi-doc bundles, source-tagged spans, supplement status |
| `target_mcp/retrieve.py` | Europe PMC JATS + supplement retrieval |
| `target_mcp/assess.py` | Prompt build, judge + scaffold, `finalize_assessment` (one validation path) |
| `target_mcp/governance.py` | Critical floor + indeterminate-gating |
| `target_mcp/corpus.py` | `aggregate_corpus` |
| `target_mcp/validate.py` | Blind coding sheets + per-leaf agreement |
| `target_mcp/server.py` | The 9 MCP tools, structured I/O, output schemas |
| `docs/DECISIONS.md` | Decision log — read this first |
| `docs/INGESTION-AND-SCORING-DESIGN.md` | Supplement/table/materiality design note |
| `docs/pilot-2026-07-08.md` | First corpus snapshot (n=12) |

## What was validated

- Scaffold ≈ judge agreement: 100% within-one-verdict-band on real papers.
- Supplement experiment (Dickerman PMC8693691): the supplement flips floor-critical
  verdicts — proved supplement handling is a validity requirement.
- 12-paper pilot: fully automated, 95.6% evidence resolution, finding = time zero
  reported / identifying assumptions absent. Illustrative only.

## Next steps (in rough priority)

1. **Gold-standard validation** — the binding gate before any completeness rate
   is a claim. Harness is built (`build_coding_sheet` → human coding →
   `validate_against_gold`); the human double-coding of 50–100 studies is the
   outstanding *human* effort. Consider designing the coding protocol +
   inter-coder reconciliation.
2. **Open-source prep** — LICENSE (+ CC BY-ND provenance note for the checklist),
   git-history secret scan, CONTRIBUTING/setup section.
3. **Table extraction** — a vision pass for the ~4% of evidence quotes that don't
   resolve (mostly two-column protocol tables). Design note steps 4–5.
4. **MCP 2026-07-28 follow-ups** (spec ships 2026-07-28; RC out):
   - Bump `mcp[cli]` when the stable Tier-1 Python SDK lands; smoke-test stdio.
   - Structured I/O already done.
   - Future: MCP Apps (inline interactive dashboard from the server), Tasks
     (long-running corpus batch), OAuth 2.1 (only if hosted remotely).
5. **Deferred tools** — `assess_item`, `check_emulation_coherence`,
   `export_identifiability_spec` (DAG Studio bridge), materiality layer.

## Watch-outs

- Output-schema TypedDicts must stay `total=False` with `| None` on nullable
  fields; the SDK strictly validates returns.
- The critical floor is a BSCL overlay, not TARGET — never present it as TARGET
  compliance.
- Absence ≠ finding: missing supplement → indeterminate, unresolved quote →
  flagged, no API key → scaffold. Preserve this invariant.
