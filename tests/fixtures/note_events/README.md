# NoteEvents v1 fixtures

Shared with sibei-score (copy these files into its tests; ADR-0002). `valid_*` must validate against
`schemas/note-events-v1.schema.json`. `invalid_*` must be rejected: `invalid_unknown_major.json` carries
`schema_version: 2`, which a v1 reader must refuse rather than guess at.

`valid_bass_line.json` is ground truth from a seeded synthetic recipe (12 notes, 100 bpm, a beat grid
with every fourth beat a downbeat). Real transcriber output sets `is_downbeat` to `null` because the
tracker does not find bar lines.

`valid_piano_truth.json` is ground truth for a seeded two-handed piano clip (soundfont renderer,
`chords` kind: a right-hand melody over left-hand triads, left hand below MIDI 55, no augmentation).
`valid_piano_baseline.json` is the classical CQT baseline run on the audio of that same clip, so it has
the errors real output will have (extra and merged notes, no velocities). Both carry the same
`source.sha256`. Use the pair to test hand splitting against imperfect input.
