import pytest

from mat.eval.suite import run_mono
from mat.synth.generate import build_clip
from mat.synth.recipe import Recipe
from mat.synth.render import fluidsynth_available, soundfont_path

pytestmark = pytest.mark.integration

needs_fs = pytest.mark.skipif(
    not (fluidsynth_available() and soundfont_path()),
    reason="needs fluidsynth (or `make docker-fluidsynth`) and `mat synth fetch-soundfont`",
)


@needs_fs
def test_fluidsynth_render_is_byte_identical_for_the_same_recipe() -> None:
    r = Recipe(seed=21, instrument="bass", renderer="fluidsynth", patch="gm:33", n_notes=10)
    assert build_clip(r).audio.tobytes() == build_clip(r).audio.tobytes()


@needs_fs
def test_mono_suite_on_soundfont_audio_meets_the_provisional_bars() -> None:
    report = run_mono("fluidsynth", n=24, seed=0)
    s = report.summary()
    by = s["synthetic_f1_by_instrument"]
    assert isinstance(by, dict)
    # Bass is the clean case. Soft-attack voice-range patches (flute, choir) are the weak spot:
    # V1 records the number (about 0.80) rather than hiding it; see SLICES.md V1.
    assert by["bass"] >= 0.95
    assert by["voice"] >= 0.70
    synthetic = s["synthetic_f1"]
    assert isinstance(synthetic, float) and synthetic >= 0.85
