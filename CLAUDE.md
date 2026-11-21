# Music audio transcriber: agent brief

Audio (or video) of a performance in, NoteEvents + MIDI out; sheet music comes from the sibei-score repo
(`~/projects/sibei-score`) through the NoteEvents contract. Plan: `PLAN.md`. Build order: `SLICES.md`.
Decisions: `docs/adr/`. Decision register and licence research: `QUESTIONS.md`. Board: Pandan `MUS` (id 48).

**Trust the code over the docs where they disagree, then fix the docs.**

## Status

| Slice | State |
|---|---|
| Scaffold, CI, hooks | built |
| V1 mono eval loop | see `SLICES.md` and the board |
| V2 voice/bass to sheet | blocked on sibei-score SIB2-E9 for the real importer |
| V3 and later | not started |

## Commands

```
make            # list targets
make install    # uv sync --frozen
make check      # pre-push gate: ruff, mypy --strict, unit tests (fast, no infra)
make test-integration   # needs fluidsynth + soundfont: `uv run mat synth fetch-soundfont`
make licenses   # fail on GPL/AGPL runtime deps
make hooks      # install the pre-push hook
```

## Conventions

- Branch per slice off fresh `main`; PRs only; CI green before merge; never push to `main`.
- Every bug becomes a failing test first. Tests assert behaviour at the stage seam, not internals.
- `tests/unit` needs no external binaries (use the numpy tone renderer). `tests/integration` may use
  fluidsynth and the soundfont. Mark integration tests with `@pytest.mark.integration`.
- Synthetic clips are recipes (seeded); audio is a cache. Same recipe + seed must give identical bytes.
- Licences (ADR-0001, ADR-0004, ADR-0006): no GPL/AGPL in `src/`; no NC-trained weights in the paid path;
  every dataset, soundfont or model gets a row in `bom/sources.toml` with a source URL. Weights, audio,
  and soundfonts are never committed.
- NoteEvents is the only interface to sibei-score (ADR-0002). This repo never emits notation. The reference
  quantizer in `src/mat/eval` exists only to score; it is not the product's quantizer.
- Do not publish datasets or weights. Do not put secrets or personal details in commits.

## Layout

`src/mat/core` NoteEvents model, schema, MIDI export · `src/mat/synth` recipes, renderers, augmentation ·
`src/mat/transcribe` transcribers · `src/mat/eval` metrics and suites · `src/mat/cli.py` the `mat` CLI ·
`schemas/` JSON Schemas · `bom/` bill of materials · `scripts/` hooks and checks.
