import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_licenses", ROOT / "scripts" / "check_licenses.py"
)
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class _Meta(dict):  # type: ignore[type-arg]
    def __init__(self, name: str, lic: str) -> None:
        super().__init__({"Name": name, "License": lic, "License-Expression": ""})

    def get_all(self, key: str) -> list[str]:
        return []


def _dist(name: str, lic: str) -> Any:
    return SimpleNamespace(metadata=_Meta(name, lic))


def test_gpl_and_agpl_are_copyleft_but_lgpl_is_not() -> None:
    assert check.is_copyleft("GPL-3.0-or-later")
    assert check.is_copyleft("GNU General Public License v3")
    assert check.is_copyleft("AGPL-3.0")
    assert not check.is_copyleft("LGPL-2.1")
    assert not check.is_copyleft("GNU Lesser General Public License v2.1")
    assert not check.is_copyleft("MIT")


def test_planted_gpl_dependency_fails_the_check(monkeypatch: Any) -> None:
    monkeypatch.setattr(check, "distributions", lambda: [_dist("evil", "GPL-3.0-only")])
    assert check.main() == 1


def test_clean_dependencies_pass(monkeypatch: Any) -> None:
    monkeypatch.setattr(check, "distributions", lambda: [_dist("fine", "MIT")])
    assert check.main() == 0
