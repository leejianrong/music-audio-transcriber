from pathlib import Path

import pytest
from pydantic import ValidationError

from mat.core.note_events import NoteEvents

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "note_events"


@pytest.mark.parametrize("path", sorted(FIX.glob("valid_*.json")), ids=lambda p: p.name)
def test_valid_fixtures_validate(path: Path) -> None:
    NoteEvents.model_validate_json(path.read_text())


@pytest.mark.parametrize("path", sorted(FIX.glob("invalid_*.json")), ids=lambda p: p.name)
def test_invalid_fixtures_are_rejected(path: Path) -> None:
    with pytest.raises(ValidationError):
        NoteEvents.model_validate_json(path.read_text())


def test_there_are_fixtures_of_both_kinds() -> None:
    assert list(FIX.glob("valid_*.json")) and list(FIX.glob("invalid_*.json"))
