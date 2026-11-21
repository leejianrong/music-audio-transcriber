# Music audio transcriber: Plan

Status: agreed (rounds 1 and 2 closed; budget F5 deferred) · Milestone: MVP = voice and bass to sheet music, hosted

## Problem

A musician with a recording or video of a performance has no cheap way to get notes out of it. Transcribing by ear
is slow, and existing automatic tools either output a messy MIDI file with no notation, or are trained on data
nobody can verify the licence of. Players who want to learn or arrange a part also cannot isolate one instrument
from a full-band recording without a service like Moises.

For us there is a second problem: almost every public pretrained music model carries weights trained on
non-commercial data (ADR-0001), so a paid product cannot simply wrap them.

## Solution

Upload an audio or video file, pick the instrument, and get back MIDI and engraved sheet music (PDF, MusicXML)
that you can fix in a score editor. Later, upload a full-band mix and get separated stems, each of them
transcribed to its own staff, with an optional "clean" re-rendered or enhanced stem. Free tier with limited minutes,
paid subscription for more. Sold as one product with sibei-score, which is the notation editor and web shell.

## Users and actors

- **Primary:** a working or learning musician (jazz-leaning first, since sibei-score is a lead-sheet tool) who wants
  a readable chart from a recording.
- **Secondary:** a producer or teacher who wants stems and MIDI.
- **Non-human:** the sibei-score hosted app (calls this repo's workers through a queue), CI and the eval harness.
- When actors conflict, the NoteEvents contract is the arbiter (ADR-0002): this repo never emits notation, and
  sibei-score never touches audio.

## Scope

**In the MVP (V1 to V3).**
- Single-instrument upload (audio or video, audio extracted with ffmpeg), user-selected instrument: voice or bass.
- Output: NoteEvents, MIDI, and, through sibei-score, a lead-sheet PDF and MusicXML, editable in its browser.
- Synthetic data engine, eval harness with numeric scores on synthetic and real held-out clips.
- Hosted behind sibei-score accounts with a free-tier usage cap.

**Planned after the MVP.** Piano, drums, guitar (V4 to V6), 4-stem separation (V7), the staged pipeline (V8),
optional reconstruction research (V9), paid-launch gate (V10). Separation work starts in parallel once V3 ships.

**Out.**
- Lyrics, auto instrument detection, real-time or live transcription, mobile apps, a DAW plugin.
- Chord recognition from audio. sibei-score has a chord model, but recognition is a separate problem.
- Training on, or shipping weights trained on, NC-licensed data in the paid tier (ADR-0001).
- Guitar tab in the MVP (staff first).

## Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | A user uploads a performance and gets editable sheet music and MIDI, hosted, with free and paid tiers | Core goal |
| R1 | Monophonic transcription (voice, bass) reaches the quality bar in V1 and V2 using no NC-trained weights | Must-have |
| R2 | NoteEvents contract is the only interface to sibei-score, versioned and schema-validated on both sides | Must-have |
| R3 | Synthetic clips are reproducible from a recipe and carry symbolic ground truth | Must-have |
| R4 | Every model is scored on synthetic and real held-out sets, and the gap is reported | Must-have |
| R5 | Piano, drums and guitar transcription with our own weights | Must-have, post-MVP |
| R6 | Separation into at least vocals, drums, bass, other, with a measured SDR bar | Must-have, post-MVP |
| R7 | Staged pipeline: separate, transcribe each stem, optionally reconstruct, with inspectable artifacts | Must-have, post-MVP |
| R8 | Optional audio reconstruction or enhancement that measurably beats raw separation | Nice-to-have, research |
| R9 | Licence hygiene: BOM for all data and models, no GPL in the service, lawyer review before paid launch | Must-have |

## Shape

| Part | Mechanism | ADR |
|------|-----------|-----|
| S1 | `core` library: `Stage(inputs, outputs, model_version)`, content-hashed artifacts, job directory per run | ADR-0005 |
| S2 | Transcribers behind a `Transcriber` protocol: pYIN (monophonic), later own models; pretrained third-party models allowed in dev only | ADR-0001, 0003 |
| S3 | NoteEvents v1 JSON schema, validator, MIDI exporter | ADR-0002 |
| S4 | Beat and downbeat tracker, output attached to NoteEvents (Beat This! MIT is the candidate, verify weights terms) | ADR-0002 |
| S5 | `synth`: recipe format, symbolic generators, FluidSynth/sfizz renderer, augmentation chain, BOM | ADR-0004 |
| S6 | `eval`: mir_eval note F1, onset F1 for drums, museval SDR, synthetic-vs-real gap report | ADR-0004 |
| S7 | `mat` CLI (`--json`, exit codes) and a worker entry point that pulls jobs from sibei-score's queue | ADR-0002 |
| S8 | `Separator` protocol and training loop (V7); reconstruct stage (V9) | ADR-0005 |
| S9 | Training on rented GPUs through the `runpod-jobs` workflow with a teardown guard | ADR-0001 |
| S10 | Dependency register and CI licence check | ADR-0006 |

## Non-UI affordances

| Affordance | Kind | Wires to |
|------------|------|----------|
| `mat transcribe <file> --instrument voice` | CLI | S1, S2, S3 |
| `mat synth generate --recipe r.yaml` | CLI | S5 |
| `mat eval --suite <name>` | CLI | S6 |
| `mat worker` (consumes audio jobs, writes NoteEvents) | Worker | S7, sibei-score queue |
| `mat bom check` | CLI / CI | S10 |

UI is sibei-score's (upload, job progress, review, export); its work is tracked on its own board.

## Implementation decisions

- Python via uv, PyTorch for training, ONNX Runtime for inference where practical. One installable package `mat`
  with subpackages `core`, `synth`, `transcribe`, `eval` (and later `train`, `worker`). A uv workspace of several
  packages is deferred until a subpackage needs its own dependency set.
- Storage is a directory per job plus a small SQLite index locally. In hosted mode, sibei-score's Postgres and object
  store are the source of truth, and this repo reads and writes through presigned URLs (its ADR-0034 pattern).
- Failure behaviour: silence, clipping, or very low confidence produce a result with `warnings[]`, not an error. An
  undecodable file or a file over limits is a hard error.
- Security: probe files with ffprobe (never trust extensions), run ffmpeg with a timeout and no network, size and
  duration caps, workers have no egress. No secrets in the repo.
- Every NoteEvents and artifact records `schema_version` and the producing model version.

## Testing approach

Test at the stage seam: given an input artifact, assert the output artifact against ground truth. The synthetic
corpus is the main test fixture, and its recipes are seeded so tests are deterministic. Metric tests assert numeric
thresholds, not "looks right". The cross-repo check (audio to engraved PDF) is one integration test that runs both
repos' CLIs on a fixture. Per-slice plans are in SLICES.md.

## Assumed defaults

| ID | Assumed | Cost if wrong |
|----|---------|---------------|
| A18 | Provisional quality bars: mono synthetic note F1 at least 0.90, real clips at least 0.70, separation average SDR at least 7 dB on an internal real eval set and no more than 2 dB below htdemucs on the same set | Re-set after V1 and V7 baselines; low cost |
| A19 | Real mono eval clips are recorded by us (about 10 voice and 10 bass clips from written scores), aligned semi-automatically | Without them the real-set number is missing; the gap report depends on it |
| A20 | Free tier is a monthly audio-minute cap, sized after V3 cost measurements | Pricing delay only |
| A21 | Reconstruction ships only if it beats raw separation on SI-SDR and a listening check (ADR-0005) | None; it is a gate |

## Open risks

- **Separation licensing (highest).** No clean real-stem data exists beyond a cappella VocalSet. A launch-quality
  separator may need licensed stems or a lawyer-approved decision. First visible at V7.
- **Sim-to-real gap.** Soundfont audio may not predict real recordings. V1 measures it first.
- **Schedule coupling to sibei-score.** Hosted audio and billing land after its end-2026 launch, and multi-staff
  notation in early 2027. The audio engine can finish V1, V2 and the separation research (V7, V9) in the meantime,
  but nothing paid goes live before those.
- **Uploaded audio is copyright-sensitive.** Retention and deletion must be stated before any hosted audio (story
  MUS-35, and sibei-score SIB2-135).
- **Contract drift across two repos.** Mitigated by schema validation on both sides and a shared synthetic corpus.
- **Quantization is hard.** sibei-score's note-events importer will determine sheet quality more than our F1
  does; V2 is where we find out.
- **Training budget (F5, deferred).** Revisit after benchmarking and before V4.
