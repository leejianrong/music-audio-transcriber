import shutil

import pytest

pytestmark = pytest.mark.integration


def test_ffmpeg_present() -> None:
    assert shutil.which("ffmpeg")
