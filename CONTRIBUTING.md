# Contributing

Thanks for your interest in the TARGET Checklist MCP server. This is a research
instrument as much as a piece of software — it scores how *completely* an
observational target-trial-emulation (TTE) study reports what the TARGET
guideline requires (Cashin et al., JAMA/BMJ 2025), with auditable evidence. A few
conventions exist to keep it trustworthy; please skim this before opening a PR.

## Read first

- **`docs/STATUS.md`** — cold-start snapshot: what exists, the tools, how to run.
- **`docs/DECISIONS.md`** — the decision log. Several things are the way they are
  on purpose (e.g. the pass/fail "critical floor" was **removed** deliberately;
  please don't reintroduce it without opening an issue first). Read this before
  proposing a structural change.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m pytest -q        # 44 tests, should all pass
```

Run the server (stdio) with `.venv/bin/target-mcp`, and batch corpus runs with
`.venv/bin/target-mcp-corpus ids.txt -o out/` (judge mode; needs
`ANTHROPIC_API_KEY`).

## Architecture, briefly

A one-way pipeline, each layer a module under `target_mcp/`:

`spec` (encoded checklist) → `ingest` (SectionMap, source-tagged spans) →
`retrieve` (Europe PMC) → `assess` (scaffold + judge; one `finalize_assessment`
validation path) → `render` / `render_html` / `render_docx` (completed checklist)
→ `corpus` + `corpus_run` (aggregate; concurrent batch) + `validate` (agreement).
`server.py` is the MCP composition layer (11 tools). See STATUS.md for the map.

## Conventions that keep the instrument honest

Please preserve these — they are the difference between a scorer and an auditable
instrument:

1. **The spec YAML is the single source of truth.** The 39 leaves live in
   `target_mcp/specs/target-<version>.yaml`. To change scoring semantics, bump to
   a **new versioned file** rather than editing a published one — provenance
   stamps and prior results reference the version.
2. **Own-words re-encoding only in the spec.** The spec re-expresses each item's
   *intent* in original wording; it must **not** reproduce the published TARGET
   checklist text (commons hygiene — the checklist is CC BY-ND 4.0). The verbatim
   published wording lives in exactly one place, `render.py`'s `OFFICIAL_TEXT`,
   reproduced under CC BY-ND with attribution. Keep that boundary.
3. **Evidence is verbatim and resolved to spans.** Every `reported`/`partial`
   verdict carries quotes copied character-for-character from the ingested text,
   machine-resolved to offsets. Don't loosen this to paraphrase.
4. **The stamped render is the artifact of record.** Don't add paths that
   hand-assemble a checklist document outside the renderer — it would lack the
   provenance stamp. If you surface a model label, attest it truthfully (scaffold
   mode can't verify the caller's model; `unspecified` is the honest default).
5. **Structured I/O discipline.** MCP output TypedDicts are `total=False`, and any
   field that can be absent must be typed `X | None` — the SDK strictly validates
   returns, and a bare `dict`/object default of `null` will crash. See the
   `usage`/`report` fields in `server.py` for the pattern.
6. **Scope:** the tool measures reporting *completeness*, not study *quality*. A
   clearly-reported-but-questionable choice is still `reported`. Keep verdicts and
   any new docs on that side of the line.

## Tests

- All PRs must keep `pytest` green. Add tests for new behavior.
- **Tests must not hit the network or a paid API.** Use the scaffold path
  (`build_judge_request` + `finalize_assessment`) for assessment, and inject
  `fetch_fn`/`judge_fn` into `run_corpus` (see `tests/test_corpus_run.py`) rather
  than calling Europe PMC or Anthropic.

## Pull requests

- Keep changes focused; one concern per PR.
- Note any decision that future contributors shouldn't relitigate in
  `docs/DECISIONS.md` (newest first, `what — why — status`).
- Never commit secrets. `.keyfile` is git-ignored; API keys belong in the
  environment, never in code, tests, or fixtures.

## Reporting issues

Bug reports that name a real manuscript and the surprising verdict/behavior are
especially useful (the instrument has been hardened by exactly these). For
scoring disagreements, include the leaf id, the paper, and what you'd have
expected — those feed the gold-standard validation effort.

## Licensing

Code is Apache-2.0 (see `LICENSE`/`NOTICE`). By contributing you agree your
contributions are licensed under the same terms. Do not add code under an
incompatible license, and do not paste verbatim TARGET checklist wording into the
spec (see convention 2).
