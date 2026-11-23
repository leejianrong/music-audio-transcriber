"""Decode an audio or video file to mono float32. Hard error if it cannot be decoded."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import librosa
import numpy as np
import numpy.typing as npt
import soundfile as sf


class AudioDecodeError(Exception):
    pass


def load_audio(path: Path, sr: int) -> npt.NDArray[np.float32]:
    """Mono float32 at `sr`. Tries libsndfile first, then ffmpeg (mp3, video containers)."""
    if not path.exists():
        raise AudioDecodeError(f"no such file: {path}")
    try:
        data, native = sf.read(str(path), dtype="float32", always_2d=True)
        y = data.mean(axis=1)
        if native != sr:
            y = librosa.resample(y, orig_sr=native, target_sr=sr)
        return np.asarray(y, dtype=np.float32)
    except Exception:  # noqa: BLE001 - fall through to ffmpeg
        pass
    if not shutil.which("ffmpeg"):
        raise AudioDecodeError(f"cannot decode {path.name} and ffmpeg is not installed")
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr)]
    cmd += ["-f", "f32le", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, check=True, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise AudioDecodeError(f"cannot decode {path.name}") from e
    y = np.frombuffer(r.stdout, dtype=np.float32)
    if y.size == 0:
        raise AudioDecodeError(f"no audio stream in {path.name}")
    return y.copy()
