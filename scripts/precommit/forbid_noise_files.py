#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

DENY_SUBSTRINGS = ["/_context/"]
DENY_BASENAMES = {".DS_Store", "...", ".__context"}


def is_denied(path: Path) -> bool:
    p = path.as_posix()
    if any(s in p for s in DENY_SUBSTRINGS):
        return True
    if path.name in DENY_BASENAMES:
        return True
    if path.name.startswith("._"):
        return True
    return False


def main(argv: list[str]) -> int:
    bad = [raw for raw in argv[1:] if is_denied(Path(raw))]
    if bad:
        print("ERROR: noise files detected (remove + ensure .gitignore blocks them):")
        for f in bad:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
