# Xello 使用方式

[README](../README.zh-CN.md) | [English usage](usage.md)

这份文档只放操作命令。README 关注已实现矩阵、桥接结果和 benchmark 快照。

## 构建和测试

```sh
make build
make test
```

C++ runner 和 Python extension 会使用 pybind11 头文件。CI 和 Docker 会自动安装；本机构建时，需要把它装进 `PYTHON` 所使用的 Python 环境：

```sh
python3 -m pip install pybind11
```

MoonBit 使用 native C 后端，在 macOS 和 Linux 上同时构建 runner 和 provider。先安装官方工具链并加入 `PATH`（CI 和 Docker 会自动安装）：

```sh
curl --retry 3 -fsSL https://cli.moonbitlang.com/install/unix.sh -o /tmp/install-moonbit.sh
bash /tmp/install-moonbit.sh
export PATH="$HOME/.moon/bin:$PATH"
python3 tools/build.py --languages moonbit
./build/bin/xello_moonbit --json call moonbit
```

已验证 `moon 0.1.20261021` / `moonc 0.10.17`。构建会从官方工具链生成的 C 代码和运行时源码编译共享库，并隐藏运行时符号以隔离 MoonBit runner 与 provider。缺少工具链时，默认构建会在 `planned_languages` 记录原因；显式指定 MoonBit 时会报错。`--languages` 会重写 manifest，恢复完整集合请运行 `make build`。MoonBit 的 JS、Wasm 和 LLVM 后端不在当前矩阵中。

macOS 上的 Go provider 和 Linux 上的 Kotlin/Native provider 会驻留到进程退出，保证矩阵各条边之间的后台运行时线程仍然有效。

`make build` 会把实际构建成功的语言写入 `build/xello_languages.json`。完整矩阵和 benchmark 都读取这个 manifest，所以可选语言只会在工具链可用时进入结果。

查看实际构建和跳过的语言：

```sh
cat build/xello_languages.json
```

## 矩阵、Fanout 和链条

从默认 Python runner 运行：

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
make matrix-from RUNNER=moonbit
make fanout-from RUNNER=cpp FROM=rust
make fanout-from RUNNER=rust FROM=go
make fanout-from RUNNER=zig FROM=kotlin_native
make fanout-from RUNNER=moonbit FROM=moonbit
make chain-from RUNNER=moonbit CHAIN=moonbit:python,python:moonbit,moonbit:c,c:moonbit
make chain-from RUNNER=wasm CHAIN=wasm:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:c
```

链条格式是逗号分隔的 `caller:callee`。选中的入口会在当前进程里通过 provider 函数执行这些边，而不是每一跳再启动另一个 runner 可执行文件，所以链条可以从任意已构建语言开始，也不会让 Python 成为隐藏编排入口。

链条输出会按顺序保留每条选中的边。人类可读输出会在每条边前加 `step=N`，JSON 输出也会在该边的 `duration_ns` 旁边包含同一个 `step` 字段。

## 直接调用 Runner

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
./build/bin/xello_moonbit call python
./build/bin/xello_moonbit call moonbit
./build/bin/xello_c call moonbit
```

脚本处理时使用 JSON 输出：

```sh
python3 tools/xello.py --json matrix
python3 tools/run_from.py rust --json chain --edges "rust:python,python:c,c:go"
```

## Benchmark

跑已构建 manifest 中的完整 caller/callee 矩阵：

```sh
make benchmark
```

快速对比单个 caller 到所有支持 callee：

```sh
make benchmark-from FROM=c BENCH_ARGS="--iterations 50 --warmup 5"
```

也可以直接按语言跑 fanout benchmark：

```sh
python3 tools/benchmark.py fanout python
python3 tools/benchmark.py fanout c
python3 tools/benchmark.py fanout cpp
python3 tools/benchmark.py fanout go
python3 tools/benchmark.py fanout rust
python3 tools/benchmark.py fanout zig
python3 tools/benchmark.py fanout kotlin_native
python3 tools/benchmark.py fanout wasm
python3 tools/benchmark.py fanout moonbit
```

等价 Make 入口：

```sh
make benchmark-from FROM=python
make benchmark-from FROM=c
make benchmark-from FROM=cpp
make benchmark-from FROM=go
make benchmark-from FROM=rust
make benchmark-from FROM=zig
make benchmark-from FROM=kotlin_native
make benchmark-from FROM=wasm
make benchmark-from FROM=moonbit
```

Benchmark 输出两组耗时：

- `call_duration_ns`：caller runner 在语言桥接调用附近测到的耗时。
- `total_duration_ns`：benchmark harness 调用 runner 子进程的完整往返耗时。

`benchmark.py chain` 的每一行或 JSON item 也会包含 `step`，方便单独查看连跳中每一跳的调用耗时和子进程往返耗时汇总。

需要脚本比较时使用 JSON 输出：

```sh
python3 tools/benchmark.py --json --iterations 50 matrix
python3 tools/benchmark.py --json call python rust
python3 tools/benchmark.py --json chain --edges "c:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:wasm,wasm:c"
```

部分边有多个 bridge 实现。Rust 调 Python 同时提供 PyO3 embedding 和 Python/C API provider：

```sh
python3 tools/benchmark.py call rust python
python3 tools/benchmark.py call rust python --bridge pyo3
python3 tools/benchmark.py call rust python --bridge capi
```

C++ 调 Python 同时提供 pybind11 embedding 和 Python/C API provider：

```sh
python3 tools/benchmark.py call cpp python
python3 tools/benchmark.py call cpp python --bridge pybind
python3 tools/benchmark.py call cpp python --bridge capi
```

C++ 调 C 同时提供默认 `dlopen` 路径和 `extern "C"` 直连 C provider：

```sh
python3 tools/benchmark.py call cpp c
python3 tools/benchmark.py call cpp c --bridge dlopen
python3 tools/benchmark.py call cpp c --bridge extern-c
```

## Docker

Docker 会构建完整工具链镜像。本机没有 Zig、Kotlin/Native 或 WebAssembly 工具链时，可以用 Docker 跑这些可选路径。

```sh
docker build -t xello .
docker run --rm xello make test
docker run --rm xello make fanout FROM=c
docker run --rm xello make benchmark-from FROM=zig BENCH_ARGS="--iterations 5 --warmup 1"
docker run --rm xello make chain-from RUNNER=wasm CHAIN=wasm:python,python:rust,rust:go,go:cpp,cpp:zig,zig:kotlin_native,kotlin_native:c
```

仓库内置 Docker benchmark 入口：

```sh
make docker-benchmark
make docker-benchmark BENCH="call python rust" BENCH_ARGS="--iterations 50 --warmup 5"
make docker-benchmark-from FROM=zig BENCH_ARGS="--iterations 50 --warmup 5"
```

复现 README 中的完整 Docker 快照时，使用 `docker build` 已经构建好的镜像 artifacts：

```sh
docker build -t xello .
docker run --rm xello python3 tools/benchmark.py --iterations 10 --warmup 1 matrix
```

## 格式化

Xello 使用 `prek` 做格式化和基础文件检查：

```sh
prek install
make fmt
```

已配置 formatter：

| 语言/文件类型 | Formatter |
| --- | --- |
| Python | Ruff |
| C、C++、Objective-C | clang-format |
| Go | gofmt |
| Rust | rustfmt |
| Zig | zig fmt |
| MoonBit | moon fmt |
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

没有匹配文件的语言 hook 会自动跳过。

## 项目结构

- `runners/*`：每种语言自己的入口 runner。
- `bindings/rust_python`：Python 调用 Rust 的 PyO3 扩展模块。
- `bindings/cpp_python`：Python 调用 C++ 的 pybind11 扩展模块。
- `providers/*`：provider 实现，主要通过 C ABI 边界暴露。
- `moon.mod`、`providers/moonbit/moon.pkg`、`runners/moonbit/moon.pkg`：MoonBit 模块和包配置。
- `include/xello.h`：共享兜底 ABI。
- `build/xello_languages.json`：构建后生成的实际语言 manifest。
- `tools/build.py`：构建共享库、runner、binding 和 manifest。
- `tools/xello.py`：兼容入口，转到 Python runner。
- `tools/run_from.py`：按语言选择 runner 的辅助入口。
- `tools/benchmark.py`：跨语言 benchmark harness。
- `tests/test_xello.py`：矩阵、链条、bridge、耗时、benchmark 和 manifest 测试。
