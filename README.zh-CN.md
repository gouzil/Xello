# Xello

[English README](README.md)

[贡献指南](CONTRIBUTING.zh-CN.md)

Xello 是一个跨语言 Hello World 调用矩阵。现在的设计不是“只能从 Python 脚本启动”，而是每种语言都有自己的 runner；任意语言都可以作为入口，任意语言也都可以作为被调用方。

当前支持语言：

- Python
- C
- C++
- Go
- Rust
- Zig
- Kotlin/Native
- WebAssembly

每个 runner 都支持直接调用、单个 caller 快速调用所有支持语言、执行自定义链条、执行完整矩阵：

```sh
make matrix
make fanout FROM=c
make chain CHAIN=c:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:wasm,wasm:c
make fanout-from RUNNER=rust FROM=go
make fanout-from RUNNER=cpp FROM=rust
make fanout-from RUNNER=zig FROM=kotlin_native
make chain-from RUNNER=wasm CHAIN=wasm:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:c
```

链条格式是逗号分隔的 `caller:callee`。每条边都会由该边的 caller runner 执行，所以可以从 Python、C、C++、Go、Rust、Zig、Kotlin/Native、WebAssembly 任意语言入口启动。

`fanout` 是“单个语言到所有支持语言”的快速命令。例如工具链完整时，`make fanout FROM=c` 会依次运行 `c -> python`、`c -> c`、`c -> cpp`、`c -> go`、`c -> rust`、`c -> zig`、`c -> kotlin_native`、`c -> wasm`。

## 调用桥接策略

优先使用成熟的语言桥接库；只有没有合适成熟桥接时，才使用 C ABI/FFI 作为兜底。

当前矩阵里的代表性桥接：

- `python -> rust`：PyO3 扩展模块。
- `rust -> python`：PyO3 embedded Python。
- `python -> c`：Python 标准库 `ctypes`。
- `c -> python`：Python/C API。
- `go/cpp -> python`：基于 Python/C API 的 Python provider 动态库。
- `rust -> c`：Rust `libloading` crate。
- `go -> c`：cgo over C ABI。
- `cpp -> c/go/rust/zig/kotlin_native/wasm`：C++ `dlopen` over C ABI。
- `cpp -> c`：可选的 `extern "C"` 声明直连 C provider。
- `python/c/go/rust/cpp -> cpp`：C++ provider 暴露 C ABI。
- `python/c/cpp/go/rust -> zig`：Zig provider 暴露 C ABI。
- `python/c/cpp/go/rust -> kotlin_native`：Kotlin/Native provider 暴露 C ABI。
- `python/c/cpp/go/rust -> wasm`：WebAssembly provider 通过 C ABI shim 暴露。
- `go -> rust`、`rust -> go`、`python -> go`、`c -> rust`、`c -> go`：C ABI 兜底。

每条结果都会包含 caller、callee、bridge、hello world 消息和调用耗时：

```text
python runner -> rust implementation via PyO3: hello world from rust implementation, called by python (duration_ns=...)
```

结构化输出：

```sh
python3 tools/xello.py --json matrix
```

## 技术路线

后续扩展语言时，Xello 会优先选择能稳定产出 native 可执行文件、shared library，或者有明确跨平台 bytecode/runtime 交付模型的语言。判断标准不是“语言是否流行”，而是能否在 CI 中可靠构建、能否暴露清晰调用边界、能否和现有 runner/provider 矩阵组合。

优先支持：

| 语言/目标 | 路线 | 说明 |
| --- | --- | --- |
| C++ | 已接入 native runner/provider | 当前通过 C ABI 暴露 provider，通过 `dlopen` 调用其他 provider。 |
| Zig | 已接入 native runner/provider | 安装 `zig` 后会进入矩阵。 |
| Kotlin/Native | 已接入 native runner/provider | 安装 `kotlinc-native` 后会进入矩阵。 |
| WebAssembly | 已接入 WAT module、C ABI shim 和 Python runtime runner | 安装 `wasm-tools` 后会进入矩阵。 |

构建后可以查看实际进入矩阵的语言和被跳过的可选语言：

```sh
cat build/xello_languages.json
```

可以支持，但需要明确边界：

| 语言/目标 | 路线 | 边界 |
| --- | --- | --- |
| Java | JVM bytecode / GraalVM Native Image | JVM bytecode 跨平台稳定；Native Image 跨平台构建限制更多。 |
| Kotlin/JVM | JVM bytecode | 和 Java 一样，运行依赖 JVM。 |
| C#/.NET | .NET runtime / Native AOT | Native AOT 可以做部分 cross-arch；cross-OS 通常需要目标 OS runner。 |
| Dart | `dart compile exe` | 适合可执行文件；不适合作为通用 shared provider。 |
| JavaScript / Node.js | Node SEA / Bun / Deno compile | 更像打包 runtime + JS，不是传统 native library。 |
| TypeScript | TS -> JS -> Node/Bun/Deno | 需要先转成 JavaScript，再进入 JS runtime 打包链路。 |
| Swift | Swift toolchain | 跨平台可做；Apple 平台强依赖 macOS/Xcode，跨 OS 不如 Zig/Go/Rust 直接。 |
| Objective-C | Clang + ObjC runtime | 语法可编译；Foundation/Cocoa 和 ObjC runtime 强依赖目标平台。 |
| Lua | 嵌入 Lua runtime | Lua 脚本不是 native cross-compile；适合作为嵌入式 runtime 路线。 |

暂不作为交叉编译一等支持：

| 语言/目标 | 原因 |
| --- | --- |
| Ruby | 通常依赖 Ruby runtime；可做 mruby 或扩展交叉编译，但不是通用稳定路线。 |
| PHP | 可嵌入 runtime，但跨平台 native provider 成本高。 |
| R | 主要依赖 R runtime/package 生态，不适合作为 native provider。 |
| Julia | PackageCompiler 可产出 app/library，但跨平台通常仍需要目标平台构建。 |
| Assembly | 源码本身强绑定目标架构；只能按架构分别维护，不能做通用语言层支持。 |

## 入口命令

构建：

```sh
make build
```

默认从 Python runner 运行：

```sh
make matrix
make fanout FROM=c
make chain CHAIN=python:c,c:rust,rust:go,go:python
```

从指定语言 runner 启动：

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

直接调用单个 runner：

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

## 测试

```sh
make test
```

测试覆盖：

- 当前机器已构建语言的完整 caller/callee 矩阵。
- 单个 caller fanout 到所有支持语言。
- 可以通过任意已构建 runner 启动链条。
- 每个 runner 都能直接调用每种语言。
- 每条边都有 `duration_ns` 耗时。
- 关键成熟桥接选择，例如 `python -> rust` 必须走 PyO3。

## Benchmark

跑完整 caller/callee 矩阵的基准：

```sh
make benchmark
```

快速对比单个 caller 到所有支持语言：

```sh
make benchmark-from FROM=c BENCH_ARGS="--iterations 50 --warmup 5"
```

Benchmark 命令会读取 `build/xello_languages.json`，所以完整矩阵和 fanout 模式会包含所有已经实际构建成功的语言。在 Docker 工具链下，按语言拆开的 fanout benchmark 是：

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

等价的 Make 入口是：

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

`build/xello_languages.json` 中出现在 `planned_languages` 里的语言不会进入 benchmark 输出。本机没有 Zig、Kotlin/Native 或 WebAssembly 工具链时，可以直接使用 Docker 镜像跑完整矩阵。

Benchmark 会输出两组耗时：

- `call_duration_ns`：caller runner 在语言桥接调用附近测到的耗时。
- `total_duration_ns`：benchmark harness 调用 runner 子进程的完整往返耗时。

当一条边有多种 bridge 实现时，benchmark 默认会把所有实现都输出出来；只有显式传 `--bridge` 时才收窄到单个实现。

需要脚本处理时可以输出 JSON：

```sh
python3 tools/benchmark.py --json --iterations 50 matrix
python3 tools/benchmark.py --json call python rust
python3 tools/benchmark.py chain --edges "c:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:wasm,wasm:c"
```

Rust 调 Python 当前同时提供 PyO3 embedding 和 Python/C API provider。默认 benchmark 会输出两条：

```sh
python3 tools/benchmark.py call rust python
```

C++ 调 C 当前同时提供默认 `dlopen` 路径和 `extern "C"` 直连 C provider 路径：

```sh
python3 tools/benchmark.py call cpp c
```

只想看单条实现时再使用 `--bridge`：

```sh
python3 tools/benchmark.py call rust python --bridge pyo3
python3 tools/benchmark.py call rust python --bridge capi
python3 tools/benchmark.py call cpp c --bridge dlopen
python3 tools/benchmark.py call cpp c --bridge extern-c
```

## 格式化

Xello 使用 [`prek`](https://github.com/j178/prek) 做格式化和基础文件检查：

```sh
prek install
make fmt
```

当前已有源码会格式化 Python、C/C++/Objective-C、Go、Rust。配置里也预留了 Zig、JavaScript/Node.js、TypeScript、Java、Kotlin/JVM、Kotlin/Native、C#/.NET、Swift、Dart、Ruby、PHP、Lua、R、Julia、Assembly、WebAssembly text 的成熟 formatter 入口；对应文件不存在时这些 hook 会自动跳过。

已配置的 formatter：

| 语言/文件类型 | Formatter |
| --- | --- |
| Python | Ruff |
| C、C++、Objective-C | clang-format |
| Go | gofmt |
| Rust | rustfmt |
| Zig | zig fmt |
| JavaScript、Node.js、TypeScript | Prettier |
| Java | google-java-format |
| Kotlin/JVM、Kotlin/Native | ktfmt |
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

## 项目结构

- `runners/*`：每种语言自己的入口 runner。
- `bindings/rust_python`：Python 调用 Rust 的 PyO3 扩展模块。
- `providers/*`：C ABI 兜底 provider 共享库。
- `build/xello_languages.json`：构建后生成的实际语言 manifest。
- `include/xello.h`：共享兜底 ABI。
- `tools/build.py`：构建共享库、runner 和绑定模块。
- `tools/xello.py`：兼容入口，转到 Python runner。
- `tools/run_from.py`：按语言选择 runner 的辅助入口。
- `tests/test_xello.py`：矩阵、链条、bridge 和耗时测试。
