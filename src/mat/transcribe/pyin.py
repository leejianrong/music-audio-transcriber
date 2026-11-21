"""Monophonic transcription with librosa pYIN: classical DSP, no learned weights (ADR-0001)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import librosa
import numpy as np
import numpy.typing as npt

from mat.core.note_events import (
    Note,
    NoteEvents,
    NoteWarning,
    Producer,
    Source,
    sha256_file,
)
from mat.transcribe.audio_io import load_audio
from mat.transcribe.beats import LibrosaBeatTracker, refine_with_onsets

SR = 22050
HOP = 256
FRAME = 2048
ENV_FRAME = 1024  # envelope window: shorter than FRAME so a 60 ms gap between repeats is visible
MODEL_ID = "pyin-notes"
MODEL_VERSION = "1"

# (fmin, fmax) in Hz. Bass goes below 40 Hz so a 5-string B0 (30.9 Hz) is reachable.
F0_RANGE: dict[str, tuple[float, float]] = {"bass": (30.0, 440.0), "voice": (65.0, 1100.0)}

Mono = Literal["voice", "bass"]


@dataclass(frozen=True)
class PyinParams:
    min_note_s: float = 0.06
    rms_floor_db: float = -45.0  # frames below this (relative to the clip peak) are silent
    dip_ratio: float = 0.45  # split a held pitch where RMS falls below this fraction of the peaks
    onset_frac: float = (
        0.15  # walk an onset back to where energy first exceeds this fraction of the note peak
    )
    onset_back_s: float = 0.14  # ...by at most this much (pYIN voices late on soft attacks)


def _runs(labels: npt.NDArray[np.int_]) -> list[tuple[int, int, int]]:
    """(start, end_exclusive, label) of consecutive equal values."""
    out: list[tuple[int, int, int]] = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            out.append((start, i, int(labels[start])))
            start = i
    return out


def _split_on_dips(
    rms: npt.NDArray[np.float64], start: int, end: int, ratio: float, min_frames: int
) -> list[tuple[int, int]]:
    """Split a constant-pitch run where the envelope dips: repeated notes of the same pitch."""
    if end - start < 2 * min_frames:
        return [(start, end)]
    seg = rms[start:end]
    cuts: list[int] = []
    last_cut = 0
    for i in range(min_frames, len(seg) - min_frames):
        if seg[i] <= seg[i - 1] and seg[i] <= seg[i + 1] and i - last_cut >= min_frames:
            left = seg[max(last_cut, i - 40) : i].max()
            right = seg[i + 1 : i + 41].max()
            if seg[i] < ratio * min(left, right):
                cuts.append(i)
                last_cut = i
    bounds = [0, *cuts, len(seg)]
    return [(start + a, start + b) for a, b in zip(bounds[:-1], bounds[1:], strict=True)]


def transcribe_audio(
    y: npt.NDArray[np.float32], instrument: Mono, params: PyinParams | None = None
) -> tuple[list[Note], list[NoteWarning]]:
    p = params or PyinParams()
    warnings: list[NoteWarning] = []
    if y.size == 0 or float(np.max(np.abs(y))) < 1e-4:
        return [], [NoteWarning(code="silent_input", message="no audible signal in the input")]
    if float(np.max(np.abs(y))) >= 0.999:
        warnings.append(NoteWarning(code="clipping", message="input peaks at full scale"))

    fmin, fmax = F0_RANGE[instrument]
    f0, voiced, prob = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=SR, frame_length=FRAME, hop_length=HOP
    )
    rms = librosa.feature.rms(y=y, frame_length=ENV_FRAME, hop_length=HOP)[0].astype(np.float64)
    n = min(len(f0), len(rms))
    f0, voiced, prob, rms = f0[:n], voiced[:n], prob[:n], rms[:n]

    peak = float(rms.max()) or 1.0
    audible = rms > peak * 10 ** (p.rms_floor_db / 20)
    mask = voiced & audible & np.isfinite(f0)
    midi = np.full(n, np.nan)
    midi[mask] = librosa.hz_to_midi(f0[mask])
    labels = np.where(mask, np.round(np.nan_to_num(midi, nan=-1)).astype(int), -1)

    min_frames = max(2, int(round(p.min_note_s * SR / HOP)))
    runs = _runs(labels)
    # Drop short blips; bridge a short run sandwiched between two runs of the same pitch.
    kept: list[tuple[int, int, int]] = []
    for i, (s, e, lab) in enumerate(runs):
        if e - s >= min_frames:
            kept.append((s, e, lab))
        elif lab != -1 and 0 < i < len(runs) - 1 and runs[i - 1][2] == runs[i + 1][2] != -1:
            kept.append((s, e, runs[i - 1][2]))
    merged: list[list[int]] = []
    for s, e, lab in kept:
        if merged and merged[-1][2] == lab and s - merged[-1][1] <= 1 and lab != -1:
            merged[-1][1] = e
        else:
            merged.append([s, e, lab])

    notes: list[Note] = []
    back_frames = int(round(p.onset_back_s * SR / HOP))
    prev_end = 0
    for s, e, lab in merged:
        if lab == -1:
            continue
        for a, b in _split_on_dips(rms, s, e, p.dip_ratio, min_frames):
            if b - a < min_frames:
                continue
            seg = midi[a:b]
            med = float(np.nanmedian(seg))
            pitch = int(round(med))
            cents = int(np.clip(round((med - pitch) * 100), -50, 50))
            conf = float(np.clip(np.nanmean(prob[a:b]), 0.0, 1.0))
            lo = max(prev_end, a - back_frames)
            peak_note = float(rms[a:b].max())
            a_on = a
            while a_on > lo and rms[a_on - 1] >= p.onset_frac * peak_note:
                a_on -= 1
            prev_end = b
            onset = float(librosa.frames_to_time(a_on, sr=SR, hop_length=HOP))
            offset = float(librosa.frames_to_time(b, sr=SR, hop_length=HOP))
            notes.append(
                Note(
                    id=f"n{len(notes)}",
                    onset_s=onset,
                    offset_s=max(offset, onset + 1e-3),
                    pitch=int(np.clip(pitch, 0, 127)),
                    cents=cents,
                    confidence=conf,
                )
            )
    if not notes:
        warnings.append(NoteWarning(code="no_pitch_detected", message="no pitched notes found"))
    elif float(np.mean([n.confidence for n in notes])) < 0.5:
        warnings.append(
            NoteWarning(code="low_confidence", message="mean note confidence below 0.5")
        )
    return notes, warnings


def _events(y: npt.NDArray[np.float32], instrument: Mono, sha256: str) -> NoteEvents:
    """Notes plus a beat grid for a clip already resampled to SR."""
    notes, warnings = transcribe_audio(y, instrument)
    beats, beat_warnings = LibrosaBeatTracker().track(y, SR)
    beats = refine_with_onsets(beats, [n.onset_s for n in notes], float(len(y) / SR))
    return NoteEvents(
        source=Source(sha256=sha256, duration_s=float(len(y) / SR)),
        instrument=instrument,
        producer=Producer(model_id=MODEL_ID, model_version=MODEL_VERSION),
        beats=beats,
        notes=notes,
        warnings=[*warnings, *beat_warnings],
    )


def transcribe_file(path: Path, instrument: Mono) -> NoteEvents:
    return _events(load_audio(path, SR), instrument, sha256_file(path))


def transcribe_array(
    y: npt.NDArray[np.float32], sr: int, instrument: Mono, sha256: str
) -> NoteEvents:
    """Transcribe an in-memory clip (used by the eval suite)."""
    yy = librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y
    return _events(yy, instrument, sha256)
