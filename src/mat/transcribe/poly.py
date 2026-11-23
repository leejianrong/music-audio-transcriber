"""Polyphonic baseline: constant-Q salience, harmonic suppression, per-pitch activity runs.

Classical DSP with no learned weights (ADR-0001). It is the floor our own piano model has to beat,
and the stand-in that lets sibei-score exercise its hand split on imperfect, real-shaped output.
"""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt

from mat.core.note_events import Note, NoteEvents, Producer, Source, sha256_file
from mat.transcribe.audio_io import load_audio

SR = 22050
HOP = 512
LOW, HIGH = 36, 96  # C2..C7, covers the piano range we synthesise
ACTIVE_DB = -28.0  # relative to the clip's loudest bin
OCTAVE_RATIO = 0.6  # a bin an octave above an active one is a harmonic unless it is this strong
REATTACK = 1.8  # an energy rise of this factor within two frames starts a new note
MIN_NOTE_S = 0.08
MODEL_ID = "cqt-poly-baseline"


def _salience(y: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
    cqt = np.abs(
        librosa.cqt(
            y,
            sr=SR,
            hop_length=HOP,
            fmin=float(librosa.midi_to_hz(LOW)),
            n_bins=HIGH - LOW + 1,
            bins_per_octave=12,
        )
    )
    return np.asarray(cqt, dtype=np.float64)


def _active(mag: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
    peak = float(mag.max()) or 1.0
    on = mag > peak * 10 ** (ACTIVE_DB / 20)
    padded = np.pad(mag, ((1, 1), (0, 0)))
    on &= (mag >= padded[:-2]) & (mag >= padded[2:])  # a pitch is a local peak: no leakage notes
    for k in range(mag.shape[0] - 1, 11, -1):  # high to low: judge a bin against the one below
        harmonic = on[k - 12] & (mag[k] < OCTAVE_RATIO * mag[k - 12])
        on[k] &= ~harmonic
    for k in range(mag.shape[0] - 1, 18, -1):  # twelfth (octave + fifth) harmonics
        on[k] &= ~(on[k - 19] & (mag[k] < OCTAVE_RATIO * mag[k - 19]))
    return on


def _events(y: npt.NDArray[np.float32], sha256: str) -> NoteEvents:
    mag = _salience(y)
    on = _active(mag)
    frame_s = HOP / SR
    min_frames = max(1, int(round(MIN_NOTE_S / frame_s)))
    notes: list[Note] = []
    for k in range(mag.shape[0]):
        start: int | None = None
        for f in range(mag.shape[1] + 1):
            alive = f < mag.shape[1] and bool(on[k, f])
            rise = (
                alive
                and start is not None
                and f >= 2
                and mag[k, f] > REATTACK * max(mag[k, f - 1], mag[k, f - 2], 1e-9)
            )
            if start is not None and (not alive or rise):
                if f - start >= min_frames:
                    peak = float(mag[k, start:f].max())
                    notes.append(
                        Note(
                            id="",
                            onset_s=start * frame_s,
                            offset_s=f * frame_s,
                            pitch=LOW + k,
                            confidence=float(np.clip(peak / (float(mag.max()) or 1.0), 0.05, 1.0)),
                        )
                    )
                start = None
            if alive and start is None:
                start = f
    notes.sort(key=lambda n: (n.onset_s, n.pitch))
    notes = [n.model_copy(update={"id": f"n{i}"}) for i, n in enumerate(notes)]
    return NoteEvents(
        source=Source(sha256=sha256, duration_s=len(y) / SR),
        instrument="piano",
        producer=Producer(model_id=MODEL_ID, model_version="1"),
        notes=notes,
    )


def transcribe_array(y: npt.NDArray[np.float32], sr: int, sha256: str) -> NoteEvents:
    yy = librosa.resample(y, orig_sr=sr, target_sr=SR) if sr != SR else y
    return _events(yy, sha256)


def transcribe_file(path: Path) -> NoteEvents:
    return _events(load_audio(path, SR), sha256_file(path))
