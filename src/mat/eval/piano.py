"""Piano eval suite: polyphonic synthetic clips scored with onset note F1 (50 ms, 50 cents).

`run_piano` takes any transcriber `(audio, sample_rate) -> NoteEvents`, so our own model and the
dev-only baselines (Basic Pitch, ByteDance piano; MUS-40 style, never in the paid path) plug in
beside the classical baseline and are scored on the same clips.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt

from mat.core.note_events import NoteEvents
from mat.eval.notes import note_scores
from mat.synth.generate import build_clip
from mat.synth.suites import piano_recipes
from mat.transcribe import poly

PianoTranscriber = Callable[[npt.NDArray[np.float32], int], NoteEvents]


def baseline(y: npt.NDArray[np.float32], sr: int) -> NoteEvents:
    return poly.transcribe_array(y, sr, "0" * 64)


@dataclass
class PianoReport:
    renderer: str
    transcriber: str
    precision: list[float] = field(default_factory=list)
    recall: list[float] = field(default_factory=list)
    f1: list[float] = field(default_factory=list)
    f1_by_kind: dict[str, list[float]] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        return {
            "renderer": self.renderer,
            "transcriber": self.transcriber,
            "clips": len(self.f1),
            "precision": float(np.mean(self.precision)),
            "recall": float(np.mean(self.recall)),
            "f1": float(np.mean(self.f1)),
            "f1_by_kind": {k: float(np.mean(v)) for k, v in sorted(self.f1_by_kind.items())},
        }


def run_piano(
    renderer: Literal["tone", "fluidsynth"] = "tone",
    n: int = 24,
    seed: int = 0,
    transcribe: PianoTranscriber = baseline,
    name: str = poly.MODEL_ID,
) -> PianoReport:
    report = PianoReport(renderer, name)
    for recipe in piano_recipes(renderer, n, seed):
        clip = build_clip(recipe)
        s = note_scores(clip.truth, transcribe(clip.audio, recipe.sample_rate))
        report.precision.append(s.precision)
        report.recall.append(s.recall)
        report.f1.append(s.f1)
        report.f1_by_kind.setdefault(recipe.kind, []).append(s.f1)
    return report


def format_piano(report: PianoReport) -> str:
    s = report.summary()
    by = s["f1_by_kind"]
    assert isinstance(by, dict)
    lines = [
        f"piano suite ({s['renderer']} renderer, {s['transcriber']})",
        f"  {s['clips']} clips: precision {s['precision']:.3f} recall {s['recall']:.3f} "
        f"note F1 {s['f1']:.3f}",
    ]
    lines += [f"    {kind}: {v:.3f}" for kind, v in by.items()]
    return "\n".join(lines)
