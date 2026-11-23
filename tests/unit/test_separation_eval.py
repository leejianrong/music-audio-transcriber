import numpy as np

from mat.eval.separation import sdr, si_sdr
from mat.separate.baselines import HpssSeparator, IdentitySeparator, OracleMaskSeparator
from mat.synth.mix import STEMS, MixRecipe, build_mix, resolve


def _noise_at(ref: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = rng.standard_normal(len(ref))
    n *= np.sqrt(np.mean(ref**2) / (np.mean(n**2) * 10 ** (snr_db / 10)))
    return n


def _tone(n: int = 22050) -> np.ndarray:
    t = np.arange(n) / 22050
    return (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)


def test_si_sdr_matches_the_snr_it_was_built_with() -> None:
    ref = _tone()
    est = (ref + _noise_at(ref, 10.0)).astype(np.float32)
    assert abs(si_sdr(ref, est) - 10.0) < 0.5


def test_si_sdr_ignores_scale_and_rewards_a_perfect_estimate() -> None:
    ref = _tone()
    assert si_sdr(ref, 0.3 * ref) > 60
    assert si_sdr(ref, ref) > 60


def test_sdr_is_close_to_the_snr_for_additive_noise() -> None:
    a, b = _tone(), np.roll(_tone(), 777) * 0.8
    refs = {"vocals": a, "drums": b}
    ests = {
        "vocals": (a + _noise_at(a, 20.0, 1)).astype(np.float32),
        "drums": (b + _noise_at(b, 20.0, 2)).astype(np.float32),
    }
    out = sdr(refs, ests)
    assert all(abs(v - 20.0) < 2.0 for v in out.values()), out


def test_sdr_of_an_identical_estimate_is_very_high() -> None:
    a, b = _tone(), np.roll(_tone(), 777) * 0.8
    assert all(v > 40 for v in sdr({"vocals": a, "drums": b}, {"vocals": a, "drums": b}).values())


def _small_clip():  # type: ignore[no-untyped-def]
    return build_mix(resolve(MixRecipe(seed=7, bars=2, sample_rate=22050, bpm=120.0)))


def test_identity_returns_the_mix_for_every_stem() -> None:
    clip = _small_clip()
    out = IdentitySeparator().separate(clip.mix, 22050)
    assert set(out) == set(STEMS) and all(np.array_equal(v, clip.mix) for v in out.values())


def test_oracle_mask_stems_add_back_to_the_mix() -> None:
    clip = _small_clip()
    out = OracleMaskSeparator(clip.stems).separate(clip.mix, 22050)
    total = np.sum([out[s] for s in STEMS], axis=0)
    assert np.max(np.abs(total - clip.mix)) < 1e-3  # ratio masks sum to one


def test_baselines_are_ordered_floor_then_classical_then_oracle() -> None:
    clip = _small_clip()
    scores = {}
    for sep in (IdentitySeparator(), HpssSeparator(), OracleMaskSeparator(clip.stems)):
        res = sdr(clip.stems, sep.separate(clip.mix, 22050))
        scores[sep.name.split()[0]] = float(np.mean(list(res.values())))
    assert scores["identity"] < scores["hpss"] < scores["oracle"], scores
