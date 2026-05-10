# Xello

[中文 README](README.zh-CN.md) | [Usage](docs/usage.md) | [Chinese usage](docs/usage.zh-CN.md) | [Contribution guide in Chinese](CONTRIBUTING.zh-CN.md)

Xello is a cross-language Hello World matrix. Every supported language is a real entrypoint, and every supported language can be the callee.

The project is intentionally result-oriented:

- Each language has its own runner.
- The built language set is manifest-driven through `build/xello_languages.json`.
- Direct calls, fanout, selected chains, and full matrices all report structured edge results.
- Every edge result includes `caller`, `callee`, `bridge`, `message`, `output`, and positive `duration_ns`.
- Benchmark output records both in-runner bridge timing and benchmark harness subprocess timing.

## Current Matrix

The full Docker toolchain is designed to build these first-class languages:

| Language | Runner | Provider route |
| --- | --- | --- |
| Python | `runners/python/xello_python.py` | Python direct import, `ctypes`, PyO3 extension, or C ABI providers |
| C | `build/bin/xello_c` | Native C runner and C provider |
| C++ | `build/bin/xello_cpp` | Native C++ runner/provider, C ABI provider, and `extern "C"` C-provider variant |
| Go | `build/bin/xello_go` | Native Go runner/provider over cgo/C ABI |
| Rust | `build/bin/xello_rust` | Native Rust runner/provider, PyO3 embedded Python, and `libloading` |
| Zig | `build/bin/xello_zig` | Native Zig runner/provider over C ABI |
| Kotlin/Native | `build/bin/xello_kotlin_native.kexe` | Native Kotlin/Native runner plus C ABI shim |
| WebAssembly | `runners/wasm/xello_wasm.py` | WAT module, WebAssembly runtime host, and C ABI shim |

The Docker benchmark image builds the full matrix. In the snapshot below, `build/xello_languages.json` contains all eight languages and `planned_languages` is empty, so the benchmark includes Zig, Kotlin/Native, and WebAssembly even when the host machine does not have those optional toolchains installed.

## Result Shape

Human output:

```text
python runner -> rust implementation via PyO3: hello world from rust implementation, called by python (duration_ns=...)
```

JSON output includes the same data in a scriptable form:

```json
{
  "bridge": "PyO3",
  "callee": "rust",
  "caller": "python",
  "duration_ns": 910452,
  "message": "hello world from rust implementation, called by python",
  "output": "python runner -> rust implementation via PyO3: hello world from rust implementation, called by python"
}
```

## Bridge Results

Xello prefers mature language bridges over handwritten FFI. C ABI is kept as the fallback boundary when a direct mature bridge is not practical for this compact matrix.

| Edge | Bridge selected |
| --- | --- |
| `python -> rust` | PyO3 extension module |
| `rust -> python` | PyO3 embedded Python by default, with Python/C API provider also benchmarkable |
| `python -> c` | Python `ctypes` standard library |
| `c -> python` | Python/C API |
| `go/cpp -> python` | Python provider shared library using Python/C API |
| `rust -> c` | Rust `libloading` crate |
| `go -> c` | cgo over C ABI |
| `cpp -> c` | `dlopen` over C ABI by default, with direct `extern "C"` provider variant |
| `python/c/go/rust/cpp -> cpp` | C++ provider exposing C ABI |
| `python/c/go/rust/cpp -> zig` | Zig provider exposing C ABI |
| `python/c/go/rust/cpp -> kotlin_native` | Kotlin/Native provider exposed through a C ABI shim |
| `python/c/go/rust/cpp -> wasm` | WebAssembly provider exposed through a C ABI shim |

## Benchmark Snapshot

Snapshot command:

```sh
docker build -t xello .
docker run --rm xello python3 tools/benchmark.py --iterations 10 --warmup 1 matrix
```

Container environment: Linux x86_64, Python 3.11.15, Go 1.26.3, Rust 1.95.0, Zig 0.16.0, Kotlin/Native 1.9.24, wasm-tools 1.246.2. Measured on 2026-05-09 from the Docker image after the full toolchain build. On an arm64 host, Docker may run this linux/amd64 image through emulation, so these numbers are best read as a complete, reproducible Docker matrix snapshot rather than universal performance claims.

| Caller | Callee | Bridge | call mean | call p95 | total mean |
| --- | --- | --- | ---: | ---: | ---: |
| `python` | `python` | python direct import | 17,767 ns | 42,375 ns | 117.29 ms |
| `c` | `c` | direct C function | 355,598 ns | 385,539 ns | 10.10 ms |
| `go` | `go` | direct Go function | 79,245 ns | 168,665 ns | 29.83 ms |
| `rust` | `rust` | direct Rust function | 201,282 ns | 265,623 ns | 15.09 ms |
| `cpp` | `cpp` | direct C++ function | 552,213 ns | 588,704 ns | 10.50 ms |
| `zig` | `zig` | direct Zig function | 261,631 ns | 274,331 ns | 10.51 ms |
| `kotlin_native` | `kotlin_native` | direct Kotlin/Native function | 110,624 ns | 132,124 ns | 16.28 ms |
| `wasm` | `wasm` | WebAssembly runtime host | 12,967 ns | 15,792 ns | 116.20 ms |
| `python` | `rust` | PyO3 | 910,452 ns | 1,004,244 ns | 121.35 ms |
| `rust` | `python` | PyO3 embedded Python | 337,460 ns | 365,123 ns | 67.11 ms |
| `rust` | `python` | Python shared library via Python/C API | 52.04 ms | 53.39 ms | 68.83 ms |
| `cpp` | `c` | C shared library via C ABI | 377,152 ns | 393,122 ns | 11.83 ms |
| `cpp` | `c` | C provider linked through `extern "C"` | 518,313 ns | 543,789 ns | 10.89 ms |
| `python` | `zig` | Zig shared library via C ABI | 609,655 ns | 720,996 ns | 113.97 ms |
| `c` | `kotlin_native` | Kotlin/Native dynamic library via C ABI | 2.31 ms | 2.55 ms | 17.65 ms |
| `go` | `wasm` | WebAssembly C ABI shim | 340,194 ns | 367,748 ns | 29.91 ms |
| `kotlin_native` | `cpp` | C++ shared library via C ABI | 227,565 ns | 250,956 ns | 20.08 ms |
| `wasm` | `kotlin_native` | kotlin_native shared library via C ABI | 2.60 ms | 2.81 ms | 119.04 ms |

`call mean` and `call p95` are measured inside the caller around the language bridge call. `total mean` is the benchmark harness subprocess round trip.

Full matrix, fanout, Docker, JSON, and bridge-variant benchmark commands are in [Usage](docs/usage.md).

## Technical Direction

When adding languages, Xello prioritizes targets that can reliably produce native executables, shared libraries, or a clear cross-platform bytecode/runtime artifact. The deciding factor is not language popularity; it is whether CI can build the target repeatably, whether the target exposes a clear call boundary, and whether it composes with the runner/provider matrix.

| Language/target | Current route | Boundary |
| --- | --- | --- |
| C++ | Implemented native runner/provider | Provider exposes C ABI; runner also includes direct C `extern "C"` variant |
| Zig | Implemented optional native runner/provider | Enters the matrix when `zig` is installed |
| Kotlin/Native | Implemented optional native runner/provider | Enters the matrix when `kotlinc-native` is installed |
| WebAssembly | Implemented optional WAT module, C ABI shim, and Python runtime runner | Enters the matrix when `wasm-tools` is installed |
| Java/Kotlin JVM/C#/.NET/Dart/Swift/Objective-C/Lua | Possible with explicit runtime or platform boundaries | Needs target-specific build/runtime policy before becoming first-class |
| Ruby/PHP/R/Julia/Assembly | Not first-class for now | Runtime, packaging, or architecture-specific constraints make them poor generic matrix targets |
