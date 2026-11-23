from pathlib import Path

import numpy as np
import soundfile as sf

from mat.core.note_events import NoteEvents
from mat.synth.mix import STEMS, MixRecipe, build_mix, resolve, stem_truth, write_mix


def small(seed: int = 3, **kw: object) -> MixRecipe:
    base: dict[str, object] = {"seed": seed, "bars": 2, "sample_rate": 22050, "bpm": 120.0}
    return resolve(MixRecipe(**{**base, **kw}))  # type: ignore[arg-type]


def test_same_recipe_gives_identical_stems_and_mix() -> None:
    a, b = build_mix(small()), build_mix(small())
    assert a.mix.tobytes() == b.mix.tobytes()
    assert all(a.stems[s].tobytes() == b.stems[s].tobytes() for s in STEMS)


def test_different_seed_changes_the_mix() -> None:
    assert build_mix(small(1)).mix.tobytes() != build_mix(small(2)).mix.tobytes()


def test_stems_sum_to_the_mix_and_the_mix_does_not_clip() -> None:
    for seed in range(5):
        clip = build_mix(small(seed))
        total = np.sum([clip.stems[s].astype(np.float64) for s in STEMS], axis=0)
        assert np.max(np.abs(total - clip.mix)) < 1e-5
        assert float(np.max(np.abs(clip.mix))) <= 0.9 + 1e-6


def test_every_stem_has_signal_and_the_same_length() -> None:
    clip = build_mix(small())
    assert {len(a) for a in clip.stems.values()} == {len(clip.mix)}
    for stem, audio in clip.stems.items():
        assert float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) > 1e-3, stem


def test_resolving_twice_changes_nothing() -> None:
    r = small()
    assert resolve(r) == r


def test_drum_stem_has_kick_snare_and_hat_ground_truth() -> None:
    truth = stem_truth(build_mix(small()), "drums")
    assert truth.instrument == "drums"
    assert {n.drum_class for n in truth.notes} >= {"kick", "snare", "hihat-closed"}


def test_chord_stem_is_polyphonic_and_melodic_stems_are_not() -> None:
    clip = build_mix(small())
    chord_onsets = [n.onset_beat for n in clip.symbolic["other"]]
    assert max(chord_onsets.count(o) for o in set(chord_onsets)) >= 3
    for stem in ("vocals", "bass"):
        onsets = [n.onset_beat for n in clip.symbolic[stem]]
        assert len(onsets) == len(set(onsets))


def test_ground_truth_validates_as_note_events() -> None:
    clip = build_mix(small())
    for stem in STEMS:
        NoteEvents.model_validate_json(stem_truth(clip, stem).model_dump_json())


def test_written_clip_reloads_to_the_same_audio(tmp_path: Path) -> None:
    clip = build_mix(small())
    mix_path = write_mix(clip, tmp_path)
    again = build_mix(MixRecipe.load(tmp_path / "mix.recipe.json"))
    assert again.mix.tobytes() == clip.mix.tobytes()
    data, sr = sf.read(str(mix_path), dtype="float32")
    assert sr == 22050 and np.array_equal(data, clip.mix)
    assert all((tmp_path / "mix.stems" / f"{s}.wav").exists() for s in STEMS)
