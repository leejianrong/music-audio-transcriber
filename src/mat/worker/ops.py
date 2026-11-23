"""Operating a pull worker that has no inbound port: liveness file, JSON logs, request audit.

A pull worker cannot be probed over HTTP, so it proves it is alive by touching a file that
`mat worker --healthcheck` (and a container HEALTHCHECK) reads. The audit hook records, per outbound
request, only the host and whether an Authorization header was present; never any value. It lets an
end-to-end run assert that the worker credential went to the API and never to the object store.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

DEFAULT_LIVENESS = Path(
    os.environ.get("MAT_LIVENESS_FILE", Path(tempfile.gettempdir()) / "mat-worker.alive")
)
DEFAULT_MAX_AGE_S = 90.0

# The only per-record fields a JSON log line may carry besides the message: no URLs, no tokens.
EXTRA_FIELDS = ("event", "job_id", "outcome", "attempt", "processing_s", "audio_s", "retry_in_s")


def touch(path: Path) -> None:
    path.write_text(f"{time.time():.3f}\n")


def check_health(path: Path, max_age_s: float, now: float | None = None) -> tuple[bool, str]:
    """(healthy, reason). Healthy means the loop ticked within `max_age_s`."""
    try:
        age = (now if now is not None else time.time()) - path.stat().st_mtime
    except FileNotFoundError:
        return False, "no liveness file: the worker has not started its loop"
    if age > max_age_s:
        return False, f"the worker loop last ticked {age:.0f} s ago (limit {max_age_s:.0f} s)"
    return True, f"ok (ticked {age:.0f} s ago)"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in EXTRA_FIELDS:
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(out, separators=(",", ":"))


def configure_logging(fmt: str) -> None:
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def audit_hook(path: Path) -> Callable[[httpx.Request], None]:
    def hook(request: httpx.Request) -> None:
        line = {
            "host": request.url.host,
            "port": request.url.port,
            "authorization": "authorization" in request.headers,
        }
        with path.open("a") as f:
            f.write(json.dumps(line) + "\n")

    return hook
