# Decision log

Load-bearing decisions for the TARGET Checklist MCP server, with rationale, so a
future session (or contributor) doesn't re-litigate them. Newest first.

Format: **what** — why — status.

---

## 2026-07-19 · Structured tool I/O (inputs + output schemas)
Replaced JSON-string tool parameters with structured array/object inputs
(`submit_scaffold_verdicts(items=[...])`, `check_critical_floor(assessment={...})`,
`aggregate_corpus`/`build_coding_sheet(assessments=[...])`,
`validate_against_gold(instrument=[...], human_codings=[...])`) and declared
`outputSchema` on all nine tools via `total=False` TypedDicts.
- **Why:** the JSON-string params were a workaround; the 2026-07-28 MCP spec
  lifts tool in/output to full JSON Schema 2020-12, and the current SDK (1.28.1)
  already supports structured I/O. Cleaner, host-validatable.
- **Gotcha recorded:** the SDK *strictly validates* returns against the schema —
  a missing required field is a hard error. Hence `total=False` (optional keys)
  **and** `X | None` on nullable fields (`n_pages`, `temperature`,
  `pooled_*`, `critical_floor_distribution`). `total=False` alone does not allow
  a present-but-null value.
- Status: done, committed. `assess_manuscript` left as `dict` (polymorphic
  scaffold-vs-judge return).

## 2026-07-19 · Keep judge mode; going open source
Judge mode stays (not deleted) even though it is not used in the interactive
review case.
- **Why:** it will be reused by the separate corpus/batch project, and the
  two-mode architecture is intentional. Project will be published open source.
- **Open-source prep still TODO:** LICENSE (code license distinct from the
  CC BY-ND checklist provenance note), git-history secret scan, CONTRIBUTING.
  `.keyfile` is git-ignored and was never committed.
- Status: decision recorded; prep not yet done.

## 2026-07-19 · Scaffold is the default assessment mode
`assess_manuscript` defaults to `mode="scaffold"`; the tool is framed around
reviewing one publication.
- **Why:** the everyday case is an agent reviewing a single paper, where the LLM
  is already in the loop — so it should be the scorer. Judge mode (server makes
  its own pinned model call) is redundant there; it earns its keep only in the
  headless/batch corpus case, which lives in a separate project.
- **Judge's actual value** (for the record): pins the whole measurement process
  (model + settings + hashed prompt) server-side, so a corpus result is
  caller-independent, reproducible, and truthfully provenanced — not
  bit-determinism (LLMs aren't bit-deterministic even so).
- Status: done, committed.

## 2026-07-19 · `parse_manuscript` is the primary entry point
Framing across docs/tool descriptions leads with `parse_manuscript` (file-in);
`parse_pmcid` is the corpus/batch or OA-supplement-fetch convenience path.
- **Why:** in practice you are handed a manuscript, not a PMCID. Corollary: when
  given a manuscript, also expect its **supplement** — floor-critical content
  lives there, and `parse_manuscript` takes `supplements=`.
- Status: done, committed.

## 2026-07-08 · Supplement handling + indeterminate-gating
Multi-document ingestion with source-tagged evidence spans; Europe PMC retrieval
(JATS + PMC-hosted supplements); and the rule that a critical-floor failure with
**no supplement ingested** is reported `indeterminate`, not `fail`.
- **Why (empirical):** the Dickerman NEJM exemplar *failed* the floor on its main
  text but its estimand and identifying assumptions were in Table S1 — adding the
  supplement flipped the verdicts. High-impact journals exile methods to
  supplements, so scoring main-text-only systematically under-rates rigorous
  papers. "Absence must never look like a finding."
- `SUPPLEMENT_CONFIDENT = {retrieved, user_provided, none_exists}`; otherwise a
  floor failure is `pending_supplement`.
- Status: done, committed. See `docs/INGESTION-AND-SCORING-DESIGN.md`.

## 2026-07-08 · Materiality layer deferred; floor kept strict
Did **not** loosen completeness verdicts for "obvious" estimands; deferred a
separate materiality/design-risk scorer to a later release.
- **Why:** letting the model decide an estimand is "obvious enough" reintroduces
  the caller-dependent judgment the pinned design exists to remove. Completeness
  (did they report it?) and materiality (how much does the omission matter?) are
  different axes; keep the first pure and reproducible. Floor calibration is a
  BSCL decision, revisitable once gold-standard data exists.
- Status: deferred by user sign-off.

## 2026-07-08 · Pilot corpus run (n=12) as a shakedown, not a claim
Ran the full pipeline over 12 OA studies to prove it end-to-end and measure
coverage — explicitly *not* to estimate literature-wide reporting rates.
- **Finding:** time zero well reported (7d 0.92), estimand/identifying
  assumptions systematically absent (6g 0.00) — the gap TARGET targets.
- **Guardrail:** the numbers are not gold-standard calibrated; the validation
  harness must run before any such number is a claim.
- Status: done. `docs/pilot-2026-07-08.md`; dashboard artifact.

## 2026-07-07 · The critical floor is a BSCL overlay, not TARGET
The six-leaf non-waivable floor (time zero 6d/7d, estimand 6f/7f, identifying
assumptions 6g/7g.i) is a Black Swan Causal Labs governance overlay.
- **Why:** published TARGET presents all 21 items as essential with **no
  tiering**. Stamped `provenance: bscl_overlay` and kept structurally separable
  so a corpus result never misrepresents TARGET as tiering its own items.
- Status: foundational; enforced in the spec and every floor result.

## 2026-07-07 · Foundational build choices
- **Python + FastMCP** (`mcp[cli]`) — best PDF/scientific tooling, natural fit
  for the batch pipeline.
- **39 leaf subitems**, not 21 items — items 1/6/7 have lettered/roman subitems;
  the leaf is the unit of assessment, grouped back by `item_no`. Makes the 6x↔7x
  specification/emulation pairing machine-checkable.
- **Mandatory verbatim evidence resolved to spans** for every reported/partial
  verdict — makes results auditable and gold-standard adjudication tractable.
- **Own-words re-encoding** of item intent, never the copyrighted checklist text
  (CC BY-ND 4.0). Commons hygiene.
- Status: foundational.
