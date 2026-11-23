import json
from pathlib import Path

import soundfile as sf

from mat import bom
from mat.cli import main
from mat.synth.generate import build_clip
from mat.synth.recipe import Recipe


def _wav(tmp_path: Path) -> Path:
    clip = build_clip(Recipe(seed=4, instrument="bass", kind="scale", n_notes=8, patch="pluck"))
    p = tmp_path / "bassline.wav"
    sf.write(str(p), clip.audio, 44100)
    return p


def test_transcribe_writes_notes_json_and_midi(tmp_path: Path, capsys: object) -> None:
    wav = _wav(tmp_path)
    assert main(["transcribe", str(wav), "--instrument", "bass", "--json"]) == 0
    assert (tmp_path / "bassline.notes.json").exists()
    assert (tmp_path / "bassline.mid").exists()
    data = json.loads((tmp_path / "bassline.notes.json").read_text())
    assert data["schema_version"] == 1 and data["notes"]


def test_silent_input_exits_zero_with_a_warning(tmp_path: Path) -> None:
    p = tmp_path / "silence.wav"
    sf.write(str(p), [0.0] * 22050, 22050)
    assert main(["transcribe", str(p), "--instrument", "voice"]) == 0
    assert json.loads((tmp_path / "silence.notes.json").read_text())["warnings"][0]["code"] == (
        "silent_input"
    )


def test_undecodable_file_exits_nonzero(tmp_path: Path) -> None:
    p = tmp_path / "fake.mp3"
    p.write_bytes(b"this is not audio")
    assert main(["transcribe", str(p), "--instrument", "voice"]) == 1


def test_missing_file_exits_nonzero(tmp_path: Path) -> None:
    assert main(["transcribe", str(tmp_path / "nope.wav"), "--instrument", "bass"]) == 1


def test_checked_in_bom_is_complete() -> None:
    assert bom.problems(bom.load()) == []


def test_bom_rejects_a_row_without_a_source_url() -> None:
    row = {"id": "x", "kind": "dataset", "licence": "CC-BY", "reviewed": True, "paid_path": True}
    assert any("source_url" in p for p in bom.problems([row]))


def test_bom_paid_path_requires_review() -> None:
    row = {
        "id": "x",
        "kind": "model",
        "licence": "MIT",
        "source_url": "https://example.com",
        "reviewed": False,
        "paid_path": True,
    }
    assert bom.problems([row]) == []
    assert any("not reviewed" in p for p in bom.problems([row], paid_path_only=True))
