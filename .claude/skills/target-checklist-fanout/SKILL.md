---
name: target-checklist-fanout
description: >-
  Assess a manuscript against the TARGET reporting checklist FAST by fanning the
  39 leaves out across parallel scoring subagents, then merging and submitting
  through the target-checklist MCP server. Use when a user asks to review, score,
  or assess an observational target-trial-emulation study against TARGET and the
  client supports subagents (Claude Code CLI, or the Code/Cowork tab). Requires
  the target-checklist MCP server connected (11 tools). If subagents are NOT
  available (e.g. the Claude Desktop Chat tab), fall back to a single scaffold
  pass — see "Fallback" below.
---

# TARGET checklist — parallel fan-out orchestration

You are the **orchestrator**. You do not score the paper yourself; you split the
39-leaf checklist across parallel subagents, each scoring a few leaves, then you
merge their verdicts and submit them to the MCP server for validation and
rendering. This cuts a ~20-minute single pass to ~2 minutes wall-clock.

The whole point is that **all MCP calls stay with you (the orchestrator)**. The
subagents are pure scorers: they receive the rubric and manuscript as plain text
and return a verdict array. They do NOT need to reach the MCP tools themselves —
keep it that way; it is simpler and avoids subagent-reachability questions.

## Step 1 — Parse the manuscript (you, one MCP call)

Call `parse_manuscript` with the manuscript TEXT (or `parse_pmcid` for an
open-access PMCID). Pass `citation=` with the paper's full APA reference so it
appears on the render; on the PMCID path it is auto-built. Also pass
`supplements=` when you have them — TTE methods (estimand, identifying
assumptions) frequently live in a supplementary protocol table.

Keep the returned `text_sha256` — you need it to submit.

## Step 2 — Get the scaffold prompt (you, one MCP call)

Call `assess_manuscript` with `mode="scaffold"`. It returns:
- `system` — the rules + the full per-leaf rubric for all applicable leaves,
- `user_content` — the manuscript as the server ingested it (the ONLY text
  evidence quotes may be copied from),
- `leaf_ids` — the ordered list of leaves to score (usually all 39).

Do NOT hand-score. Move to the fan-out.

## Step 3 — Split the leaves into batches (keep 6x/7x pairs together)

Group `leaf_ids` into ~11 batches of 3–4 leaves. **Rule that matters:** keep each
`6x` specification leaf with its paired `7x` emulation leaf (and lettered/roman
siblings) in the SAME batch — judging the emulation of a component is more
coherent when the same subagent just judged its specification. This is the one
dependency in an otherwise-independent checklist.

Default grouping (works for the standard 39-leaf set):

    B01: 1a, 1b, 1c
    B02: 2, 3, 4, 5
    B03: 6a, 7a, 6b, 7b
    B04: 6c, 7c, 6d, 7d
    B05: 6e, 7e, 6f, 7f
    B06: 6g, 7g.i, 7g.ii
    B07: 6h, 7h.i, 7h.ii
    B08: 8, 9, 10, 11
    B09: 12, 13, 14
    B10: 15, 16, 17, 18
    B11: 19, 20, 21

## Step 4 — Dispatch one subagent per batch, IN PARALLEL, with a PINNED model

Send all batch subagents in a single message so they run concurrently.

**Pin the model explicitly** on every subagent (e.g. `model: "fable"`). This is
a provenance requirement, not a nicety: in scaffold mode the server cannot see
which model scored, so unless you pin it you can only honestly stamp the render
`model unspecified`. Pinning makes the attested model a verified fact — and you
must pass that SAME model string to `submit` in Step 6.

Give each subagent, as plain context:
1. The `system` rules + rubric (you may pass the whole `system` block — it is
   fine for a subagent to see all leaves and score only its own; that is more
   robust than slicing the rubric text, and prompt caching makes the repeated
   text cheap).
2. The `user_content` manuscript.
3. Its assigned leaf ids, with a firm instruction: **score ONLY these ids.**

Each subagent returns a JSON array, one object per assigned leaf:

    {"id": "<exact leaf id, e.g. 7g.i — NOT 'Leaf 7g.i'>",
     "verdict": "reported|partial|not_reported|not_applicable",
     "confidence": <0-1 float>,
     "rationale": "<1-3 sentences grounded in the verdict boundaries>",
     "evidence_quotes": ["<verbatim spans copied EXACTLY from the manuscript,
        <=300 chars each, ONLY for reported/partial>"]}

Tell them: quotes must be character-for-character from the manuscript (the server
resolves them to offsets; an unfound quote is rejected). `not_reported` and
`not_applicable` carry empty `evidence_quotes`. Judge completeness of REPORTING,
not methodological quality.

## Step 5 — Merge with integrity checks (you) — DO NOT SKIP

Independent subagents drift in two predictable ways; both were observed in
testing and both would make `submit` reject the array. Guard against them:

1. **Normalize ids.** Strip any `"Leaf "` prefix and stray whitespace so ids
   match `leaf_ids` exactly (e.g. `"Leaf 8"` → `"8"`).
2. **Check full coverage.** You must end with exactly the `leaf_ids` set — no
   missing, no duplicates, no extras. If a batch dropped a leaf (seen in
   testing: a 3-leaf batch returning only 2), **re-dispatch one subagent for
   just the missing leaf(s)** and add it in.
3. **Order** the merged objects to match `leaf_ids`.

## Step 6 — Submit (you, one MCP call)

Call `submit_scaffold_verdicts` with:
- `text_sha256` from Step 1 (or pass `document=` to re-parse if the cache was
  wiped by a server restart),
- `items` = your merged, ordered 39-object array,
- `model` = the SAME pinned model string from Step 4 (e.g. `"claude-fable-5"`),
  so the render truthfully names what scored,
- optionally `report_formats=["html"]` (the default) — HTML falls out inline in
  `result["report"]`. Add `"docx"`/`"markdown"` only if asked; they cost context.

The server validates coverage, vocabulary, and evidence resolution, then returns
the finished, provenance-STAMPED deliverable. **That stamped render is the
artifact of record — present it.** Do NOT hand-assemble your own checklist
document; it lacks the stamp. Offer the Word (.docx) version on request (call
`render_checklist_docx`, which returns base64 bytes).

## Fallback — no subagents (e.g. Claude Desktop Chat tab)

If the client cannot spawn subagents, skip the fan-out: run the `system` prompt
against `user_content` yourself in one pass, produce all 39 verdicts, and call
`submit_scaffold_verdicts` once. Same deliverable, slower (~20 min). Stamp
`model` honestly (`"unspecified"` unless you can attest what you ran on).

## Why these guardrails exist

- **Pin the model** → provenance is verified, not a leaked default. (A test run
  once mislabeled a paper `claude-sonnet-5` — merely the server's judge default
  bleeding through an unpinned run.)
- **6x/7x pairs in one batch** → preserves specification↔emulation coherence.
- **Merge integrity** → `submit` correctly rejects an incomplete/mislabeled
  array, so a dropped or "Leaf N"-prefixed leaf must be fixed before submitting.
- **MCP calls stay with the orchestrator** → subagents need no server access;
  fewer moving parts, portable across however the client wires subagents.
