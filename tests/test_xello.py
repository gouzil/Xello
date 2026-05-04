from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def run_make(target: str, **variables: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(variables)
    return subprocess.run(
        ["make", target],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


class XelloTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run_command([sys.executable, "tools/build.py"])

    def test_matrix_contains_every_caller_callee_pair(self) -> None:
        completed = run_command([sys.executable, "tools/xello.py", "--json", "matrix"])
        results = json.loads(completed.stdout)

        expected = {
            (caller, callee)
            for caller in ("python", "c", "go", "rust")
            for callee in ("python", "c", "go", "rust")
        }
        actual = {(item["caller"], item["callee"]) for item in results}

        self.assertEqual(expected, actual)
        self.assertEqual(16, len(results))
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
        self.assertEqual("libloading crate", bridge_by_edge[("rust", "c")])

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
        for runner in ("python", "c", "go", "rust"):
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
        for runner in ("python", "c", "go", "rust"):
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
        for runner in ("python", "c", "go", "rust"):
            for callee in ("python", "c", "go", "rust"):
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

    def test_fanout_runs_one_language_to_all_supported_languages(self) -> None:
        for caller in ("python", "c", "go", "rust"):
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
                    [(caller, callee) for callee in ("python", "c", "go", "rust")],
                    [(item["caller"], item["callee"]) for item in results],
                )
                self.assertTrue(all(item["duration_ns"] > 0 for item in results))

    def test_fanout_can_be_started_from_any_runner(self) -> None:
        for runner in ("python", "c", "go", "rust"):
            for caller in ("python", "c", "go", "rust"):
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
                        [(caller, callee) for callee in ("python", "c", "go", "rust")],
                        [(item["caller"], item["callee"]) for item in results],
                    )

    def test_human_fanout_and_make_fanout(self) -> None:
        completed = run_make("fanout", FROM="c")
        self.assertEqual(4, completed.stdout.count("duration_ns="))
        self.assertIn("c runner -> python implementation", completed.stdout)
        self.assertIn("c runner -> c implementation", completed.stdout)
        self.assertIn("c runner -> go implementation", completed.stdout)
        self.assertIn("c runner -> rust implementation", completed.stdout)

        completed_from = run_make("fanout-from", RUNNER="rust", FROM="go")
        self.assertEqual(4, completed_from.stdout.count("duration_ns="))
        self.assertIn("go runner -> python implementation", completed_from.stdout)
        self.assertIn("go runner -> c implementation", completed_from.stdout)
        self.assertIn("go runner -> go implementation", completed_from.stdout)
        self.assertIn("go runner -> rust implementation", completed_from.stdout)

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
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(2, completed.returncode)
        self.assertIn("unknown language: java", completed.stderr)


if __name__ == "__main__":
    unittest.main()
