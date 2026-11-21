"""NoteEvents v1: the only interface between this repo and sibei-score (ADR-0002).

Times are seconds, never beats. Pitch is a MIDI integer plus optional cents.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1

Instrument = Literal["voice", "bass", "piano", "drums", "guitar", "other"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_s: float = Field(ge=0)


class Producer(_Strict):
    model_id: str
    model_version: str
    stage: Literal["transcribe"] = "transcribe"


class Beat(_Strict):
    t_s: float = Field(ge=0)
    # None means the tracker could not tell (sibei-score must not assume a bar line).
    is_downbeat: bool | None = None


class Note(_Strict):
    id: str
    onset_s: float = Field(ge=0)
    offset_s: float
    pitch: int = Field(ge=0, le=127)
    cents: int | None = Field(default=None, ge=-50, le=50)
    velocity: int | None = Field(default=None, ge=0, le=127)
    confidence: float = Field(ge=0, le=1)
    drum_class: str | None = None

    @model_validator(mode="after")
    def _offset_after_onset(self) -> Note:
        if self.offset_s <= self.onset_s:
            raise ValueError("offset_s must be greater than onset_s")
        return self


class NoteWarning(_Strict):
    code: str
    message: str
    t_s: float | None = None


class NoteEvents(_Strict):
    schema_version: Literal[1] = 1
    source: Source
    instrument: Instrument
    producer: Producer
    beats: list[Beat] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
    warnings: list[NoteWarning] = Field(default_factory=list)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def json_schema() -> dict[str, object]:
    schema = NoteEvents.model_json_schema()
    schema["$id"] = "https://github.com/leejianrong/music-audio-transcriber/schemas/note-events-v1"
    schema["title"] = "NoteEvents v1"
    return schema


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"


def dump(events: NoteEvents) -> str:
    return events.model_dump_json(indent=2, exclude_none=False) + "\n"


def load(path: Path) -> NoteEvents:
    return NoteEvents.model_validate_json(path.read_text())
