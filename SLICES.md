# Music audio transcriber: Slices

Vertical increments. Each ends in something you can demonstrate. V1 confronts the riskiest unknown: whether a
synthetic-data eval loop predicts anything about real recordings.

## Cross-repo dependencies (sibei-score)

| Our slice | Needs from sibei-score (its board) |
|---|---|
| V2 | "Import from NoteEvents" op: quantize voice/bass NoteEvents to a lead-sheet draft with review flags |
| V3 | Audio upload job type, usage metering, free-tier cap, accounts (hosted shell, its ADR-0034) |
| V4 | Grand staff and two-voice notation, hand splitting |
| V5 | Percussion staff and drum mapping |
| V6 | Guitar notation (tab later) |
| V8 | Multi-staff score from several NoteEvents |

**Timing from sibei-score (its ADR-0039, 2026-11-22):** the hosted service launches by **2026-12-31 with audio in it** (presigned upload, an audio job, NoteEvents import as a draft, audio-second metering and a free-tier cap); subscriptions and billing are not in that launch. The worker **pulls** jobs. Piano, drums and multi-staff need its parts x staves x voices model (its ADR-0040, implementation after the launch, general arrangers by 2027-04), so V4 to V6 and V8 wait on it. Its epics: SIB2-E9 (NoteEvents import), SIB2-E10 (hosted audio jobs), SIB2-E11 (multi-staff for audio). **This makes V3 urgent:** the audio worker must exist before the end of 2026.

## V1: Mono eval loop, hum to MIDI

**Delivers:** R1 (partial), R3, R4

**Build plan**

1. Repo scaffold: uv workspace, pytest, ruff, CI with the licence check (S10).
2. Recipe format and a symbolic generator for monophonic lines (scales, arpeggios, simple melodies in set ranges).
3. FluidSynth renderer with at least three bass and three melody patches, plus the augmentation chain, plus BOM rows.
4. pYIN transcriber (voice and bass ranges, bass lower bound at or below 40 Hz) emitting NoteEvents v1 and a MIDI file.
5. `eval` with mir_eval note F1 (50 ms onset, 50 cent pitch) and the sim-to-real gap report.
6. Record 10 voice and 10 bass clips from written scores for the real set (A19).

**Demo:** `mat eval --suite mono` prints F1 on synthetic and on the real clips and the gap. `mat transcribe clip.wav --instrument bass` writes `clip.notes.json` and `clip.mid` that play back recognisably.

**Rests on assumptions:** A18 (the bars), A19 (we record the real set). If the real set is skipped the headline number is missing.

**Result so far (2026-11-22):** tone renderer note F1 0.980 over 24 clips; FluidSynth/MuseScore_General 0.892 (bass 0.989, voice-range patches 0.795). The voice shortfall is soft-attack patches (flute, choir): pitch is right (F1 about 0.9 to 1.0 at a 200 ms onset tolerance) but onsets are late or notes split. Real clips: not yet recorded, so the sim-to-real gap is unmeasured (needs-human card on the board).

### Test plan

#### End-to-end

- On the synthetic mono suite (seed fixed), note F1 is at least 0.90.
- On the real clips, F1 is reported, and at least 0.70 (provisional) or a written explanation is attached.
- The same recipe and seed render byte-identical audio twice.

#### Integration

- A recipe renders, transcribes, and scores with a known perfect-transcriber stub giving F1 = 1.0.
- `mat transcribe` exit codes: 0 ok, non-zero on undecodable file, a warning (not error) on silent input.

#### Unit

- pYIN note segmentation splits repeated same-pitch notes at amplitude dips.
- NoteEvents validates against the JSON Schema, and rejects `onset_s > offset_s`.
- Licence check fails on a planted GPL dependency.

## V2: Voice and bass to engraved sheet music

**Delivers:** R0 (local), R1, R2

**Build plan**

1. Beat and downbeat tracking attached to NoteEvents (verify the tracker's weight terms first).
2. Freeze NoteEvents v1 schema; hand the schema and fixtures to sibei-score.
3. Integration harness: run `mat transcribe`, then sibei-score's import op, then PDF export.
4. Score-level metric against the ground-truth score for synthetic clips (note-by-bar-and-beat agreement).

**Status (2026-11-22):** beats attached, fixtures frozen in `tests/fixtures/note_events`, score-level metric built. The audio-to-PDF run waits on sibei-score SIB2-131 to SIB2-133 (quantizer, draft mapping, import surfaces).

**Demo:** `mat transcribe melody.wav --instrument voice | sbscore import-notes -` produces a PDF lead sheet you can open and edit in the browser.

**Result so far:** score-level agreement (reference quantizer, scoring only) is 0.915 on the tone suite and 0.906 on the FluidSynth suite. Synthetic clips keep a constant tempo with notes on half-beat positions, so this is optimistic; rubato in real performances will be harder.

**Rests on assumptions:** A18. Depends on sibei-score's import op (cross-repo table).

### Test plan

#### End-to-end

- A synthetic bass line with a known score yields an engraved PDF whose notes match the ground truth at least 0.80 by pitch plus bar and beat position.
- A real recorded clip produces a PDF and a list of review-flagged notes.

#### Integration

- NoteEvents fixtures validate in both repos' test suites.
- A NoteEvents file with an unknown major version is rejected by sibei-score with a clear error.

#### Unit

- Beat tracker output with no detectable beat yields an empty `beats` array and a warning, not a crash.

## V3: Hosted upload, free tier

**Delivers:** R0 (MVP), R9 (partial)

**Build plan**

1. ffmpeg ingest: audio or video in, mono 44.1 kHz wav out, ffprobe validation, duration and size caps.
2. `mat worker` speaks sibei-score's worker protocol and writes NoteEvents to object storage by presigned URL. Pull versus push is undecided (sibei-score SIB2-135 decides); build the worker as a transport-agnostic handler first.
3. Usage report in audio-seconds per job for sibei-score metering.
4. Free-tier cap and a paid flag come from sibei-score; worker enforces job duration limit it is given.
5. Isolation: ffmpeg gets file and pipe protocols only plus CPU, memory and time limits; the worker container is non-root, read-only, capability-free and resource-capped. It cannot be egress-free (it pulls from the API and the object store), so egress is restricted to those two hosts at the network layer when deployed.

**Demo:** On the hosted app, sign in, drop a short video of someone playing bass, select Bass, and receive an editable lead sheet and a MIDI download.

**Status (2026-11-22):** built. `mat worker` speaks the pull protocol and was run against a real local sibei-score server: claim, download, ingest, transcribe, complete, a draft in the library, 12.08 audio-seconds metered, and a PDF. `make e2e-sibei` repeats it (`SIBEI_SCORE_DIR` points at a sibei-score checkout). Not yet done: a hosted deployment (none exists), and S3 presigned transfer against a real bucket (covered here by a fake).

**Cost:** about 5.3 CPU-seconds per audio-minute for voice and bass (pYIN plus beats, warm, one core); peak memory about 2.5 GB at the 10-minute cap.

**Deploy readiness (2026-11-23):** health check, graceful shutdown, JSON logs, `make e2e-sibei-s3` (presigned path, with an audit that the object store never receives the credential) and `docs/worker-runbook.md`.

**Rests on assumptions:** A20 (the cap is sized after this slice's cost data).

### Test plan

#### End-to-end

- Uploading a 30 s mp4 of a bass line through the hosted UI ends in a PDF and MIDI download within 2 minutes.
- A file over the duration cap is refused with a clear message before processing.

#### Integration

- A job that fails mid-stage leaves earlier artifacts and returns warnings with the failed stage named.
- A mislabelled file (png renamed .mp3) is rejected by ffprobe, not passed to a decoder.

#### Unit

- Usage reporting rounds up to the next second and records the model version.

## V4: Piano with our own model

**Delivers:** R5 (piano)

**Gate:** F5 (GPU budget) is decided, and the data BOM for piano is reviewed, before this slice starts.

**Build plan**

1. Clean piano symbolic sources (generated plus public domain scores) and renders with CC0/MIT piano patches.
2. Small polyphonic onsets-and-frames style model, training loop, RunPod job with teardown guard.
3. Dev baselines (Basic Pitch, ByteDance piano) on the same held-out sets for comparison only.
4. Export ONNX and run on CPU.

**Groundwork built (no spend, before the gate):** piano recipes (two-handed, polyphonic; `chords` and
`broken` left hands), `mat eval --suite piano` taking any transcriber, and a classical CQT baseline
(`mat transcribe --instrument piano` uses it until our model exists). Baseline note F1 on 16 clips: 0.80
tone renderer, 0.35 soundfont renderer (precision 0.22, recall 0.86). That 0.35 is the floor our model
must clear; the 0.85 target is on this suite. Training, dev baselines and ONNX wait for F5.

**Demo:** `mat transcribe piano.wav --instrument piano` writes a two-hand MIDI, and the eval report compares ours vs the dev baselines on synthetic and real clips.

**Rests on assumptions:** A18, and ADR-0004's claim that synthetic piano is a usable training base. If the gap is large, real licensed recordings are needed.

### Test plan

#### End-to-end

- Piano note F1 on the synthetic held-out set at least 0.85, and the gap to real is reported with the dev-baseline numbers beside it.

#### Integration

- Training job resumes from a checkpoint and the teardown guard stops the pod when the job ends or fails.

#### Unit

- Pedal and overlapping-note handling in the label builder.

## V5: Drums

**Delivers:** R5 (drums). Needs sibei-score percussion staff.

**Build plan:** drum recipes (grooves with variations), E-GMD and Groove MIDI (CC BY) added to the BOM, small CNN-RNN onset model with class outputs, GM-pitch NoteEvents with `drum_class`.

**Demo:** `mat transcribe groove.wav --instrument drums` gives a drum MIDI and a percussion-staff PDF.

**Rests on assumptions:** A18. E-GMD audio is e-kit renders, so the real-world gap needs a real eval set.

### Test plan

#### End-to-end

- Kick, snare and hi-hat onset F1 on synthetic and real clips at least 0.80 each (provisional).

#### Integration

- Drum NoteEvents round-trip into sibei-score's percussion staff with class-to-line mapping preserved.

#### Unit

- Hi-hat open versus closed label mapping.

## V6: Guitar

**Delivers:** R5 (guitar). Needs sibei-score guitar notation.

**Build plan:** guitar recipes, GuitarSet (CC BY) in the BOM, own model (Guitab code is MIT but its weights are NC, so only the architecture is reusable), NoteEvents with optional string/fret hints.

**Demo:** `mat transcribe riff.wav --instrument guitar` gives MIDI and a staff PDF.

**Rests on assumptions:** A18.

### Test plan

#### End-to-end

- Note F1 on GuitarSet test split at least 0.70 and on synthetic at least 0.85 (provisional).

#### Integration

- String and fret hints survive the NoteEvents contract into sibei-score.

#### Unit

- Open-string and harmonic pitch handling in label construction.

## V7: Separation baseline

**Delivers:** R6. Starts in parallel once V3 has shipped.

**Build plan**

1. Mix recipes: several recipe tracks mixed with levels, panning, bus effects, so stems are exact ground truth.
2. `Separator` protocol, SDR/SI-SDR evaluation, htdemucs and Banquet as dev baselines only.
3. Own model (band-split transformer family under an MIT code base), trained on synthetic mixes plus any licensed stems.
4. Report SDR per stem on synthetic and on an internal real set, with the gap.

**Demo:** `mat separate mix.wav` writes vocals, drums, bass and other stems, and the report prints SDR beside the dev baselines.

**Status (2026-11-23):** groundwork built: seeded 4-stem mix recipes with exact stems (`mat.synth.mix`), the `Separator` protocol, SDR (mir_eval BSS Eval) and SI-SDR, and three reference baselines. `mat eval --suite separation` prints them. Not yet done: htdemucs as a dev-only baseline, our own model, and any real-music evaluation.

**Reference points (4 synthetic mixes, SDR dB, mono):**

| Separator | tone renderer avg | soundfont avg |
|---|---|---|
| identity (mix as every stem), the floor | -7.8 | -6.7 |
| harmonic/percussive plus band splits (classical) | 1.2 | 0.3 |
| oracle ratio mask, the ceiling for mask-based models | 11.0 | 10.7 |

The 7 dB bar in A18 is for real music, not these mixes. These numbers only show the harness separates good from bad separators and that a masking model cannot score much above 11 dB on this data even with the answer.

**Rests on assumptions:** A18 (the 7 dB bar), and the open risk that clean real stems may not exist. The slice reveals this.

### Test plan

#### End-to-end

- Average SDR on synthetic held-out mixes reported, and on the internal real set at least 7 dB (provisional) or a written plan to reach it.

#### Integration

- Stems sum back to the mix within a stated tolerance.

#### Unit

- SDR computation matches museval on a known fixture.

## V8: Staged pipeline

**Delivers:** R7

**Build plan:** wire ingest, separate, transcribe each stem; one NoteEvents per stem; stage caching by input hash; sibei-score builds a multi-staff score.

**Wire contract (sibei-score ADR-0034 amendment, SIB2-147, merged):** `complete` takes
`{"inline": {"stems": [NoteEvents, ...]}}`, at most 12 stems, one shared `source.sha256` and `duration_s`
(10 ms), metered once per job. Built here: `WorkerClient.complete_stems`, which refuses a bad set before
sending. Not built: the pipeline that produces stems, and wiring `process_job` to it (needs a separator).

**Demo:** upload a synthetic band mix and receive stems plus a multi-staff PDF.

### Test plan

#### End-to-end

- A synthetic three-instrument mix with a known score yields a multi-staff score whose per-staff note agreement is at least 0.70 (provisional).

#### Integration

- Rerunning with a changed transcriber version recomputes only the transcribe stage.

#### Unit

- Stage cache key changes when any input hash or model version changes.

## V9: Reconstruction research

**Delivers:** R8. Research slice with a ship gate (ADR-0005).

**Build plan:** render-from-notes baseline; a notes-informed refinement model trained on synthetic (mix, stems, notes); SI-SDR and a short listening check against raw separated stems.

**Demo:** A/B page of raw stem, rendered stem and refined stem for the same clip with SI-SDR for each.

**Rests on assumptions:** A21.

### Test plan

#### End-to-end

- On synthetic held-out mixes the refined stem beats the raw separated stem on SI-SDR, or the slice closes with "not shipped" recorded.

#### Integration

- Reconstruction is off unless a job requests it, and output carries the approximation warning.

#### Unit

- Render-from-notes output length matches the source stem length.

## V10: Paid-launch gate

**Delivers:** R9

**Build plan:** BOM audit, lawyer review of weights, data and render-to-train terms, swap any dev-only model out of the paid path, metering and subscription wiring with sibei-score, load and cost measurement.

**Demo:** a paid account runs a job, usage is metered, and the BOM report shows no unreviewed row on the serving path.

### Test plan

#### End-to-end

- `mat bom check --paid-path` exits 0 only when every model and dataset on the serving path has a reviewed licence row.

#### Integration

- A dev-only model configured on the paid path fails the check.

#### Unit

- BOM parser rejects a row with no source URL.
