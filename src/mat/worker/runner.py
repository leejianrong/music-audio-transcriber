"""The claim loop and the per-job pipeline: download, ingest, transcribe, complete or fail.

Retention (sibei-score ADR-0034 decision 16): audio is download-once. It lives only in a temporary
directory that is removed when the job ends, however it ends, and nothing here logs a presigned URL,
a lease token, or the worker credential.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import httpx

from mat.core.note_events import NoteEvents, sha256_file
from mat.transcribe.pyin import Mono, transcribe_file
from mat.worker import ops
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
    auth_backoff_s: float = (
        15.0  # base delay after a rejected credential (sibei-score throttles it)
    )
    auth_backoff_cap_s: float = 300.0
    liveness_file: Path | None = None
    # sibei-score's lease has no absolute cap, so a hung job would be extended forever. After this
    # long we stop heartbeating (the server re-queues the job) and stop reporting liveness.
    max_job_s: float = 1800.0


class Heartbeater:
    """Keeps the lease alive from a thread while the main thread does the CPU-bound work."""

    def __init__(self, client: WorkerClient, job: Job, cfg: WorkerConfig) -> None:
        self._client, self._job, self._cfg = client, job, cfg
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stage: tuple[str, float] = ("claimed", 0.0)
        self._started = time.monotonic()
        self.lost = False
        self.cancelled = False
        self.timed_out = False
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
        except (ApiError, OSError, httpx.TransportError) as e:
            log.warning("heartbeat failed for %s: %s", self._job.id, type(e).__name__)
            return
        if res.cancelled:  # job deleted, or the lease is gone: the server answers both this way
            self.cancelled = True

    def _run(self) -> None:
        interval = max(1, self._job.heartbeatIntervalSeconds)
        while not self._stop.wait(interval):
            if time.monotonic() - self._started > self._cfg.max_job_s:
                self.timed_out = True
                log.error(
                    "job exceeded %.0f s; no longer heartbeating",
                    self._cfg.max_job_s,
                    extra={"event": "job-timeout", "job_id": self._job.id},
                )
                return  # the lease lapses, the server re-queues, and the health check goes stale
            if self._cfg.liveness_file:
                ops.touch(self._cfg.liveness_file)
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

    with Heartbeater(client, job, cfg) as hb, tempfile.TemporaryDirectory(prefix="mat-job-") as tmp:
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
            if e.status == 413:
                return refuse("unsupported-audio", e.message)
            return refuse("engine-error", e.message, retryable=True)
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


def _tick(cfg: WorkerConfig) -> None:
    if cfg.liveness_file:
        ops.touch(cfg.liveness_file)


def run(client: WorkerClient, cfg: WorkerConfig, stop: threading.Event, once: bool = False) -> int:
    """Claim and process jobs until `stop` is set (or one job with `once`). Returns jobs handled.

    `stop` is checked between jobs only: a job already claimed is finished first (graceful
    shutdown). One claim loop per worker: sibei-score allows a credential at most 4 concurrent
    long-polls. A rejected credential is retried slowly rather than in a tight loop (failed auth is
    rate limited per IP, and an operator can add the credential and restart the server).
    """
    handled = 0
    net_failures = 0
    auth_failures = 0
    api_failures = 0
    while not stop.is_set():
        _tick(cfg)
        try:
            job = client.claim(cfg.wait_seconds)
        except ApiError as e:
            if e.status in (401, 403):
                if once:
                    raise
                auth_failures += 1
                shift = min(auth_failures - 1, 6)
                delay = min(cfg.auth_backoff_cap_s, cfg.auth_backoff_s * 2**shift)
                log.error(
                    "worker credential rejected (%s); retrying in %.0f s",
                    e.kind,
                    delay,
                    extra={"event": "auth-rejected", "retry_in_s": delay},
                )
            else:
                api_failures += 1
                delay = min(60.0, 5.0 * 2 ** min(api_failures - 1, 4))
                log.error(
                    "claim refused (%s); retrying in %.0f s",
                    e.kind,
                    delay,
                    extra={"event": "claim-refused", "retry_in_s": delay},
                )
            _tick(cfg)
            stop.wait(delay)
            continue
        except (OSError, httpx.TransportError) as e:  # httpx transport errors are not OSErrors
            net_failures += 1
            delay = float(min(30, 2 ** min(net_failures, 5)))
            log.warning(
                "claim failed (%s); backing off %.0f s",
                type(e).__name__,
                delay,
                extra={"event": "claim-network-error", "retry_in_s": delay},
            )
            _tick(cfg)
            stop.wait(delay)
            continue
        net_failures = auth_failures = api_failures = 0
        _tick(cfg)
        if job is None:
            if once:
                return handled
            continue
        log.info(
            "claimed %s (attempt %d)",
            job.id,
            job.attempt,
            extra={"event": "claimed", "job_id": job.id, "attempt": job.attempt},
        )
        started = time.monotonic()
        try:
            outcome = process_job(client, job, cfg)
        except (ApiError, OSError, httpx.TransportError) as e:
            # We could not report the result (API unreachable, or it refused): the lease will
            # lapse and the server re-queues the job. The loop must survive this.
            log.error(
                "job %s could not be reported (%s)",
                job.id,
                type(e).__name__,
                extra={"event": "report-failed", "job_id": job.id},
            )
            outcome = "abandoned"
        log.info(
            "job %s: %s",
            job.id,
            outcome,
            extra={
                "event": "job-finished",
                "job_id": job.id,
                "outcome": outcome,
                "processing_s": round(time.monotonic() - started, 2),
            },
        )
        handled += 1
        _tick(cfg)
        if once:
            return handled
    return handled
