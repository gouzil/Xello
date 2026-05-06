from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.xello_registry import load_runtime_manifest, supported_languages


def languages() -> tuple[str, ...]:
    return supported_languages()


def optional_languages() -> tuple[str, ...]:
    return tuple(language for language in ("zig", "kotlin_native", "wasm") if language in languages())


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def run_make(target: str, **variables: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(variables)
    return subprocess.run(
        ["make", target],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


class XelloTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run_command([sys.executable, "tools/build.py"])

    def test_matrix_contains_every_caller_callee_pair(self) -> None:
        completed = run_command([sys.executable, "tools/xello.py", "--json", "matrix"])
        results = json.loads(completed.stdout)
        current_languages = languages()

        expected = {(caller, callee) for caller in current_languages for callee in current_languages}
        actual = {(item["caller"], item["callee"]) for item in results}

        self.assertEqual(expected, actual)
        self.assertEqual(len(current_languages) * len(current_languages), len(results))
        for item in results:
            self.assertIsInstance(item["duration_ns"], int)
            self.assertGreater(item["duration_ns"], 0)
            self.assertIn("bridge", item)
            self.assertNotIn("planned", item["bridge"].lower())
            self.assertIn("hello world", item["output"])
            self.assertIn(f"{item['caller']} runner", item["output"])
            self.assertIn(f"{item['callee']} implementation", item["output"])
            self.assertIn(f"called by {item['caller']}", item["output"])

        bridge_by_edge = {(item["caller"], item["callee"]): item["bridge"] for item in results}
        self.assertEqual("PyO3", bridge_by_edge[("python", "rust")])
        self.assertEqual("Python/C API", bridge_by_edge[("c", "python")])
        self.assertEqual("Python shared library via Python/C API", bridge_by_edge[("go", "python")])
        self.assertEqual("PyO3 embedded Python", bridge_by_edge[("rust", "python")])
        self.assertEqual("libloading crate", bridge_by_edge[("rust", "c")])
        if "cpp" in current_languages:
            self.assertEqual("Python shared library via Python/C API", bridge_by_edge[("cpp", "python")])
            self.assertEqual("direct C++ function", bridge_by_edge[("cpp", "cpp")])
            self.assertEqual("C++ shared library via C ABI", bridge_by_edge[("python", "cpp")])
        if "zig" in current_languages:
            self.assertEqual("Zig shared library via C ABI", bridge_by_edge[("python", "zig")])
            self.assertEqual("direct Zig function", bridge_by_edge[("zig", "zig")])
        if "kotlin_native" in current_languages:
            self.assertEqual(
                "Kotlin/Native dynamic library via C ABI",
                bridge_by_edge[("python", "kotlin_native")],
            )
            self.assertEqual("direct Kotlin/Native function", bridge_by_edge[("kotlin_native", "kotlin_native")])
        if "wasm" in current_languages:
            self.assertEqual("WebAssembly C ABI shim", bridge_by_edge[("python", "wasm")])
            self.assertEqual("WebAssembly runtime host", bridge_by_edge[("wasm", "wasm")])
        for item in results:
            self.assertNotIn("exec", item["bridge"].lower())
            self.assertNotIn("std::process", item["bridge"])

    def test_priority_cross_compile_languages_are_reported(self) -> None:
        manifest = load_runtime_manifest()
        current_languages = set(manifest["languages"])
        planned_languages = manifest["planned_languages"]

        self.assertIn("cpp", current_languages)
        for language in ("zig", "kotlin_native", "wasm"):
            self.assertTrue(
                language in current_languages or language in planned_languages,
                f"{language} should either be built or reported as planned/skipped",
            )

    def test_priority_cross_compile_runner_sources_exist(self) -> None:
        self.assertTrue((ROOT / "runners/cpp/xello_cpp.cpp").exists())
        self.assertTrue((ROOT / "runners/zig/xello_zig.zig").exists())
        self.assertTrue((ROOT / "runners/kotlin_native/xello_kotlin_runner.kt").exists())
        self.assertTrue((ROOT / "runners/wasm/xello_wasm.py").exists())

    def test_makefile_and_readmes_cover_supported_language_examples(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        readmes = {
            "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
            "README.zh-CN.md": (ROOT / "README.zh-CN.md").read_text(encoding="utf-8"),
        }

        for language in languages():
            with self.subTest(language=language, file="Makefile"):
                self.assertRegex(makefile, rf"(?m)^{re.escape(language)}: build$")
                expected_runner = (
                    "runners/python/xello_python.py chain"
                    if language == "python"
                    else "runners/wasm/xello_wasm.py chain"
                    if language == "wasm"
                    else "./build/bin/xello_kotlin_native.kexe chain"
                    if language == "kotlin_native"
                    else f"./build/bin/xello_{language} chain"
                )
                self.assertIn(expected_runner, makefile)

            for name, content in readmes.items():
                with self.subTest(language=language, file=name):
                    self.assertIn(f"make matrix-from RUNNER={language}", content)
                    self.assertIn(f"make benchmark-from FROM={language}", content)
                    self.assertIn(f"python3 tools/benchmark.py fanout {language}", content)
                    expected_runner = (
                        "python3 runners/python/xello_python.py"
                        if language == "python"
                        else "python3 runners/wasm/xello_wasm.py"
                        if language == "wasm"
                        else "./build/bin/xello_kotlin_native.kexe"
                        if language == "kotlin_native"
                        else f"./build/bin/xello_{language}"
                    )
                    self.assertIn(expected_runner, content)

    def test_chain_runs_only_selected_edges_in_order(self) -> None:
        completed = run_command(
            [
                sys.executable,
                "tools/xello.py",
                "--json",
                "chain",
                "--edges",
                "python:c,c:rust,rust:go",
            ]
        )
        results = json.loads(completed.stdout)

        self.assertEqual(
            [
                ("python", "c"),
                ("c", "rust"),
                ("rust", "go"),
            ],
            [(item["caller"], item["callee"]) for item in results],
        )
        self.assertTrue(all("hello world" in item["output"] for item in results))
        self.assertTrue(all(isinstance(item["duration_ns"], int) for item in results))

    def test_chain_can_start_from_any_runner(self) -> None:
        chain = "c:python,python:rust,rust:go,go:c"
        for runner in languages():
            with self.subTest(runner=runner):
                completed = run_command(
                    [
                        sys.executable,
                        "tools/run_from.py",
                        runner,
                        "--json",
                        "chain",
                        "--edges",
                        chain,
                    ]
                )
                results = json.loads(completed.stdout)
                self.assertEqual(
                    [
                        ("c", "python"),
                        ("python", "rust"),
                        ("rust", "go"),
                        ("go", "c"),
                    ],
                    [(item["caller"], item["callee"]) for item in results],
                )

    def test_human_chain_can_start_from_any_runner(self) -> None:
        chain = "c:python,python:rust,rust:go,go:c"
        for runner in languages():
            with self.subTest(runner=runner):
                completed = run_command(
                    [
                        sys.executable,
                        "tools/run_from.py",
                        runner,
                        "chain",
                        "--edges",
                        chain,
                    ]
                )
                self.assertEqual(4, completed.stdout.count("duration_ns="))
                self.assertIn("c runner -> python implementation", completed.stdout)
                self.assertIn("python runner -> rust implementation via PyO3", completed.stdout)
                self.assertIn("rust runner -> go implementation", completed.stdout)
                self.assertIn("go runner -> c implementation", completed.stdout)
                self.assertNotIn("chain requires at least one caller:callee edge", completed.stderr)

    def test_make_chain_from_c_regression(self) -> None:
        completed = run_make(
            "chain-from",
            RUNNER="c",
            CHAIN="c:python,python:rust,rust:go,go:c",
        )

        self.assertEqual(4, completed.stdout.count("duration_ns="))
        self.assertIn("c runner -> python implementation", completed.stdout)
        self.assertIn("python runner -> rust implementation via PyO3", completed.stdout)
        self.assertIn("rust runner -> go implementation", completed.stdout)
        self.assertIn("go runner -> c implementation", completed.stdout)
        self.assertNotIn("chain requires at least one caller:callee edge", completed.stderr)

    def test_each_runner_can_directly_call_each_language(self) -> None:
        for runner in languages():
            for callee in languages():
                with self.subTest(runner=runner, callee=callee):
                    completed = run_command(
                        [
                            sys.executable,
                            "tools/run_from.py",
                            runner,
                            "--json",
                            "call",
                            callee,
                        ]
                    )
                    results = json.loads(completed.stdout)
                    self.assertEqual([(runner, callee)], [(item["caller"], item["callee"]) for item in results])
                    self.assertIn("bridge", results[0])
                    self.assertGreater(results[0]["duration_ns"], 0)

    def test_rust_python_bridge_variants_are_available(self) -> None:
        default_completed = run_command(
            [
                str(ROOT / "build/bin/xello_rust"),
                "--json",
                "call",
                "python",
            ]
        )
        default_results = json.loads(default_completed.stdout)
        self.assertEqual("PyO3 embedded Python", default_results[0]["bridge"])

        capi_completed = run_command(
            [
                str(ROOT / "build/bin/xello_rust"),
                "--json",
                "call",
                "--bridge",
                "capi",
                "python",
            ]
        )
        capi_results = json.loads(capi_completed.stdout)
        self.assertEqual("Python shared library via Python/C API", capi_results[0]["bridge"])

    def test_cpp_c_bridge_variants_are_available(self) -> None:
        default_completed = run_command(
            [
                str(ROOT / "build/bin/xello_cpp"),
                "--json",
                "call",
                "c",
            ]
        )
        default_results = json.loads(default_completed.stdout)
        self.assertEqual("C shared library via C ABI", default_results[0]["bridge"])

        extern_c_completed = run_command(
            [
                str(ROOT / "build/bin/xello_cpp"),
                "--json",
                "call",
                "--bridge",
                "extern-c",
                "c",
            ]
        )
        extern_c_results = json.loads(extern_c_completed.stdout)
        self.assertEqual('C provider linked through extern "C"', extern_c_results[0]["bridge"])
        self.assertIn("called by cpp", extern_c_results[0]["message"])

    def test_fanout_runs_one_language_to_all_supported_languages(self) -> None:
        for caller in languages():
            with self.subTest(caller=caller):
                completed = run_command(
                    [
                        sys.executable,
                        "tools/xello.py",
                        "--json",
                        "fanout",
                        caller,
                    ]
                )
                results = json.loads(completed.stdout)
                self.assertEqual(
                    [(caller, callee) for callee in languages()],
                    [(item["caller"], item["callee"]) for item in results],
                )
                self.assertTrue(all(item["duration_ns"] > 0 for item in results))

    def test_fanout_can_be_started_from_any_runner(self) -> None:
        for runner in languages():
            for caller in languages():
                with self.subTest(runner=runner, caller=caller):
                    completed = run_command(
                        [
                            sys.executable,
                            "tools/run_from.py",
                            runner,
                            "--json",
                            "fanout",
                            caller,
                        ]
                    )
                    results = json.loads(completed.stdout)
                    self.assertEqual(
                        [(caller, callee) for callee in languages()],
                        [(item["caller"], item["callee"]) for item in results],
                    )

    def test_human_fanout_and_make_fanout(self) -> None:
        completed = run_make("fanout", FROM="c")
        self.assertEqual(len(languages()), completed.stdout.count("duration_ns="))
        self.assertIn("c runner -> python implementation", completed.stdout)
        self.assertIn("c runner -> c implementation", completed.stdout)
        self.assertIn("c runner -> go implementation", completed.stdout)
        self.assertIn("c runner -> rust implementation", completed.stdout)
        if "cpp" in languages():
            self.assertIn("c runner -> cpp implementation", completed.stdout)

        completed_from = run_make("fanout-from", RUNNER="rust", FROM="go")
        self.assertEqual(len(languages()), completed_from.stdout.count("duration_ns="))
        self.assertIn("go runner -> python implementation", completed_from.stdout)
        self.assertIn("go runner -> c implementation", completed_from.stdout)
        self.assertIn("go runner -> go implementation", completed_from.stdout)
        self.assertIn("go runner -> rust implementation", completed_from.stdout)
        if "cpp" in languages():
            self.assertIn("go runner -> cpp implementation", completed_from.stdout)

    def test_text_output_shows_call_duration(self) -> None:
        completed = run_command(
            [
                sys.executable,
                "tools/xello.py",
                "chain",
                "--edges",
                "python:c",
            ]
        )

        self.assertIn("python runner -> c implementation", completed.stdout)
        self.assertIn("duration_ns=", completed.stdout)

    def test_invalid_chain_edge_is_rejected(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/xello.py", "chain", "--edges", "python:java"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(2, completed.returncode)
        self.assertIn("unknown language: java", completed.stderr)

    def test_benchmark_call_reports_call_and_total_durations(self) -> None:
        completed = run_command(
            [
                sys.executable,
                "tools/benchmark.py",
                "--json",
                "--iterations",
                "2",
                "--warmup",
                "0",
                "call",
                "python",
                "rust",
            ]
        )
        results = json.loads(completed.stdout)

        self.assertEqual(1, len(results))
        item = results[0]
        self.assertEqual(("python", "rust"), (item["caller"], item["callee"]))
        self.assertEqual("PyO3", item["bridge"])
        self.assertEqual(2, item["iterations"])
        for key in ("call_duration_ns", "total_duration_ns"):
            self.assertEqual({"min", "mean", "median", "p95", "max"}, set(item[key]))
            self.assertGreater(item[key]["min"], 0)
            self.assertGreaterEqual(item[key]["max"], item[key]["min"])

    def test_benchmark_expands_bridge_variants_by_default(self) -> None:
        completed = run_command(
            [
                sys.executable,
                "tools/benchmark.py",
                "--json",
                "--iterations",
                "1",
                "--warmup",
                "0",
                "call",
                "rust",
                "python",
            ]
        )
        results = json.loads(completed.stdout)
        self.assertEqual(
            ["PyO3 embedded Python", "Python shared library via Python/C API"],
            [item["bridge"] for item in results],
        )

        capi_completed = run_command(
            [
                sys.executable,
                "tools/benchmark.py",
                "--json",
                "--iterations",
                "1",
                "--warmup",
                "0",
                "call",
                "rust",
                "python",
                "--bridge",
                "capi",
            ]
        )
        capi_results = json.loads(capi_completed.stdout)
        self.assertEqual(1, len(capi_results))
        self.assertEqual("Python shared library via Python/C API", capi_results[0]["bridge"])

    def test_benchmark_expands_cpp_c_bridge_variants_by_default(self) -> None:
        completed = run_command(
            [
                sys.executable,
                "tools/benchmark.py",
                "--json",
                "--iterations",
                "1",
                "--warmup",
                "0",
                "call",
                "cpp",
                "c",
            ]
        )
        results = json.loads(completed.stdout)
        self.assertEqual(
            ["C shared library via C ABI", 'C provider linked through extern "C"'],
            [item["bridge"] for item in results],
        )

        extern_c_completed = run_command(
            [
                sys.executable,
                "tools/benchmark.py",
                "--json",
                "--iterations",
                "1",
                "--warmup",
                "0",
                "call",
                "cpp",
                "c",
                "--bridge",
                "extern-c",
            ]
        )
        extern_c_results = json.loads(extern_c_completed.stdout)
        self.assertEqual(1, len(extern_c_results))
        self.assertEqual('C provider linked through extern "C"', extern_c_results[0]["bridge"])

    def test_benchmark_fanout_table_covers_one_caller(self) -> None:
        completed = run_command(
            [
                sys.executable,
                "tools/benchmark.py",
                "--iterations",
                "1",
                "--warmup",
                "0",
                "fanout",
                "c",
            ]
        )

        self.assertIn("caller", completed.stdout)
        self.assertIn("call_mean_ns", completed.stdout)
        self.assertIn("total_mean_ns", completed.stdout)
        self.assertEqual(len(languages()), completed.stdout.count("\nc"))

    def test_make_benchmark_from_runs_one_language_to_all_supported_languages(self) -> None:
        completed = run_make(
            "benchmark-from",
            FROM="go",
            BENCH_ARGS="--iterations 1 --warmup 0",
        )

        self.assertIn("caller", completed.stdout)
        self.assertIn("go", completed.stdout)
        self.assertEqual(len(languages()), completed.stdout.count("\ngo"))

        if "cpp" in languages():
            completed_cpp = run_make(
                "benchmark-from",
                FROM="cpp",
                BENCH_ARGS="--iterations 1 --warmup 0",
            )
            self.assertIn("caller", completed_cpp.stdout)
            self.assertIn("cpp", completed_cpp.stdout)
            self.assertEqual(len(languages()) + 1, completed_cpp.stdout.count("\ncpp"))

        for language in optional_languages():
            with self.subTest(language=language):
                completed_optional = run_make(
                    "benchmark-from",
                    FROM=language,
                    BENCH_ARGS="--iterations 1 --warmup 0",
                )
                self.assertIn("caller", completed_optional.stdout)
                self.assertIn(language, completed_optional.stdout)
                self.assertEqual(len(languages()), completed_optional.stdout.count(f"\n{language}"))


if __name__ == "__main__":
    unittest.main()
