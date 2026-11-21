"""Bill-of-materials checks. `mat bom check` fails on a row with no source URL or licence."""

from __future__ import annotations

import tomllib
from pathlib import Path

REQUIRED = ("id", "kind", "licence", "source_url", "reviewed", "paid_path")
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "bom" / "sources.toml"


def load(path: Path = DEFAULT_PATH) -> list[dict[str, object]]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    rows = data.get("source", [])
    assert isinstance(rows, list)
    return rows


def problems(rows: list[dict[str, object]], paid_path_only: bool = False) -> list[str]:
    out: list[str] = []
    seen: set[object] = set()
    for i, row in enumerate(rows):
        label = str(row.get("id", f"row {i}"))
        for key in REQUIRED:
            if key not in row or row[key] in ("", None):
                out.append(f"{label}: missing {key}")
        url = str(row.get("source_url", ""))
        if url and not url.startswith(("http://", "https://")):
            out.append(f"{label}: source_url is not a URL")
        if row.get("id") in seen:
            out.append(f"{label}: duplicate id")
        seen.add(row.get("id"))
        if paid_path_only and row.get("paid_path") and not row.get("reviewed"):
            out.append(f"{label}: on the paid path but not reviewed")
    return out
