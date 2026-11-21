"""Augmentation chain: EQ, reverb, noise, codec, gain. Deterministic given the recipe seed."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from mat.synth.recipe import AugmentSpec
from mat.synth.render import Audio


def synthetic_reverb_ir(rt60_s: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """Exponentially decaying noise: our own impulse response, so no third-party IR licence."""
    n = int(rt60_s * sr)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n) * np.exp(-6.9 * t / rt60_s)  # -60 dB at rt60
    ir[0] = 1.0
    return np.asarray(ir / np.sqrt(np.sum(ir**2)), dtype=np.float64)


def apply(audio: Audio, spec: AugmentSpec, sr: int, seed: int) -> Audio:
    rng = np.random.default_rng(seed + 7919)
    y = audio.astype(np.float64)
    if spec.highpass_hz:
        sos = signal.butter(2, spec.highpass_hz, "highpass", fs=sr, output="sos")
        y = signal.sosfilt(sos, y)
    if spec.lowpass_hz:
        sos = signal.butter(2, spec.lowpass_hz, "lowpass", fs=sr, output="sos")
        y = signal.sosfilt(sos, y)
    if spec.reverb_rt60_s:
        ir = synthetic_reverb_ir(spec.reverb_rt60_s, sr, rng)
        wet = signal.fftconvolve(y, ir)[: len(y)]
        wet *= np.sqrt(np.mean(y**2) / (np.mean(wet**2) + 1e-12))
        y = (1 - spec.reverb_wet) * y + spec.reverb_wet * wet
    if spec.noise_snr_db is not None:
        p_sig = np.mean(y**2)
        p_noise = p_sig / (10 ** (spec.noise_snr_db / 10))
        y = y + rng.standard_normal(len(y)) * np.sqrt(p_noise)
    if spec.codec == "mp3":
        y = _mp3_roundtrip(y, sr)
    y = y * 10 ** (spec.gain_db / 20)
    return np.clip(y, -1.0, 1.0).astype(np.float32)


def _mp3_roundtrip(y: np.ndarray, sr: int) -> np.ndarray:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg required for codec augmentation")
    with tempfile.TemporaryDirectory(prefix="mat-codec-") as tmp:
        src, mp3, out = (Path(tmp) / n for n in ("a.wav", "a.mp3", "b.wav"))
        sf.write(str(src), y.astype(np.float32), sr)
        for cmd in (
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-b:a", "96k", str(mp3)],
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", str(sr), str(out)],
        ):
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        data, _ = sf.read(str(out), dtype="float32")
    data = np.asarray(data).reshape(-1)
    n = len(y)
    return np.pad(data, (0, max(0, n - len(data))))[:n].astype(np.float64)
