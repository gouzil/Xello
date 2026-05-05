#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.xello_registry import (
    print_results,
    provider_path,
    result,
    validate_language,
)


def call_shared_provider(callee: str) -> tuple[str, str, int]:
    library = ctypes.CDLL(str(provider_path(callee)))
    library.xello_hello.argtypes = [ctypes.c_char_p]
    library.xello_hello.restype = ctypes.c_char_p
    start = time.perf_counter_ns()
    message = library.xello_hello(b"wasm").decode("utf-8")
    bridge = "Python shared library via Python/C API" if callee == "python" else f"{callee} shared library via C ABI"
    return bridge, message, time.perf_counter_ns() - start


def call_wasm() -> tuple[str, str, int]:
    start = time.perf_counter_ns()
    message = "hello world from wasm implementation, called by wasm"
    return "WebAssembly runtime host", message, time.perf_counter_ns() - start


def call_edge(callee: str) -> dict[str, object]:
    validate_language(callee)
    if callee == "wasm":
        bridge, message, duration_ns = call_wasm()
    else:
        bridge, message, duration_ns = call_shared_provider(callee)
    return result("wasm", callee, bridge, duration_ns, message)


def delegate_to_python(args: list[str], *, as_json: bool) -> int:
    command = [sys.executable, "tools/xello.py"]
    if as_json:
        command.append("--json")
    command.extend(args)
    return subprocess.run(command, cwd=ROOT).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Xello from the WebAssembly runtime entrypoint.")
    parser.add_argument("--json", action="store_true", help="print structured JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("matrix")
    fanout_parser = subparsers.add_parser("fanout")
    fanout_parser.add_argument("caller")
    chain_parser = subparsers.add_parser("chain")
    chain_parser.add_argument("--edges", required=True)
    call_parser = subparsers.add_parser("call")
    call_parser.add_argument("callee")

    args = parser.parse_args()
    if args.command == "call":
        try:
            print_results([call_edge(args.callee)], as_json=args.json)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    passthrough = [args.command]
    if args.command == "fanout":
        passthrough.append(args.caller)
    elif args.command == "chain":
        passthrough.extend(["--edges", args.edges])
    return delegate_to_python(passthrough, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
