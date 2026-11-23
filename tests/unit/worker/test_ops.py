import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from mat.cli import main
from mat.core.note_events import NoteEvents
from mat.worker import ops, runner
from mat.worker.runner import WorkerConfig, process_job

from .fakes import LEASE, STORAGE_URL, TOKEN, FakeApi, fake_events, fake_ingest, job_json, parse_job


@pytest.fixture(autouse=True)
def _stub_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ingest", fake_ingest())


def test_health_check_is_ok_when_fresh_and_stale_when_old(tmp_path: Path) -> None:
    f = tmp_path / "alive"
    assert ops.check_health(f, 90)[0] is False  # never started
    ops.touch(f)
    assert ops.check_health(f, 90)[0] is True
    old = time.time() - 200
    os.utime(f, (old, old))
    ok, reason = ops.check_health(f, 90)
    assert ok is False and "ticked" in reason


def test_cli_healthcheck_exit_codes(tmp_path: Path) -> None:
    f = tmp_path / "alive"
    assert main(["worker", "--healthcheck", "--liveness-file", str(f)]) == 1
    ops.touch(f)
    assert main(["worker", "--healthcheck", "--liveness-file", str(f)]) == 0
    old = time.time() - 300
    os.utime(f, (old, old))
    assert main(["worker", "--healthcheck", "--liveness-file", str(f)]) == 1


def test_worker_without_a_token_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAT_WORKER_TOKEN", raising=False)
    assert main(["worker", "--api-url", "https://x.test", "--once"]) == 2


def test_the_claim_loop_and_a_running_job_both_keep_the_liveness_file_fresh(tmp_path: Path) -> None:
    live = tmp_path / "alive"
    api = FakeApi()
    api.claims.append(httpx.Response(200, json=job_json(interval=1)))
    cfg = WorkerConfig(liveness_file=live)

    def slow(path: Path, instrument: str) -> NoteEvents:
        ops.touch(live)
        old = time.time() - 500
        os.utime(live, (old, old))  # pretend the loop has been silent
        assert api.heartbeat_served.wait(timeout=15)
        assert ops.check_health(live, 90)[0], "the heartbeat thread should have touched the file"
        return fake_events(path, instrument)

    out = process_job(api.client(), parse_job(interval=1), cfg, slow)
    assert out == "completed"


def test_a_hung_job_stops_heartbeating_after_max_job_seconds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    api = FakeApi()
    cfg = WorkerConfig(max_job_s=0.2)

    def hang(path: Path, instrument: str) -> NoteEvents:
        time.sleep(1.8)  # long enough for the 1 s heartbeat tick to see the budget exceeded
        return fake_events(path, instrument)

    process_job(api.client(), parse_job(interval=1), cfg, hang)
    assert not api.calls("/heartbeat"), "a hung job must not keep its lease alive"
    assert any(getattr(r, "event", "") == "job-timeout" for r in caplog.records)


def test_stop_during_a_job_lets_it_finish_then_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    api.claims.append(httpx.Response(200, json=job_json()))
    api.claims.append(httpx.Response(200, json=job_json()))  # must never be claimed
    stop = threading.Event()
    finished: list[str] = []

    def work(client: Any, job: Any, cfg: Any) -> str:
        stop.set()  # SIGTERM arrives while the job is running
        finished.append(job.id)
        return "completed"

    monkeypatch.setattr(runner, "process_job", work)
    assert runner.run(api.client(), WorkerConfig(), stop) == 1
    assert finished == ["job_1"] and len(api.claims) == 1


def test_json_log_lines_carry_structured_fields_and_no_secrets(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "_default_transcribe", fake_events)
    ops.configure_logging("json")
    api = FakeApi()
    api.claims.append(httpx.Response(200, json=job_json()))
    api.completes.append(httpx.Response(503))
    runner.run(api.client(), WorkerConfig(), threading.Event(), once=True)
    err = capsys.readouterr().err
    lines = [json.loads(line) for line in err.splitlines() if line.strip()]
    events = {line.get("event"): line for line in lines}
    assert events["claimed"]["job_id"] == "job_1"
    assert events["job-finished"]["outcome"] == "completed"
    assert "processing_s" in events["job-finished"]
    for secret in (TOKEN, LEASE, "sig_secret", STORAGE_URL):
        assert secret not in err


def test_audit_hook_records_host_and_whether_auth_was_sent_never_the_value(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    hook = ops.audit_hook(log)
    hook(
        httpx.Request("POST", "https://api.test/v1/x", headers={"Authorization": f"Bearer {TOKEN}"})
    )
    hook(httpx.Request("GET", "http://storage.test:9000/b?X-Amz-Signature=sig_secret"))
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert rows == [
        {"host": "api.test", "port": None, "authorization": True},
        {"host": "storage.test", "port": 9000, "authorization": False},
    ]
    assert TOKEN not in log.read_text() and "sig_secret" not in log.read_text()


def test_an_unreachable_api_makes_the_loop_back_off_not_crash() -> None:
    api = FakeApi()
    stop = threading.Event()
    waits: list[float] = []
    real_wait = stop.wait

    def record(timeout: float | None = None) -> bool:
        waits.append(float(timeout or 0))
        if len(waits) >= 3:
            stop.set()
        return real_wait(0)

    stop.wait = record  # type: ignore[method-assign]
    api.claims.extend([httpx.ConnectError("api is down")] * 60)  # type: ignore[arg-type]

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("api is down")

    from mat.worker.client import WorkerClient

    client = WorkerClient(
        "https://api.test",
        TOKEN,
        "w",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _s: None,
        max_retries=1,
    )
    assert runner.run(client, WorkerConfig(), stop) == 0  # no exception escaped
    assert waits == [2.0, 4.0, 8.0]  # exponential back-off between claim attempts


def test_a_result_that_cannot_be_reported_does_not_kill_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "_default_transcribe", fake_events)
    api = FakeApi()
    api.claims.append(httpx.Response(200, json=job_json()))
    api.completes.extend([httpx.ConnectError("down")] * 20)
    assert runner.run(api.client(), WorkerConfig(), threading.Event(), once=True) == 1
