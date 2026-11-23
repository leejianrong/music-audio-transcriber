import numpy as np
import pytest

from mat.synth.mix import STEMS, MixRecipe, build_mix, resolve
from mat.synth.render import fluidsynth_available, soundfont_path

pytestmark = pytest.mark.integration

needs_fs = pytest.mark.skipif(
    not (fluidsynth_available() and soundfont_path()),
    reason="needs fluidsynth (or `make docker-fluidsynth`) and `mat synth fetch-soundfont`",
)


@needs_fs
def test_soundfont_mix_has_four_audible_stems_that_sum_to_the_mix() -> None:
    clip = build_mix(resolve(MixRecipe(seed=5, bars=2, bpm=120.0, renderer="fluidsynth")))
    total = np.sum([clip.stems[s].astype(np.float64) for s in STEMS], axis=0)
    assert np.max(np.abs(total - clip.mix)) < 1e-5
    for stem in STEMS:
        assert float(np.sqrt(np.mean(clip.stems[stem].astype(np.float64) ** 2))) > 1e-3, stem


@needs_fs
def test_soundfont_mix_is_byte_identical_for_the_same_recipe() -> None:
    r = resolve(MixRecipe(seed=6, bars=2, bpm=100.0, renderer="fluidsynth"))
    assert build_mix(r).mix.tobytes() == build_mix(r).mix.tobytes()
