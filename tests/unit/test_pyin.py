import numpy as np
import pytest

from mat.eval.notes import note_scores
from mat.synth.generate import build_clip
from mat.synth.recipe import Recipe, SymNote
from mat.synth.render import render_tone
from mat.transcribe.pyin import transcribe_array, transcribe_audio


def test_clean_tone_bass_line_scores_high() -> None:
    clip = build_clip(Recipe(seed=11, instrument="bass", kind="melody", n_notes=14, patch="pluck"))
    est = transcribe_array(clip.audio, 44100, "bass", "0" * 64)
    assert note_scores(clip.truth, est).f1 >= 0.9


def test_clean_tone_voice_scale_scores_high() -> None:
    clip = build_clip(Recipe(seed=5, instrument="voice", kind="scale", n_notes=12, patch="saw"))
    est = transcribe_array(clip.audio, 44100, "voice", "0" * 64)
    assert note_scores(clip.truth, est).f1 >= 0.9


def test_repeated_same_pitch_notes_are_separated() -> None:
    r = Recipe(seed=0, instrument="bass", patch="pluck")
    notes = [SymNote(float(i), 1.0, 40) for i in range(4)]
    audio = render_tone(r, notes)
    import librosa

    y = librosa.resample(audio, orig_sr=44100, target_sr=22050)
    found, _ = transcribe_audio(y, "bass")
    assert [n.pitch for n in found] == [40, 40, 40, 40]


def test_bass_low_b_is_reachable() -> None:
    r = Recipe(seed=0, instrument="bass", patch="pluck")
    audio = render_tone(r, [SymNote(0.0, 2.0, 23)])  # B0, 30.9 Hz
    import librosa

    y = librosa.resample(audio, orig_sr=44100, target_sr=22050)
    found, _ = transcribe_audio(y, "bass")
    assert found and found[0].pitch == 23


def test_silence_is_a_warning_not_an_error() -> None:
    notes, warnings = transcribe_audio(np.zeros(22050, dtype=np.float32), "voice")
    assert notes == []
    assert [w.code for w in warnings] == ["silent_input"]


def test_noise_gives_no_pitch_warning_or_low_confidence() -> None:
    rng = np.random.default_rng(0)
    y = (rng.standard_normal(22050 * 2) * 0.1).astype(np.float32)
    notes, warnings = transcribe_audio(y, "voice")
    assert warnings or not notes


@pytest.mark.parametrize("instrument", ["voice", "bass"])
def test_pitch_precision_reports_cents(instrument: str) -> None:
    clip = build_clip(Recipe(seed=2, instrument=instrument, kind="scale", n_notes=8))  # type: ignore[arg-type]
    est = transcribe_array(clip.audio, 44100, instrument, "0" * 64)  # type: ignore[arg-type]
    assert all(n.cents is not None and -50 <= n.cents <= 50 for n in est.notes)
