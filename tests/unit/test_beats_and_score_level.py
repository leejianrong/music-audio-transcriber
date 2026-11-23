import numpy as np

from mat.core.note_events import Beat, Note
from mat.eval.score_level import beat_positions, score_agreement
from mat.synth.generate import build_clip
from mat.synth.recipe import Recipe, SymNote
from mat.transcribe.beats import LibrosaBeatTracker, refine_with_onsets
from mat.transcribe.pyin import transcribe_array


def _beats(bpm: float, n: int = 40, offset: float = 0.0) -> list[Beat]:
    return [Beat(t_s=offset + i * 60.0 / bpm) for i in range(n)]


def _notes(onsets: list[float], pitches: list[int]) -> list[Note]:
    return [
        Note(id=f"n{i}", onset_s=o, offset_s=o + 0.1, pitch=p, confidence=1.0)
        for i, (o, p) in enumerate(zip(onsets, pitches, strict=True))
    ]


def test_beat_positions_interpolate_and_extrapolate() -> None:
    pos = beat_positions([0.0, 0.3, 0.75], _beats(100.0, offset=0.0))
    assert np.allclose(pos, [0.0, 0.5, 1.25])
    assert beat_positions([-0.6], _beats(100.0))[0] == -1.0


def test_perfect_notes_on_a_perfect_grid_agree_fully() -> None:
    truth = [SymNote(0.0, 1.0, 40), SymNote(1.0, 0.5, 43), SymNote(1.5, 0.5, 45)]
    est = _notes([0.0, 0.6, 0.9], [40, 43, 45])
    assert score_agreement(truth, est, _beats(100.0)) == 1.0


def test_whole_beat_phase_shift_is_forgiven_but_half_time_is_not() -> None:
    truth = [SymNote(float(i), 1.0, 40 + i % 3) for i in range(8)]
    onsets = [i * 0.6 + 1.2 for i in range(8)]  # starts two beats later
    est = _notes(onsets, [40 + i % 3 for i in range(8)])
    assert score_agreement(truth, est, _beats(100.0)) == 1.0
    assert score_agreement(truth, est, _beats(50.0)) < 0.6  # tracker locked to half time


def test_refine_snaps_a_drifting_tempo_to_the_note_grid() -> None:
    true_bpm = 120.0
    onsets = [i * 0.5 * 60 / true_bpm for i in range(16)]
    coarse = _beats(117.5, n=20)  # the 2% error librosa shows
    refined = refine_with_onsets(coarse, onsets, duration_s=8.0)
    est_bpm = 60.0 / float(np.median(np.diff([b.t_s for b in refined])))
    assert abs(est_bpm - true_bpm) < 0.5


def test_refine_leaves_beats_alone_with_too_few_notes() -> None:
    coarse = _beats(100.0, n=10)
    assert refine_with_onsets(coarse, [0.0, 1.0], 6.0) == coarse


def test_tracker_returns_nothing_for_silence() -> None:
    beats, warnings = LibrosaBeatTracker().track(np.zeros(22050, dtype=np.float32), 22050)
    assert beats == [] and warnings == []


def test_transcription_attaches_beats_and_flags_unknown_downbeats() -> None:
    clip = build_clip(Recipe(seed=8, instrument="bass", kind="melody", n_notes=16, patch="pluck"))
    ev = transcribe_array(clip.audio, 44100, "bass", "0" * 64)
    assert len(ev.beats) > 8
    assert all(b.is_downbeat is None for b in ev.beats)
    assert "downbeats_unknown" in [w.code for w in ev.warnings]


def test_synthetic_score_level_agreement_meets_the_bar() -> None:
    from mat.eval.suite import run_mono

    summary = run_mono("tone", n=12, seed=0).summary()
    agreement = summary["synthetic_score_agreement"]
    assert isinstance(agreement, float) and agreement >= 0.80
