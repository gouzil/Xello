#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.xello_registry import parse_edges, runner_path, supported_languages, validate_language

DEFAULT_WARMUP = 1
DEFAULT_ITERATIONS = 10
BRIDGE_VARIANTS = {
    ("rust", "python"): ("pyo3", "capi"),
}


def positive_duration(duration_ns: int) -> int:
    return max(int(duration_ns), 1)


def percentile(values: list[int], rank: float) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = round((len(ordered) - 1) * rank)
    return ordered[index]


def runner_command(caller: str, callee: str, *, bridge_variant: str | None = None) -> list[str]:
    command = [str(runner_path(caller)), "--json", "call", callee]
    if bridge_variant is not None:
        command[-1:-1] = ["--bridge", bridge_variant]
    if caller in ("python", "wasm"):
        command.insert(0, sys.executable)
    return command


def call_once(caller: str, callee: str, *, bridge_variant: str | None = None) -> dict[str, Any]:
    start = time.perf_counter_ns()
    completed = subprocess.run(
        runner_command(caller, callee, bridge_variant=bridge_variant),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    total_duration_ns = positive_duration(time.perf_counter_ns() - start)
    results = json.loads(completed.stdout)
    if len(results) != 1:
        raise RuntimeError(f"expected one result from {caller}:{callee}, got {len(results)}")
    item = results[0]
    item["total_duration_ns"] = total_duration_ns
    return item


def bridge_variants_for(caller: str, callee: str, requested: str | None = None) -> tuple[str | None, ...]:
    validate_language(caller)
    validate_language(callee)
    variants = BRIDGE_VARIANTS.get((caller, callee))
    if requested is not None:
        if variants is None or requested not in variants:
            raise ValueError(f"--bridge is not supported for {caller} -> {callee}")
        return (requested,)
    if variants is None:
        return (None,)
    return variants


def benchmark_edge_variant(
    caller: str,
    callee: str,
    *,
    iterations: int,
    warmup: int,
    bridge_variant: str | None = None,
) -> dict[str, Any]:
    for _ in range(warmup):
        call_once(caller, callee, bridge_variant=bridge_variant)

    call_durations: list[int] = []
    total_durations: list[int] = []
    selected_bridge = ""
    message = ""
    for _ in range(iterations):
        item = call_once(caller, callee, bridge_variant=bridge_variant)
        selected_bridge = str(item["bridge"])
        message = str(item["message"])
        call_durations.append(positive_duration(int(item["duration_ns"])))
        total_durations.append(positive_duration(int(item["total_duration_ns"])))

    return {
        "caller": caller,
        "callee": callee,
        "bridge": selected_bridge,
        "iterations": iterations,
        "warmup": warmup,
        "call_duration_ns": summarize(call_durations),
        "total_duration_ns": summarize(total_durations),
        "message": message,
    }


def benchmark_edge(
    caller: str,
    callee: str,
    *,
    iterations: int,
    warmup: int,
    bridge_variant: str | None = None,
) -> list[dict[str, Any]]:
    return [
        benchmark_edge_variant(
            caller,
            callee,
            iterations=iterations,
            warmup=warmup,
            bridge_variant=variant,
        )
        for variant in bridge_variants_for(caller, callee, bridge_variant)
    ]


def summarize(values: list[int]) -> dict[str, int]:
    return {
        "min": min(values),
        "mean": round(statistics.fmean(values)),
        "median": round(statistics.median(values)),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def benchmark_matrix(*, iterations: int, warmup: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for caller in supported_languages():
        for callee in supported_languages():
            results.extend(benchmark_edge(caller, callee, iterations=iterations, warmup=warmup))
    return results


def benchmark_fanout(caller: str, *, iterations: int, warmup: int) -> list[dict[str, Any]]:
    validate_language(caller)
    results: list[dict[str, Any]] = []
    for callee in supported_languages():
        results.extend(benchmark_edge(caller, callee, iterations=iterations, warmup=warmup))
    return results


def benchmark_chain(raw_edges: str, *, iterations: int, warmup: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for caller, callee in parse_edges(raw_edges):
        results.extend(benchmark_edge(caller, callee, iterations=iterations, warmup=warmup))
    return results


def print_table(results: list[dict[str, Any]]) -> None:
    headers = [
        "caller",
        "callee",
        "bridge",
        "iters",
        "call_mean_ns",
        "call_p95_ns",
        "total_mean_ns",
        "total_p95_ns",
    ]
    rows = [
        [
            item["caller"],
            item["callee"],
            item["bridge"],
            str(item["iterations"]),
            str(item["call_duration_ns"]["mean"]),
            str(item["call_duration_ns"]["p95"]),
            str(item["total_duration_ns"]["mean"]),
            str(item["total_duration_ns"]["p95"]),
        ]
        for item in results
    ]
    widths = [max(len(headers[index]), *(len(row[index]) for row in rows)) for index in range(len(headers))]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Xello cross-language call edges.")
    parser.add_argument("--json", action="store_true", help="print structured JSON output")
    parser.add_argument(
        "--iterations",
        type=positive_int,
        default=DEFAULT_ITERATIONS,
        help=f"measured calls per edge, default {DEFAULT_ITERATIONS}",
    )
    parser.add_argument(
        "--warmup",
        type=non_negative_int,
        default=DEFAULT_WARMUP,
        help=f"unmeasured warmup calls per edge, default {DEFAULT_WARMUP}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("matrix", help="benchmark every caller/callee pair")

    fanout_parser = subparsers.add_parser("fanout", help="benchmark one caller against every callee")
    fanout_parser.add_argument("caller")

    call_parser = subparsers.add_parser("call", help="benchmark one caller/callee edge")
    call_parser.add_argument("caller")
    call_parser.add_argument("callee")
    call_parser.add_argument(
        "--bridge",
        choices=("pyo3", "capi"),
        help="optional bridge variant for callers that expose multiple implementations",
    )

    chain_parser = subparsers.add_parser("chain", help="benchmark selected caller/callee edges")
    chain_parser.add_argument("--edges", required=True, help="comma-separated caller:callee edges")

    args = parser.parse_args()

    try:
        if args.command == "matrix":
            results = benchmark_matrix(iterations=args.iterations, warmup=args.warmup)
        elif args.command == "fanout":
            results = benchmark_fanout(args.caller, iterations=args.iterations, warmup=args.warmup)
        elif args.command == "call":
            results = benchmark_edge(
                args.caller,
                args.callee,
                iterations=args.iterations,
                warmup=args.warmup,
                bridge_variant=args.bridge,
            )
        elif args.command == "chain":
            results = benchmark_chain(args.edges, iterations=args.iterations, warmup=args.warmup)
        else:
            parser.error(f"unsupported command: {args.command}")
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
