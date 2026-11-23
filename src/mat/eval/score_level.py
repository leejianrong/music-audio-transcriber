"""Score-level agreement: do notes land on the right beat positions, not just the right seconds?

IMPORTANT: the quantizer here is a *reference for scoring only*. The product's quantizer lives in
sibei-score (ADR-0002); this one exists so the audio engine can measure how useful its beats and
onsets are without that dependency, using the symbolic ground truth the synth recipes carry.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from mat.core.note_events import Beat, Note
from mat.synth.recipe import SymNote

GRID = 4  # positions are snapped to 1/4 of a beat (a 16th note in 4/4)


def beat_positions(onsets_s: list[float], beats: list[Beat]) -> list[float]:
    """Onset times in beat units: interpolated between tracked beats, extrapolated at the ends."""
    t = np.array([b.t_s for b in beats])
    idx = np.arange(len(t), dtype=np.float64)
    out = np.interp(onsets_s, t, idx)
    first, last = float(t[1] - t[0]), float(t[-1] - t[-2])
    for i, o in enumerate(onsets_s):
        if o < t[0]:
            out[i] = (o - t[0]) / first
        elif o > t[-1]:
            out[i] = (len(t) - 1) + (o - t[-1]) / last
    return [float(x) for x in out]


def quantize(positions: list[float]) -> list[int]:
    return [int(round(p * GRID)) for p in positions]


def score_agreement(
    truth: list[SymNote], est_notes: list[Note], est_beats: list[Beat], max_shift_beats: int = 8
) -> float:
    """F1 over (pitch, quantized beat position). Phase-agnostic: the best whole-beat shift wins.

    A tracker can start counting on any beat, and sibei-score will anchor bars itself, so only
    relative placement is scored. A tempo-octave error (half or double time) still scores badly.
    """
    if not truth or not est_notes or len(est_beats) < 2:
        return 0.0
    notes = sorted(est_notes, key=lambda n: n.onset_s)
    est = list(
        zip(
            [n.pitch for n in notes],
            quantize(beat_positions([n.onset_s for n in notes], est_beats)),
            strict=True,
        )
    )
    ref = [(n.pitch, int(round(n.onset_beat * GRID))) for n in truth]
    best = 0.0
    for shift in range(-max_shift_beats * GRID, max_shift_beats * GRID + 1, GRID):
        shifted = Counter((p, q + shift) for p, q in est)
        hits = sum((shifted & Counter(ref)).values())
        precision, recall = hits / len(est), hits / len(ref)
        if hits:
            best = max(best, 2 * precision * recall / (precision + recall))
    return best
