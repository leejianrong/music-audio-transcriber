"""NoteEvents <-> MIDI. MIDI loses confidences, warnings and sub-semitone pitch."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pretty_midi

from mat.core.note_events import Instrument, Note, NoteEvents, Producer, Source

GM_PROGRAM: dict[str, int] = {
    "voice": 53,  # Voice Oohs
    "bass": 33,  # Electric Bass (finger)
    "piano": 0,
    "guitar": 25,
    "other": 0,
}


def _tempo(events: NoteEvents) -> float:
    if len(events.beats) >= 2:
        times = np.array([b.t_s for b in events.beats])
        return float(60.0 / np.median(np.diff(times)))
    return 120.0


def to_pretty_midi(events: NoteEvents) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=_tempo(events))
    is_drum = events.instrument == "drums"
    inst = pretty_midi.Instrument(program=GM_PROGRAM.get(events.instrument, 0), is_drum=is_drum)
    for n in events.notes:
        inst.notes.append(
            pretty_midi.Note(
                velocity=n.velocity if n.velocity is not None else 80,
                pitch=n.pitch,
                start=n.onset_s,
                end=n.offset_s,
            )
        )
    pm.instruments.append(inst)
    return pm


def write_midi(events: NoteEvents, path: Path) -> None:
    to_pretty_midi(events).write(str(path))


def from_midi(path: Path, instrument: Instrument, sha256: str = "0" * 64) -> NoteEvents:
    """Read a ground-truth MIDI file (all tracks merged) as NoteEvents."""
    pm = pretty_midi.PrettyMIDI(str(path))
    raw = sorted(
        (n for inst in pm.instruments if not inst.is_drum for n in inst.notes),
        key=lambda n: (n.start, n.pitch),
    )
    notes = [
        Note(
            id=f"n{i}",
            onset_s=float(n.start),
            offset_s=float(max(n.end, n.start + 1e-3)),
            pitch=int(n.pitch),
            velocity=int(n.velocity),
            confidence=1.0,
        )
        for i, n in enumerate(raw)
    ]
    return NoteEvents(
        source=Source(sha256=sha256, duration_s=float(pm.get_end_time())),
        instrument=instrument,
        producer=Producer(model_id="ground-truth", model_version="midi"),
        notes=notes,
    )
