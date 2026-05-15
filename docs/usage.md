# Xello Usage

[README](../README.md) | [中文使用方式](usage.zh-CN.md)

This guide contains the operational commands. The README focuses on the implemented matrix, bridge results, and benchmark snapshot.

## Build And Test

```sh
make build
make test
```

`make build` writes the actual built language set to `build/xello_languages.json`. Full matrix and benchmark commands use that manifest, so optional languages are included only when their toolchains are available.

Inspect the built and skipped language set:

```sh
cat build/xello_languages.json
```

## Matrix, Fanout, And Chains

Run from the default Python runner:

```sh
make matrix
make fanout FROM=c
make chain CHAIN=python:c,c:rust,rust:go,go:python
```

Run from a specific language runner:

```sh
make matrix-from RUNNER=python
make matrix-from RUNNER=c
make matrix-from RUNNER=cpp
make matrix-from RUNNER=go
make matrix-from RUNNER=rust
make matrix-from RUNNER=zig
make matrix-from RUNNER=kotlin_native
make matrix-from RUNNER=wasm
make fanout-from RUNNER=cpp FROM=rust
make fanout-from RUNNER=rust FROM=go
make fanout-from RUNNER=zig FROM=kotlin_native
make chain-from RUNNER=wasm CHAIN=wasm:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:c
```

The chain format is a comma-separated list of `caller:callee` edges. The selected entrypoint executes the listed edges through in-process provider functions instead of starting another runner executable for each hop, so a chain can start from any built language without making Python the hidden orchestrator.

Chain output includes every selected edge in order. Human output prefixes each edge with `step=N`, and JSON output includes the same `step` field beside that edge's `duration_ns`.

## Direct Runners

```sh
python3 runners/python/xello_python.py call cpp
python3 runners/python/xello_python.py fanout c
./build/bin/xello_c call python
./build/bin/xello_c fanout cpp
./build/bin/xello_cpp call python
./build/bin/xello_cpp call c
./build/bin/xello_cpp fanout rust
./build/bin/xello_go call rust
./build/bin/xello_go fanout rust
./build/bin/xello_rust call go
./build/bin/xello_rust call cpp
./build/bin/xello_zig call kotlin_native
./build/bin/xello_kotlin_native.kexe call wasm
python3 runners/wasm/xello_wasm.py fanout zig
```

Use JSON output when a script needs structured results:

```sh
python3 tools/xello.py --json matrix
python3 tools/run_from.py rust --json chain --edges "rust:python,python:c,c:go"
```

## Benchmark

Benchmark every caller/callee edge in the built manifest:

```sh
make benchmark
```

Benchmark one caller against all supported callees:

```sh
make benchmark-from FROM=c BENCH_ARGS="--iterations 50 --warmup 5"
```

The same fanout benchmark can be run directly:

```sh
python3 tools/benchmark.py fanout python
python3 tools/benchmark.py fanout c
python3 tools/benchmark.py fanout cpp
python3 tools/benchmark.py fanout go
python3 tools/benchmark.py fanout rust
python3 tools/benchmark.py fanout zig
python3 tools/benchmark.py fanout kotlin_native
python3 tools/benchmark.py fanout wasm
```

Equivalent Make targets:

```sh
make benchmark-from FROM=python
make benchmark-from FROM=c
make benchmark-from FROM=cpp
make benchmark-from FROM=go
make benchmark-from FROM=rust
make benchmark-from FROM=zig
make benchmark-from FROM=kotlin_native
make benchmark-from FROM=wasm
```

Benchmark output includes two duration groups:

- `call_duration_ns`: duration reported by the caller runner around the language bridge call.
- `total_duration_ns`: full subprocess round trip used by the benchmark harness.

For `benchmark.py chain`, each row or JSON item also includes `step`, so every hop's call and subprocess duration summary can be inspected independently.

Use JSON output when comparing results in scripts:

```sh
python3 tools/benchmark.py --json --iterations 50 matrix
python3 tools/benchmark.py --json call python rust
python3 tools/benchmark.py --json chain --edges "c:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:wasm,wasm:c"
```

Some edges intentionally expose multiple bridge implementations. Rust calling Python provides PyO3 embedding and Python/C API provider variants:

```sh
python3 tools/benchmark.py call rust python
python3 tools/benchmark.py call rust python --bridge pyo3
python3 tools/benchmark.py call rust python --bridge capi
```

C++ calling C provides the default `dlopen` path and a direct linked C provider through `extern "C"`:

```sh
python3 tools/benchmark.py call cpp c
python3 tools/benchmark.py call cpp c --bridge dlopen
python3 tools/benchmark.py call cpp c --bridge extern-c
```

## Docker

Docker builds the full toolchain image and is the easiest way to exercise optional Zig, Kotlin/Native, and WebAssembly paths on machines that do not have those tools installed locally.

```sh
docker build -t xello .
docker run --rm xello make test
docker run --rm xello make fanout FROM=c
docker run --rm xello make benchmark-from FROM=zig BENCH_ARGS="--iterations 5 --warmup 1"
docker run --rm xello make chain-from RUNNER=wasm CHAIN=wasm:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:c
```

Repo-native Docker benchmark targets:

```sh
make docker-benchmark
make docker-benchmark BENCH="call python rust" BENCH_ARGS="--iterations 50 --warmup 5"
make docker-benchmark-from FROM=zig BENCH_ARGS="--iterations 50 --warmup 5"
```

To reproduce the README's full Docker snapshot from the image artifacts built by `docker build`, run:

```sh
docker build -t xello .
docker run --rm xello python3 tools/benchmark.py --iterations 10 --warmup 1 matrix
```

## Formatting

Xello uses `prek` for formatting and basic file hygiene:

```sh
prek install
make fmt
```

Configured formatter coverage:

| Language/file family | Formatter |
| --- | --- |
| Python | Ruff |
| C, C++, Objective-C | clang-format |
| Go | gofmt |
| Rust | rustfmt |
| Zig | zig fmt |
| JavaScript, Node.js, TypeScript | Prettier |
| Java | google-java-format |
| Kotlin/JVM, Kotlin/Native | ktfmt |
| C#/.NET | dotnet format |
| Swift | swift-format |
| Dart | dart format |
| Ruby | RuboCop |
| PHP | PHP-CS-Fixer |
| Lua | StyLua |
| R | styler |
| Julia | JuliaFormatter |
| Assembly | asmfmt |
| WebAssembly text | wat-fmt |

Hooks for languages without matching files are skipped.

## Project Layout

- `runners/*`: language entrypoint runners.
- `bindings/rust_python`: PyO3 Python extension for Python calling Rust.
- `providers/*`: provider implementations, mostly exposed through C ABI boundaries.
- `include/xello.h`: shared fallback ABI.
- `build/xello_languages.json`: generated runtime manifest for the actual built language set.
- `tools/build.py`: builds shared libraries, runners, bindings, and the manifest.
- `tools/xello.py`: compatibility entrypoint for the Python runner.
- `tools/run_from.py`: runner selection helper.
- `tools/benchmark.py`: cross-language benchmark harness.
- `tests/test_xello.py`: matrix, chain, bridge, timing, benchmark, and manifest tests.
