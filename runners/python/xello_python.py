#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import json
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runners.python.xello_python_impl import hello as python_hello
from tools.xello_registry import (
    bridge_kind,
    parse_edges,
    print_results,
    provider_path,
    result,
    rust_python_module_path,
    runner_path,
    supported_languages,
    validate_language,
)


def call_local(caller: str) -> tuple[str, str, int]:
    start = time.perf_counter_ns()
    message = python_hello(caller)
    return bridge_kind(caller, "python"), message, time.perf_counter_ns() - start


def call_shared_provider(caller: str, callee: str) -> tuple[str, str, int]:
    library = ctypes.CDLL(str(provider_path(callee)))
    library.xello_hello.argtypes = [ctypes.c_char_p]
    library.xello_hello.restype = ctypes.c_char_p
    start = time.perf_counter_ns()
    message = library.xello_hello(caller.encode("utf-8")).decode("utf-8")
    return bridge_kind(caller, callee), message, time.perf_counter_ns() - start


def call_rust_via_pyo3(caller: str) -> tuple[str, str, int]:
    module_path = rust_python_module_path()
    spec = importlib.util.spec_from_file_location("xello_rust_py", module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load PyO3 module at {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    start = time.perf_counter_ns()
    message = module.hello(caller)
    return bridge_kind(caller, "rust"), message, time.perf_counter_ns() - start


def call_edge(caller: str, callee: str) -> dict[str, object]:
    if caller != "python":
        raise ValueError("python runner can only execute edges whose caller is python")
    validate_language(callee)
    if callee == "python":
        bridge, message, duration_ns = call_local(caller)
    elif callee == "rust":
        bridge, message, duration_ns = call_rust_via_pyo3(caller)
    else:
        bridge, message, duration_ns = call_shared_provider(caller, callee)
    return result(caller, callee, bridge, duration_ns, message)


def delegate_edge(caller: str, callee: str) -> dict[str, object]:
    if caller == "python":
        return call_edge(caller, callee)
    command = [str(runner_path(caller)), "--json", "call", callee]
    if caller == "wasm":
        command.insert(0, sys.executable)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(f"{caller} runner failed for {callee}: {detail}")
    if not completed.stdout.strip():
        detail = completed.stderr.strip() or "empty stdout"
        raise ValueError(f"{caller} runner returned no JSON for {callee}: {detail}")

    return json.loads(completed.stdout)[0]


def run_chain(raw_edges: str) -> list[dict[str, object]]:
    return [delegate_edge(caller, callee) for caller, callee in parse_edges(raw_edges)]


def run_fanout(caller: str) -> list[dict[str, object]]:
    validate_language(caller)
    return [delegate_edge(caller, callee) for callee in supported_languages()]


def run_matrix() -> list[dict[str, object]]:
    return [delegate_edge(caller, callee) for caller in supported_languages() for callee in supported_languages()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Xello from the Python entrypoint.")
    parser.add_argument("--json", action="store_true", help="print structured JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("matrix", help="run every caller/callee pair")

    chain_parser = subparsers.add_parser("chain", help="run selected caller/callee edges")
    chain_parser.add_argument("--edges", required=True, help="comma-separated caller:callee edges")

    fanout_parser = subparsers.add_parser("fanout", help="run one caller against every supported callee")
    fanout_parser.add_argument("caller")

    call_parser = subparsers.add_parser("call", help="call one callee from the Python runner")
    call_parser.add_argument("callee")

    args = parser.parse_args()

    try:
        if args.command == "matrix":
            results = run_matrix()
        elif args.command == "chain":
            results = run_chain(args.edges)
        elif args.command == "fanout":
            results = run_fanout(args.caller)
        elif args.command == "call":
            results = [call_edge("python", args.callee)]
        else:
            parser.error(f"unsupported command: {args.command}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print_results(results, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
