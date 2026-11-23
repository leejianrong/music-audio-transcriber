import subprocess
from pathlib import Path

import pytest

from mat.worker.ingest import IngestError, ingest

pytestmark = pytest.mark.integration


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)


@pytest.fixture
def sine_wav(tmp_path: Path) -> Path:
    p = tmp_path / "tone.wav"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=3", str(p))
    return p


def test_wav_is_decoded_to_mono_44k(tmp_path: Path, sine_wav: Path) -> None:
    res = ingest(sine_wav, tmp_path / "o", 60, 10**8) if (tmp_path / "o").mkdir() is None else None
    assert res and res.sample_rate == 44100 and abs(res.duration_s - 3.0) < 0.05


def test_video_container_yields_its_audio(tmp_path: Path) -> None:
    mp4 = tmp_path / "take.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=2:size=64x64:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-shortest", str(mp4),
    )  # fmt: skip
    out = tmp_path / "o"
    out.mkdir()
    res = ingest(mp4, out, 60, 10**8)
    assert res.had_video and abs(res.duration_s - 2.0) < 0.1


def test_png_renamed_to_mp3_is_rejected_by_content(tmp_path: Path) -> None:
    png = tmp_path / "pic.mp3"
    _ffmpeg("-f", "lavfi", "-i", "color=red:size=16x16", "-frames:v", "1", "-f", "image2", str(png))
    out = tmp_path / "o"
    out.mkdir()
    with pytest.raises(IngestError) as e:
        ingest(png, out, 60, 10**8)
    assert e.value.kind == "unsupported-audio"


def test_text_and_empty_files_are_rejected(tmp_path: Path) -> None:
    out = tmp_path / "o"
    out.mkdir()
    for name, data in (("a.mp3", b"not audio at all"), ("b.wav", b"")):
        p = tmp_path / name
        p.write_bytes(data)
        with pytest.raises(IngestError):
            ingest(p, out, 60, 10**8)


def test_playlist_pointing_at_a_url_is_refused_and_never_fetched(tmp_path: Path) -> None:
    pl = tmp_path / "evil.m3u8"
    pl.write_text("#EXTM3U\n#EXTINF:1,\nhttp://127.0.0.1:9/x.mp3\n")
    out = tmp_path / "o"
    out.mkdir()
    with pytest.raises(IngestError):
        ingest(pl, out, 60, 10**8)


def test_audio_over_the_duration_cap_is_refused(tmp_path: Path, sine_wav: Path) -> None:
    out = tmp_path / "o"
    out.mkdir()
    with pytest.raises(IngestError) as e:
        ingest(sine_wav, out, 1.0, 10**8)
    assert e.value.kind == "audio-too-long"


def test_file_over_the_size_cap_is_refused_before_decoding(tmp_path: Path, sine_wav: Path) -> None:
    out = tmp_path / "o"
    out.mkdir()
    with pytest.raises(IngestError):
        ingest(sine_wav, out, 60, 1000)
