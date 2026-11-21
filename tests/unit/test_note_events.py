import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mat.core import midi
from mat.core.note_events import Note, NoteEvents, Producer, Source, schema_text

ROOT = Path(__file__).resolve().parents[2]


def _events(notes: list[Note]) -> NoteEvents:
    return NoteEvents(
        source=Source(sha256="a" * 64, duration_s=2.0),
        instrument="bass",
        producer=Producer(model_id="t", model_version="1"),
        notes=notes,
    )


def test_valid_events_round_trip_json() -> None:
    ev = _events([Note(id="n0", onset_s=0.0, offset_s=0.5, pitch=40, confidence=0.9)])
    again = NoteEvents.model_validate_json(ev.model_dump_json())
    assert again == ev


def test_rejects_offset_not_after_onset() -> None:
    with pytest.raises(ValidationError):
        Note(id="n0", onset_s=1.0, offset_s=1.0, pitch=40, confidence=1.0)


def test_rejects_unknown_fields_and_bad_sha() -> None:
    with pytest.raises(ValidationError):
        NoteEvents.model_validate({**_events([]).model_dump(), "surprise": 1})
    with pytest.raises(ValidationError):
        Source(sha256="xyz", duration_s=1.0)


def test_rejects_unknown_schema_version() -> None:
    bad = {**_events([]).model_dump(), "schema_version": 2}
    with pytest.raises(ValidationError):
        NoteEvents.model_validate(bad)


def test_checked_in_schema_matches_model() -> None:
    on_disk = (ROOT / "schemas" / "note-events-v1.schema.json").read_text()
    assert on_disk == schema_text(), "run: uv run mat schema > schemas/note-events-v1.schema.json"
    assert json.loads(on_disk)["properties"]["schema_version"]["const"] == 1


def test_midi_round_trip(tmp_path: Path) -> None:
    ev = _events(
        [
            Note(id="n0", onset_s=0.0, offset_s=0.5, pitch=40, confidence=1.0),
            Note(id="n1", onset_s=0.5, offset_s=1.25, pitch=43, confidence=1.0),
        ]
    )
    path = tmp_path / "x.mid"
    midi.write_midi(ev, path)
    back = midi.from_midi(path, "bass")
    assert [n.pitch for n in back.notes] == [40, 43]
    assert back.notes[1].onset_s == pytest.approx(0.5, abs=0.01)
