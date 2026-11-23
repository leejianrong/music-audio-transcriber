"""The separator seam (S8): anything that turns a mono mix into named stems.

Pretrained third-party separators are dev-only baselines behind this protocol (ADR-0001); only
weights we trained ourselves may serve paying users.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import numpy.typing as npt

Audio = npt.NDArray[np.float32]


class Separator(Protocol):
    name: str

    def separate(self, mix: Audio, sr: int) -> dict[str, Audio]: ...
