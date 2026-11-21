# ADR-0005: Separation, transcription and reconstruction are separate stages with inspectable artifacts

- Status: Accepted
- Date: 2026-11-22
- Deciders: Jian (requested the staged design and an optional reconstruction stage)

## Context

For multi-instrument audio the user wants: (1) a first-pass ML separation, (2) per-stem audio-to-notes, and
optionally (3) a reconstruction stage that cleans up or re-creates the audio from the transcribed notes.
Stage 3 is exploratory. Two different ideas hide in it:

- **Render-from-notes:** synthesize each stem from its NoteEvents. Clean, noise-free, bleed-free, but the timbre
  is a soundfont, not the original player. Useful as a "clean practice track" and as a diagnostic.
- **Notes-informed refinement:** use the NoteEvents as side information to improve the separated stem (the
  field is called score-informed source separation). Keeps the original timbre, can suppress bleed and artifacts.
  A model trained on synthetic data can learn it, because we have ground truth for the mix, stems and notes.

## Decision

1. The pipeline is `ingest → separate → transcribe (per stem) → [reconstruct]`. Each stage reads and writes
   a typed artifact (audio file with a content hash, NoteEvents, etc.) in the job directory, so a stage can be
   rerun, swapped, or inspected alone.
2. Each stage declares `Stage(inputs, outputs, model_version)`, and results are cached by hash of inputs
   plus model version.
3. Reconstruction is **optional and off by default**. It is a research track starting at V9, gated on a
   measured result: on synthetic ground truth, the refined or rendered stem must improve SI-SDR (and a
   listening check) over the raw separated stem, or it is not shipped.
4. Reconstruction output carries its own warning that it is a re-rendered or enhanced approximation.

## Alternatives considered

| Option | Why not |
|---|---|
| One end-to-end model (mix to notes) | Hard to train, hard to debug, and loses the stems users also want as a product |
| Render-from-notes only | Cheap, but cannot recover the original timbre, and errors in transcription become audible |

## Consequences

- Stage artifacts double as products (stems for download, MIDI export, sheet music).
- Transcription quality gates reconstruction quality, so the stage can only be as good as stage 2. Errors compound.
- Rendered output must respect soundfont licences for outputs sold to users, a BOM check at V9.
