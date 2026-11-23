"""HTTP client for the pull protocol: claim, heartbeat, complete, fail, and the audio download.

Secrets rule: the worker token goes only to the API origin. Presigned storage URLs are fetched
with no Authorization header (the signature is the credential, and a bearer token must never reach
the object store). Neither the token nor a presigned URL is ever logged.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from mat.worker.protocol import (
    ApiError,
    AudioRef,
    ClaimResponse,
    HeartbeatResult,
    Job,
    LeaseLost,
)

log = logging.getLogger("mat.worker")

# httpx logs every request URL at INFO. Presigned URLs carry their signature in the query string,
# so those loggers stay quiet below WARNING (a test fails if a signature reaches the logs).
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_STEMS = 12  # sibei-score ADR-0034 amendment (SIB2-147)
STEM_DURATION_TOL_S = 0.01  # all stems describe one upload; the server allows 10 ms


class WorkerClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        worker_id: str,
        *,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
        backoff_base_s: float = 0.5,
        backoff_cap_s: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.worker_id = worker_id
        self._http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
        self._sleep = sleep
        self._max_retries = max_retries
        self._backoff_base = backoff_base_s
        self._backoff_cap = backoff_cap_s

    # --- plumbing ---------------------------------------------------------------------------

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), self._backoff_cap)
        base = min(self._backoff_cap, self._backoff_base * 2**attempt)
        return float(base * random.uniform(0.5, 1.0))  # noqa: S311

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Send with retry on network errors, 5xx and 429; 4xx answers go back to the caller."""
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._http.request(
                    method,
                    url,
                    json=json,
                    headers=headers,
                    timeout=timeout or httpx.USE_CLIENT_DEFAULT,
                )
            except httpx.TransportError as e:
                last = e
                log.warning(
                    "network error on %s (attempt %d): %s", method, attempt + 1, type(e).__name__
                )
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    return resp
                last = ApiError(resp.status_code, "retryable", "server asked us to retry")
                log.warning("HTTP %d on %s (attempt %d)", resp.status_code, method, attempt + 1)
                if attempt < self._max_retries:
                    self._sleep(self._delay(attempt, resp.headers.get("retry-after")))
                    continue
            if attempt < self._max_retries:
                self._sleep(self._delay(attempt, None))
        assert last is not None
        raise last

    def _raise_for(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        kind, message = "error", resp.text[:200]
        try:
            err = resp.json().get("error", {})
            kind, message = str(err.get("kind", kind)), str(err.get("message", message))
        except (ValueError, AttributeError):
            pass
        if resp.status_code == 409 or kind in ("lease-lost", "no-such-audio-job"):
            raise LeaseLost(resp.status_code, kind, message)
        raise ApiError(resp.status_code, kind, message)

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        resp = self._request("POST", f"{self.base_url}{path}", json=body, headers=self._auth())
        self._raise_for(resp)
        return resp

    # --- protocol calls ---------------------------------------------------------------------

    def claim(self, wait_seconds: int = 20) -> Job | None:
        resp = self._request(
            "POST",
            f"{self.base_url}/v1/worker/audio/claim",
            json={"workerId": self.worker_id, "waitSeconds": wait_seconds},
            headers=self._auth(),
            timeout=wait_seconds + 30.0,
        )
        if resp.status_code == 204:
            return None
        self._raise_for(resp)
        return ClaimResponse.model_validate(resp.json()).job

    def heartbeat(
        self, job_id: str, lease: str, stage: str | None = None, fraction: float | None = None
    ) -> HeartbeatResult:
        body: dict[str, Any] = {"leaseToken": lease}
        if stage is not None:
            body["progress"] = {
                "stage": stage,
                "fraction": fraction if fraction is not None else 0.0,
            }
        resp = self._post(f"/v1/worker/audio/jobs/{job_id}/heartbeat", body)
        return HeartbeatResult.model_validate(resp.json())

    def complete(
        self, job_id: str, lease: str, duration_s: float, result: dict[str, Any]
    ) -> dict[str, Any]:
        resp = self._post(
            f"/v1/worker/audio/jobs/{job_id}/complete",
            {"leaseToken": lease, "durationSeconds": duration_s, "result": {"inline": result}},
        )
        out: dict[str, Any] = resp.json()
        return out

    def complete_stems(
        self, job_id: str, lease: str, duration_s: float, stems: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Complete a multi-stem job: one NoteEvents per stem, all about the same upload.

        sibei-score fails the whole job (non-retryable, nothing metered) on a differing source or
        more than 12 stems, so refuse here, before spending a request, with the stem index.
        """
        if not stems:
            raise ValueError("a result needs at least one stem")
        if len(stems) > MAX_STEMS:
            raise ValueError(f"at most {MAX_STEMS} stems per job, got {len(stems)}")
        first = stems[0]["source"]
        for i, st in enumerate(stems[1:], start=1):
            src = st["source"]
            if src["sha256"] != first["sha256"]:
                raise ValueError(f"stems[{i}].source.sha256 differs from stems[0]")
            if abs(src["duration_s"] - first["duration_s"]) > STEM_DURATION_TOL_S:
                raise ValueError(f"stems[{i}].source.duration_s differs from stems[0]")
        return self.complete(job_id, lease, duration_s, {"stems": stems})

    def fail(
        self, job_id: str, lease: str, kind: str, message: str, retryable: bool
    ) -> dict[str, Any]:
        resp = self._post(
            f"/v1/worker/audio/jobs/{job_id}/fail",
            {"leaseToken": lease, "kind": kind, "message": message[:500], "retryable": retryable},
        )
        out: dict[str, Any] = resp.json()
        return out

    # --- audio download ---------------------------------------------------------------------

    def download_audio(self, audio: AudioRef, dest: Path, max_bytes: int) -> int:
        """Stream the audio to `dest`, refusing more than `max_bytes`. Returns bytes written."""
        if audio.viaApi:
            url = audio.url if audio.url.startswith("http") else f"{self.base_url}{audio.url}"
            headers = {**self._auth(), **audio.headers}
        else:
            url, headers = audio.url, dict(audio.headers)  # presigned: no bearer token
        written = 0
        with self._http.stream(audio.method, url, headers=headers) as resp:
            if resp.status_code >= 400:
                raise ApiError(resp.status_code, "download-failed", "could not fetch the audio")
            with dest.open("wb") as f:
                for chunk in resp.iter_bytes(1 << 20):
                    written += len(chunk)
                    if written > max_bytes:
                        raise ApiError(413, "audio-too-large", "audio exceeds the size limit")
                    f.write(chunk)
        return written
