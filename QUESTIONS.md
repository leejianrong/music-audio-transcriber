# Questions

Statuses: `DECIDED` (user answered) · `ASSUMED` (default taken, correct it if wrong) · `FORK` (waiting on the user) · `DEFERRED` (not needed yet).

Host facts (2026-11-22): WSL2, 16 cores, 7 GB RAM, no GPU; ffmpeg, uv, docker present; fluidsynth, sox, lilypond, musescore absent.

## Open forks

None. Rounds 1 and 2 are closed.

## Register

| ID | Question | Status | Answer or default | Landed |
|----|----------|--------|-------------------|--------|
| F1 | Wrap pretrained or train from scratch? | DECIDED | Pretrained for dev and benchmarking, careful with licences; paid tier uses own weights (G1) | ADR-0001 |
| F2 | Audience and commercial intent | DECIDED | Hosted SaaS with free tier and subscriptions, sold with sibei-score | PLAN, ADR-0002, ADR-0006 |
| F3 | Output scope | DECIDED | Sheet music in the MVP, engraved by sibei-score; MIDI too | ADR-0002 |
| F4 | Separation success bar | DECIDED | Done means a working Moises-like feature; provisional numeric bar in A18 | PLAN R6, V7 |
| F5 | GPU budget | DEFERRED | Revisit after licence review and benchmarks, before V4 | SLICES V4 gate |
| G1 | Legal posture for paid-tier weights | DECIDED | Clean-room weights only; pretrained dev-only; lawyer before launch | ADR-0001 |
| G2 | First instruments | DECIDED | Voice and bass, then piano, drums, guitar | ADR-0003 |
| G3 | Product boundary | DECIDED | Audio engine here, notation and shell in sibei-score, NoteEvents contract | ADR-0002 |
| U1 | Reconstruction stage (user note) | DECIDED | Optional staged pipeline; research track with a ship gate | ADR-0005, V9 |
| A1 | Primary user | ASSUMED | Musician wanting a readable chart; jazz-leaning first | PLAN |
| A2 | Instrument selection | ASSUMED | User picks at upload; singing plus playing videos unsupported until V7 | ADR-0003 |
| A4 | Data model and identity | ASSUMED | Job, Source (sha256), Artifact, ModelVersion; ULID job id; artifacts record model version | PLAN §Implementation |
| A5 | Synthetic data identity | ASSUMED | Clip is a recipe; audio is a cache | ADR-0004 |
| A6 | Storage | ASSUMED | Local: directory per job plus SQLite; hosted: sibei-score Postgres and object store | PLAN |
| A7 | Concurrency | ASSUMED | Queue with worker pool; identical inputs return cached artifact | PLAN |
| A8 | Interfaces | ASSUMED | One core library, `mat` CLI with `--json` and exit codes, worker entry point | PLAN S7 |
| A9 | Failure behaviour | ASSUMED | Warnings for degraded input; hard error for undecodable or over-limit | PLAN |
| A10 | Dependencies | ASSUMED | pYIN (librosa, ISC), FluidSynth (LGPL), sfizz (BSD), mir_eval, museval, music21/partitura; dev-only baselines per ADR-0001; each verified at its slice | ADR-0001, 0004, 0006 |
| A11 | Renderer | ASSUMED | Drop Ableton; FluidSynth plus augmentation | ADR-0004 |
| A12 | Runtime | ASSUMED | Dev on local CPU, training on RunPod via runpod-jobs, inference CPU first and GPU where needed | ADR-0001 |
| A13 | Success measures | ASSUMED | mir_eval note F1, onset F1 for drums, SDR, sim-to-real gap | PLAN R4, A18 |
| A14 | Security | ASSUMED | ffprobe validation, caps, no-egress workers; uploaded media is user's responsibility with a terms-of-service; hosted adds takedown path | PLAN |
| A15 | Versioning | ASSUMED | NoteEvents `schema_version`; forward-compatible read, reject unknown majors | ADR-0002 |
| A16 | Stack | ASSUMED | Python 3.13, uv, PyTorch, ONNX Runtime, pytest | PLAN |
| A17 | Dataset licences | ASSUMED | Track per dataset; MAESTRO, MUSDB, MedleyDB, MoisesDB, ADTOF, Aria-MIDI etc. are not training data; NC test sets only as internal benchmarks pending lawyer | ADR-0001, 0004 |
| A18 | Quality bars | ASSUMED | See PLAN | PLAN |
| A19 | Real eval clips | ASSUMED | We record about 20 and align them | V1 |
| A20 | Free tier size | ASSUMED | Monthly audio-minute cap after V3 costs | V3 |
| A21 | Reconstruction ship gate | ASSUMED | Must beat raw separation on SI-SDR plus listening | ADR-0005 |
| A22 | Code licence | ASSUMED | Apache-2.0-compatible, weights and data proprietary, final licence at first public release | ADR-0006 |

## Research record (2026-11-22)

Gathered by three subagent web-research passes (summarised pages, not full LICENSE files). Treat every licence row as "to be re-verified by a person at the slice that uses it", and the lawyer at V10.

- **Separation:** no pretrained model with a clear commercial weights licence. Demucs weights licence "unclear" per its author; community RoFormer weights mostly unlicensed; Open-Unmix umxl is CC BY-NC-SA.
- **Transcription:** Basic Pitch (Apache-2.0, 16,782 params, trained partly on MAESTRO/MedleyDB), ByteDance piano (MIT code, MAESTRO-trained, weights licence unverified), MT3 (Apache code, checkpoint terms unstated), YourMT3+ (GPL-3.0), ADTOF (CC BY-NC-SA), Guitab weights (CC BY-NC-SA), Aria-AMT weights (CC BY-NC-SA dataset repo).
- **Data safe on licence text:** MusicNet, E-GMD, Groove MIDI, GuitarSet, VocalSet, VCSL (CC0). **Needs review:** Slakh/Lakh, GiantMIDI-Piano, POP909, Vocadito, EGDB, GeneralUser GS. **NC:** MAESTRO, MUSDB18, MedleyDB, MoisesDB, ADTOF, MAPS, SMD, Aria-MIDI, DALI, IDMT-SMT-Guitar, GAPS.
- **Not verified:** most parameter counts, VRAM and speed outside Demucs, Salamander, FluidR3, Spitfire LABS, EchoThief, OpenAIR, bass-specific models.

## Coverage

| Category | Covered by |
|----------|-----------|
| Primary user and actors | A1, F2 |
| Scope boundary | F3, G2, G3, PLAN §Scope |
| Data model and identity | A4, A5, ADR-0002 |
| State and storage | A6 |
| Concurrency and conflict | A7 |
| Interfaces and contracts | A8, ADR-0002 |
| Failure behaviour | A9 |
| External dependencies | A10, A17, ADR-0001, 0004, 0006 |
| Runtime and deployment | A12, ADR-0002 |
| Measurable success | A13, A18, SLICES test plans |
| Security and secrets | A14 |
| Versioning and migration | A15 |
| Legal and licensing (domain) | G1, A17, A22, ADR-0001, 0006 |
