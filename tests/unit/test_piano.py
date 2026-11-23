"""Piano groundwork: polyphonic recipes, the classical baseline, the eval suite and the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from mat.cli import main
from mat.core.note_events import NoteEvents
from mat.eval.piano import format_piano, run_piano
from mat.synth.generate import build_clip
from mat.synth.recipe import PIANO_SPLIT, RANGES
from mat.synth.suites import piano_recipes
from mat.transcribe import poly


def test_piano_recipes_are_deterministic_and_in_range() -> None:
    a, b = piano_recipes("tone", 6, seed=3), piano_recipes("tone", 6, seed=3)
    assert a == b
    for r in a:
        clip = build_clip(r)
        again = build_clip(r)
        assert clip.audio.tobytes() == again.audio.tobytes()
        lo, hi = RANGES["piano"]
        assert all(lo <= n.pitch <= hi for n in clip.truth.notes)
        assert clip.truth.instrument == "piano"


def test_piano_clips_are_two_handed_and_polyphonic() -> None:
    for r in piano_recipes("tone", 4, seed=1):
        notes = build_clip(r).truth.notes
        assert any(n.pitch < PIANO_SPLIT for n in notes)
        assert any(n.pitch >= PIANO_SPLIT for n in notes)
        overlaps = sum(
            1
            for a in notes
            for b in notes
            if a.id < b.id and a.onset_s < b.offset_s - 0.01 and b.onset_s < a.offset_s - 0.01
        )
        assert overlaps > 0


def test_baseline_recovers_most_notes_on_tone_piano() -> None:
    report = run_piano("tone", n=6, seed=0)
    s = report.summary()
    assert s["recall"] > 0.85  # type: ignore[operator]
    assert s["f1"] > 0.6  # type: ignore[operator]
    assert "piano suite" in format_piano(report)


def test_silence_gives_no_notes() -> None:
    ev = poly.transcribe_array(np.zeros(22050, dtype=np.float32), 22050, "0" * 64)
    assert ev.notes == []


def test_cli_transcribes_piano_to_valid_note_events(tmp_path: Path) -> None:
    clip = build_clip(piano_recipes("tone", 1, seed=0)[0])
    wav = tmp_path / "p.wav"
    sf.write(str(wav), clip.audio, clip.recipe.sample_rate)
    assert (
        main(["transcribe", str(wav), "--instrument", "piano", "-o", str(tmp_path), "--json"]) == 0
    )
    ev = NoteEvents.model_validate(json.loads((tmp_path / "p.notes.json").read_text()))
    assert ev.instrument == "piano"
    assert ev.producer.model_id == poly.MODEL_ID
    assert len(ev.notes) > 5
