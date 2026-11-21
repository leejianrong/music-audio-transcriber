from mat.core.note_events import Note, NoteEvents, Producer, Source
from mat.eval.notes import best_offset_scores, note_scores


def _ev(onsets: list[float], pitch: int = 40) -> NoteEvents:
    return NoteEvents(
        source=Source(sha256="b" * 64, duration_s=10.0),
        instrument="bass",
        producer=Producer(model_id="t", model_version="1"),
        notes=[
            Note(id=f"n{i}", onset_s=o, offset_s=o + 0.4, pitch=pitch + i, confidence=1.0)
            for i, o in enumerate(onsets)
        ],
    )


def test_perfect_transcriber_scores_one() -> None:
    ref = _ev([0.0, 1.0, 2.0])
    assert note_scores(ref, ref).f1 == 1.0


def test_shifted_by_100ms_misses_the_50ms_tolerance() -> None:
    assert note_scores(_ev([0.0, 1.0, 2.0]), _ev([0.1, 1.1, 2.1])).f1 == 0.0


def test_empty_estimate_scores_zero() -> None:
    assert note_scores(_ev([0.0]), _ev([])).f1 == 0.0


def test_best_offset_recovers_a_count_in_shift() -> None:
    ref = _ev([0.0, 1.0, 2.0])
    shifted = _ev([0.5, 1.5, 2.5])
    scores, shift = best_offset_scores(ref, shifted)
    assert scores.f1 == 1.0
    assert abs(shift + 0.5) < 0.03
