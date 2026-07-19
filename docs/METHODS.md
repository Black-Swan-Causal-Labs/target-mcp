# TARGET Checklist MCP Server — Methods

**Black Swan Causal Labs**
Instrument version: spec `target-0.1.0`, ingest `target-mcp-ingest/0.1.0`, judge prompt `judge-prompt/0.1.0`
Document date: 2026-07-08
Status: vertical-slice build, internally validated on one reference manuscript

---

## 1. Background and rationale

### 1.1 The TARGET guideline

TARGET (**TrAnsparent ReportinG of observational studies Emulating a Target
trial**) is a reporting guideline published simultaneously in JAMA and BMJ in
September 2025 (Cashin AG, Hansford HJ, Hernán MA, et al. JAMA 2025,
doi:10.1001/jama.2025.13350; BMJ 2025;390:e087179). It was developed under the
EQUATOR framework through a systematic review, a two-round expert survey, a
three-day consensus meeting, and internal/external piloting.

TARGET gives reporting guidance for observational studies that estimate causal
effects by explicitly emulating a **target trial** — a hypothetical pragmatic,
parallel-group, individually randomized trial, with adjustment for baseline
confounding. Its distinctive structure is the **target-trial-specification /
emulation pairing**: item 6 (subitems 6a–6h) specifies what the hypothetical
trial protocol would say for each protocol element, and item 7 (subitems
7a–7h) describes how each element was mapped to the observational data. The
published checklist is 21 items across six sections (abstract, introduction,
methods, results, discussion, other information).

### 1.2 The problem this server addresses

The published checklist is a prose instrument: a reader (human or LLM) reads
the checklist and a manuscript and forms a completeness judgment. That form is
fine for auditing one paper, but it does not support a **reproducible,
corpus-scale measurement** — where the scientific claim is of the form "X% of
target-trial-emulation studies report item Y." A prose-checklist judgment
varies with whichever agent, model, and prompt happened to run it, and it
leaves no audit trail linking a verdict to specific manuscript text.

This server re-casts TARGET as an **executable, deterministic, provenanced
scoring engine**: a measurement instrument, not an opinion generator. It
produces an item-by-item, evidence-linked matrix with fixed model provenance
stamped on every result, so a corpus result is reproducible and each verdict
is auditable back to the manuscript span that supports it.

### 1.3 Design commitments

Four properties motivate building a server rather than reusing a prose
checklist:

1. **Deterministic and pinned.** Scoring uses a fixed model id, temperature
   0, and a prompt hash stamped on every result. A corpus result does not
   depend on the caller.
2. **Corpus-scale.** Built to score many manuscripts and roll up per-item
   completeness rates in one batched pass per manuscript, not 39 calls per
   paper.
3. **Provenanced.** Every non-trivial verdict carries a verbatim evidence
   quote resolved to a character span, which makes results auditable and makes
   gold-standard adjudication tractable (disagreements point at a span).
4. **Composable.** Exposed as MCP tools so it can act as a completeness gate
   in a governed pipeline and hand off to downstream identifiability tooling.

---

## 2. Architecture

The server is Python (≥3.11) built on the official MCP Python SDK
(`mcp[cli]`, FastMCP). It is organized as the six layers of the design, bottom
to top. Each layer is a module in `target_mcp/`.

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Spec | `spec.py` + `specs/target-0.1.0.yaml` | Versioned, validated encoded checklist — single source of truth |
| Ingestion | `ingest.py` | Document → `SectionMap` with character-offset spans |
| Assessment | `assess.py` | Pinned-model judging; prompt construction; verdict validation and provenance |
| Governance | `governance.py` | Pure-logic critical-floor gate over assessment output |
| Composition | `server.py` | The MCP tool surface |
| (Batch/corpus) | — | Deferred to a batch wrapper over the same engine |

Dependencies: `mcp[cli]`, `pypdf` (PDF text extraction), `pyyaml` (spec
loading), `anthropic` (judge-mode model calls), `httpx`.

---

## 3. Spec layer — the encoded checklist

### 3.1 Decomposition to leaf subitems

The 21 published items decompose into **39 scoreable leaf subitems**, because
items 1, 6, and 7 carry lettered/roman subitems (e.g. 6a–6h, 7a–7h, with 7g
and 7h further split into .i/.ii). The **leaf** is the unit of assessment;
each leaf records `item_no` so leaves roll back up to the 21 published items.
Leaf distribution by section:

| Section | Leaves |
|---------|-------:|
| abstract | 3 |
| introduction | 3 |
| methods | 19 |
| results | 7 |
| discussion | 2 |
| other information | 5 |
| **Total** | **39** |

The concentration in methods (19/39) reflects that the specification/emulation
protocol elements (6a–h, 7a–h) all live there, and is the empirical basis for
full-text gating (§4.3): the guideline cannot be meaningfully scored from an
abstract alone.

### 3.2 What each leaf encodes

Each leaf is a YAML record. It re-encodes item **intent in original words**
plus assessor guidance; it does **not** reproduce the copyrighted checklist
wording. Fields:

- `id`, `item_no`, `label`, `section`, `element` — identity and grouping.
- `role` — `specification` (6x), `emulation` (7x), or `null` (unpaired).
- `paired_with` — the specification↔emulation link (e.g. `6a`↔`7a`; `6g`
  pairs with both `7g.i` and `7g.ii`). Pairing symmetry is enforced at load.
- `applicability` — `always` or `conditional`; conditional leaves (14 of 39)
  carry an `applicability_rule` naming the condition under which a
  `not_applicable` verdict is legitimate.
- `critical_floor` — boolean floor-membership flag (see §5).
- `abstract_supportable` — whether the leaf can be judged from an abstract
  alone (3 of 39: items 1a/1b/1c). Drives full-text gating.
- `objective_prefilter` — whether the leaf is objective enough for a
  deterministic pre-filter (9 of 39; e.g. registration, ethics, funding
  presence). Reserved for a future optimization; not yet applied.
- `intent` — own-words summary of what the item asks the author to report.
- `assessor_notes` — the boundaries that distinguish `reported` / `partial` /
  `not_reported` for this leaf. This is the operative rubric.
- `signal_terms` — lexical cues (not decisive, but useful for pre-filters).
- `e_e_pending` — flags leaves whose semantics should be re-checked when the
  TARGET Explanation & Elaboration document is released (currently all leaves,
  since the E&E is not yet published).

### 3.3 Verdict vocabulary and evidence policy

Fixed vocabulary: **`reported`**, **`partial`**, **`not_reported`**,
**`not_applicable`**. Policy: any `reported` or `partial` verdict **must**
carry at least one verbatim evidence quote resolvable to a manuscript span;
`not_applicable` is legal only on conditional leaves and must name the
condition invoked.

### 3.4 Load-time validation

`spec.py` validates the spec on load and refuses a malformed file: exactly 39
unique leaf ids, `item_no` covering 1–21, valid section names, symmetric
`paired_with` links, an `applicability_rule` present on every conditional
leaf, and agreement between the declared `critical_floor.leaves` list and the
per-leaf `critical_floor` flags. This turns the spec into a checked artifact
rather than a trusted one.

### 3.5 Versioning

The spec is addressed by version (`target-0.1.0`). The E&E document, when
released, will sharpen several leaf boundaries; that pass becomes a clean
minor release, and existing assessments remain interpretable against the
version stamped on them.

---

## 4. Ingestion layer — document to SectionMap

### 4.1 SectionMap

Ingestion converts a document into a `SectionMap`: the normalized full text
plus a list of `Section` records, each with a canonical name and `[start,
end)` character offsets into that text. All downstream evidence spans are
offsets into this text, so the map also carries an **extractor version** and a
**SHA-256 of the normalized text**. A span is only meaningful alongside those
two values — they travel together through every assessment.

### 4.2 Pipeline

1. **Extraction.** PDFs via `pypdf` (page text concatenated); text/`.pdf`
   files and raw text strings are all accepted by a single `parse_document`
   dispatcher.
2. **Normalization.** Unicode NFKC, newline canonicalization, and
   de-hyphenation of line-break hyphens (`confound-\ning` → `confounding`).
3. **Section detection.** Heading patterns match canonical sections
   (abstract, introduction, methods, results, discussion, other) on short
   standalone lines. Only the first occurrence of each section is kept, order
   is required to be non-regressing (a "Results" heading appearing before
   "Methods" is treated as a running-header artifact and ignored), and
   front-matter before the first heading is mapped to `abstract` when no
   explicit Abstract heading exists (common in journal styling). Undetected
   sections are recorded as warnings rather than silently dropped.
4. **Structural detection.** Regexes flag whether a **target-trial protocol
   table** and a **participant flow diagram** are present — both are
   TARGET-relevant reporting features (items 6/7 and item 8 respectively).
5. **Quote resolution.** `SectionMap.locate(quote)` resolves a verbatim quote
   to a `[start, end)` span using **whitespace-insensitive** matching: both
   sides are collapsed to single spaces, matched case-insensitively, then
   mapped back to original offsets. This tolerates the line-wrapping and
   spacing noise of PDF extraction while still requiring the actual words.
   `section_at(offset)` names the section a span falls in.

### 4.3 Full-text gating

Because 36 of 39 leaves live in methods/results and cannot be supported by an
abstract, the assessment layer inspects the SectionMap: if methods **and**
results sections are both absent, only the 3 abstract-supportable leaves are
scored and the other 36 are returned as **explicitly excluded** (with reason),
never silently marked `not_reported`. This makes the full-text ceiling on
corpus assessment visible in the output instead of hidden.

---

## 5. Assessment layer — pinned-model judging

### 5.1 One batched pass

`assess_manuscript` scores every applicable leaf for a manuscript in a
**single** structured model call, not one call per leaf. The model is forced
to return its verdicts through a `submit_target_assessment` tool whose schema
constrains the shape (leaf id enum, verdict enum, confidence 0–1, up to three
evidence quotes, rationale). This is the dominant cost lever for corpus-scale
runs.

### 5.2 Two modes, one validation path

- **Scaffold mode (default).** The path for reviewing a publication. The server
  returns the exact system prompt, tool schema, manuscript payload, and prompt
  hash for the agent already in the loop to execute, then validates the verdicts
  that agent produces. In an agentic setup the reviewing Claude *is* the scorer,
  so making the server spin up a second, separate model call is redundant — the
  server's job is to supply the rubric and validate the output.
- **Judge mode.** For the headless/batch case where no LLM is in the loop (e.g.
  a corpus run driven by a script). The server makes its own model call with a
  **pinned model** (default `claude-sonnet-5`, overridable via
  `TARGET_JUDGE_MODEL`; temperature omitted for models that deprecate it),
  requiring `ANTHROPIC_API_KEY`, so a corpus result is reproducible and does not
  vary with the caller. Overkill when an agent is already reviewing the paper.

Both modes converge on **one validation function** (`finalize_assessment`), so
verdicts are held to identical rules regardless of who produced them.

### 5.3 Prompt construction and hashing

The system prompt renders each in-scope leaf (label, section, intent,
verdict boundaries, applicability rule, and pairing note instructing
independent scoring of paired leaves) plus the fixed judging rules
(vocabulary, mandatory verbatim evidence, completeness-not-quality, confidence
as calibrated agreement probability). A **SHA-256 prompt hash** is computed
over the prompt template version, the rendered system prompt, and the tool
schema, and is stamped on the result. Identical inputs produce an identical
hash (verified by test), so any change to the encoded rubric or rules is
detectable in the provenance.

### 5.4 Validation and evidence resolution (`finalize_assessment`)

Every raw verdict set is validated before it becomes a result:

- **Leaf coverage** — the returned leaf ids must exactly match the in-scope
  set (missing or extra leaves raise an error).
- **Verdict legality** — verdict in vocabulary; `not_applicable` only on
  conditional leaves.
- **Mandatory evidence** — `reported`/`partial` without an evidence quote is
  rejected. Each quote is run through `SectionMap.locate`; resolved quotes get
  a span and section, unresolved quotes are retained but marked
  `resolved: false` and the leaf id is listed in
  `unresolved_evidence_leaves`. Unresolved evidence is surfaced, never
  silently discarded.

The finalized result is provenance-stamped with: `spec_version`, resolved
`model` id, `temperature`, `prompt_hash`, `prompt_template_version`,
`extractor_version`, `text_sha256`, `assessed_at`, `full_text_available`, the
per-leaf items (verdict, confidence, rationale, resolved evidence),
`section_rollups` (per-section verdict counts), and `excluded_leaves`.

---

## 6. Governance layer — the critical floor

`check_critical_floor` is a **pure-logic** pass/fail gate (no model call) over
a designated set of non-waivable leaves. The floor covers three pillars, each
requiring **both** the specification leaf and its emulation leaf:

| Pillar | Leaves |
|--------|--------|
| Time zero (eligibility/assignment/follow-up alignment; immortal-time control) | `6d`, `7d` |
| Causal estimand actually stated | `6f`, `7f` |
| Identifying assumptions, incl. baseline confounding | `6g`, `7g.i` |

**Pass rule:** every floor leaf must be `reported` (a `partial` fails). Floor
leaves that were excluded from scoring (e.g. under abstract-only ingestion)
make the gate **indeterminate** rather than falsely failing it.

> **Provenance caveat — this floor is not part of published TARGET.** TARGET
> presents all 21 items as essential minimum items with **no tiering**. The
> critical floor is a **Black Swan Causal Labs governance overlay** for a
> governed pipeline lane. It is stamped `provenance: bscl_overlay` in the spec
> and in every gate result, and is kept structurally separable so a corpus
> result never misrepresents TARGET as tiering its own items.

---

## 7. Tool surface (MCP)

The FastMCP server registers nine tools.

**Primary manuscript flow** — the everyday path, when you have been given a
paper as a file:

| Tool | Input | Returns |
|------|-------|---------|
| `parse_manuscript` | `document` (PDF/text/docx path or raw text), `manuscript_id`, `supplements` (file paths), `supplement_status` | **Primary entry point.** SectionMap summary: source-tagged section boundaries (main vs `supplement:<file>`) with offsets, protocol-table/flow-diagram flags, `supplement_status`, and the `text_sha256` used to key later calls. Pass the supplement when you have it — floor-critical content often lives there. |
| `assess_manuscript` | `document`, `manuscript_id`, `spec_version`, `mode` (`judge`/`scaffold`), `model` | Judge mode: the full validated, provenance-stamped 39-leaf matrix. Scaffold mode: the exact prompt, tool schema, and prompt hash for the caller to execute. |
| `check_critical_floor` | `assessment_json` **or** `manuscript_id` | Pass / fail / indeterminate over the floor leaves. `indeterminate` when a floor leaf failed but no supplement was ingested to check. |

The recommended flow is therefore `parse_manuscript` → `assess_manuscript` →
`check_critical_floor`.

**Supporting tools:**

| Tool | Input | Returns |
|------|-------|---------|
| `get_checklist` | `version` (optional) | The full encoded spec: 39 leaves with intent, assessor notes, signal terms, pairing, applicability, the critical-floor overlay, verdict vocabulary, and evidence policy. |
| `parse_pmcid` | `pmcid`, `include_supplements` | Convenience/batch entry: fetch an open-access article from Europe PMC (JATS main text + PMC-hosted supplements). For the corpus case or to auto-grab an OA supplement — not the path for a manuscript you were handed. |
| `submit_scaffold_verdicts` | `text_sha256`, `items_json`, `spec_version`, `model` | Scaffold-mode completion: validates caller-produced verdicts through the same path judge mode uses and returns the stamped assessment. |
| `aggregate_corpus` | `assessments_json` **or** `use_session` | Per-item completeness rates plus coverage denominators (supplement status, full-text, evidence resolution) and the critical-floor distribution. |
| `build_coding_sheet` | `assessments_json`/`use_session`, `blind` | Blank, blind per-leaf coding sheets for human gold-standard coders (instrument verdicts withheld by default). |
| `validate_against_gold` | `instrument_json`, `human_codings_json` | Per-leaf agreement (raw, Cohen's κ, Gwet's AC1, sensitivity/specificity) with a span-keyed disagreement list. |

Parsed manuscripts are cached in-process by text hash, and assessments by
manuscript id, so `assess_manuscript` and `check_critical_floor` can reference
prior work by id instead of re-supplying documents.

### 7.1 What it can and cannot do today

**Can:** introspect the encoded 39-leaf spec; ingest a PDF/text/docx manuscript
and its supplements into an offset-addressed, source-tagged SectionMap with
protocol-table and flow-diagram detection; fetch open-access papers by PMCID
(JATS + PMC-hosted supplements) for the batch case; score all applicable leaves
in one batched pass in either judge or scaffold mode with mandatory evidence
resolved to spans and full provenance; apply full-text and supplement gating;
run the critical-floor gate; roll up many assessments into per-item completeness
rates (`aggregate_corpus`); and validate against human gold-standard coding
(`build_coding_sheet`, `validate_against_gold`).

**Not yet (deferred per the build order):** `assess_item` (single-leaf
re-checks); `check_emulation_coherence` (cross-element specification↔emulation
coherence); `export_identifiability_spec` (the DAG Studio identifiability
bridge); publisher-site supplement retrieval beyond the PMC open-access tier;
better protocol-table extraction; the separate materiality/design-risk layer;
and the deterministic objective pre-filters (the `objective_prefilter` flags are
encoded but not yet wired into scoring).

---

## 8. Initial validation

### 8.1 Purpose and scope

This is an **internal shakedown of the pipeline on one reference manuscript**,
not the gold-standard validation that must precede any corpus run. Its goal
was to confirm the full path — parse → score all 39 leaves → resolve evidence
to spans → run the floor gate — executes correctly on a real
target-trial-emulation paper and produces defensible, auditable output. It is
not a measure of the instrument's accuracy against a human reference standard.

### 8.2 Reference manuscript

Xie Y, Bowe B, Al-Aly Z. *Molnupiravir and risk of hospital admission or death
in adults with covid-19: emulation of a randomized target trial using
electronic health records* (BMJ 2023;380:e072705; doi:10.1136/bmj-2022-072705;
PMC9989554). An applied TTE using US Veterans Affairs EHR
data with the clone-censor-weight method — chosen because it exercises the
harder leaves (time zero, cloning-based assignment, competing events,
sensitivity analyses). Full text was retrieved as JATS XML from Europe PMC and
rendered to sectioned plain text.

### 8.3 Procedure

Because `ANTHROPIC_API_KEY` was not available in the build environment, judge
mode could not make a live call. The pipeline was instead exercised through
**scaffold mode**: the manuscript was parsed, the judge request (prompt +
tool schema + prompt hash) was built, and verdicts for all 39 leaves were
produced by a model reading the manuscript against the rendered rubric, then
run through the **production** `finalize_assessment` and `check_critical_floor`
code — the same validation and gating path judge mode uses. This validates the
engine end-to-end; it does **not** validate the pinned judge model's
unaided output (that requires the live path, §9).

### 8.4 Results

Ingestion resolved all six canonical sections with correct offsets; the
protocol-table and flow-diagram detectors both fired (the paper reports a
target-trial specification table and a cohort flow figure). All 39 leaves were
in scope (`full_text_available: true`; zero excluded). Verdict tally:

| Verdict | Leaves |
|---------|-------:|
| reported | 27 |
| partial | 9 |
| not_reported | 3 |

**Critical floor: FAIL**, on leaves `6g` and `7g.i` (identifying assumptions).
This is a defensible finding, not an artifact: the paper motivates confounder
adjustment with a directed acyclic graph and a covariate set but does not
state its identifying assumptions (conditional exchangeability, positivity,
consistency) explicitly in methods — acknowledging residual confounding only
later, in limitations. The floor pillars for time zero (`6d`/`7d`) and the
causal estimand (`6f`/`7f`) passed.

The three `not_reported` leaves were registration (18) and — an important
caveat — funding (20) and conflicts of interest (21). The latter two are
extraction artifacts: JATS carries competing-interest and funding statements
in article metadata that this run's body-only extraction did not include. This
correctly illustrates that ingestion completeness bounds assessment validity.

### 8.5 Evidence-resolution guardrail (a positive negative result)

One evidence quote, on leaf `6g`, **failed to resolve** and was flagged in
`unresolved_evidence_leaves`. Cause: the manuscript text reads
`covariates,10 which` — an inline superscript citation marker glued to the
word — while the authored quote omitted the `10`. The resolver refused to
fake-match a quote that does not literally appear, exactly as intended. This
surfaced a concrete ingestion refinement (§9): strip inline reference/
superscript markers in the normalizer so verbatim quotes from clean prose do
not spuriously fail.

### 8.6 Automated tests

Eleven tests pass (`tests/test_core.py`), covering: spec load and structural
invariants (39 leaves, item coverage, pairing symmetry); rejection of unknown
versions; section mapping and whitespace-insensitive quote resolution on both
synthetic and the real BMJ statement PDF; the full `finalize_assessment` +
`check_critical_floor` path; the floor failing on a `partial` floor leaf; the
evidence-required guard; the `not_applicable`-only-on-conditional-leaves rule;
leaf-coverage-mismatch rejection; abstract-only full-text gating (3 in scope,
36 excluded, floor indeterminate); and prompt-hash stability.

### 8.7 Interpretation and limits

The engine is correct and its output is auditable, but no accuracy claim can
be made from n=1 with the model acting as its own judge. **The instrument is
not validated as a measurement device.** Per the design, a corpus run must be
gated on formal validation (§9).

---

## 9. Limitations and next steps

- **No live judge-mode run yet.** The reproducible path (server-side pinned
  model call) has not been exercised against a real key. Next: run judge mode
  on PMC9989554 and confirm the live output matches the scaffold path.
- **Ingestion refinement.** Strip inline reference/superscript markers during
  normalization (surfaced by §8.5); include JATS metadata blocks (funding,
  competing interests) so items 20/21 are assessable (surfaced by §8.4).
- **Gold-standard validation required before any corpus run.** 50–100 articles
  double-coded by humans against TARGET, with **per-item** agreement reported
  (not a single aggregate kappa, which would hide the split between high-
  agreement objective leaves and noisy judgment leaves). Disagreements are
  adjudicated against the evidence span each verdict carries.
- **Full-text coverage** across the target corpus must be measured first — it
  is the ceiling on corpus-scale assessment.
- **Deferred tools** (§7.1) to be built in design order after validation.
- **E&E enrichment.** All leaves are `e_e_pending`; the Explanation &
  Elaboration release triggers a spec minor version with sharpened boundaries.

---

## 10. Reproducibility and provenance summary

Every assessment is self-describing. To reproduce or audit a verdict, the
stamped fields suffice: `spec_version` (which rubric), `model` +
`temperature` + `prompt_hash` + `prompt_template_version` (which judgment
process), and `extractor_version` + `text_sha256` (which text, and therefore
which spans). Change any of these and the provenance reflects it. This is what
distinguishes the instrument from a prose-checklist judgment and is the
precondition for a defensible corpus-scale reporting-completeness claim.

## 11. Commons hygiene

The encoded checklist re-encodes item intent in original words plus assessor
notes; it does not reproduce the TARGET checklist wording, which is © the
TARGET group under CC BY-ND 4.0. Operationalizing the semantics is the
intended ecosystem contribution; republishing the source documents (or, once
released, E&E text) is not.
