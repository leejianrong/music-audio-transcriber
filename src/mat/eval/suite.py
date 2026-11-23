"""The mono eval suite: synthetic clips with exact ground truth, plus optional real clips.

Real clips live in one directory as `<voice|bass>_<name>.wav` with a ground-truth
`<voice|bass>_<name>.mid` of the intended melody. Recording protocol: play along with a click and
a count-in; the eval searches a small global shift to absorb the count-in.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, cast

import numpy as np

from mat.core.midi import from_midi
from mat.eval.notes import best_offset_scores, note_scores
from mat.eval.score_level import score_agreement
from mat.synth.generate import build_clip
from mat.synth.suites import mono_recipes
from mat.transcribe.audio_io import load_audio
from mat.transcribe.pyin import SR, Mono, transcribe_array


@dataclass
class ClipResult:
    name: str
    instrument: str
    f1: float
    f1_with_offset: float
    shift_s: float = 0.0
    score_agreement: float | None = None


@dataclass
class MonoReport:
    renderer: str
    synthetic: list[ClipResult] = field(default_factory=list)
    real: list[ClipResult] = field(default_factory=list)

    @staticmethod
    def _mean(rs: list[ClipResult]) -> float | None:
        return float(np.mean([r.f1 for r in rs])) if rs else None

    def summary(self) -> dict[str, object]:
        syn, real = self._mean(self.synthetic), self._mean(self.real)
        by_inst = {
            i: float(np.mean([r.f1 for r in self.synthetic if r.instrument == i]))
            for i in sorted({r.instrument for r in self.synthetic})
        }
        agree = [r.score_agreement for r in self.synthetic if r.score_agreement is not None]
        return {
            "renderer": self.renderer,
            "synthetic_score_agreement": float(np.mean(agree)) if agree else None,
            "synthetic_clips": len(self.synthetic),
            "synthetic_f1": syn,
            "synthetic_f1_by_instrument": by_inst,
            "real_clips": len(self.real),
            "real_f1": real,
            "sim_to_real_gap": (syn - real) if syn is not None and real is not None else None,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary(),
            "synthetic": [asdict(r) for r in self.synthetic],
            "real": [asdict(r) for r in self.real],
        }


def run_mono(
    renderer: Literal["tone", "fluidsynth"] = "tone",
    n: int = 24,
    seed: int = 0,
    real_dir: Path | None = None,
) -> MonoReport:
    report = MonoReport(renderer=renderer)
    for i, recipe in enumerate(mono_recipes(renderer, n, seed)):
        clip = build_clip(recipe)
        est = transcribe_array(
            clip.audio,
            recipe.sample_rate,
            cast("Mono", recipe.instrument),
            "0" * 64,
        )
        s = note_scores(clip.truth, est)
        agreement = score_agreement(clip.symbolic, est.notes, est.beats)
        report.synthetic.append(
            ClipResult(f"synth-{i:03d}", recipe.instrument, s.f1, s.f1_with_offset, 0.0, agreement)
        )
    if real_dir is not None:
        for wav in sorted(real_dir.glob("*.wav")):
            instrument = wav.stem.split("_", 1)[0]
            mid = wav.with_suffix(".mid")
            if instrument not in ("voice", "bass") or not mid.exists():
                continue
            truth = from_midi(mid, instrument)  # type: ignore[arg-type]
            y = load_audio(wav, SR)
            est = transcribe_array(y, SR, instrument, "0" * 64)  # type: ignore[arg-type]
            s, shift = best_offset_scores(truth, est)
            report.real.append(ClipResult(wav.stem, instrument, s.f1, s.f1_with_offset, shift))
    return report


def format_report(report: MonoReport) -> str:
    s = report.summary()

    def fmt(v: object) -> str:
        return "n/a" if v is None else f"{v:.3f}"

    lines = [
        f"mono suite ({s['renderer']} renderer)",
        f"  synthetic: {s['synthetic_clips']} clips, note F1 {fmt(s['synthetic_f1'])}",
    ]
    by = s["synthetic_f1_by_instrument"]
    assert isinstance(by, dict)
    for inst, v in by.items():
        lines.append(f"    {inst}: {v:.3f}")
    lines.append(
        f"    score-level agreement (reference quantizer): {fmt(s['synthetic_score_agreement'])}"
    )
    lines.append(f"  real:      {s['real_clips']} clips, note F1 {fmt(s['real_f1'])}")
    lines.append(f"  sim-to-real gap: {fmt(s['sim_to_real_gap'])}")
    if not report.real:
        lines.append("  (no real clips: pass --real-dir with <instrument>_<name>.wav + .mid pairs)")
    return "\n".join(lines)
