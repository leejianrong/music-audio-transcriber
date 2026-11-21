# ADR-0002: Boundary with sibei-score, and the NoteEvents contract

- Status: Accepted
- Date: 2026-11-22
- Deciders: Jian (G3, accepting the recommendation)

## Context

sibei-score (`~/projects/sibei-score`, MIT, TypeScript API + Python worker) owns the score model, engraver, PDF
and MusicXML export, and has a hosted-app direction (its ADR-0034: accounts, Postgres, job queue, Compose on a
VM). Its notation boundary (its ADR-0021) is a single melody staff with chords, and explicitly excludes
piano and drum notation, multi-staff scores and MIDI. The two will be sold as one product.

## Decision

**This repo (the audio engine) owns:** audio/video ingest, separation, audio-to-notes transcription, beat and
downbeat tracking, synthetic data, training, evaluation, GPU workers, and optional audio reconstruction. It
never sees bars, clefs or engraving.

**sibei-score owns:** everything symbolic. Quantization to a metrical grid, bar/key/time inference, voice and
hand splitting, drum mapping, tab, the score model, review flags, engraving, PDF and MusicXML. Quantization lives
there because it is a notation problem, it is testable with no audio, and it reuses the "parse is a draft"
review flow (its ADR-0019) that OMR import already has.

**Product shell:** sibei-score's hosted app is the front door: accounts, billing, library, job UI. This repo
runs as a GPU worker service behind a queue and reports usage in audio-seconds. This repo also ships a CLI
for local use.

**The contract is `NoteEvents` v1**, a JSON document owned by this repo (JSON Schema checked in here,
copied into sibei-score's fixtures). Shape:

```
NoteEvents {
  schema_version: 1,
  source: { sha256, duration_s },
  instrument: "voice" | "bass" | "piano" | "drums" | "guitar" | "other",
  producer: { model_id, model_version, stage: "transcribe" },
  beats: [ { t_s, is_downbeat } ],            // from beat tracking; may be empty with a warning
  notes: [ { id, onset_s, offset_s, pitch: <MIDI int>, cents?: <int>,
             velocity?: 0-127, confidence: 0-1, drum_class?: string } ],
  warnings: [ { code, message, t_s? } ]
}
```

Times are seconds, never beats. Percussion uses General MIDI pitch numbers plus `drum_class`. A separated
multi-instrument job produces one NoteEvents per stem. Contract changes bump `schema_version`; sibei-score reads
forward-compatibly and rejects unknown majors.

**Transport is not decided.** sibei-score's current ADR-0005 has the API push to its worker over HTTP, while this
plan assumed workers pull from a queue. Its SIB2-135 decides; our worker is a transport-agnostic handler until then.
The NoteEvents contract does not depend on the answer.

**Notation scope in sibei-score grows by its own ADRs** (grand staff, percussion staff, tab). Those are its
decisions, tracked on its board, and sequenced against our slices (see SLICES.md "Cross-repo dependencies").

## Alternatives considered

| Option | Why not |
|---|---|
| Build engraving and quantization in this repo | Duplicates a mature engraver and splits notation knowledge across two codebases |
| Pass MIDI instead of NoteEvents | MIDI has no confidences, no warnings, no beat grid with downbeats, and loses sub-semitone pitch |
| Pass MusicXML straight from this repo | Forces us to do quantization and notation inference, which is the part sibei-score is built for |
| Merge the repos | Different runtimes (Python GPU vs Node) and licences; the contract keeps them independently testable |

## Consequences

- Each repo can be tested alone: ours with NoteEvents fixtures vs ground truth, sibei-score with NoteEvents
  fixtures to score. The end-to-end check (audio to engraved sheet) runs only at integration level.
- sibei-score has real work to do before piano or drum sheet music exists. That is the long pole for those
  instruments, and why voice and bass go first (ADR-0003).
- Two repos means contract drift is the main failure mode. Mitigation: schema validated on both sides, and a
  shared synthetic corpus whose ground truth is a score in sibei's model.
- sibei-score is MIT and this repo is Apache-2.0 (ADR-0006). Both are compatible with a combined product.
