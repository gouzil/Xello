#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shlex
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
LANGUAGE_ORDER = ("python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm", "moonbit")


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


def pybind11_config_args(*args: str) -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pybind11", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout.split()


def python_extension_link_flags() -> list[str]:
    return ["-undefined", "dynamic_lookup"] if platform.system() == "Darwin" else []


def parse_requested_languages(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    languages = {item.strip().lower() for item in raw.split(",") if item.strip()}
    if not languages:
        raise SystemExit("--languages requires at least one language")
    unknown = sorted(languages - set(LANGUAGE_ORDER))
    if unknown:
        raise SystemExit(f"unknown language(s): {', '.join(unknown)}")
    return languages


def build_moonbit_vm(moon: str, moon_home: Path, backend: str) -> None:
    require("node")
    if importlib.util.find_spec("py_mini_racer") is None:
        raise SystemExit("MoonBit VM backends require: python3 -m pip install -r requirements-moonbit.txt")
    node = subprocess.run(["node", "-p", "process.execPath"], check=True, capture_output=True, text=True).stdout.strip()
    version = subprocess.run(
        ["node", "-p", "process.versions.node.split('.')[0]"], check=True, capture_output=True, text=True
    )
    if int(version.stdout) < 22:
        raise SystemExit("MoonBit VM backends require Node.js 22 or later (including Wasm GC support)")
    headers = next(
        (
            path
            for path in (
                Path(node).resolve().parent.parent / "include/node",
                Path("/usr/include/node"),
                Path("/usr/local/include/node"),
            )
            if (path / "node_api.h").is_file()
        ),
        None,
    )
    if headers is None:
        raise SystemExit("MoonBit VM backends require Node-API headers alongside Node.js")
    if not (moon_home / f"lib/core/_build/{backend}/release/bundle/prelude/prelude.mi").is_file():
        run([moon, "bundle", "--target", backend], cwd=moon_home / "lib/core")
    target = CACHE_DIR / f"moonbit-{backend}"
    run(
        [
            moon,
            "build",
            "--target",
            backend,
            "--release",
            "--deny-warn",
            "--target-dir",
            str(target),
            "providers/moonbit",
            "runners/moonbit",
        ]
    )
    suffix = "cjs" if backend == "js" else "wasm"
    generated_suffix = "js" if backend == "js" else "wasm"
    for directory, kind in (("providers", "provider"), ("runners", "runner")):
        source = target / f"{backend}/release/build/{directory}/moonbit/moonbit.{generated_suffix}"
        shutil.copy2(source, LIB_DIR / f"xello_moonbit_{kind}_{backend}.{suffix}")
    run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-I",
            str(headers),
            str(ROOT / "runners/moonbit/node_bridge.c"),
            *python_extension_link_flags(),
            *c_dlopen_link_flags(),
            "-o",
            str(LIB_DIR / "xello_moonbit_node.node"),
        ]
    )
    run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-I",
            str(ROOT / "include"),
            str(ROOT / "providers/moonbit/vm_shim.c"),
            f'-DXELLO_MOONBIT_BACKEND="{backend}"',
            *python_config_args("--includes"),
            *python_config_args("--embed", "--ldflags"),
            *c_dlopen_link_flags(),
            "-o",
            str(LIB_DIR / f"libxello_moonbit{shared_ext()}"),
        ]
    )
    runner = BIN_DIR / exe("xello_moonbit")
    runner.write_text(
        f'#!/bin/sh\nexec node {shlex.quote(str(ROOT / "runners/moonbit/vm_host.cjs"))} {backend} "$@"\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Xello language artifacts.")
    parser.add_argument(
        "--languages",
        help="comma-separated language subset to build; omitted builds every available language",
    )
    parser.add_argument(
        "--moonbit-backend",
        choices=("c", "native", "js", "wasm", "wasm-gc"),
        default=os.environ.get("MOONBIT_BACKEND") or ("native" if os.environ.get("MOONBIT_NEW_NATIVE") == "1" else "c"),
        help="MoonBit code generator (also settable with MOONBIT_BACKEND)",
    )
    args = parser.parse_args()
    requested_languages = parse_requested_languages(args.languages)
    if args.moonbit_backend not in ("c", "native", "js", "wasm", "wasm-gc"):
        parser.error(f"invalid MoonBit backend: {args.moonbit_backend}")

    LIB_DIR.mkdir(parents=True, exist_ok=True)
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "go-build").mkdir(parents=True, exist_ok=True)

    ext = shared_ext()
    include = str(ROOT / "include")
    go_env = {"GOCACHE": str(CACHE_DIR / "go-build")}
    cargo_env = {"CARGO_TARGET_DIR": str(CACHE_DIR / "rust-target")}
    zig_env = {
        "ZIG_GLOBAL_CACHE_DIR": str(CACHE_DIR / "zig-global-cache"),
        "ZIG_LOCAL_CACHE_DIR": str(CACHE_DIR / "zig-local-cache"),
    }
    built_languages: set[str] = set()
    planned_languages: dict[str, str] = {}
    c_provider_object = CACHE_DIR / "xello_c_provider.o"
    c_provider_object_built = False

    def selected(language: str) -> bool:
        return requested_languages is None or language in requested_languages

    def mark_built(language: str) -> None:
        built_languages.add(language)

    def mark_unavailable(language: str, reason: str) -> None:
        if requested_languages is not None:
            raise SystemExit(f"{language} build required but unavailable: {reason}")
        planned_languages[language] = reason

    def ensure_c_provider_object() -> None:
        nonlocal c_provider_object_built
        if c_provider_object_built:
            return
        require("cc")
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
        c_provider_object_built = True

    def ensure_pybind11_available() -> None:
        try:
            pybind11_config_args("--includes")
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise SystemExit("pybind11 is required to build cpp") from exc

    if selected("python"):
        require("cc")
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
        mark_built("python")

    if selected("c"):
        require("cc")
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
        ensure_c_provider_object()
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
        mark_built("c")

    if selected("cpp"):
        if shutil.which("c++"):
            ensure_pybind11_available()
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
            ensure_c_provider_object()
            run(
                [
                    "c++",
                    "-I",
                    include,
                    str(ROOT / "runners/cpp/xello_cpp.cpp"),
                    str(c_provider_object),
                    "-o",
                    str(BIN_DIR / exe("xello_cpp")),
                    *pybind11_config_args("--includes"),
                    *python_config_args("--embed", "--ldflags"),
                    *c_dlopen_link_flags(),
                ]
            )
            ext_suffix = sysconfig.get_config_var("EXT_SUFFIX")
            if not ext_suffix:
                raise SystemExit("Python EXT_SUFFIX is not available")
            run(
                [
                    "c++",
                    "-O3",
                    "-shared",
                    "-std=c++17",
                    "-fPIC",
                    str(ROOT / "bindings/cpp_python/xello_cpp_pybind.cpp"),
                    "-o",
                    str(LIB_DIR / f"xello_cpp_pybind{ext_suffix}"),
                    *pybind11_config_args("--includes"),
                    *python_extension_link_flags(),
                ]
            )
            mark_built("cpp")
        else:
            mark_unavailable("cpp", "skipped: c++ compiler not found")

    if selected("go"):
        require("go")
        run(
            [
                "go",
                "build",
                "-buildmode=c-shared",
                "-o",
                str(LIB_DIR / f"libxello_go{ext}"),
                str(ROOT / "providers/go/xello_go.go"),
                *([str(ROOT / "providers/go/runtime_darwin.go")] if platform.system() == "Darwin" else []),
            ],
            env=go_env,
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
        mark_built("go")

    if selected("rust"):
        require("rustc")
        require("cargo")
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
        mark_built("rust")

    if selected("zig"):
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
                ],
                env=zig_env,
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
                ],
                env=zig_env,
            )
            if zig_provider_built and zig_runner_built:
                mark_built("zig")
            elif zig_provider_built:
                mark_unavailable("zig", "provider built: runner build failed")
            else:
                mark_unavailable("zig", "skipped: zig build failed")
        else:
            mark_unavailable("zig", "skipped: zig compiler not found")

    if selected("kotlin_native"):
        if shutil.which("kotlinc-native"):
            require("cc")
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
                    # Keep Kotlin runtime state alive across provider load/unload cycles.
                    *(["-Wl,-z,nodelete"] if platform.system() == "Linux" else []),
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
                mark_built("kotlin_native")
            elif kotlin_provider_built and kotlin_shim_built:
                mark_unavailable("kotlin_native", "provider built: runner build failed")
            elif kotlin_provider_built:
                mark_unavailable("kotlin_native", "raw provider built: C ABI shim build failed")
            else:
                mark_unavailable("kotlin_native", "skipped: kotlin/native build failed")
        else:
            mark_unavailable("kotlin_native", "skipped: kotlinc-native not found")

    if selected("wasm"):
        if shutil.which("wasm-tools"):
            require("cc")
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
                mark_built("wasm")
            elif wasm_provider_built:
                mark_unavailable("wasm", "provider built: runner missing")
            else:
                mark_unavailable("wasm", "skipped: WebAssembly C ABI shim build failed")
        else:
            mark_unavailable("wasm", "skipped: wasm-tools not found")

    if selected("moonbit"):
        moon = shutil.which("moon")
        if moon and shutil.which("moonc"):
            require("cc")
            moon_home = Path(os.environ.get("MOON_HOME") or Path(moon).resolve().parent.parent)
            if args.moonbit_backend in ("js", "wasm", "wasm-gc"):
                build_moonbit_vm(moon, moon_home, args.moonbit_backend)
            else:
                backend = args.moonbit_backend
                moon_target = CACHE_DIR / f"moonbit-{backend}"
                run(
                    [
                        moon,
                        "build",
                        "--target",
                        "native",
                        "--debug" if backend == "native" else "--release",
                        "--deny-warn",
                        "--target-dir",
                        str(moon_target),
                        "providers/moonbit",
                        "runners/moonbit",
                    ],
                    env={"MOONBIT_NEW_NATIVE": "1" if backend == "native" else "0"},
                )
                mode = "debug" if backend == "native" else "release"
                native_build = moon_target / f"native/{mode}/build"
                provider_build = native_build / "providers/moonbit"
                generated = (
                    provider_build / "__moonbit_link_core__/moonbit.o"
                    if backend == "native"
                    else provider_build / "moonbit.c"
                )
                if not generated.is_file():
                    raise SystemExit(
                        f"MoonBit {backend} backend did not generate {generated}; this platform may be unsupported"
                    )
                if platform.system() == "Darwin":
                    export_flags = ["-Wl,-exported_symbol,_xello_hello", "-Wl,-exported_symbol,_xello_language"]
                else:
                    exports = moon_target / "exports.map"
                    exports.write_text("{ global: xello_hello; xello_language; local: *; };\n", encoding="utf-8")
                    export_flags = [f"-Wl,--version-script={exports}"]
                runtime = moon_home / "lib/runtime"
                # Compile runtime sources as PIC and hide them to isolate each loaded provider.
                run(
                    [
                        "cc",
                        "-shared",
                        "-fPIC",
                        "-fvisibility=hidden",
                        "-O2",
                        "-fwrapv",
                        "-fno-strict-aliasing",
                        "-I",
                        include,
                        "-I",
                        str(moon_home / "include"),
                        str(ROOT / "providers/moonbit/xello_moonbit.c"),
                        str(generated),
                        *(str(runtime / name) for name in ("runtime.c", "utf.c", "env.c", "backtrace.c")),
                        "-lm",
                        *c_dlopen_link_flags(),
                        *export_flags,
                        "-o",
                        str(LIB_DIR / f"libxello_moonbit{ext}"),
                    ]
                )
                shutil.copy2(native_build / "runners/moonbit/moonbit.exe", BIN_DIR / exe("xello_moonbit"))
            mark_built("moonbit")
        else:
            mark_unavailable("moonbit", "skipped: moon and moonc are required (install the MoonBit toolchain)")

    MANIFEST.write_text(
        json.dumps(
            {
                "languages": [language for language in LANGUAGE_ORDER if language in built_languages],
                "planned_languages": planned_languages,
                **({"moonbit_backend": args.moonbit_backend} if "moonbit" in built_languages else {}),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
