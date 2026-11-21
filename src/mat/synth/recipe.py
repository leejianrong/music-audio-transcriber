"""Recipes: a synthetic clip is fully described by a recipe; audio is only a cache (ADR-0004)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

RECIPE_VERSION = 1

# MIDI note ranges per instrument (inclusive).
RANGES: dict[str, tuple[int, int]] = {
    "bass": (28, 55),  # E1..G3
    "voice": (48, 72),  # C3..C5
}

# Scale degrees (semitones from the tonic) used by the melody generators.
SCALES: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "pentatonic": (0, 2, 4, 7, 9),
}


@dataclass(frozen=True)
class AugmentSpec:
    gain_db: float = 0.0
    noise_snr_db: float | None = None
    highpass_hz: float | None = None
    lowpass_hz: float | None = None
    reverb_rt60_s: float | None = None
    reverb_wet: float = 0.25
    codec: Literal["mp3"] | None = None


@dataclass(frozen=True)
class Recipe:
    seed: int
    instrument: Literal["voice", "bass"]
    kind: Literal["scale", "arpeggio", "melody"] = "melody"
    n_notes: int = 16
    bpm: float = 100.0
    renderer: Literal["tone", "fluidsynth"] = "tone"
    # tone: "saw" | "sine" | "pluck". fluidsynth: "gm:<program>" (General MIDI program number).
    patch: str = "saw"
    soundfont: str | None = None
    sample_rate: int = 44100
    augment: AugmentSpec = field(default_factory=AugmentSpec)
    recipe_version: int = RECIPE_VERSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Recipe:
        d = dict(d)
        d["augment"] = AugmentSpec(**d.get("augment", {}))
        return Recipe(**d)

    @staticmethod
    def load(path: Path) -> Recipe:
        return Recipe.from_dict(json.loads(path.read_text()))


@dataclass(frozen=True)
class SymNote:
    """A note on a beat grid. This is the symbolic ground truth (a sibei-score model later)."""

    onset_beat: float
    dur_beat: float
    pitch: int


ARTICULATION = 0.9  # a note sounds for 90% of its written length, so repeats are separable


def generate_symbolic(recipe: Recipe) -> list[SymNote]:
    rng = np.random.default_rng(recipe.seed)
    lo, hi = RANGES[recipe.instrument]
    scale_name = ("major", "minor", "pentatonic")[int(rng.integers(0, 3))]
    scale = SCALES[scale_name]
    tonic = int(rng.integers(lo, lo + 12))
    pool = [
        p
        for octave in range(-12, 120, 12)
        for step in scale
        if lo <= (p := tonic % 12 + octave + step) <= hi
    ]
    pool.sort()
    if len(pool) < 4:
        raise ValueError("pitch pool too small")

    if recipe.kind == "scale":
        start = int(rng.integers(0, max(1, len(pool) - 8)))
        up = pool[start : start + 8]
        seq = (up + up[::-1][1:])[: recipe.n_notes]
        while len(seq) < recipe.n_notes:
            seq += up
        pitches = seq[: recipe.n_notes]
        durs = [1.0] * recipe.n_notes
    elif recipe.kind == "arpeggio":
        base = int(rng.integers(0, max(1, len(pool) - 5)))
        shape = [0, 2, 4, 2]
        pitches = [pool[min(base + shape[i % 4], len(pool) - 1)] for i in range(recipe.n_notes)]
        durs = [0.5] * recipe.n_notes
    else:  # melody: random walk over the pool, mixed durations, occasional repeated pitch
        idx = int(rng.integers(0, len(pool)))
        pitches = []
        for _ in range(recipe.n_notes):
            pitches.append(pool[idx])
            step = int(rng.choice([-2, -1, 0, 0, 1, 2]))
            idx = int(np.clip(idx + step, 0, len(pool) - 1))
        durs = [float(d) for d in rng.choice([0.5, 1.0, 1.0, 1.5, 2.0], size=recipe.n_notes)]

    notes: list[SymNote] = []
    t = 0.0
    for p, d in zip(pitches, durs, strict=True):
        notes.append(SymNote(onset_beat=t, dur_beat=d, pitch=int(p)))
        t += d
    return notes


def beat_seconds(recipe: Recipe) -> float:
    return 60.0 / recipe.bpm
