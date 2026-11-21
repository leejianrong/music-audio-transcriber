"""Wire types for sibei-score's audio worker protocol v1 (its ADR-0034, section of that name)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Wire(BaseModel):
    # Additive-only protocol: ignore fields we do not know.
    model_config = ConfigDict(extra="ignore")


class AudioRef(_Wire):
    url: str
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    viaApi: bool = False  # noqa: N815 - wire name
    contentType: str | None = None  # noqa: N815
    sizeBytes: int | None = None  # noqa: N815


class Params(_Wire):
    instrument: str | None = None
    declaredDurationSeconds: float | None = None  # noqa: N815


class ResultUpload(_Wire):
    url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    viaApi: bool = False  # noqa: N815


class Job(_Wire):
    id: str
    attempt: int = 1
    leaseToken: str  # noqa: N815
    heartbeatIntervalSeconds: int = 30  # noqa: N815
    audio: AudioRef
    params: Params = Field(default_factory=Params)
    resultUpload: ResultUpload | None = None  # noqa: N815


class ClaimResponse(_Wire):
    job: Job


class HeartbeatResult(_Wire):
    leaseExpiresAt: str | None = None  # noqa: N815
    cancelled: bool = False
    audio: AudioRef | None = None


class ApiError(Exception):
    """An error answer from the API: `{ "error": { "kind", "message" } }` plus the HTTP status."""

    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(f"{status} {kind}: {message}")
        self.status = status
        self.kind = kind
        self.message = message


class LeaseLost(ApiError):
    """The lease is no longer ours (re-queued, cancelled or unknown job): abandon the work."""
