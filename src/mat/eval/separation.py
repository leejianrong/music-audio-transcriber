"""Separation metrics (SDR via mir_eval's BSS Eval, SI-SDR) and the baseline suite.

SDR here is mir_eval.separation.bss_eval_sources, the BSS Eval implementation already in our
dependencies; museval (which the SiSEC benchmarks use) is a later cross-check, not a dependency.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Literal

import mir_eval.separation
import numpy as np

from mat.separate.base import Audio, Separator
from mat.separate.baselines import HpssSeparator, IdentitySeparator, OracleMaskSeparator
from mat.synth.mix import STEMS, build_mix, mix_recipes


def si_sdr(ref: Audio, est: Audio, eps: float = 1e-12) -> float:
    """Scale-invariant SDR in dB: project the estimate on the reference, compare to the residual."""
    r = ref.astype(np.float64)
    e = est.astype(np.float64)
    r, e = r - r.mean(), e - e.mean()
    scale = float(np.dot(e, r) / (np.dot(r, r) + eps))
    target = scale * r
    noise = e - target
    return float(10 * np.log10((np.sum(target**2) + eps) / (np.sum(noise**2) + eps)))


def sdr(refs: dict[str, Audio], ests: dict[str, Audio]) -> dict[str, float]:
    """Per-stem SDR (dB) with a fixed stem order (no permutation search)."""
    names = [s for s in STEMS if s in refs]
    ref = np.stack([refs[s].astype(np.float64) for s in names])
    est = np.stack([ests[s].astype(np.float64) for s in names])
    with warnings.catch_warnings():
        # Deprecated in mir_eval 0.8 and removed in 0.9, with no drop-in successor yet. pyproject
        # pins <0.9; the follow-up is a museval cross-check or our own BSS Eval implementation.
        warnings.simplefilter("ignore", FutureWarning)
        values, _, _, _ = mir_eval.separation.bss_eval_sources(ref, est, compute_permutation=False)
    return {s: float(v) for s, v in zip(names, values, strict=True)}


@dataclass
class SeparationReport:
    renderer: str
    clips: int
    # separator name -> stem -> list of per-clip values
    sdr: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    si_sdr: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def summary(self) -> dict[str, dict[str, dict[str, float]]]:
        out: dict[str, dict[str, dict[str, float]]] = {}
        for name in self.sdr:
            out[name] = {
                stem: {
                    "sdr": float(np.mean(self.sdr[name][stem])),
                    "si_sdr": float(np.mean(self.si_sdr[name][stem])),
                }
                for stem in STEMS
            }
            out[name]["average"] = {
                "sdr": float(np.mean([out[name][s]["sdr"] for s in STEMS])),
                "si_sdr": float(np.mean([out[name][s]["si_sdr"] for s in STEMS])),
            }
        return out


def run_separation(
    renderer: Literal["tone", "fluidsynth"] = "tone",
    n: int = 6,
    seed: int = 0,
    extra: list[Separator] | None = None,
) -> SeparationReport:
    report = SeparationReport(renderer=renderer, clips=n)
    for recipe in mix_recipes(renderer, n, seed):
        clip = build_mix(recipe)
        seps: list[Separator] = [
            IdentitySeparator(),
            HpssSeparator(),
            OracleMaskSeparator(clip.stems),
            *(extra or []),
        ]
        for sep in seps:
            ests = sep.separate(clip.mix, recipe.sample_rate)
            sd = sdr(clip.stems, ests)
            for stem in STEMS:
                report.sdr.setdefault(sep.name, {}).setdefault(stem, []).append(sd[stem])
                report.si_sdr.setdefault(sep.name, {}).setdefault(stem, []).append(
                    si_sdr(clip.stems[stem], ests[stem])
                )
    return report


def format_separation(report: SeparationReport) -> str:
    lines = [f"separation suite ({report.renderer} renderer, {report.clips} mixes)"]
    lines.append(f"  {'separator':<46}" + "".join(f"{s:>9}" for s in (*STEMS, "avg")))
    for name, rows in report.summary().items():
        vals = [rows[s]["sdr"] for s in STEMS] + [rows["average"]["sdr"]]
        lines.append(f"  {name:<46}" + "".join(f"{v:>9.1f}" for v in vals) + "   SDR dB")
    lines.append("  (SI-SDR per stem is in --json output; stems are synthetic, mono, 4 sources)")
    return "\n".join(lines)
