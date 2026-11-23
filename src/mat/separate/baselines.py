"""Reference baselines that bound what a learned separator has to beat.

- IdentitySeparator: the mix as every stem. The floor.
- HpssSeparator: classical harmonic/percussive split plus crude band splits. A cheap real method.
- OracleMaskSeparator: the ideal ratio mask computed from the true stems. The ceiling for any
  separator that works by masking the mix spectrogram. It needs the answer, so it only runs in eval.
"""

from __future__ import annotations

import librosa
import numpy as np
from scipy import signal

from mat.separate.base import Audio

N_FFT, HOP = 2048, 512


class IdentitySeparator:
    name = "identity (mix as every stem)"

    def __init__(self, stems: tuple[str, ...] = ("vocals", "drums", "bass", "other")) -> None:
        self._stems = stems

    def separate(self, mix: Audio, sr: int) -> dict[str, Audio]:
        return {s: mix.copy() for s in self._stems}


class HpssSeparator:
    name = "hpss + band splits (classical)"

    def separate(self, mix: Audio, sr: int) -> dict[str, Audio]:
        harmonic, percussive = librosa.effects.hpss(mix.astype(np.float64), margin=3.0)
        low = signal.butter(4, 200, "lowpass", fs=sr, output="sos")
        mid = signal.butter(4, [200, 4000], "bandpass", fs=sr, output="sos")
        bass = signal.sosfiltfilt(low, harmonic)
        vocals = signal.sosfiltfilt(mid, harmonic)
        other = harmonic - bass - vocals
        out = {"vocals": vocals, "drums": percussive, "bass": bass, "other": other}
        return {k: v.astype(np.float32) for k, v in out.items()}


class OracleMaskSeparator:
    name = "oracle ratio mask (upper bound for masking)"

    def __init__(self, true_stems: dict[str, Audio]) -> None:
        self._true = true_stems

    def separate(self, mix: Audio, sr: int) -> dict[str, Audio]:
        def stft(x: Audio) -> np.ndarray:
            return librosa.stft(x.astype(np.float64), n_fft=N_FFT, hop_length=HOP)

        x = stft(mix)
        power = {k: np.abs(stft(v)) ** 2 for k, v in self._true.items()}
        total = sum(power.values()) + 1e-12
        out: dict[str, Audio] = {}
        for k, p in power.items():
            est = librosa.istft(x * (p / total), hop_length=HOP, length=len(mix))
            out[k] = est.astype(np.float32)
        return out
