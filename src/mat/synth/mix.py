"""Multi-track mixes with exact stems (V7). The mix is the sum of the stems, by construction.

Four MUSDB-style stems: vocals (a voice-range melody; synthetic, not a real voice), drums, bass,
other (chords). Each stem is generated from a seeded symbolic score, rendered on its own, given
its own effects, then scaled. The mixture is the exact sum of the final stems (after one common
scale that keeps it out of clipping), so a separator's target is known to the sample.

Mono only for now: the rest of the pipeline is mono.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf

from mat.core.note_events import (
    Beat,
    Instrument,
    Note,
    NoteEvents,
    Producer,
    Source,
    dump,
    sha256_bytes,
)
from mat.synth import augment
from mat.synth.recipe import AugmentSpec, Recipe, SymNote, generate_symbolic
from mat.synth.render import TAIL_S, Audio, render_fluidsynth_timed, render_tone

STEMS = ("vocals", "drums", "bass", "other")
STEM_INSTRUMENT: dict[str, Instrument] = {
    "vocals": "voice",
    "drums": "drums",
    "bass": "bass",
    "other": "other",
}

KICK, SNARE, HAT_CLOSED, HAT_OPEN = 36, 38, 42, 46
DRUM_CLASS = {KICK: "kick", SNARE: "snare", HAT_CLOSED: "hihat-closed", HAT_OPEN: "hihat-open"}
BEATS_PER_BAR = 4

FLUID_PROGRAMS = {
    "vocals": (52, 53, 54, 73, 71),
    "bass": (32, 33, 34, 35),
    "other": (0, 4, 16, 19),  # piano, e-piano, organ, church organ
}
TONE_PATCHES = {"vocals": ("saw", "sine"), "bass": ("pluck", "saw"), "other": ("sine", "saw")}


@dataclass(frozen=True)
class MixRecipe:
    seed: int
    bpm: float = 100.0
    bars: int = 8
    renderer: Literal["tone", "fluidsynth"] = "tone"
    sample_rate: int = 44100
    recipe_version: int = 1
    # Filled in by `resolve`: per-stem patch and gain. Kept in the recipe so a clip is reproducible
    # from the JSON alone.
    patches: dict[str, str] = field(default_factory=dict)
    gains_db: dict[str, float] = field(default_factory=dict)
    reverb_rt60_s: dict[str, float | None] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> MixRecipe:
        import json

        return MixRecipe(**json.loads(path.read_text()))


def resolve(recipe: MixRecipe) -> MixRecipe:
    """Fill the random per-stem choices from the seed (idempotent if already filled)."""
    if recipe.patches and recipe.gains_db:
        return recipe
    rng = np.random.default_rng(recipe.seed + 101)
    patches: dict[str, str] = {"drums": "kit"}
    for stem in ("vocals", "bass", "other"):
        if recipe.renderer == "fluidsynth":
            progs = FLUID_PROGRAMS[stem]
            patches[stem] = f"gm:{progs[int(rng.integers(0, len(progs)))]}"
        else:
            opts = TONE_PATCHES[stem]
            patches[stem] = opts[int(rng.integers(0, len(opts)))]
    base = {"vocals": 0.0, "drums": -2.0, "bass": -1.0, "other": -5.0}
    gains = {s: base[s] + float(rng.uniform(-3.0, 3.0)) for s in STEMS}
    reverbs: dict[str, float | None] = {
        "vocals": [None, 0.4, 0.8][int(rng.integers(0, 3))],
        "drums": [None, 0.3][int(rng.integers(0, 2))],
        "bass": None,
        "other": [None, 0.6, 1.0][int(rng.integers(0, 3))],
    }
    return MixRecipe(
        seed=recipe.seed, bpm=recipe.bpm, bars=recipe.bars, renderer=recipe.renderer,
        sample_rate=recipe.sample_rate, patches=patches, gains_db=gains, reverb_rt60_s=reverbs,
    )  # fmt: skip


# --- symbolic -------------------------------------------------------------------------------------


def _fit(notes: list[SymNote], total_beats: float) -> list[SymNote]:
    out: list[SymNote] = []
    for n in notes:
        if n.onset_beat >= total_beats:
            break
        out.append(SymNote(n.onset_beat, min(n.dur_beat, total_beats - n.onset_beat), n.pitch))
    return out


def _melodic(seed: int, instrument: Literal["voice", "bass"], total_beats: float) -> list[SymNote]:
    base = Recipe(seed=seed, instrument=instrument, kind="melody", n_notes=int(total_beats * 2) + 4)
    return _fit(generate_symbolic(base), total_beats)


def _chords(seed: int, bars: int) -> list[SymNote]:
    """One triad per bar from a random diatonic progression; whole-bar chords, sometimes split."""
    rng = np.random.default_rng(seed)
    tonic = int(rng.integers(48, 60))
    major = (0, 2, 4, 5, 7, 9, 11)
    notes: list[SymNote] = []
    degree = 0
    for bar in range(bars):
        degree = int(rng.choice([0, 3, 4, 5, 1, degree]))
        root = tonic + major[degree % 7]
        triad = (root, root + (4 if degree in (0, 3, 4) else 3), root + 7)
        split = rng.random() < 0.3
        for half in ((0.0, 2.0), (2.0, 2.0)) if split else ((0.0, 4.0),):
            for p in triad:
                notes.append(SymNote(bar * BEATS_PER_BAR + half[0], half[1], int(p)))
    return notes


def _drums(seed: int, bars: int) -> list[SymNote]:
    rng = np.random.default_rng(seed)
    notes: list[SymNote] = []
    for bar in range(bars):
        b0 = bar * BEATS_PER_BAR
        for beat in (0.0, 2.0):
            notes.append(SymNote(b0 + beat, 0.25, KICK))
        if rng.random() < 0.6:
            notes.append(SymNote(b0 + 2.5, 0.25, KICK))
        for beat in (1.0, 3.0):
            notes.append(SymNote(b0 + beat, 0.25, SNARE))
        for i in range(8):
            open_hat = i == 7 and rng.random() < 0.4
            notes.append(SymNote(b0 + i * 0.5, 0.25, HAT_OPEN if open_hat else HAT_CLOSED))
    return notes


def symbolic_stems(recipe: MixRecipe) -> dict[str, list[SymNote]]:
    total = float(recipe.bars * BEATS_PER_BAR)
    s = recipe.seed
    return {
        "vocals": _melodic(s * 4 + 1, "voice", total),
        "drums": _drums(s * 4 + 2, recipe.bars),
        "bass": _melodic(s * 4 + 3, "bass", total),
        "other": _chords(s * 4 + 4, recipe.bars),
    }


# --- rendering ------------------------------------------------------------------------------------


def _timed(notes: list[SymNote], bpm: float, articulate: bool) -> list[tuple[float, float, int]]:
    b = 60.0 / bpm
    k = 0.9 if articulate else 1.0
    return [(n.onset_beat * b, (n.onset_beat + n.dur_beat * k) * b, n.pitch) for n in notes]


def _render_drums_tone(notes: list[SymNote], bpm: float, sr: int, seed: int, length: int) -> Audio:
    rng = np.random.default_rng(seed + 55)
    out = np.zeros(length)
    b = 60.0 / bpm
    for n in notes:
        start = int(round(n.onset_beat * b * sr))
        if n.pitch == KICK:
            t = np.arange(int(0.28 * sr)) / sr
            freq = 45 + 90 * np.exp(-t * 30)
            hit = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 12)
        elif n.pitch == SNARE:
            t = np.arange(int(0.18 * sr)) / sr
            hit = 0.7 * rng.standard_normal(len(t)) * np.exp(-t * 25) + 0.5 * np.sin(
                2 * np.pi * 190 * t
            ) * np.exp(-t * 30)
        else:
            dur = 0.3 if n.pitch == HAT_OPEN else 0.06
            t = np.arange(int(dur * sr)) / sr
            noise = rng.standard_normal(len(t))
            hit = (
                0.35
                * np.diff(noise, prepend=0.0)
                * np.exp(-t * (12 if n.pitch == HAT_OPEN else 70))
            )
        end = min(length, start + len(hit))
        out[start:end] += hit[: end - start]
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.5).astype(np.float32)


def _render_stem(
    stem: str, notes: list[SymNote], recipe: MixRecipe, length: int, index: int
) -> Audio:
    sr = recipe.sample_rate
    seed = recipe.seed * 10 + index
    if stem == "drums":
        if recipe.renderer == "fluidsynth":
            timed = _timed(notes, recipe.bpm, articulate=False)
            audio = render_fluidsynth_timed(timed, 0, True, recipe.bpm, sr)
        else:
            audio = _render_drums_tone(notes, recipe.bpm, sr, seed, length)
    else:
        patch = recipe.patches[stem]
        instrument: Literal["voice", "bass"] = "bass" if stem == "bass" else "voice"
        if recipe.renderer == "fluidsynth":
            program = int(patch.split(":", 1)[1])
            timed = _timed(notes, recipe.bpm, articulate=True)
            audio = render_fluidsynth_timed(timed, program, False, recipe.bpm, sr)
        else:
            r = Recipe(
                seed=seed, instrument=instrument, bpm=recipe.bpm, patch=patch, sample_rate=sr
            )
            audio = render_tone(r, notes)
    spec = AugmentSpec(gain_db=0.0, reverb_rt60_s=recipe.reverb_rt60_s.get(stem), reverb_wet=0.2)
    audio = augment.apply(audio, spec, sr, seed)
    audio = (audio * 10 ** (recipe.gains_db[stem] / 20)).astype(np.float32)
    out = np.zeros(length, dtype=np.float32)
    n = min(length, len(audio))
    out[:n] = audio[:n]
    return out


@dataclass(frozen=True)
class MixClip:
    recipe: MixRecipe
    symbolic: dict[str, list[SymNote]]
    stems: dict[str, Audio]
    mix: Audio


def build_mix(recipe: MixRecipe) -> MixClip:
    recipe = resolve(recipe)
    sym = symbolic_stems(recipe)
    sr = recipe.sample_rate
    length = int(np.ceil((recipe.bars * BEATS_PER_BAR * 60.0 / recipe.bpm + TAIL_S) * sr))
    stems = {s: _render_stem(s, sym[s], recipe, length, i) for i, s in enumerate(STEMS)}
    total = np.sum([stems[s].astype(np.float64) for s in STEMS], axis=0)
    peak = float(np.max(np.abs(total))) or 1.0
    scale = 0.9 / peak if peak > 0.9 else 1.0  # one common scale keeps mix == sum(stems)
    stems = {s: (a * scale).astype(np.float32) for s, a in stems.items()}
    mix = np.sum([stems[s].astype(np.float64) for s in STEMS], axis=0).astype(np.float32)
    return MixClip(recipe=recipe, symbolic=sym, stems=stems, mix=mix)


def stem_truth(clip: MixClip, stem: str) -> NoteEvents:
    r = clip.recipe
    b = 60.0 / r.bpm
    sr = r.sample_rate
    notes: list[Note] = []
    for i, n in enumerate(clip.symbolic[stem]):
        art = 1.0 if stem == "drums" else 0.9
        drum_class = DRUM_CLASS.get(n.pitch) if stem == "drums" else None
        notes.append(
            Note(
                id=f"n{i}",
                onset_s=n.onset_beat * b,
                offset_s=(n.onset_beat + n.dur_beat * art) * b,
                pitch=n.pitch,
                confidence=1.0,
                drum_class=drum_class,
            )
        )
    duration = len(clip.mix) / sr
    n_beats = int(np.floor(duration / b)) + 1
    return NoteEvents(
        source=Source(sha256=sha256_bytes(clip.stems[stem].tobytes()), duration_s=duration),
        instrument=STEM_INSTRUMENT[stem],
        producer=Producer(model_id="ground-truth", model_version="mix-recipe-v1"),
        beats=[Beat(t_s=k * b, is_downbeat=(k % BEATS_PER_BAR == 0)) for k in range(n_beats)],
        notes=notes,
    )


def write_mix(clip: MixClip, out_dir: Path, name: str = "mix") -> Path:
    import json
    from dataclasses import asdict

    out_dir.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_dir / f"{name}.wav"), clip.mix, clip.recipe.sample_rate, subtype="FLOAT")
    stems_dir = out_dir / f"{name}.stems"
    stems_dir.mkdir(exist_ok=True)
    for stem, audio in clip.stems.items():
        sf.write(str(stems_dir / f"{stem}.wav"), audio, clip.recipe.sample_rate, subtype="FLOAT")
        (stems_dir / f"{stem}.truth.json").write_text(dump(stem_truth(clip, stem)))
    (out_dir / f"{name}.recipe.json").write_text(
        json.dumps(asdict(clip.recipe), indent=2, sort_keys=True) + "\n"
    )
    return out_dir / f"{name}.wav"


def mix_recipes(renderer: Literal["tone", "fluidsynth"], n: int, seed: int = 0) -> list[MixRecipe]:
    rng = np.random.default_rng(seed)
    return [
        resolve(
            MixRecipe(
                seed=int(rng.integers(0, 2**31 - 1)),
                bpm=float([80.0, 100.0, 120.0][int(rng.integers(0, 3))]),
                bars=int(rng.integers(6, 9)),
                renderer=renderer,
            )
        )
        for _ in range(n)
    ]
