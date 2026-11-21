# music-audio-transcriber

Turn a recording of a single instrument into NoteEvents and MIDI, and (through
[sibei-score](https://github.com/leejianrong/sibei-score), the notation editor) into sheet music. Later:
separate a multi-instrument mix into stems and transcribe each one.

Status: early. Voice and bass first, using signal-processing pitch tracking and synthetic test data with
exact ground truth. See [PLAN.md](PLAN.md), [SLICES.md](SLICES.md) and [docs/adr](docs/adr).

## Develop

Needs [uv](https://docs.astral.sh/uv/). Run `make` to list targets, `make install`, then `make check`.

Code is Apache-2.0. Trained weights, generated datasets and soundfonts are not part of this repository
and are not covered by that licence ([ADR-0006](docs/adr/0006-apache-code-proprietary-weights.md)).
