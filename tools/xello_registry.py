from __future__ import annotations

import json
import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
BIN_DIR = BUILD / "bin"
LIB_DIR = BUILD / "lib"

LANGUAGES = ("python", "c", "go", "rust")

BRIDGE_KIND = {
    ("python", "python"): "python direct import",
    ("python", "c"): "ctypes standard library",
    ("python", "go"): "ctypes C ABI fallback",
    ("python", "rust"): "PyO3",
    ("c", "python"): "Python/C API",
    ("c", "c"): "direct C function",
    ("c", "go"): "cgo C ABI fallback",
    ("c", "rust"): "C ABI fallback",
    ("go", "python"): "os/exec Python runner",
    ("go", "c"): "cgo C ABI fallback",
    ("go", "go"): "direct Go function",
    ("go", "rust"): "cgo C ABI fallback",
    ("rust", "python"): "std::process Python runner",
    ("rust", "c"): "libloading crate",
    ("rust", "go"): "libloading crate over C ABI fallback",
    ("rust", "rust"): "direct Rust function",
}

FALLBACK_BRIDGE_KIND = {
    ("python", "go"),
    ("c", "go"),
    ("c", "rust"),
    ("go", "c"),
    ("go", "rust"),
    ("rust", "go"),
}


def shared_ext() -> str:
    return ".dylib" if platform.system() == "Darwin" else ".so"


def exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def runner_path(language: str) -> Path:
    if language == "python":
        return ROOT / "runners/python/xello_python.py"
    return BIN_DIR / exe(f"xello_{language}")


def provider_path(language: str) -> Path:
    return LIB_DIR / f"libxello_{language}{shared_ext()}"


def python_extension_suffix() -> str:
    import sysconfig

    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not suffix:
        raise RuntimeError("Python EXT_SUFFIX is not available")
    return suffix


def rust_python_module_path() -> Path:
    return LIB_DIR / f"xello_rust_py{python_extension_suffix()}"


def validate_language(language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"unknown language: {language}")


def parse_edges(raw: str) -> list[tuple[str, str]]:
    edges: list[tuple[str, str]] = []
    for item in raw.split(","):
        edge = item.strip()
        if not edge:
            continue
        parts = edge.split(":")
        if len(parts) != 2:
            raise ValueError(f"invalid chain edge {edge!r}; expected caller:callee")
        caller, callee = (part.strip().lower() for part in parts)
        validate_language(caller)
        validate_language(callee)
        edges.append((caller, callee))
    if not edges:
        raise ValueError("chain requires at least one caller:callee edge")
    return edges


def result(caller: str, callee: str, bridge: str, duration_ns: int, message: str) -> dict[str, object]:
    return {
        "caller": caller,
        "callee": callee,
        "bridge": bridge,
        "duration_ns": max(int(duration_ns), 1),
        "message": message,
        "output": f"{caller} runner -> {callee} implementation via {bridge}: {message}",
    }


def print_results(results: list[dict[str, object]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return
    for item in results:
        print(f"{item['output']} (duration_ns={item['duration_ns']})")
