# Xello

[English README](README.md) | [使用方式](docs/usage.zh-CN.md) | [Usage in English](docs/usage.md) | [贡献指南](CONTRIBUTING.zh-CN.md)

Xello 是一个跨语言 Hello World 调用矩阵。每种支持语言都是实际入口 runner，每种支持语言也都可以作为被调用方。

这个 README 只强调结果：

- 每种语言都有自己的 runner。
- 实际进入矩阵的语言由 `build/xello_languages.json` 记录。
- 直接调用、fanout、自定义链条、完整矩阵都会输出结构化边结果。
- 每条边都有 `caller`、`callee`、`bridge`、`message`、`output` 和正整数 `duration_ns`。
- 聚合的 matrix、fanout、chain 每条边都会在当前进程内调用 provider 函数，而不是再启动另一个 runner 可执行文件。
- Benchmark 同时记录 caller 内部桥接耗时和 benchmark harness 子进程往返耗时。

## 当前矩阵

完整 Docker 工具链目标支持这些一等语言：

| 语言 | Runner | Provider 路线 |
| --- | --- | --- |
| Python | `runners/python/xello_python.py` | Python direct import、`ctypes`、PyO3/pybind11 extension module，或 C ABI provider |
| C | `build/bin/xello_c` | Native C runner 和 C provider |
| C++ | `build/bin/xello_cpp` | Native C++ runner/provider、pybind11 embedded Python、C ABI provider，以及 `extern "C"` C-provider 变体 |
| Go | `build/bin/xello_go` | Native Go runner/provider over cgo/C ABI |
| Rust | `build/bin/xello_rust` | Native Rust runner/provider、PyO3 embedded Python，以及 `libloading` |
| Zig | `build/bin/xello_zig` | Native Zig runner/provider over C ABI |
| Kotlin/Native | `build/bin/xello_kotlin_native.kexe` | Kotlin/Native runner 加 C ABI shim |
| WebAssembly | `runners/wasm/xello_wasm.py` | WAT module、WebAssembly runtime host 和 C ABI shim |

Docker benchmark 镜像会构建完整矩阵。下面快照里的 `build/xello_languages.json` 包含全部 8 种语言，`planned_languages` 为空，所以即使宿主机没有 Zig、Kotlin/Native、WebAssembly 工具链，benchmark 也能覆盖这些可选路径。

## 执行模型

Xello 把 runner 入口和 provider 调用分开：

- Runner 是被选中的入口进程，例如 `build/bin/xello_go` 或 `runners/python/xello_python.py`。
- Provider 是被调用语言的实现，可以暴露为 direct import、native function、shared library symbol、PyO3/pybind11 module，或 runtime shim。
- 直接 `call` 命令会走所选 runner 自己的原生 bridge 路径，只验证一条 caller/callee 边。
- 聚合的 `matrix`、`fanout` 和 `chain` 命令会留在所选 runner 进程内，直接调用 provider 函数。它们不会通过执行另一种语言的 runner 可执行文件来让边成功。

Benchmark harness 仍然会启动所选 runner 进程，用来统计完整命令往返耗时。这部分子进程耗时会和 runner 内部围绕 provider 调用测到的 `duration_ns` 分开报告。

## 结果形状

人类可读输出：

```text
python runner -> rust implementation via PyO3: hello world from rust implementation, called by python (duration_ns=...)
```

链条输出会给每条选中的边加 1-based 步骤号：

```text
step=1 python runner -> c implementation via ctypes standard library: hello world from c implementation, called by python (duration_ns=...)
step=2 c runner -> rust implementation via C ABI fallback: hello world from rust implementation, called by c (duration_ns=...)
```

JSON 输出包含同一组可脚本处理字段：

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

命令为 `chain` 时，每条 JSON 边还会包含 `step`。

## 桥接结果

Xello 优先使用成熟语言桥接库。没有合适成熟桥接时，才使用 C ABI 作为兜底边界。

直接 `call` 命令会使用对应 runner 自己的原生 bridge 路径。聚合命令使用上面的执行模型，所以矩阵证明的是函数级 provider 调用，而不是 runner 到 runner 的进程委托。

| 边 | 已选择桥接 |
| --- | --- |
| `python -> rust` | PyO3 extension module |
| `rust -> python` | 默认 PyO3 embedded Python，也可 benchmark Python/C API provider |
| `python -> cpp` | pybind11 extension module |
| `cpp -> python` | 默认 pybind11 embedded Python，也可 benchmark Python/C API provider |
| `python -> c` | Python `ctypes` 标准库 |
| `c -> python` | Python/C API |
| `go -> python` | 基于 Python/C API 的 Python provider 动态库 |
| `rust -> c` | Rust `libloading` crate |
| `go -> c` | cgo over C ABI |
| `cpp -> c` | 默认 `dlopen` over C ABI，也提供直接 `extern "C"` provider 变体 |
| `python/c/go/rust/cpp -> cpp` | C++ provider 暴露 C ABI |
| `python/c/go/rust/cpp -> zig` | Zig provider 暴露 C ABI |
| `python/c/go/rust/cpp -> kotlin_native` | Kotlin/Native provider 通过 C ABI shim 暴露 |
| `python/c/go/rust/cpp -> wasm` | WebAssembly provider 通过 C ABI shim 暴露 |

## Benchmark 快照

快照命令：

```sh
docker build -t xello .
docker run --rm xello python3 tools/benchmark.py --iterations 10 --warmup 1 matrix
```

容器环境：Linux x86_64，Python 3.11.15，Go 1.26.3，Rust 1.95.0，Zig 0.16.0，Kotlin/Native 1.9.24，wasm-tools 1.246.2，pybind11 3.0.4。测量日期 2026-05-16，使用完整工具链构建后的 Docker 镜像。arm64 宿主机上 Docker 可能会通过 emulation 运行 linux/amd64 镜像，所以这些数字更适合作为完整、可复现的 Docker 矩阵快照，而不是跨机器通用性能承诺。

| Caller | Callee | Bridge | call mean | call p95 | total mean |
| --- | --- | --- | ---: | ---: | ---: |
| `python` | `python` | python direct import | 13,104 ns | 16,500 ns | 106.93 ms |
| `c` | `c` | direct C function | 350,370 ns | 355,342 ns | 9.26 ms |
| `go` | `go` | direct Go function | 70,327 ns | 78,239 ns | 29.28 ms |
| `rust` | `rust` | direct Rust function | 183,813 ns | 187,873 ns | 13.40 ms |
| `cpp` | `cpp` | direct C++ function | 546,674 ns | 576,358 ns | 10.57 ms |
| `zig` | `zig` | direct Zig function | 239,574 ns | 244,292 ns | 10.80 ms |
| `kotlin_native` | `kotlin_native` | direct Kotlin/Native function | 108,301 ns | 115,505 ns | 16.38 ms |
| `wasm` | `wasm` | WebAssembly runtime host | 11,042 ns | 13,324 ns | 103.29 ms |
| `python` | `rust` | PyO3 | 869,192 ns | 916,336 ns | 110.24 ms |
| `python` | `cpp` | pybind11 extension module | 567,910 ns | 579,439 ns | 108.87 ms |
| `rust` | `python` | PyO3 embedded Python | 333,944 ns | 361,338 ns | 66.45 ms |
| `rust` | `python` | Python shared library via Python/C API | 50.78 ms | 54.03 ms | 67.19 ms |
| `cpp` | `python` | pybind11 embedded Python | 273,094 ns | 298,838 ns | 69.07 ms |
| `cpp` | `python` | Python shared library via Python/C API | 50.79 ms | 54.52 ms | 62.81 ms |
| `cpp` | `c` | C shared library via C ABI | 381,366 ns | 386,529 ns | 12.09 ms |
| `cpp` | `c` | C provider linked through `extern "C"` | 486,669 ns | 500,993 ns | 10.60 ms |
| `python` | `zig` | Zig shared library via C ABI | 582,521 ns | 652,681 ns | 104.93 ms |
| `c` | `kotlin_native` | Kotlin/Native dynamic library via C ABI | 2.19 ms | 2.41 ms | 16.63 ms |
| `go` | `wasm` | WebAssembly C ABI shim | 369,332 ns | 434,079 ns | 30.39 ms |
| `kotlin_native` | `cpp` | C++ shared library via C ABI | 221,449 ns | 242,918 ns | 19.99 ms |
| `wasm` | `kotlin_native` | kotlin_native shared library via C ABI | 2.56 ms | 2.87 ms | 110.40 ms |

`call mean` 和 `call p95` 是 caller runner 在语言桥接调用附近测到的耗时。`total mean` 是 benchmark harness 调用 runner 子进程的完整往返耗时。

完整矩阵、fanout、Docker、JSON 和多 bridge 变体 benchmark 命令在 [使用方式](docs/usage.zh-CN.md) 中。

## 技术方向

后续扩展语言时，Xello 优先选择能稳定产出 native 可执行文件、shared library，或者有明确跨平台 bytecode/runtime 交付模型的目标。判断标准不是语言热度，而是能否在 CI 中可靠构建、能否暴露清晰调用边界、能否和 runner/provider 矩阵组合。

| 语言/目标 | 当前路线 | 边界 |
| --- | --- | --- |
| C++ | 已实现 native runner/provider | Provider 暴露 C ABI；runner 也包含直接 C `extern "C"` 变体 |
| Zig | 已实现可选 native runner/provider | 安装 `zig` 后进入矩阵 |
| Kotlin/Native | 已实现可选 native runner/provider | 安装 `kotlinc-native` 后进入矩阵 |
| WebAssembly | 已实现可选 WAT module、C ABI shim 和 Python runtime runner | 安装 `wasm-tools` 后进入矩阵 |
| Java/Kotlin JVM/C#/.NET/Dart/Swift/Objective-C/Lua | 可以支持，但需要明确 runtime 或平台边界 | 成为一等语言前需要先定义目标构建/运行策略 |
| Ruby/PHP/R/Julia/Assembly | 暂不作为一等支持 | runtime、打包或架构绑定问题使它们不适合做通用矩阵目标 |
