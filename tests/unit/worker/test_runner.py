import logging
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from mat.core.note_events import NoteEvents
from mat.worker import runner
from mat.worker.ingest import IngestError
from mat.worker.protocol import ApiError
from mat.worker.runner import WorkerConfig, process_job

from .fakes import (
    LEASE,
    STORAGE_URL,
    TOKEN,
    FakeApi,
    fake_events,
    fake_ingest,
    job_json,
    parse_job,
)

CFG = WorkerConfig()


@pytest.fixture(autouse=True)
def _stub_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ingest", fake_ingest(duration=12.5))


def test_claim_returns_none_on_204_and_a_job_on_200() -> None:
    api = FakeApi()
    client = api.client()
    assert client.claim(0) is None
    api.claims.append(httpx.Response(200, json=job_json()))
    job = client.claim(0)
    assert job is not None and job.id == "job_1" and job.params.instrument == "bass"


def test_happy_path_completes_with_decoded_duration_and_upload_hash() -> None:
    api = FakeApi(audio=b"original upload bytes")
    out = process_job(api.client(), parse_job(), CFG, fake_events)
    assert out == "completed"
    (done,) = api.calls("/complete")
    assert done["leaseToken"] == LEASE
    assert done["durationSeconds"] == 12.5
    result = NoteEvents.model_validate(done["result"]["inline"])
    import hashlib

    assert result.source.sha256 == hashlib.sha256(b"original upload bytes").hexdigest()


def test_presigned_download_never_carries_the_worker_token() -> None:
    api = FakeApi()
    process_job(api.client(), parse_job(), CFG, fake_events)
    storage = [r for r in api.requests if r.url.host == "storage.test"]
    assert storage and all("authorization" not in r.headers for r in storage)
    api_calls = [r for r in api.requests if r.url.host == "api.test"]
    assert api_calls and all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in api_calls)


def test_via_api_download_sends_bearer_and_lease_header() -> None:
    api = FakeApi()
    process_job(api.client(), parse_job(via_api=True), CFG, fake_events)
    (dl,) = [r for r in api.requests if r.url.path.endswith("/content")]
    assert dl.headers["authorization"] == f"Bearer {TOKEN}"
    assert dl.headers["x-lease-token"] == LEASE


def test_unsupported_instrument_fails_without_downloading() -> None:
    api = FakeApi()
    out = process_job(api.client(), parse_job(instrument="piano"), CFG, fake_events)
    assert out == "failed"
    (fail,) = api.calls("/fail")
    assert fail["kind"] == "unsupported-instrument" and fail["retryable"] is False
    assert not [r for r in api.requests if r.url.host == "storage.test"]


def test_missing_instrument_is_refused() -> None:
    api = FakeApi()
    assert process_job(api.client(), parse_job(instrument=None), CFG, fake_events) == "failed"


def test_oversize_declared_file_is_refused_before_download() -> None:
    api = FakeApi()
    job = parse_job()
    job.audio.sizeBytes = CFG.max_bytes + 1
    assert process_job(api.client(), job, CFG, fake_events) == "failed"
    assert not [r for r in api.requests if r.url.host == "storage.test"]


def test_ingest_refusal_is_a_non_retryable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise IngestError("audio-too-long", "audio is longer than 600 s")

    monkeypatch.setattr(runner, "ingest", refuse)
    api = FakeApi()
    assert process_job(api.client(), parse_job(), CFG, fake_events) == "failed"
    (fail,) = api.calls("/fail")
    assert fail["kind"] == "audio-too-long" and fail["retryable"] is False


def test_engine_bug_is_a_retryable_clean_failure() -> None:
    def boom(path: Path, instrument: str) -> NoteEvents:
        raise RuntimeError("model exploded: secret detail")

    api = FakeApi()
    assert process_job(api.client(), parse_job(), CFG, boom) == "failed"
    (fail,) = api.calls("/fail")
    assert fail["kind"] == "engine-error" and fail["retryable"] is True
    assert "secret detail" not in fail["message"]  # only the exception type goes to the server


def test_lease_lost_on_complete_is_abandoned_not_an_error() -> None:
    api = FakeApi()
    api.completes.append(
        httpx.Response(409, json={"error": {"kind": "lease-lost", "message": "x"}})
    )
    assert process_job(api.client(), parse_job(), CFG, fake_events) == "abandoned"
    assert not api.calls("/fail")


def test_complete_retries_through_5xx_and_network_errors() -> None:
    api = FakeApi()
    api.completes.extend(
        [
            httpx.Response(503),
            httpx.ConnectError("reset"),
            httpx.Response(200, json={"status": "succeeded"}),
        ]
    )
    assert process_job(api.client(), parse_job(), CFG, fake_events) == "completed"
    assert len(api.calls("/complete")) == 3  # same lease token each time: complete is idempotent
    assert {c["leaseToken"] for c in api.calls("/complete")} == {LEASE}


def test_gives_up_after_the_retry_budget() -> None:
    api = FakeApi()
    api.completes.extend([httpx.Response(503)] * 20)
    with pytest.raises(ApiError):
        process_job(api.client(), parse_job(), CFG, fake_events)


def _wait_for_heartbeat(api: FakeApi) -> Any:
    def transcribe(path: Path, instrument: str) -> NoteEvents:
        assert api.heartbeat_served.wait(timeout=15), "no heartbeat was sent"
        return fake_events(path, instrument)

    return transcribe


def test_heartbeat_lease_loss_abandons_the_job() -> None:
    api = FakeApi()
    api.heartbeat_response = httpx.Response(
        409, json={"error": {"kind": "lease-lost", "message": "x"}}
    )
    out = process_job(api.client(), parse_job(interval=1), CFG, _wait_for_heartbeat(api))
    assert out == "abandoned"
    assert not api.calls("/complete")


def test_cancelled_job_is_discarded_without_completing() -> None:
    api = FakeApi()
    api.heartbeat_response = httpx.Response(200, json={"leaseExpiresAt": None, "cancelled": True})
    out = process_job(api.client(), parse_job(interval=1), CFG, _wait_for_heartbeat(api))
    assert out == "cancelled"
    assert not api.calls("/complete")


def test_heartbeats_report_progress() -> None:
    api = FakeApi()
    process_job(api.client(), parse_job(interval=1), CFG, _wait_for_heartbeat(api))
    beats = api.calls("/heartbeat")
    assert beats and beats[0]["leaseToken"] == LEASE
    assert beats[0]["progress"]["stage"] in {"downloading", "decoding", "transcribing"}


def test_temp_audio_is_deleted_however_the_job_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Path] = []

    def spy_ingest(src: Path, out_dir: Path, *a: Any, **k: Any) -> Any:
        seen.append(out_dir)
        assert src.exists()
        return fake_ingest()(src, out_dir, *a, **k)

    monkeypatch.setattr(runner, "ingest", spy_ingest)

    def boom(path: Path, instrument: str) -> NoteEvents:
        raise RuntimeError("x")

    process_job(FakeApi().client(), parse_job(), CFG, fake_events)
    process_job(FakeApi().client(), parse_job(), CFG, boom)
    assert len(seen) == 2 and not any(p.exists() for p in seen)


def test_logs_never_contain_the_token_lease_or_presigned_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    api = FakeApi()
    api.completes.append(httpx.Response(503))
    process_job(api.client(), parse_job(), CFG, fake_events)
    process_job(api.client(), parse_job(instrument="piano"), CFG, fake_events)
    text = caplog.text
    for secret in (TOKEN, LEASE, "sig_secret", STORAGE_URL, "storage.test"):
        assert secret not in text, f"leaked {secret!r} into logs"


def test_run_once_processes_one_job_and_returns() -> None:
    api = FakeApi()
    api.claims.append(httpx.Response(200, json=job_json()))
    handled = runner.run(api.client(), CFG, threading.Event(), once=True)
    assert handled == 1


def test_a_rejected_worker_credential_stops_the_loop() -> None:
    api = FakeApi()
    api.claims.append(
        httpx.Response(401, json={"error": {"kind": "unauthenticated", "message": "x"}})
    )
    with pytest.raises(ApiError):
        runner.run(api.client(), CFG, threading.Event(), once=True)
