# Decision log

Load-bearing decisions for the TARGET Checklist MCP server, with rationale, so a
future session (or contributor) doesn't re-litigate them. Newest first.

Format: **what** — why — status.

---

## 2026-07-20 · Inline report bundle slimmed to HTML-only by default
`submit_scaffold_verdicts` now renders only HTML into `report` unless the caller
passes `report_formats=` (any of `html`/`markdown`/`docx`).
- **Why:** in real Claude Desktop use the triple-format bundle (a) caused a
  4-minute client timeout on the first `submit` call — the same call with
  `render=false` plus a separate render succeeded immediately — and (b) burned
  the agent's context window: the docx base64 blob alone is 10–30k tokens of
  noise the model drags through every later turn, and markdown duplicated the
  HTML's content. Chat-side context is the scarce resource in scaffold mode
  (the manuscript already transits it up to three times).
- **Anti-drift preserved:** exactly one sanctioned, stamped render still falls
  out of validation; markdown/docx are one `render_checklist` /
  `render_checklist_docx` call away from the same stamped artifact.
- Status: done; 35 tests.

## 2026-07-20 · HTML renderer + structural anti-drift safeguards
An agent, reviewing a paper, hand-built its own Word document instead of calling
the sanctioned renderer — a richer analytic memo that nonetheless inherited the
checklist's authority without its provenance. Root cause: rendering was a
separate, optional, forgettable call (and the renderer wasn't even in the agent's
loaded toolset). Fix is STRUCTURAL, not advisory (tool instructions are the
weakest layer — the agent had the right instruction and drifted anyway):
- **The deliverable falls out of validation.** `submit_scaffold_verdicts` now
  returns the finished, rendered artifact inline in `report` — Markdown + HTML +
  .docx bytes — so there is no separate render step to skip. `render=False` opts
  out. This is the highest-leverage change: the right path is the only path.
- **Self-attesting provenance stamp.** `render.provenance()` derives a short
  `stamp` (TGT-XXXXXXXXXXXX) from spec version + ingested-text sha256 + prompt
  hash. Every render carries it: Markdown/HTML footer, HTML `<meta>` tags, and
  .docx **core properties** (keywords=stamp, comments=hashes) + footer. A
  hand-built document cannot carry the correct stamp, so drift is detectable at
  point of use — worth having for a regulatory-grade instrument regardless.
- **Tool language as the belt, not the fix.** submit/instructions now state the
  stamped `report` is the ARTIFACT OF RECORD; the `items` verdicts are an
  intermediate object; do not present a hand-assembled report as instrument
  output. Explicitly PERMITS an analytic memo but requires it be labeled
  commentary that cites the stamp — separating the narrative from the canonical
  form rather than banning it (the memo was real added value; the problem was it
  masqueraded as the assessment).
- **Honest boundary:** a server cannot stop a client agent from calling docx-js.
  These make the sanctioned path cheaper (inline render), make deviation
  detectable (stamp), or are advisory (language). Full removal of discretion is
  only the inline-render piece. A client-side pinned skill/workflow is the
  complementary lever for the user's own runs.
- **`render_checklist_html` tool** (new, 11th): self-contained single-file HTML
  page (`render_html.py`), committed single light-canvas theme (no dark variant,
  so it never flips to black in a dark-mode viewer), styled to the BSCL registry
  identity (canvas #F4F1E8, black divider bar, teal #15655A accent, oxblood
  #9B3A2E). Returns the HTML string + base64. Renders identically on any host
  (Claude, OpenAI, plain file) — only the Artifact hosting layer is Anthropic-only.
- Status: done. 35 tests pass (was 30).

## 2026-07-20 · Report header restructured (user preference)
The completed-checklist header (Markdown + .docx, both views) now reads:
- **Title:** "Transparent Reporting of Observational Studies Emulating a Target
  Trial (TARGET) Checklist" (the published guideline's full name), replacing
  "TARGET reporting checklist — completed assessment".
- **Citation** directly under the title (moved up from the footer; footer keeps
  the CC BY-ND license line only).
- **One instrument line:** "Instrument: TARGET MCP (Black Swan Causal Labs), spec
  <v> · <mode> mode · model <model> · assessed <YYYY-MM-DD> · supplement:
  <status>" — consolidates the old spec/mode/model prov line + separate
  supplement-status line. Date is truncated to the day; supplement underscores
  shown as hyphens; an `external:` model prefix is stripped for display.
- **Removed** the "third-party reading … not an author self-report … verdicts
  assess completeness not quality" note (`INSTRUMENT_NOTE`, and
  `attribution.instrument_note`) — the instrument line already signals it's a
  tool-produced assessment. User found the note unnecessary.
- **Completeness** line capitalized (Reported/Partial/Not reported/N/A/Not
  assessed) and the "(of N leaves)" parenthetical dropped.
- **Subtitle + "third-party" scrub (later same day):** the agent was labeling
  the enriched output "TARGET Checklist — Third-Party Reporting-Completeness
  Assessment" — its own synthesis, not our render (our title spells TARGET out).
  Added `render.SUBTITLE = "Black Swan Causal Labs — Completeness Assessment"`
  under the title in both renderers, and removed the "third-party" framing from
  the tool/docstring language (logo-gating text now says "the enriched view" /
  "machine-generated assessment") so the agent stops producing that phrase.
- Shared helpers `render.TITLE`, `render.SUBTITLE`, `render.instrument_line()`,
  `render.completeness_line()` drive both renderers.
- Status: done. 31 tests pass (assert subtitle present + no "third-party" in output).

## 2026-07-20 · Agent-boundary fixes from a second real-use bug report
A second run (agent-in-a-chat, files on a different filesystem) surfaced I/O-
boundary bugs plus the root cause of the submit serialization crash.
- **docx deliverable now returns its bytes.** `render_checklist_docx` wrote to
  the server's filesystem and returned a server-side `path` the caller couldn't
  read — making the one tool whose job is the submission-ready deliverable
  unusable from a chat/agent context. The return now carries `content_base64`
  (+ `content_type`, `filename`); `path` is documented as server-local only.
- **submit serialization crash — root-caused and fixed.** "None is not of type
  'object'" was NOT the not_reported/empty-evidence path (the reporter's guess).
  `total=False` makes every field emit `default: null` in the generated schema;
  `usage` is a plain `dict` present only in judge mode, so scaffold returns omit
  it and a validator that fills defaults injects `usage: null`, which fails
  `type: object`. Fixed by typing `usage: dict | None` so the null-default is
  valid. (Only manifests under SDKs that fill defaults, which is why it repro'd
  for the reporter but not locally.) The write always succeeded; only the
  response validation failed — the dangerous "success looks like failure" shape.
- **Tool descriptions lead with text/PMCID, not path.** `document` paths must be
  readable on the SERVER host; an agent's uploaded files (mounts, sandboxes) are
  not. parse_manuscript + top-level instructions now lead with "paste the text /
  use a PMCID" and flag that a path is server-local only.
- **protocol_table_detected content fallback.** Was structure-keyed (needed the
  literal word "table"), so raw-text/docx ingestion (which #3 pushes callers
  onto) blinded it even with a canonical spec↔emulation table present. Added
  `_PROTOCOL_TABLE_HEADER_RE`: a column-header signature requiring a pipe/tab
  separator between "target trial"/"component"/"specification" and "emulat", so
  delimited tables register without false-positiving on prose.
- **get_checklist marked optional.** It duplicates the rubric that
  assess_manuscript already embeds; docstring + instructions now say it's
  introspection-only, not a required step (avoids a large duplicate payload).
- Status: done. 31 tests pass (was 28).

## 2026-07-19 · Robustness fixes from a real-use bug report
Fixed a batch of ingestion/serialization bugs surfaced by running the server on
a live paper. Most were silent-failure bugs (the worst kind).
- **Silent path truncation → loud raise.** `parse_document` treated any string
  that wasn't an existing file as raw text, so a mistyped or relative path (the
  server's cwd under Claude Desktop is often `/`) was ingested as its own
  ~30-char "manuscript." Now a string that *looks like* a path (single line, a
  doc extension or a separator) but doesn't resolve raises `FileNotFoundError`
  naming the cwd. Genuine inline text still parses.
- **No-text-layer PDFs → extractor fallback + loud raise.** pypdf returned
  near-nothing on an accepted-manuscript proof that pdfplumber read cleanly.
  Added a pypdf → pdfplumber fallback (`_extract_pdf`) and `_assert_plausible`,
  which raises `ExtractionError` when a paged doc resolves to <100 chars (scanned
  / watermarked, needs OCR) instead of assessing near-empty content. pdfplumber
  is now a dependency; the extractor stamp records which engine ran (bumped to
  `target-mcp-ingest/0.2.0`).
- **Section-order gating relaxed.** `select_leaves` excluded 36/39 leaves
  whenever Methods/Results headings weren't detected — which happens for valid
  layouts (Methods after Discussion in Nature-family proofs). Now a substantial
  body (>= 6000 chars) also unlocks the full checklist; the section map is a hint
  for locating evidence, not a gate on whether content exists. This also removes
  the need to manually reorder text, which was the source of the "spec leaf
  stamped Discussion" wrong-provenance complaint.
- **Unresolved quotes carry a reason.** An evidence quote that doesn't resolve
  now gets an actionable `reason` (paraphrased / not verbatim / possibly in an
  un-ingested supplement) so the in-loop agent can fix the quote instead of
  facing an opaque flag. (Note: `locate()` uses `.find`, which takes the first
  match, so *ambiguity* was never the failure mode — *no verbatim match* was.)
- **docx default path → temp dir.** `render_checklist_docx` defaulted to a bare
  relative filename, which resolved against cwd `/` and failed. Now defaults into
  `tempfile.gettempdir()`.
- **Parse cache survives a restart.** `submit_scaffold_verdicts` now accepts
  `document=` to re-parse transparently when the in-process `text_sha256` cache
  has been wiped by a restart, with a clearer error otherwise — so staged
  verdicts aren't lost.
- **Could not reproduce** the `None is not of type 'object'` submit crash in
  current code — an unresolvable quote now returns cleanly and flags the leaf, so
  it was likely pre-structured-I/O. The unresolved-reason work covers the
  actionable core of that report.
- Status: done. 28 tests pass (was 21).

## 2026-07-19 · Removed the critical floor entirely (reverses all prior floor decisions)
Deleted the critical-floor overlay root and branch: `governance.py`, the
`check_critical_floor` tool, the `critical_floor` block + per-leaf flags in the
spec YAML, the floor distribution in `aggregate_corpus`, the `critical_floor`
markers in `corpus.py`/`validate.py`, the render banner + ⚑ markers, and the
`SUPPLEMENT_CONFIDENT` / indeterminate-gating machinery that existed only to
qualify floor failures. The tool now outputs the 39 verdicts + evidence + a
completeness tally, and makes no pass/fail claim.
- **Why:** the floor was a BSCL invention, not part of published TARGET (which
  deliberately tiers no items). In a tool whose value proposition is faithfully
  completing the TARGET checklist, a non-TARGET pass/fail gate was off-message
  and actively confusing in testing — it read as a *quality/adequacy* judgment
  layered on top of *reporting-completeness* scoring, two different registers.
  It also added no information: it was a derived rule over six verdicts a reader
  can already see in the table. The user hit exactly this confusion on a real
  paper and chose full removal over demote-to-opt-in.
- **What was preserved:** the substantive causal-inference insight (time zero,
  estimand, identifying assumptions are the causal spine) still lives in the
  leaf `assessor_notes`; the "absence ≠ finding" safeguard now rests on
  `supplement_status` being surfaced on every render (a reader can discount a
  not_reported that may reflect an un-ingested appendix) rather than on the
  floor's indeterminate gating.
- **This supersedes** the earlier floor decisions below (strict floor, floor as
  BSCL overlay, indeterminate-gating). They are kept as history; the floor no
  longer exists.
- Status: done. 21 tests pass (was 24; three floor-specific tests removed, their
  non-floor coverage folded into the finalize/aggregate/render tests).

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
