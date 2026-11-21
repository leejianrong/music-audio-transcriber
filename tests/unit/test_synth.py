import numpy as np

from mat.synth.generate import build_clip
from mat.synth.recipe import RANGES, AugmentSpec, Recipe, generate_symbolic
from mat.synth.suites import mono_recipes


def _recipe(**kw: object) -> Recipe:
    base: dict[str, object] = {"seed": 3, "instrument": "bass", "kind": "melody", "n_notes": 12}
    return Recipe(**{**base, **kw})  # type: ignore[arg-type]


def test_same_recipe_gives_identical_symbolic_and_audio_bytes() -> None:
    r = _recipe(augment=AugmentSpec(noise_snr_db=30.0, reverb_rt60_s=0.5, lowpass_hz=6000.0))
    a, b = build_clip(r), build_clip(r)
    assert a.symbolic == b.symbolic
    assert a.audio.tobytes() == b.audio.tobytes()


def test_different_seed_changes_the_clip() -> None:
    assert generate_symbolic(_recipe(seed=1)) != generate_symbolic(_recipe(seed=2))


def test_notes_stay_in_instrument_range() -> None:
    for inst in ("bass", "voice"):
        for kind in ("scale", "arpeggio", "melody"):
            notes = generate_symbolic(_recipe(instrument=inst, kind=kind, n_notes=20))
            lo, hi = RANGES[inst]
            assert len(notes) == 20
            assert all(lo <= n.pitch <= hi for n in notes), (inst, kind)


def test_ground_truth_has_a_note_per_symbolic_note_and_a_beat_grid() -> None:
    clip = build_clip(_recipe())
    assert len(clip.truth.notes) == len(clip.symbolic)
    assert clip.truth.beats[0].is_downbeat is True
    assert clip.truth.beats[1].t_s == np.float64(60.0 / 100.0)


def test_recipe_json_round_trip() -> None:
    r = _recipe(augment=AugmentSpec(gain_db=-3.0, reverb_rt60_s=0.4))
    assert Recipe.from_dict(__import__("json").loads(r.to_json())) == r


def test_suite_is_deterministic() -> None:
    assert mono_recipes("tone", 6, seed=5) == mono_recipes("tone", 6, seed=5)
