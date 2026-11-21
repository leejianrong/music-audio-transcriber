"""Note-level metrics with mir_eval: onset F1 (50 ms, 50 cents), plus an offset-aware variant."""

from __future__ import annotations

from dataclasses import dataclass

import mir_eval
import numpy as np

from mat.core.note_events import Note, NoteEvents


@dataclass(frozen=True)
class NoteScores:
    precision: float
    recall: float
    f1: float
    f1_with_offset: float


def _arrays(notes: list[Note], shift_s: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    kept = [n for n in notes if n.offset_s + shift_s > 1e-3]  # a shift can push notes before t=0
    if not kept:
        return np.zeros((0, 2)), np.zeros(0)
    iv = np.array([[max(n.onset_s + shift_s, 0.0), n.offset_s + shift_s] for n in kept])
    hz = np.array([440.0 * 2 ** ((n.pitch + (n.cents or 0) / 100 - 69) / 12) for n in kept])
    return iv, hz


def note_scores(
    ref: NoteEvents,
    est: NoteEvents,
    onset_tol_s: float = 0.05,
    pitch_tol_cents: float = 50.0,
    est_shift_s: float = 0.0,
) -> NoteScores:
    ref_iv, ref_hz = _arrays(ref.notes)
    est_iv, est_hz = _arrays(est.notes, est_shift_s)
    if len(ref_hz) == 0 or len(est_hz) == 0:
        return NoteScores(0.0, 0.0, 0.0, 0.0)
    p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_iv,
        ref_hz,
        est_iv,
        est_hz,
        onset_tolerance=onset_tol_s,
        pitch_tolerance=pitch_tol_cents,
        offset_ratio=None,
    )
    _, _, f_off, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_iv,
        ref_hz,
        est_iv,
        est_hz,
        onset_tolerance=onset_tol_s,
        pitch_tolerance=pitch_tol_cents,
        offset_ratio=0.2,
    )
    return NoteScores(float(p), float(r), float(f), float(f_off))


def best_offset_scores(
    ref: NoteEvents, est: NoteEvents, max_shift_s: float = 1.0, step_s: float = 0.025
) -> tuple[NoteScores, float]:
    """Real clips are recorded against a click with a count-in, so search a small global shift.

    Ties are common (any shift inside the onset tolerance scores the same), so take their middle.
    """
    shifts = [float(x) for x in np.arange(-max_shift_s, max_shift_s + step_s, step_s)]
    scored = [(note_scores(ref, est, est_shift_s=x), x) for x in shifts]
    top = max(s.f1 for s, _ in scored)
    tied = [(s, x) for s, x in scored if s.f1 >= top - 1e-12]
    mid = tied[len(tied) // 2]
    return mid
