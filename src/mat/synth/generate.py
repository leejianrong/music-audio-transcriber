"""Turn a recipe into a clip: audio, ground-truth NoteEvents, and the recipe itself."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from mat.core.note_events import Note, NoteEvents, Producer, Source, dump, sha256_bytes
from mat.synth import augment
from mat.synth.recipe import Recipe, SymNote, beat_seconds, generate_symbolic
from mat.synth.render import Audio, note_times, render


@dataclass(frozen=True)
class Clip:
    recipe: Recipe
    symbolic: list[SymNote]
    audio: Audio
    truth: NoteEvents


def truth_events(recipe: Recipe, notes: list[SymNote], audio: Audio) -> NoteEvents:
    from mat.core.note_events import Beat

    timed = note_times(recipe, notes)
    duration = len(audio) / recipe.sample_rate
    n_beats = int(np.floor(duration / beat_seconds(recipe))) + 1
    beats = [Beat(t_s=i * beat_seconds(recipe), is_downbeat=(i % 4 == 0)) for i in range(n_beats)]
    return NoteEvents(
        source=Source(sha256=sha256_bytes(audio.tobytes()), duration_s=duration),
        instrument=recipe.instrument,
        producer=Producer(model_id="ground-truth", model_version="recipe-v1"),
        beats=beats,
        notes=[
            Note(id=f"n{i}", onset_s=on, offset_s=off, pitch=p, confidence=1.0)
            for i, (on, off, p) in enumerate(timed)
        ],
    )


def build_clip(recipe: Recipe) -> Clip:
    notes = generate_symbolic(recipe)
    dry = render(recipe, notes)
    wet = augment.apply(dry, recipe.augment, recipe.sample_rate, recipe.seed)
    return Clip(recipe=recipe, symbolic=notes, audio=wet, truth=truth_events(recipe, notes, wet))


def write_clip(clip: Clip, out_dir: Path, name: str = "clip") -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "audio": out_dir / f"{name}.wav",
        "truth": out_dir / f"{name}.truth.json",
        "recipe": out_dir / f"{name}.recipe.json",
    }
    sf.write(str(paths["audio"]), clip.audio, clip.recipe.sample_rate, subtype="PCM_16")
    paths["truth"].write_text(dump(clip.truth))
    paths["recipe"].write_text(clip.recipe.to_json())
    return paths
