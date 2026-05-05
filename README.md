# Xello

[中文 README](README.zh-CN.md)

[Contribution guide in Chinese](CONTRIBUTING.zh-CN.md)

Xello is a cross-language Hello World matrix where every supported language can be the entrypoint and every supported language can be the callee.

The current language set is:

- Python
- C
- C++
- Go
- Rust
- Zig
- Kotlin/Native
- WebAssembly

Each language has a runner. A runner can execute one direct call, one caller fanning out to every supported callee, a selected chain, or the full matrix:

```sh
make matrix
make fanout FROM=c
make chain CHAIN=c:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:wasm,wasm:c
make fanout-from RUNNER=rust FROM=go
make fanout-from RUNNER=cpp FROM=rust
make fanout-from RUNNER=zig FROM=kotlin_native
make chain-from RUNNER=wasm CHAIN=wasm:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:c
```

The chain format is a comma-separated list of `caller:callee` edges. Each edge is executed by that edge's caller runner, so a chain can start from C, C++, Go, Rust, Python, Zig, Kotlin/Native, or WebAssembly without requiring Python to be the only real entrypoint.

The fanout command is the fast path for "one language to all supported languages". For example, `make fanout FROM=c` runs `c -> python`, `c -> c`, `c -> cpp`, `c -> go`, `c -> rust`, `c -> zig`, `c -> kotlin_native`, and `c -> wasm` when the full toolchain is available.

## Bridge Policy

Xello prefers mature language bridges over hand-written FFI. C ABI is kept as the fallback bridge when a direct mature bridge is not practical for this small demo.

Examples in the current matrix:

- `python -> rust`: PyO3 extension module.
- `rust -> python`: PyO3 embedded Python.
- `python -> c`: Python `ctypes` standard library.
- `c -> python`: Python/C API.
- `go/cpp -> python`: Python provider shared library using the Python/C API.
- `rust -> c`: Rust `libloading` crate.
- `go -> c`: cgo over the C ABI.
- `cpp -> c/go/rust/zig/kotlin_native/wasm`: C++ `dlopen` over C ABI.
- `python/c/go/rust/cpp -> cpp`: C++ provider exposing C ABI.
- `python/c/cpp/go/rust -> zig`: Zig provider exposing C ABI.
- `python/c/cpp/go/rust -> kotlin_native`: Kotlin/Native provider exposing C ABI.
- `python/c/cpp/go/rust -> wasm`: WebAssembly provider exposed through the C ABI shim.
- `go -> rust`, `rust -> go`, `python -> go`, `c -> rust`, `c -> go`: C ABI fallback.

Every result includes the selected bridge, caller, callee, hello message, and measured call duration:

```text
python runner -> rust implementation via PyO3: hello world from rust implementation, called by python (duration_ns=...)
```

For structured timing and bridge data:

```sh
python3 tools/xello.py --json matrix
```

## Technical Roadmap

When adding more languages, Xello prioritizes languages that can reliably produce native executables, shared libraries, or a clear cross-platform bytecode/runtime artifact. The criterion is not language popularity; it is whether CI can build it repeatably, whether it exposes a clear call boundary, and whether it composes with the runner/provider matrix.

Priority targets:

| Language/target | Route | Notes |
| --- | --- | --- |
| C++ | Native runner/provider is implemented | The provider exposes C ABI; the runner calls other providers through `dlopen`. |
| Zig | Native runner/provider is implemented | Installing `zig` lets both artifacts enter the matrix. |
| Kotlin/Native | Native runner/provider is implemented | Installing `kotlinc-native` lets both artifacts enter the matrix. |
| WebAssembly | WAT module plus C ABI shim and Python runtime runner are implemented | Installing `wasm-tools` lets the module and shim enter the matrix. |

After building, inspect the actual matrix language set and skipped optional languages:

```sh
cat build/xello_languages.json
```

Supported with explicit boundaries:

| Language/target | Route | Boundary |
| --- | --- | --- |
| Java | JVM bytecode / GraalVM Native Image | JVM bytecode is portable; Native Image has stronger cross-build limits. |
| Kotlin/JVM | JVM bytecode | Same as Java; runtime depends on the JVM. |
| C#/.NET | .NET runtime / Native AOT | Native AOT can cover some cross-arch cases; cross-OS usually needs target OS runners. |
| Dart | `dart compile exe` | Good for executables; not a general shared-provider route. |
| JavaScript / Node.js | Node SEA / Bun / Deno compile | More like packaging a runtime plus JS than producing a traditional native library. |
| TypeScript | TS -> JS -> Node/Bun/Deno | Must compile to JavaScript before using the JS runtime packaging route. |
| Swift | Swift toolchain | Possible across platforms; Apple targets strongly depend on macOS/Xcode. |
| Objective-C | Clang + ObjC runtime | Syntax is cross-compiled by Clang, but Foundation/Cocoa and ObjC runtime support are platform-bound. |
| Lua | Embedded Lua runtime | Lua scripts are not native cross-compiled; this fits an embedded-runtime route. |

Not first-class cross-compilation targets for now:

| Language/target | Reason |
| --- | --- |
| Ruby | Usually depends on the Ruby runtime; mruby or extensions are possible, but not a general stable route. |
| PHP | Runtime embedding is possible, but native cross-platform providers are high-cost. |
| R | Mostly runtime/package-ecosystem driven; not a good native provider target. |
| Julia | PackageCompiler can produce apps/libraries, but cross-platform delivery usually still needs target-platform builds. |
| Assembly | Source is architecture-specific; support must be maintained per target architecture rather than as a generic language layer. |

## Entrypoints

Build everything:

```sh
make build
```

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

Direct runner examples:

```sh
python3 runners/python/xello_python.py call cpp
python3 runners/python/xello_python.py fanout c
./build/bin/xello_c call python
./build/bin/xello_c fanout cpp
./build/bin/xello_cpp call python
./build/bin/xello_cpp fanout rust
./build/bin/xello_go fanout rust
./build/bin/xello_go call c
./build/bin/xello_rust call go
./build/bin/xello_rust call cpp
./build/bin/xello_zig call kotlin_native
./build/bin/xello_kotlin_native.kexe call wasm
python3 runners/wasm/xello_wasm.py fanout zig
```

## Tests

```sh
make test
```

The tests verify:

- The full caller/callee matrix for the languages built on the current machine.
- Fanout from one caller to every supported callee.
- Chains can be started through any built runner.
- Every runner can directly call every language.
- Per-edge duration is present.
- Important mature bridge selections, including `python -> rust` via PyO3.

## Benchmark

Benchmark every caller/callee edge:

```sh
make benchmark
```

Benchmark one caller against all supported callees:

```sh
make benchmark-from FROM=c BENCH_ARGS="--iterations 50 --warmup 5"
```

The benchmark commands use `build/xello_languages.json`, so the full matrix and fanout modes include every language that was actually built. With the Docker toolchain, the language-specific fanout benchmarks are:

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

The equivalent Make targets are:

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

Languages reported under `planned_languages` in `build/xello_languages.json` are intentionally not included in benchmark output. Use the Docker image when your local machine does not have the optional Zig, Kotlin/Native, or WebAssembly toolchains installed.

Benchmark output includes two duration groups:

- `call_duration_ns`: the duration reported by the caller runner around the language bridge call.
- `total_duration_ns`: the full subprocess round-trip used by the benchmark harness.

When an edge has multiple bridge implementations, benchmark output includes every implementation by default. Use `--bridge` only when you want to narrow the output to one implementation.

Use JSON output when comparing results in scripts:

```sh
python3 tools/benchmark.py --json --iterations 50 matrix
python3 tools/benchmark.py --json call python rust
python3 tools/benchmark.py chain --edges "c:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:wasm,wasm:c"
```

Rust calling Python currently exposes both PyO3 embedding and the Python/C API provider. The default benchmark prints both:

```sh
python3 tools/benchmark.py call rust python
```

Use `--bridge` to show only one implementation:

```sh
python3 tools/benchmark.py call rust python --bridge pyo3
python3 tools/benchmark.py call rust python --bridge capi
```

## Formatting

Xello uses [`prek`](https://github.com/j178/prek) for formatting and basic file hygiene:

```sh
prek install
make fmt
```

The current hooks format Python, C/C++/Objective-C, Go, and Rust files in this repo. The config also includes formatter entries for Zig, JavaScript/Node.js, TypeScript, Java, Kotlin/JVM, Kotlin/Native, C#/.NET, Swift, Dart, Ruby, PHP, Lua, R, Julia, Assembly, and WebAssembly text files; those hooks are skipped until matching files exist.

Configured formatter tools:

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

## Docker

```sh
docker build -t xello .
docker run --rm xello make test
docker run --rm xello make fanout FROM=c
docker run --rm xello make benchmark-from FROM=zig BENCH_ARGS="--iterations 5 --warmup 1"
docker run --rm xello make chain-from RUNNER=wasm CHAIN=wasm:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:c
```

## Project Layout

- `runners/*`: language entrypoints.
- `bindings/rust_python`: PyO3 Python extension for Python calling Rust.
- `providers/*`: C ABI provider fallback libraries.
- `build/xello_languages.json`: generated manifest for the actual built language set.
- `include/xello.h`: shared fallback ABI.
- `tools/build.py`: builds shared libraries, runners, and bindings.
- `tools/xello.py`: compatibility entrypoint for the Python runner.
- `tools/run_from.py`: runner selection helper.
- `tests/test_xello.py`: matrix, chain, bridge, and timing tests.
