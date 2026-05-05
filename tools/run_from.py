#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.xello_registry import runner_path, validate_language


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: tools/run_from.py <language> <call|chain|matrix> ...", file=sys.stderr)
        return 2

    runner = sys.argv[1]
    try:
        validate_language(runner)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    command = [str(runner_path(runner)), *sys.argv[2:]]
    if runner in ("python", "wasm"):
        command.insert(0, sys.executable)
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
