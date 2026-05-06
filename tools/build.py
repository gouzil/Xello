#!/usr/bin/env python3
from __future__ import annotations

import json
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
MANIFEST = BUILD / "xello_languages.json"


def run(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args))
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    subprocess.run(args, cwd=cwd or ROOT, check=True, env=command_env)


def try_run(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> bool:
    try:
        run(args, cwd=cwd, env=env)
    except subprocess.CalledProcessError:
        return False
    return True


def require(command: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"required command not found: {command}")


def shared_ext() -> str:
    return ".dylib" if platform.system() == "Darwin" else ".so"


def exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def kotlin_native_exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else f"{name}.kexe"


def c_dlopen_link_flags() -> list[str]:
    return [] if platform.system() == "Darwin" else ["-ldl"]


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
    raw_candidates.extend(
        Path(command)
        for command in (shutil.which(f"python{version}-config"), shutil.which("python3-config"))
        if command
    )
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
    languages = ["python", "c", "go", "rust"]
    planned_languages: dict[str, str] = {}

    run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-I",
            include,
            str(ROOT / "providers/python/xello_python.c"),
            "-o",
            str(LIB_DIR / f"libxello_python{ext}"),
            *python_config_args("--includes"),
            *python_config_args("--embed", "--ldflags"),
        ]
    )

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
    c_provider_object = CACHE_DIR / "xello_c_provider.o"
    run(
        [
            "cc",
            "-fPIC",
            "-I",
            include,
            "-c",
            str(ROOT / "providers/c/xello_c.c"),
            "-o",
            str(c_provider_object),
        ]
    )

    if shutil.which("c++"):
        run(
            [
                "c++",
                "-shared",
                "-fPIC",
                "-I",
                include,
                str(ROOT / "providers/cpp/xello_cpp.cpp"),
                "-o",
                str(LIB_DIR / f"libxello_cpp{ext}"),
            ]
        )
    else:
        planned_languages["cpp"] = "skipped: c++ compiler not found"

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

    if shutil.which("c++"):
        run(
            [
                "c++",
                "-I",
                include,
                str(ROOT / "runners/cpp/xello_cpp.cpp"),
                str(c_provider_object),
                "-o",
                str(BIN_DIR / exe("xello_cpp")),
                *c_dlopen_link_flags(),
            ]
        )
        languages.append("cpp")

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

    if shutil.which("zig"):
        zig_provider_built = try_run(
            [
                "zig",
                "build-lib",
                "-dynamic",
                "-O",
                "ReleaseSafe",
                str(ROOT / "providers/zig/xello_zig.zig"),
                "-femit-bin=" + str(LIB_DIR / f"libxello_zig{ext}"),
            ]
        )
        zig_runner_built = try_run(
            [
                "zig",
                "build-exe",
                "-lc",
                "-O",
                "ReleaseSafe",
                str(ROOT / "runners/zig/xello_zig.zig"),
                "-femit-bin=" + str(BIN_DIR / exe("xello_zig")),
            ]
        )
        if zig_provider_built and zig_runner_built:
            languages.append("zig")
        elif zig_provider_built:
            planned_languages["zig"] = "provider built: runner build failed"
        else:
            planned_languages["zig"] = "skipped: zig build failed"
    else:
        planned_languages["zig"] = "skipped: zig compiler not found"

    if shutil.which("kotlinc-native"):
        kotlin_raw_dir = LIB_DIR / "kotlin_native"
        kotlin_raw_dir.mkdir(parents=True, exist_ok=True)
        kotlin_raw_base = kotlin_raw_dir / "libxello_kotlin_native_raw"
        kotlin_provider_built = try_run(
            [
                "kotlinc-native",
                str(ROOT / "providers/kotlin_native/xello_kotlin.kt"),
                "-produce",
                "dynamic",
                "-o",
                str(kotlin_raw_base),
            ]
        )
        kotlin_shim_built = kotlin_provider_built and try_run(
            [
                "cc",
                "-shared",
                "-fPIC",
                "-I",
                include,
                "-I",
                str(kotlin_raw_dir),
                str(ROOT / "providers/kotlin_native/xello_kotlin_shim.c"),
                "-L",
                str(kotlin_raw_dir),
                "-lxello_kotlin_native_raw",
                *(
                    ["-Wl,-rpath,@loader_path/kotlin_native"]
                    if platform.system() == "Darwin"
                    else ["-Wl,-rpath,$ORIGIN/kotlin_native"]
                ),
                "-o",
                str(LIB_DIR / f"libxello_kotlin_native{ext}"),
            ]
        )
        kotlin_runner_built = try_run(
            [
                "kotlinc-native",
                str(ROOT / "runners/kotlin_native/xello_kotlin_runner.kt"),
                "-o",
                str(BIN_DIR / "xello_kotlin_native"),
            ]
        )
        if kotlin_provider_built and kotlin_shim_built and kotlin_runner_built:
            languages.append("kotlin_native")
        elif kotlin_provider_built and kotlin_shim_built:
            planned_languages["kotlin_native"] = "provider built: runner build failed"
        elif kotlin_provider_built:
            planned_languages["kotlin_native"] = "raw provider built: C ABI shim build failed"
        else:
            planned_languages["kotlin_native"] = "skipped: kotlin/native build failed"
    else:
        planned_languages["kotlin_native"] = "skipped: kotlinc-native not found"

    if shutil.which("wasm-tools"):
        run(
            [
                "wasm-tools",
                "parse",
                str(ROOT / "providers/wasm/xello_wasm.wat"),
                "-o",
                str(LIB_DIR / "xello_wasm.wasm"),
            ]
        )
        wasm_runner_available = (ROOT / "runners/wasm/xello_wasm.py").exists()
        wasm_provider_built = try_run(
            [
                "cc",
                "-shared",
                "-fPIC",
                "-I",
                include,
                str(ROOT / "providers/wasm/xello_wasm.c"),
                "-o",
                str(LIB_DIR / f"libxello_wasm{ext}"),
            ]
        )
        if wasm_provider_built and wasm_runner_available:
            languages.append("wasm")
        elif wasm_provider_built:
            planned_languages["wasm"] = "provider built: runner missing"
        else:
            planned_languages["wasm"] = "skipped: WebAssembly C ABI shim build failed"
    else:
        planned_languages["wasm"] = "skipped: wasm-tools not found"

    MANIFEST.write_text(
        json.dumps(
            {
                "languages": languages,
                "planned_languages": planned_languages,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
