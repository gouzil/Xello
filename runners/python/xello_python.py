#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runners.python.xello_python_impl import hello as python_hello
from tools.xello_registry import (
    bridge_kind,
    cpp_python_module_path,
    parse_edges,
    print_results,
    provider_bridge_kind,
    provider_path,
    result,
    rust_python_module_path,
    supported_languages,
    validate_language,
)


def load_python_extension(name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load Python extension at {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    module = load_python_extension("xello_rust_py", rust_python_module_path())
    start = time.perf_counter_ns()
    message = module.hello(caller)
    return bridge_kind(caller, "rust"), message, time.perf_counter_ns() - start


def call_cpp_via_pybind(caller: str) -> tuple[str, str, int]:
    module = load_python_extension("xello_cpp_pybind", cpp_python_module_path())
    start = time.perf_counter_ns()
    message = module.hello(caller)
    return bridge_kind(caller, "cpp"), message, time.perf_counter_ns() - start


def call_edge(caller: str, callee: str) -> dict[str, object]:
    if caller != "python":
        raise ValueError("python runner can only execute edges whose caller is python")
    validate_language(callee)
    if callee == "python":
        bridge, message, duration_ns = call_local(caller)
    elif callee == "rust":
        bridge, message, duration_ns = call_rust_via_pyo3(caller)
    elif callee == "cpp":
        bridge, message, duration_ns = call_cpp_via_pybind(caller)
    else:
        bridge, message, duration_ns = call_shared_provider(caller, callee)
    return result(caller, callee, bridge, duration_ns, message)


def delegate_edge(caller: str, callee: str) -> dict[str, object]:
    if caller == "python":
        return call_edge(caller, callee)
    validate_language(caller)
    validate_language(callee)
    bridge, message, duration_ns = call_provider_for_caller(caller, callee)
    return result(caller, callee, bridge, duration_ns, message)


def call_provider_for_caller(caller: str, callee: str) -> tuple[str, str, int]:
    if caller == callee:
        return call_same_language_provider(caller)
    return call_provider_function(caller, callee, provider_bridge_kind(callee))


def call_provider_function(caller: str, callee: str, bridge: str) -> tuple[str, str, int]:
    library = ctypes.CDLL(str(provider_path(callee)))
    library.xello_hello.argtypes = [ctypes.c_char_p]
    library.xello_hello.restype = ctypes.c_char_p
    start = time.perf_counter_ns()
    message = library.xello_hello(caller.encode("utf-8")).decode("utf-8")
    return bridge, message, time.perf_counter_ns() - start


def call_same_language_provider(language: str) -> tuple[str, str, int]:
    if language == "python":
        return call_local("python")
    if language == "wasm":
        start = time.perf_counter_ns()
        message = "hello world from wasm implementation, called by wasm"
        return "WebAssembly runtime host", message, time.perf_counter_ns() - start
    return call_provider_function(language, language, provider_bridge_kind(language))


def run_chain(raw_edges: str) -> list[dict[str, object]]:
    results = []
    for step, (caller, callee) in enumerate(parse_edges(raw_edges), start=1):
        item = delegate_edge(caller, callee)
        item["step"] = step
        results.append(item)
    return results


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
