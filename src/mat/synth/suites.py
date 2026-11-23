"""Deterministic recipe suites: the same (name, n, seed) always yields the same recipes."""

from __future__ import annotations

from typing import Literal

import numpy as np

from mat.synth.recipe import AugmentSpec, Recipe

# General MIDI programs used for fluidsynth: bass patches and melodic (voice-range) patches.
BASS_PROGRAMS = (32, 33, 34, 35)  # acoustic, finger, pick, fretless
MELODY_PROGRAMS = (52, 53, 54, 73, 71)  # choir aahs, voice oohs, synth voice, flute, clarinet
TONE_PATCHES = ("saw", "sine", "pluck")


def _pick(rng: np.random.Generator, options: tuple[float | None, ...]) -> float | None:
    return options[int(rng.integers(0, len(options)))]


def mono_recipes(
    renderer: Literal["tone", "fluidsynth"], n: int, seed: int = 0, augment: bool = True
) -> list[Recipe]:
    rng = np.random.default_rng(seed)
    out: list[Recipe] = []
    for i in range(n):
        instrument: Literal["voice", "bass"] = "bass" if i % 2 == 0 else "voice"
        kind: Literal["scale", "arpeggio", "melody"] = ("scale", "arpeggio", "melody")[i % 3]
        if renderer == "tone":
            patch = TONE_PATCHES[int(rng.integers(0, len(TONE_PATCHES)))]
        else:
            progs = BASS_PROGRAMS if instrument == "bass" else MELODY_PROGRAMS
            patch = f"gm:{progs[int(rng.integers(0, len(progs)))]}"
        aug = AugmentSpec()
        if augment:
            aug = AugmentSpec(
                gain_db=float(rng.uniform(-6, 0)),
                noise_snr_db=_pick(rng, (None, 40.0, 30.0, 25.0)) if i % 2 else None,
                highpass_hz=_pick(rng, (None, 30.0, 60.0)) if i % 3 == 0 else None,
                lowpass_hz=_pick(rng, (None, 4000.0, 8000.0)) if i % 3 == 1 else None,
                reverb_rt60_s=_pick(rng, (None, 0.3, 0.6, 1.0)) if i % 4 != 3 else None,
                reverb_wet=float(rng.uniform(0.1, 0.35)),
            )
        out.append(
            Recipe(
                seed=int(rng.integers(0, 2**31 - 1)),
                instrument=instrument,
                kind=kind,
                n_notes=int(rng.integers(12, 21)),
                bpm=float(rng.choice([80.0, 100.0, 120.0])),
                renderer=renderer,
                patch=patch,
                augment=aug,
            )
        )
    return out
