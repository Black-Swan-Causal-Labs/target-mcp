# Status & handoff

Snapshot for picking the project back up cold. Last updated 2026-07-20.

## What this is

An MCP server that operationalizes the **TARGET reporting guideline** (Cashin
et al., JAMA/BMJ 2025) as a deterministic, provenanced, executable scoring
engine for target-trial-emulation (TTE) studies. It scores how *completely* a
finished manuscript reports what the checklist requires — not study quality.
Built by Black Swan Causal Labs. See `README.md` for the layered architecture,
`docs/METHODS.md` for the full method, `docs/DECISIONS.md` for why things are
the way they are.

## State: functionally complete, end-to-end, not yet gold-standard calibrated

All layers work and are exercised: spec → ingestion (supplement-aware) →
retrieval (Europe PMC) → assessment (scaffold + judge) → rendering (completed
checklist form, Markdown + .docx) → corpus aggregation, plus a validation
harness. **35 tests pass** (`.venv/bin/python -m pytest tests/ -q`).

> **The critical floor was removed (2026-07-19).** It was a BSCL pass/fail
> overlay over six leaves — not part of published TARGET, and a source of
> confusion (it read as a quality gate layered on completeness scoring). The
> tool now outputs verdicts + evidence + a completeness tally, with no pass/fail
> claim. See DECISIONS.md.

## The eleven tools

Primary interactive flow (reviewing one paper you were given):
`parse_manuscript` (+ `supplements=`) → `assess_manuscript` (scaffold, default)
→ `submit_scaffold_verdicts`, which **returns the finished, provenance-stamped
deliverable inline** in its `report` — **HTML only by default** (opt into
markdown/docx via `report_formats=`). That stamped render is the **artifact of
record** — no separate render step to skip. `render_checklist` /
`render_checklist_docx` / `render_checklist_html` re-render the same stamped
artifact on demand (different view, logo, format). The default was slimmed from
Markdown+HTML+docx (2026-07-20): the triple bundle both burned the caller's
context window and caused a real 4-minute client timeout under Claude Desktop.

**Anti-drift design (2026-07-20):** an agent once hand-built its own Word doc
instead of the sanctioned render, inheriting the checklist's authority without
provenance. The fix is structural, not advisory: (1) the deliverable falls out of
`submit` so there's nothing to skip; (2) `render.provenance()` stamps every
artifact with a short `stamp` (TGT-…) bound to spec+text-sha256+prompt-hash — in
Markdown/HTML footers, HTML `<meta>`, and `.docx` core properties — so a
hand-built doc is detectable; (3) tool language names the stamped `report` the
artifact of record and permits an analytic memo only if labeled commentary that
cites the stamp. See DECISIONS.md.

`render_checklist` projects a finalized assessment onto the published TARGET
checklist form: all 39 leaf rows in checklist order with the verbatim published
item wording (reproduced under CC BY-ND, in `render.py`'s `OFFICIAL_TEXT`) and a
Location-reported column derived from the resolved evidence spans. Default
`view='enriched'` adds per-leaf verdict and evidence quote; `view='official'`
strips to the published columns. Pure projection — no re-scoring. Returns
structured rows + a ready-to-display Markdown table. `render_checklist_docx`
writes the same content to a submission-ready landscape Word file
(`render_docx.py`, python-docx; one table per section, colored verdicts) and
returns the file bytes as `content_base64` (the server-side `path` is not the
caller's filesystem, so agents must use the base64); same `view` param. Optional `logo=True` heads the doc with the
published TARGET banner (bundled `assets/target-logo.png`, extracted from the
official editable checklist) but ONLY on `view='official'` (the author
self-report form); it is a no-op on the enriched third-party assessment, where
the official mark would imply an endorsement the instrument doesn't carry. Off
by default; the returned `logo_applied` reports what happened.

Supporting: `get_checklist`, `parse_pmcid` (corpus/batch or OA-supplement fetch),
`aggregate_corpus`, `build_coding_sheet`, `validate_against_gold`. All take
structured inputs and declare output schemas.

Two assessment modes: **scaffold** (default; the agent in the loop scores, the
server validates) and **judge** (server makes its own pinned model call — for
headless/batch runs; needs `ANTHROPIC_API_KEY`).

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m pytest tests/ -q          # 35 tests
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
| `target_mcp/ingest.py` | SectionMap, pypdf→pdfplumber extraction, path-vs-text guard, source-tagged spans |
| `target_mcp/retrieve.py` | Europe PMC JATS + supplement retrieval |
| `target_mcp/assess.py` | Prompt build, judge + scaffold, `finalize_assessment` (one validation path) |
| `target_mcp/render.py` | Completed-checklist projection (published wording, Location column) |
| `target_mcp/render_docx.py` | .docx serializer of a render_checklist report (python-docx) |
| `target_mcp/render_html.py` | self-contained HTML serializer (canvas theme, provenance stamp) |
| `target_mcp/corpus.py` | `aggregate_corpus` |
| `target_mcp/validate.py` | Blind coding sheets + per-leaf agreement |
| `target_mcp/server.py` | The 11 MCP tools, structured I/O, output schemas |
| `docs/DECISIONS.md` | Decision log — read this first |
| `docs/INGESTION-AND-SCORING-DESIGN.md` | Supplement/table/materiality design note |
| `docs/pilot-2026-07-08.md` | First corpus snapshot (n=12) |

## What was validated

- Scaffold ≈ judge agreement: 100% within-one-verdict-band on real papers.
- Supplement experiment (Dickerman PMC8693691): the supplement flips verdicts on
  the estimand/assumptions leaves — proved supplement handling is a validity
  requirement.
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
- The tool scores reporting completeness, not study quality, and makes no
  pass/fail claim (the critical floor was removed) — never present a verdict
  matrix as TARGET compliance or study adequacy.
- Absence ≠ finding: an unresolved quote is flagged not silently accepted, and
  no API key → scaffold not failure. `supplement_status` is surfaced on every
  render so a reader can weight not_reported verdicts that may reflect an
  un-ingested appendix. Preserve this invariant.
- Agent-boundary I/O: the server's filesystem is not the caller's. `document`
  file paths must be readable on the SERVER host — an agent's uploaded files
  (mounts/sandboxes) are not, so pass the manuscript TEXT or a PMCID. The docx
  deliverable comes back as `content_base64`, not via its server-side `path`.
- Output-schema gotcha (cost a "success looks like failure" bug): `total=False`
  emits `default: null` for every field, so any object-typed field that can be
  ABSENT (e.g. `usage`, only in judge mode) must be typed `dict | None` or a
  default-filling validator injects null and fails `type: object` on return.
- Runtime is NOT a bug. A full assessment can take ~20 min per paper. This is
  expected and is entirely model-generation time, not the tools: profiled on an
  11pp paper + 28pp supplement, all deterministic tool steps (parse, extract,
  build request, finalize, render) total **~0.4s**; evidence-span resolution is
  ~3ms/quote. The minutes are the in-loop model (scaffold mode = the desktop
  model IS the scorer) reading the whole paper + all 39 leaf rubrics and emitting
  39 evidence-backed verdicts in one careful pass, with thinking. That
  thoroughness is the point — do not "optimize the tools" to chase it. Levers
  exist if ever wanted (judge mode = one bounded API call, likely far faster;
  a lean-rubric scaffold prompt), but the user reviewed the tradeoffs and chose
  to leave it as-is.
