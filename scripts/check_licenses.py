"""Fail if an installed runtime dependency declares a GPL or AGPL licence (ADR-0006).

LGPL is allowed (separately loaded libraries). Reviewed exceptions go in scripts/license-allow.txt,
one distribution name per line, each with a reason after a '#'.
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import distributions
from pathlib import Path

ALLOW_FILE = Path(__file__).with_name("license-allow.txt")
SELF = {"mat"}
COPYLEFT = re.compile(r"\b(A?GPL)(?:[-_ ]?v?[0-9.]+)?(?:[-_ ](?:only|or[-_ ]later))?\b", re.I)


def allowed() -> set[str]:
    if not ALLOW_FILE.exists():
        return set()
    names = set()
    for line in ALLOW_FILE.read_text().splitlines():
        name = line.split("#", 1)[0].strip().lower()
        if name:
            names.add(name)
    return names


def declared(meta: object) -> list[str]:
    get = meta.get  # type: ignore[attr-defined]
    out = [get("License-Expression") or "", get("License") or ""]
    out += [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]  # type: ignore[attr-defined]
    return [o for o in out if o]


def is_copyleft(text: str) -> bool:
    cleaned = re.sub(r"\bL(?:ESSER )?GPL\b", "", text, flags=re.I)
    cleaned = re.sub(r"Lesser General Public", "", cleaned, flags=re.I)
    return bool(COPYLEFT.search(cleaned)) or "GNU General Public" in cleaned


def main() -> int:
    ok = allowed()
    bad: list[tuple[str, str]] = []
    count = 0
    for dist in distributions():
        name = (dist.metadata["Name"] or "").lower()
        if not name or name in SELF:
            continue
        count += 1
        for text in declared(dist.metadata):
            first_line = text.strip().splitlines()[0][:120]
            if is_copyleft(text if len(text) < 200 else first_line) and name not in ok:
                bad.append((name, first_line))
                break
    if bad:
        print("Copyleft (GPL/AGPL) runtime dependencies found:")
        for name, lic in bad:
            print(f"  {name}: {lic}")
        print("Review each, then add it to scripts/license-allow.txt with a reason, or remove it.")
        return 1
    print(f"licence check ok ({count} distributions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
