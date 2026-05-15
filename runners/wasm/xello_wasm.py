#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.xello_registry import (
    parse_edges,
    print_results,
    provider_bridge_kind,
    provider_path,
    result,
    supported_languages,
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


def call_provider_for_caller(caller: str, callee: str) -> tuple[str, str, int]:
    if caller == "wasm" and callee == "wasm":
        return call_wasm()
    library = ctypes.CDLL(str(provider_path(callee)))
    library.xello_hello.argtypes = [ctypes.c_char_p]
    library.xello_hello.restype = ctypes.c_char_p
    start = time.perf_counter_ns()
    message = library.xello_hello(caller.encode("utf-8")).decode("utf-8")
    return provider_bridge_kind(callee), message, time.perf_counter_ns() - start


def run_edge(caller: str, callee: str) -> dict[str, object]:
    if caller == "wasm":
        return call_edge(callee)
    validate_language(caller)
    validate_language(callee)
    bridge, message, duration_ns = call_provider_for_caller(caller, callee)
    return result(caller, callee, bridge, duration_ns, message)


def run_chain(raw_edges: str) -> list[dict[str, object]]:
    results = []
    for step, (caller, callee) in enumerate(parse_edges(raw_edges), start=1):
        item = run_edge(caller, callee)
        item["step"] = step
        results.append(item)
    return results


def run_fanout(caller: str) -> list[dict[str, object]]:
    validate_language(caller)
    return [run_edge(caller, callee) for callee in supported_languages()]


def run_matrix() -> list[dict[str, object]]:
    return [run_edge(caller, callee) for caller in supported_languages() for callee in supported_languages()]


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
    try:
        if args.command == "call":
            print_results([call_edge(args.callee)], as_json=args.json)
        elif args.command == "matrix":
            print_results(run_matrix(), as_json=args.json)
        elif args.command == "fanout":
            print_results(run_fanout(args.caller), as_json=args.json)
        elif args.command == "chain":
            print_results(run_chain(args.edges), as_json=args.json)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
