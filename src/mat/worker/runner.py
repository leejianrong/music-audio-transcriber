"""The claim loop and the per-job pipeline: download, ingest, transcribe, complete or fail.

Retention (sibei-score ADR-0034 decision 16): audio is download-once. It lives only in a temporary
directory that is removed when the job ends, however it ends, and nothing here logs a presigned URL,
a lease token, or the worker credential.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from mat.core.note_events import NoteEvents, sha256_file
from mat.transcribe.pyin import Mono, transcribe_file
from mat.worker.client import WorkerClient
from mat.worker.ingest import IngestError, ingest
from mat.worker.protocol import ApiError, Job, LeaseLost

log = logging.getLogger("mat.worker")

Outcome = Literal["completed", "failed", "abandoned", "cancelled"]
Transcriber = Callable[[Path, str], NoteEvents]


@dataclass(frozen=True)
class WorkerConfig:
    max_duration_s: float = 600.0
    max_bytes: int = 200 * 1024 * 1024
    supported_instruments: tuple[str, ...] = ("voice", "bass")
    wait_seconds: int = 20


class Heartbeater:
    """Keeps the lease alive from a thread while the main thread does the CPU-bound work."""

    def __init__(self, client: WorkerClient, job: Job) -> None:
        self._client, self._job = client, job
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stage: tuple[str, float] = ("claimed", 0.0)
        self.lost = False
        self.cancelled = False
        self._thread = threading.Thread(target=self._run, name=f"hb-{job.id}", daemon=True)

    def set_progress(self, stage: str, fraction: float) -> None:
        with self._lock:
            self._stage = (stage, fraction)

    def _beat(self) -> None:
        with self._lock:
            stage, fraction = self._stage
        try:
            res = self._client.heartbeat(self._job.id, self._job.leaseToken, stage, fraction)
        except LeaseLost:
            self.lost = True
            return
        except (ApiError, OSError) as e:
            log.warning("heartbeat failed for %s: %s", self._job.id, type(e).__name__)
            return
        if res.cancelled:
            self.cancelled = True

    def _run(self) -> None:
        interval = max(1, self._job.heartbeatIntervalSeconds)
        while not self._stop.wait(interval):
            self._beat()
            if self.lost or self.cancelled:
                return

    def __enter__(self) -> Heartbeater:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _default_transcribe(path: Path, instrument: str) -> NoteEvents:
    if instrument not in ("voice", "bass"):
        raise ValueError(f"unsupported instrument {instrument!r}")
    return transcribe_file(path, cast("Mono", instrument))


def process_job(
    client: WorkerClient,
    job: Job,
    cfg: WorkerConfig,
    transcribe: Transcriber | None = None,
) -> Outcome:
    """Run one claimed job to a terminal call (complete or fail), or abandon it on lease loss."""
    transcribe = transcribe or _default_transcribe
    instrument = job.params.instrument

    def refuse(kind: str, message: str, retryable: bool = False) -> Outcome:
        try:
            client.fail(job.id, job.leaseToken, kind, message, retryable)
        except LeaseLost:
            return "abandoned"
        return "failed"

    if instrument not in cfg.supported_instruments:
        return refuse("unsupported-instrument", f"instrument {instrument!r} is not supported yet")
    if job.audio.sizeBytes is not None and job.audio.sizeBytes > cfg.max_bytes:
        return refuse("unsupported-audio", "file exceeds the size limit")

    with Heartbeater(client, job) as hb, tempfile.TemporaryDirectory(prefix="mat-job-") as tmp:
        work = Path(tmp)
        try:
            hb.set_progress("downloading", 0.05)
            raw = work / "upload.bin"
            client.download_audio(job.audio, raw, cfg.max_bytes)
            upload_sha = sha256_file(raw)

            hb.set_progress("decoding", 0.2)
            audio = ingest(raw, work, cfg.max_duration_s, cfg.max_bytes)
            raw.unlink(missing_ok=True)  # the original is no longer needed

            hb.set_progress("transcribing", 0.4)
            events = transcribe(audio.path, str(instrument))
            events = events.model_copy(
                update={"source": events.source.model_copy(update={"sha256": upload_sha})}
            )
        except LeaseLost:
            return "abandoned"
        except IngestError as e:
            return refuse(e.kind, e.message)
        except ApiError as e:
            return refuse(
                "unsupported-audio" if e.status == 413 else "engine-error",
                e.message,
                e.status != 413,
            )
        except MemoryError:
            return refuse("out-of-memory", "ran out of memory", retryable=False)
        except Exception as e:  # noqa: BLE001 - any engine bug must become a clean failure
            log.exception("engine error on job %s", job.id)
            return refuse("engine-error", f"{type(e).__name__}", retryable=True)

        if hb.lost:
            return "abandoned"
        if hb.cancelled:
            return "cancelled"
        hb.set_progress("uploading", 0.95)
        try:
            client.complete(
                job.id, job.leaseToken, audio.duration_s, events.model_dump(mode="json")
            )
        except LeaseLost:
            return "abandoned"
        return "completed"


def run(client: WorkerClient, cfg: WorkerConfig, stop: threading.Event, once: bool = False) -> int:
    """Claim and process jobs until `stop` is set (or one job with `once`). Returns jobs handled."""
    handled = 0
    idle = 0
    while not stop.is_set():
        try:
            job = client.claim(cfg.wait_seconds)
        except ApiError as e:
            log.error("claim refused: %s", e.kind)
            if e.status in (401, 403):
                raise  # a bad credential will not fix itself
            stop.wait(5)
            continue
        except OSError as e:
            log.warning("claim failed (%s); backing off", type(e).__name__)
            stop.wait(min(30, 2 ** min(idle, 5)))
            idle += 1
            continue
        if job is None:
            idle = 0
            if once:
                return handled
            continue
        idle = 0
        log.info("claimed %s (attempt %d)", job.id, job.attempt)
        outcome = process_job(client, job, cfg)
        log.info("job %s: %s", job.id, outcome)
        handled += 1
        if once:
            return handled
    return handled
