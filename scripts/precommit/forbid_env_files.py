#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

ALLOWLIST = {".env.example"}


def main(argv: list[str]) -> int:
    bad = []
    for raw in argv[1:]:
        p = Path(raw)
        if p.name.startswith(".env") and p.name not in ALLOWLIST:
            bad.append(raw)
    if bad:
        print(
            "ERROR: dotenv files must not be committed. Use .env.example with dummy values only."
        )
        for f in bad:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
