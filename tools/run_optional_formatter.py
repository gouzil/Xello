#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_optional_formatter.py <formatter> [args...]", file=sys.stderr)
        return 2

    formatter = sys.argv[1]
    if shutil.which(formatter) is None:
        print(f"{formatter} not found; skipping optional formatter")
        return 0

    return subprocess.run(sys.argv[1:]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
