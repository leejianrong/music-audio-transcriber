import pytest

from mat.eval.piano import run_piano
from mat.synth.render import fluidsynth_available, soundfont_path

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not (fluidsynth_available() and soundfont_path()),
    reason="needs fluidsynth (or `make docker-fluidsynth`) and `mat synth fetch-soundfont`",
)
def test_soundfont_piano_scores_below_tone_piano_but_finds_most_notes() -> None:
    tone = run_piano("tone", n=4, seed=0).summary()
    sf = run_piano("fluidsynth", n=4, seed=0).summary()
    assert sf["recall"] > 0.6  # type: ignore[operator]
    assert sf["f1"] < tone["f1"]  # type: ignore[operator]  # the baseline is the floor to beat
