# Ingestion & Scoring — Design Note v0.2

> **Superseded in part (2026-07-19):** the **critical floor** and its
> indeterminate-gating (a floor failure downgraded to "check supplement" when no
> supplement was ingested) were removed. `supplement_status` is still stamped and
> surfaced on every render, but there is no longer a floor gate to qualify. Treat
> "floor" passages below as historical; see `docs/DECISIONS.md`.

**Black Swan Causal Labs · TARGET Checklist MCP**
Status: proposal for sign-off. Supersedes nothing in the built vertical slice;
extends the ingestion, governance, and provenance layers.
Date: 2026-07-08

This note proposes three linked changes, all motivated by findings from the
live validation on three real target-trial-emulation (TTE) papers. It is a
design to approve before implementation, because change #1 (supplement gating)
alters what a "critical-floor FAIL" means.

---

## 0. What the validation showed (why this note exists)

Judge mode (pinned `claude-sonnet-5`, temperature deprecated → omitted) was run
on three papers. Findings that drive this design:

| Paper | Source | Floor (judge) | Note |
|-------|--------|---------------|------|
| Molnupiravir (VA) | PMC JATS | FAIL 6f, 6g | clean main-text extraction |
| RSVpreF (French) | PDF | FAIL 6f, 7f, 6g, 7g.i | many unresolved quotes (PDF noise) |
| Dickerman (NEJM exemplar) | JATS main text | FAIL 6f, 7f, 6g, 7g.i | estimand/assumptions absent from **main text** |
| Dickerman + Table S1 | JATS + supplement PDF | 6f→reported, 6g→partial | supplement flipped floor-critical leaves |

Three conclusions:

1. **Floor-critical content routinely lives in supplements.** Dickerman's
   estimand ("intention-to-treat effect", "per-protocol effect") and its
   identifying assumption (exchangeability, validated by negative controls) are
   in Table S1, not the main text. Scoring the main text alone turned a
   rigorous study into a floor failure. Adding the supplement flipped `6f` to
   `reported` and lifted `6g`.
2. **Source format determines extraction quality.** JATS main text resolved
   cleanly (Dickerman: 0 unresolved quotes). PDF resolved poorly (RSVpreF, and
   the Dickerman supplement) — from de-hyphenation, running headers, and
   two-column tables being interleaved. But **JATS does not carry supplement
   text** — only a link. So structured retrieval solves the main text and does
   nothing for the supplement.
3. **The floor discriminates but is strict.** Per-leaf profiles differ across
   papers; the recurring failure (estimand + identifying assumptions not
   *explicitly* stated) is exactly what TARGET exists to expose. But strictness
   about explicit per-estimand statements is a calibration choice, not a fact.

The unifying principle for all three changes below:

> **Absence must never look like a finding.** A missing supplement, an
> unretrievable file, or an unresolved quote must read as *"could not assess"*,
> never as *"the authors did not report it."* At corpus scale, the difference
> is the validity of the headline statistic.

---

## 1. Supplement handling (highest priority)

### 1.1 The validity threat

TTE methods — time zero, estimand, identifying assumptions, variable
definitions — frequently sit in supplementary material. Supplements are **not
independently indexed**: they are reachable only via the article's supplement
links, the journal page, or the PDF, and are hosted as separate PDF/docx/xlsx
files.

The bias this creates is **systematic, not random, and adversarial to the
result**: higher-impact journals (NEJM, JAMA, Lancet) push more method detail
into supplements because of word limits. So incomplete supplement coverage
**under-scores the most rigorous papers**, and a corpus statistic like "X% fail
to report their estimand" degrades into "X% put it in a supplement we didn't
read." This must be measured and controlled, not left to chance.

### 1.2 Multi-document ingestion

A manuscript becomes a set of documents — main text plus N supplement files —
merged into one `SectionMap`. Requirements:

- Each `Section` and each resolved evidence span records its **source
  document** (`main` vs `supplement:<filename>`) and, where available, the
  in-source locator (e.g. "Table S1"). TARGET explicitly permits items to be
  reported in supplements, so supplement evidence is *legitimate* — but the
  locator must disclose where it was found.
- The merge is order-stable and provenance-preserving; the existing
  offset/quote-resolution machinery operates over the concatenation.
- Already validated manually: concatenating Dickerman main + supplement and
  re-running judge is exactly how `6f` flipped. What is missing is the
  source-tagging and automated retrieval.

### 1.3 Tiered retrieval

Fetch supplements in priority order, logging **which tier succeeded** per
manuscript:

1. **Europe PMC / PMC supplementary-files endpoint** — open-access, automatable
   (`.../PMCxxxxxxx/supplementaryFiles`), covers a large slice of an OA corpus.
2. **JATS `<supplementary-material>` hrefs** — follow to the hosted file.
3. **Publisher HTML "Supporting Information" links** — journal-specific,
   sometimes paywalled; best-effort.
4. **Human-provided** — file dropped in a watched folder (the route used for
   Dickerman). Most reliable, least scalable; the backstop for tiers 1–3 misses.

Full automation has a long publisher-specific tail. v1 automates tier 1,
attempts 2, and *flags* the rest for human retrieval rather than silently
proceeding.

### 1.4 Supplement-status gating (the guardrail — changes floor semantics)

Extend the gating already used for full text. Every assessment stamps:

```
supplement_status: retrieved | none_exists | not_retrieved | user_provided
```

Gating rule:

- A floor (or spec/assumption) leaf scored `not_reported`/`partial` **while
  `supplement_status ∈ {not_retrieved}`** is reported as
  **`indeterminate — check supplement`**, not a confident FAIL.
- `none_exists` (the article genuinely has no supplement) permits a confident
  verdict.
- This mirrors the existing abstract-only full-text gating, one level up.

Consequence, and the reason this note needs sign-off: **a "floor FAIL" now
means "failed *with* the supplement in hand (or with no supplement to check)."**
Corpus output leads with coverage denominators: "floor assessable for N/1500;
supplement retrieved for M/1500; indeterminate-pending-supplement for K."

---

## 2. Extraction quality

### 2.1 Prefer structured sources for the main text

For PMC-indexed papers, fetch **JATS XML** for the main text (clean, as
validated) and fall back to PDF only when no structured version exists. This
removes most main-text resolution noise for a largely PMC-indexed corpus.

### 2.2 Better PDF fallback

When PDF is unavoidable (notably supplements), replace `pypdf` with a
**layout-aware** parser (PyMuPDF or pdfplumber) to fix, in the normalizer:

- **De-hyphenation over-join** — currently `high-\ndependency` → `highdependency`
  and `RSV-\nLRTI` → `RSVLRTI`, breaking verbatim quotes. Fix: hyphen-tolerant
  resolution rather than trying to perfectly de-hyphenate.
- **Running headers/footers spliced mid-sentence** across page breaks
  (`Articles www.thelancet.com Vol 67 …`) — strip during normalization.
- **Inline reference/superscript markers glued to words** (`MATISSE trial 4 and`,
  `covariates,10 which`) — strip or make resolution marker-tolerant.

These three account for every unresolved quote observed across the runs; each
is non-fatal today (unresolved quotes are flagged) but each erodes evidence
completeness at corpus scale.

### 2.3 The protocol table is a special case

The single most floor-relevant object — the target-trial
specification/emulation table (Table S1 in Dickerman) — is exactly what plain
extraction destroys, interleaving its two semantic columns (target vs
emulation) and thereby breaking the 6x↔7x pairing. Options, in order of
preference:

1. **Vision-model pass on the table page(s)** — since scoring is already
   LLM-based, reading the table image as a 2-column structure is the natural
   tool and preserves the pairing.
2. Dedicated table extraction (camelot/tabula) — brittle across layouts.
3. Accept degraded table text but let the judge reason over it (current
   behavior — enough to lift `6f`, not enough to resolve quotes).

---

## 3. Materiality layer (separate from completeness)

### 3.1 The distinction

Two different axes are currently conflated:

- **Completeness of reporting** — *did the authors state it?* This is TARGET's
  actual scope and what the verdict measures.
- **Materiality / design-risk** — *how much does the omission threaten this
  study's validity?* This is what a human reviewer actually wants to know.

Worked example (Dickerman): the estimand feels "obvious" only because adherence
to the two-dose schedule is reported at **99%**, so intention-to-treat ≈
per-protocol and the estimand choice barely moves the result. If adherence were
60%, the same omission would be serious. So the omission is *low design-risk
here* — but that is conditional on a reported fact, and it is a different claim
from *"reported."*

### 3.2 Do NOT loosen the completeness verdict

Letting the instrument decide "the estimand is obvious, I'll pass it"
reintroduces the caller-dependent, non-reproducible judgment the pinned-model
design exists to eliminate. "Obvious" is a model opinion; it will not be stable
across runs and it dissolves the corpus statistic.

### 3.3 Add a distinct, encoded materiality scorer

- Runs **only** on floor failures (or all `partial`/`not_reported` on
  spec/assumption leaves).
- Emits a **separate** structured verdict: `design_risk ∈ {low, medium, high}`
  with a rationale grounded in an encoded rubric (e.g. adherence level, whether
  a per-protocol claim is defended by baseline-only adjustment, presence of
  negative controls, plausibility of unmeasured confounding).
- Is **as pinned and versioned as the completeness rubric** — its own signal
  terms, thresholds, prompt template, and prompt hash. Not "be lenient when it
  feels obvious."
- Composes with the BSCL floor overlay (which is *not* TARGET and is ours to
  tier): a floor failure can be **hard** (incomplete *and* high design-risk) or
  **soft/advisory** (incomplete but low design-risk). The TARGET completeness
  verdict stays pure and reproducible underneath.

Output shape (illustrative):

```
6g: { verdict: partial, design_risk: low,
      risk_rationale: "ITT≈per-protocol at 99% adherence; ...",
      floor_class: soft }
```

---

## 4. Provenance additions

New stamps on every assessment:

- `supplement_status` and per-document source list.
- Per-evidence `source_document` + in-source locator.
- `main_text_source: jats | pdf` (extraction path taken).
- Materiality block (when run): `materiality_rubric_version`,
  `materiality_prompt_hash`.

Rationale unchanged from the built design: a result is only reproducible and
auditable if it fully describes what it read and how it judged.

---

## 5. Build order

1. **Multi-doc ingestion + source-tagged evidence spans.** Small; the merge is
   already validated manually.
2. **`supplement_status` provenance + indeterminate-gating rule.** The validity
   guardrail; cheap; makes the corpus number honest even before retrieval is
   perfect. *This is the one that changes floor semantics — sign-off gate.*
3. **Europe PMC supplement retrieval (tier 1)** + human-provided backstop.
4. **Prefer-JATS main text + PDF-fallback normalizer fixes** (hyphen, headers,
   markers).
5. **Protocol-table vision pass.**
6. **Materiality scorer** (encoded rubric + pinned prompt), composed with the
   floor as hard/soft classes.

Steps 1–3 remove the dominant validity threat; 4–5 remove the dominant noise
source; 6 adds the reviewer-facing judgment without corrupting the measurement.

---

## 6. Open questions for sign-off

1. **Floor semantics.** Approve the `indeterminate — check supplement` state
   (§1.4)? This is the change with the largest downstream effect on corpus
   reporting.
2. **Retrieval scope for v1.** Automate only PMC-OA supplements and flag the
   rest, or invest early in publisher scraping?
3. **Materiality: build now or defer?** It is genuinely useful but orthogonal
   to the corpus completeness claim. Reasonable to ship the corpus instrument
   on completeness alone and add materiality as a second release.
4. **Floor calibration.** Independent of materiality: keep the floor strict on
   *explicit* per-estimand assumption statements, or relax the floor's
   definition (it is the BSCL overlay, not TARGET, so this is ours to set)?
