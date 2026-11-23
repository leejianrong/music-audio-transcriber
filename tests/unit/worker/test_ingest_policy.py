import pytest

from mat.worker.ingest import IngestError, validate_probe


def _info(fmt: str, *streams: tuple[str, int]) -> dict[str, object]:
    return {
        "format": {"format_name": fmt},
        "streams": [
            {"codec_type": kind, "disposition": {"attached_pic": pic}} for kind, pic in streams
        ],
    }


def test_audio_container_is_accepted() -> None:
    assert validate_probe(_info("wav", ("audio", 0))) == ("wav", False)


def test_video_with_audio_is_accepted_and_flagged() -> None:
    fmt, had_video = validate_probe(_info("mov,mp4,m4a,3gp,3g2,mj2", ("video", 0), ("audio", 0)))
    assert had_video and fmt.startswith("mov")


def test_cover_art_is_not_video() -> None:
    assert validate_probe(_info("mp3", ("audio", 0), ("video", 1)))[1] is False


@pytest.mark.parametrize("fmt", ["image2", "png_pipe", "concat", "hls", "sdp", "rtsp", "", "tty"])
def test_non_media_and_network_demuxers_are_refused(fmt: str) -> None:
    with pytest.raises(IngestError) as e:
        validate_probe(_info(fmt, ("audio", 0)))
    assert e.value.kind == "unsupported-audio"


def test_file_without_an_audio_stream_is_refused() -> None:
    with pytest.raises(IngestError):
        validate_probe(_info("matroska,webm", ("video", 0)))


def test_memory_limit_stops_a_runaway_child(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from mat.worker import ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "MEM_LIMIT_BYTES", 512 * 1024**2)
    r = ingest_mod._run(
        [sys.executable, "-c", "x = bytearray(2 * 1024**3); print('allocated')"], 30
    )
    assert r.returncode != 0 and b"allocated" not in r.stdout


def test_a_hung_child_is_killed_at_the_timeout() -> None:
    import sys

    from mat.worker import ingest as ingest_mod

    with pytest.raises(IngestError):
        ingest_mod._run([sys.executable, "-c", "import time; time.sleep(30)"], 1)
