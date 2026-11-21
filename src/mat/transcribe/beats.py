"""Beat tracking attached to NoteEvents (S4). librosa's tracker first; Beat This! is a later swap.

The tracker finds beats but not downbeats, so `is_downbeat` stays None (unknown) and sibei-score
must not assume where bar lines fall.
"""

from __future__ import annotations

from typing import Protocol

import librosa
import numpy as np
import numpy.typing as npt

from mat.core.note_events import Beat, NoteWarning


class BeatTracker(Protocol):
    def track(
        self, y: npt.NDArray[np.float32], sr: int
    ) -> tuple[list[Beat], list[NoteWarning]]: ...


class LibrosaBeatTracker:
    model_id = "librosa-beat"

    def __init__(self, start_bpm: float = 100.0) -> None:
        self.start_bpm = start_bpm

    def track(self, y: npt.NDArray[np.float32], sr: int) -> tuple[list[Beat], list[NoteWarning]]:
        if y.size == 0 or float(np.max(np.abs(y))) < 1e-4:
            return [], []
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        _, frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, start_bpm=self.start_bpm, units="frames"
        )
        times = librosa.frames_to_time(frames, sr=sr)
        if len(times) < 2:
            return [], [NoteWarning(code="no_beats", message="no steady beat was detected")]
        beats = [Beat(t_s=float(t), is_downbeat=None) for t in times]
        return beats, [
            NoteWarning(
                code="downbeats_unknown",
                message="beats were tracked but bar lines (downbeats) were not detected",
            )
        ]


TEMPO_RANGE = (70.0, 160.0)


def _fold_tempo(bpm: float) -> float:
    lo, hi = TEMPO_RANGE
    while bpm < lo:
        bpm *= 2
    while bpm >= hi:
        bpm /= 2
    return bpm


def refine_with_onsets(
    beats: list[Beat], onsets_s: list[float], duration_s: float, tempo_prior: float = 0.05
) -> list[Beat]:
    """Fit a steady beat grid to the note onsets, starting from the tracker's tempo.

    The audio tracker is coarse (about 2% tempo error), which drifts out of step over a phrase.
    Note onsets are much sharper, so scan tempi from 70 to 160 bpm for the grid that puts most
    onsets on half-beat positions, with a small prior toward the tracker's tempo (folded into that
    range). The phase is then chosen so the first note falls on a beat, as performances usually
    begin.
    Returns the input unchanged if there are too few notes or the fit is weak.
    """
    if len(beats) < 2 or len(onsets_s) < 4:
        return beats
    times = np.array([b.t_s for b in beats])
    base = _fold_tempo(float(60.0 / np.median(np.diff(times))))
    o = np.array(onsets_s)
    best_r, best_bpm, best_z, best_obj = -1.0, base, 0j, -1e9
    lo, hi = TEMPO_RANGE
    for bpm in np.arange(lo, hi, 0.2):
        period = 60.0 / bpm
        z = np.exp(2j * np.pi * (2.0 * o / period)).mean()
        # Prefer the tracker's tempo: tempos in simple ratios fit equally well (80 vs 160 bpm).
        obj = float(abs(z)) - tempo_prior * abs(np.log2(bpm / base))
        if obj > best_obj:
            best_obj, best_r, best_bpm, best_z = obj, float(abs(z)), float(bpm), z
    if best_r < 0.5:
        return beats
    period = 60.0 / best_bpm
    phase = (np.angle(best_z) / (2 * np.pi)) * period / 2.0  # aligned to a half-beat grid
    candidates = [phase % period, (phase + period / 2.0) % period]

    def first_note_error(ph: float) -> float:
        frac = ((o[0] - ph) / period) % 1.0
        return float(min(frac, 1.0 - frac))

    ph = min(candidates, key=first_note_error)
    k0 = int(np.ceil((0.0 - ph) / period))
    k1 = int(np.floor((duration_s - ph) / period))
    return [Beat(t_s=float(ph + k * period), is_downbeat=None) for k in range(k0, k1 + 1)]
