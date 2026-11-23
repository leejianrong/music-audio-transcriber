"""A fake sibei-score audio API (worker protocol v1) served through httpx.MockTransport."""

from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import soundfile as sf

from mat.core.note_events import Note, NoteEvents, Producer, Source
from mat.worker.client import WorkerClient
from mat.worker.ingest import Ingested
from mat.worker.protocol import Job

TOKEN = "sbsw_" + "k" * 40
LEASE = "l_secret_lease_token"
API = "https://api.test"
STORAGE_URL = "https://storage.test/bucket/audio?X-Amz-Signature=sig_secret"


def make_wav_bytes(seconds: float = 1.0) -> bytes:
    path = Path("/tmp") / f"mat-test-{threading.get_ident()}.wav"
    sf.write(str(path), np.zeros(int(22050 * seconds), dtype=np.float32), 22050)
    data = path.read_bytes()
    path.unlink()
    return data


def job_json(
    instrument: str | None = "bass", via_api: bool = False, interval: int = 30
) -> dict[str, Any]:
    audio: dict[str, Any] = {"url": STORAGE_URL, "method": "GET", "headers": {}, "viaApi": False}
    if via_api:
        audio = {
            "url": "/v1/worker/audio/jobs/job_1/content",
            "method": "GET",
            "headers": {"x-lease-token": LEASE},
            "viaApi": True,
        }
    return {
        "job": {
            "id": "job_1",
            "attempt": 1,
            "leaseToken": LEASE,
            "heartbeatIntervalSeconds": interval,
            "audio": audio,
            "params": {"instrument": instrument, "declaredDurationSeconds": 1.0},
        }
    }


class FakeApi:
    def __init__(self, audio: bytes = b"RIFFfakeaudio") -> None:
        self.audio = audio
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []
        self.claims: deque[httpx.Response] = deque()
        self.completes: deque[httpx.Response | Exception] = deque()
        self.heartbeat_response = httpx.Response(
            200, json={"leaseExpiresAt": "x", "cancelled": False}
        )
        self.heartbeat_served = threading.Event()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        self.bodies.append(body)
        path = request.url.path
        if request.url.host == "storage.test" or path.endswith("/content"):
            return httpx.Response(200, content=self.audio)
        if path == "/v1/worker/audio/claim":
            return self.claims.popleft() if self.claims else httpx.Response(204)
        if path.endswith("/heartbeat"):
            self.heartbeat_served.set()
            return self.heartbeat_response
        if path.endswith("/complete"):
            nxt = (
                self.completes.popleft()
                if self.completes
                else httpx.Response(200, json={"status": "succeeded"})
            )
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        if path.endswith("/fail"):
            return httpx.Response(200, json={"status": "failed"})
        return httpx.Response(404, json={"error": {"kind": "bad-request", "message": "?"}})

    def client(self) -> WorkerClient:
        http = httpx.Client(transport=httpx.MockTransport(self.handler))
        return WorkerClient(API, TOKEN, "test-worker", http=http, sleep=lambda _s: None)

    def calls(self, suffix: str) -> list[dict[str, Any]]:
        return [
            b
            for r, b in zip(self.requests, self.bodies, strict=True)
            if r.url.path.endswith(suffix)
        ]


def parse_job(**kw: Any) -> Job:
    return Job.model_validate(job_json(**kw)["job"])


def fake_ingest(duration: float = 1.0) -> Any:
    def _ingest(src: Path, out_dir: Path, max_duration_s: float, max_bytes: int) -> Ingested:
        out = out_dir / "audio.wav"
        out.write_bytes(b"decoded")
        return Ingested(out, duration, 44100, "wav", False)

    return _ingest


def fake_events(path: Path, instrument: str) -> NoteEvents:
    return NoteEvents(
        source=Source(sha256="0" * 64, duration_s=1.0),
        instrument="bass",
        producer=Producer(model_id="stub", model_version="1"),
        notes=[Note(id="n0", onset_s=0.0, offset_s=0.5, pitch=40, confidence=0.9)],
    )
