#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
LIB_DIR = BUILD / "lib"
BIN_DIR = BUILD / "bin"
CACHE_DIR = BUILD / "cache"


def run(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args))
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    subprocess.run(args, cwd=cwd or ROOT, check=True, env=command_env)


def require(command: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"required command not found: {command}")


def shared_ext() -> str:
    return ".dylib" if platform.system() == "Darwin" else ".so"


def exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def c_dlopen_link_flags() -> list[str]:
    return [] if platform.system() == "Darwin" else ["-ldl"]


def rust_dlopen_link_flags() -> list[str]:
    return [] if platform.system() == "Darwin" else ["-l", "dl"]


def pyo3_env(base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    if platform.system() == "Darwin":
        existing = os.environ.get("RUSTFLAGS", "")
        dynamic_lookup = "-C link-arg=-undefined -C link-arg=dynamic_lookup"
        env["RUSTFLAGS"] = f"{existing} {dynamic_lookup}".strip()
    return env


def python_config_args(*args: str) -> list[str]:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    raw_candidates = [
        Path(sysconfig.get_config_var("BINDIR") or "") / f"python{version}-config",
        Path(sysconfig.get_config_var("BINDIR") or "") / "python3-config",
    ]
    for command in (shutil.which(f"python{version}-config"), shutil.which("python3-config")):
        if command:
            raw_candidates.append(Path(command))
    candidates = [path for path in raw_candidates if str(path) not in ("", ".")]
    command = next((str(path) for path in candidates if str(path) and path.exists()), None)
    if command is not None:
        completed = subprocess.run(
            [command, *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        return completed.stdout.split()

    if args == ("--includes",):
        include_dir = sysconfig.get_path("include")
        if include_dir and (Path(include_dir) / "Python.h").exists():
            return [f"-I{include_dir}"]
    if args == ("--embed", "--ldflags"):
        libdir = sysconfig.get_config_var("LIBDIR")
        ldlib = sysconfig.get_config_var("LDLIBRARY") or ""
        library = ldlib.removeprefix("lib").removesuffix(".so").removesuffix(".a").removesuffix(".dylib")
        flags: list[str] = []
        if libdir:
            flags.append(f"-L{libdir}")
        if library:
            flags.append(f"-l{library}")
        flags.extend((sysconfig.get_config_var("LIBS") or "").split())
        flags.extend((sysconfig.get_config_var("SYSLIBS") or "").split())
        if flags:
            return flags

    raise SystemExit("required Python development headers/link flags are not available")


def main() -> None:
    for command in ("cc", "go", "rustc"):
        require(command)

    LIB_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "go-build").mkdir(parents=True, exist_ok=True)

    ext = shared_ext()
    include = str(ROOT / "include")
    go_env = {"GOCACHE": str(CACHE_DIR / "go-build")}
    cargo_env = {"CARGO_TARGET_DIR": str(CACHE_DIR / "rust-target")}

    run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-I",
            include,
            str(ROOT / "providers/c/xello_c.c"),
            "-o",
            str(LIB_DIR / f"libxello_c{ext}"),
        ]
    )

    run(
        [
            "go",
            "build",
            "-buildmode=c-shared",
            "-o",
            str(LIB_DIR / f"libxello_go{ext}"),
            str(ROOT / "providers/go/xello_go.go"),
        ],
        env=go_env,
    )

    run(
        [
            "rustc",
            "--crate-type",
            "cdylib",
            str(ROOT / "providers/rust/xello_rust.rs"),
            "-o",
            str(LIB_DIR / f"libxello_rust{ext}"),
        ]
    )

    run(
        [
            "cc",
            str(ROOT / "hosts/c/xello_c_host.c"),
            "-o",
            str(BIN_DIR / exe("xello_c_host")),
            *c_dlopen_link_flags(),
        ]
    )

    run(
        [
            "go",
            "build",
            "-o",
            str(BIN_DIR / exe("xello_go_host")),
            str(ROOT / "hosts/go/xello_go_host.go"),
        ],
        env=go_env,
    )

    run(
        [
            "rustc",
            str(ROOT / "hosts/rust/xello_rust_host.rs"),
            "-o",
            str(BIN_DIR / exe("xello_rust_host")),
            *rust_dlopen_link_flags(),
        ]
    )

    run(
        [
            "cc",
            str(ROOT / "runners/c/xello_c.c"),
            "-o",
            str(BIN_DIR / exe("xello_c")),
            *python_config_args("--includes"),
            *python_config_args("--embed", "--ldflags"),
            *c_dlopen_link_flags(),
        ]
    )

    run(
        [
            "go",
            "build",
            "-o",
            str(BIN_DIR / exe("xello_go")),
            str(ROOT / "runners/go/xello_go.go"),
        ],
        env=go_env,
    )

    run(
        [
            "cargo",
            "build",
            "--manifest-path",
            str(ROOT / "runners/rust/Cargo.toml"),
        ],
        env=cargo_env,
    )
    rust_runner = CACHE_DIR / "rust-target" / "debug" / exe("xello_rust_runner")
    shutil.copy2(rust_runner, BIN_DIR / exe("xello_rust"))

    run(
        [
            "cargo",
            "build",
            "--manifest-path",
            str(ROOT / "bindings/rust_python/Cargo.toml"),
        ],
        env=pyo3_env(cargo_env),
    )
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not ext_suffix:
        raise SystemExit("Python EXT_SUFFIX is not available")
    rust_py_lib = CACHE_DIR / "rust-target" / "debug" / f"libxello_rust_py{shared_ext()}"
    shutil.copy2(rust_py_lib, LIB_DIR / f"xello_rust_py{ext_suffix}")


if __name__ == "__main__":
    main()
