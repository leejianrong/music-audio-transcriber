"""Ingest untrusted uploads: probe by content, cap size and duration, decode to mono 44.1 kHz wav.

Uploads are hostile bytes. We never trust the extension or declared content type: ffprobe decides
what the file is, only an allowlist of container formats passes, ffmpeg may open local files and
pipes only (no network, no playlists that pull other URLs), and every subprocess has a timeout and
CPU and memory limits.
"""

from __future__ import annotations

import json
import resource
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import soundfile as sf

# ffprobe `format_name` values we accept. Anything else (image2, concat, hls, sdp...) is refused.
ALLOWED_FORMATS = frozenset(
    {
        "wav",
        "mp3",
        "flac",
        "ogg",
        "aac",
        "aiff",
        "mov,mp4,m4a,3gp,3g2,mj2",
        "matroska,webm",
        "avi",
    }
)
SAMPLE_RATE = 44100
PROBE_TIMEOUT_S = 30
DECODE_TIMEOUT_S = 300
CPU_LIMIT_S = 600
MEM_LIMIT_BYTES = 4 * 1024**3
PROTOCOL_WHITELIST = "file,pipe"


class IngestError(Exception):
    """A file we refuse. `kind` is the protocol's failure slug; refusals are never retryable."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class Ingested:
    path: Path
    duration_s: float
    sample_rate: int
    source_format: str
    had_video: bool


def _limits() -> None:  # runs in the child before exec (Linux)
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_S, CPU_LIMIT_S))
    resource.setrlimit(resource.RLIMIT_AS, (MEM_LIMIT_BYTES, MEM_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**3, 2 * 1024**3))


def _run(cmd: list[str], timeout_s: int) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd,
            capture_output=True,
            timeout=timeout_s,
            check=False,
            preexec_fn=_limits,  # noqa: PLW1509
        )
    except subprocess.TimeoutExpired as e:
        raise IngestError("unsupported-audio", "decoding timed out") from e
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg/ffprobe is not installed") from e


def probe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error", "-protocol_whitelist", PROTOCOL_WHITELIST,
        "-print_format", "json", "-show_format", "-show_streams", "-i", str(path.resolve()),
    ]  # fmt: skip
    r = _run(cmd, PROBE_TIMEOUT_S)
    if r.returncode != 0:
        raise IngestError("unsupported-audio", "not a readable audio or video file")
    try:
        data: dict[str, Any] = json.loads(r.stdout)
    except ValueError as e:
        raise IngestError("unsupported-audio", "unreadable media metadata") from e
    return data


def validate_probe(info: dict[str, Any]) -> tuple[str, bool]:
    """Pure policy: returns (format_name, had_video) or raises IngestError."""
    fmt = str(info.get("format", {}).get("format_name", ""))
    if fmt not in ALLOWED_FORMATS:
        raise IngestError("unsupported-audio", f"unsupported container: {fmt or 'unknown'}")
    streams = info.get("streams", [])
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise IngestError("unsupported-audio", "no audio stream")
    had_video = any(
        s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) != 1
        for s in streams
    )
    return fmt, had_video


def ingest(src: Path, out_dir: Path, max_duration_s: float, max_bytes: int) -> Ingested:
    if not src.is_file():
        raise IngestError("unsupported-audio", "no such file")
    if src.stat().st_size > max_bytes:
        raise IngestError("unsupported-audio", "file exceeds the size limit")
    fmt, had_video = validate_probe(probe(src))
    out = out_dir / "audio.wav"
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", PROTOCOL_WHITELIST,
        "-i", str(src.resolve()), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-t", str(max_duration_s + 1.0), "-c:a", "pcm_s16le", "-f", "wav", "-y", str(out),
    ]  # fmt: skip
    r = _run(cmd, DECODE_TIMEOUT_S)
    if r.returncode != 0 or not out.exists():
        raise IngestError("unsupported-audio", "could not decode the audio stream")
    info = sf.info(str(out))
    duration = float(info.frames / info.samplerate)
    if duration <= 0:
        raise IngestError("unsupported-audio", "the audio stream is empty")
    if duration > max_duration_s:
        out.unlink(missing_ok=True)
        raise IngestError("audio-too-long", f"audio is longer than {max_duration_s:.0f} s")
    return Ingested(out, duration, int(info.samplerate), fmt, had_video)
