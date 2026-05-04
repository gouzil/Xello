# Xello

[English README](README.md)

Xello 是一个跨语言 Hello World 调用矩阵。现在的设计不是“只能从 Python 脚本启动”，而是每种语言都有自己的 runner；任意语言都可以作为入口，任意语言也都可以作为被调用方。

当前支持语言：

- Python
- C
- Go
- Rust

每个 runner 都支持直接调用、单个 caller 快速调用所有支持语言、执行自定义链条、执行完整矩阵：

```sh
make matrix
make fanout FROM=c
make chain CHAIN=c:python,python:rust,rust:go,go:c
make fanout-from RUNNER=rust FROM=go
make chain-from RUNNER=rust CHAIN=c:python,python:rust,rust:go,go:c
```

链条格式是逗号分隔的 `caller:callee`。每条边都会由该边的 caller runner 执行，所以可以从 C、Go、Rust 或 Python 任意语言入口启动。

`fanout` 是“单个语言到所有支持语言”的快速命令。例如 `make fanout FROM=c` 会依次运行 `c -> python`、`c -> c`、`c -> go`、`c -> rust`。

## 调用桥接策略

优先使用成熟的语言桥接库；只有没有合适成熟桥接时，才使用 C ABI/FFI 作为兜底。

当前矩阵里的代表性桥接：

- `python -> rust`：PyO3 扩展模块。
- `python -> c`：Python 标准库 `ctypes`。
- `c -> python`：Python/C API。
- `rust -> c`：Rust `libloading` crate。
- `go -> c`：cgo over C ABI。
- `go -> rust`、`rust -> go`、`python -> go`、`c -> rust`、`c -> go`：C ABI 兜底。

每条结果都会包含 caller、callee、bridge、hello world 消息和调用耗时：

```text
python runner -> rust implementation via PyO3: hello world from rust implementation, called by python (duration_ns=...)
```

结构化输出：

```sh
python3 tools/xello.py --json matrix
```

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
make matrix-from RUNNER=c
make fanout-from RUNNER=rust FROM=go
make matrix-from RUNNER=go
make matrix-from RUNNER=rust
make chain-from RUNNER=c CHAIN=c:python,python:rust,rust:go,go:c
```

直接调用单个 runner：

```sh
python3 runners/python/xello_python.py call rust
python3 runners/python/xello_python.py fanout c
./build/bin/xello_c call python
./build/bin/xello_go fanout rust
./build/bin/xello_go call c
./build/bin/xello_rust call go
```

## 测试

```sh
make test
```

测试覆盖：

- 完整 4x4 caller/callee 矩阵。
- 单个 caller fanout 到所有支持语言。
- 可以通过 Python、C、Go、Rust 任意 runner 启动链条。
- 每个 runner 都能直接调用每种语言。
- 每条边都有 `duration_ns` 耗时。
- 关键成熟桥接选择，例如 `python -> rust` 必须走 PyO3。

## Docker

```sh
docker build -t xello .
docker run --rm xello make test
docker run --rm xello make fanout FROM=c
docker run --rm xello make chain-from RUNNER=rust CHAIN=c:python,python:rust,rust:go
```

## 项目结构

- `runners/*`：每种语言自己的入口 runner。
- `bindings/rust_python`：Python 调用 Rust 的 PyO3 扩展模块。
- `providers/*`：C ABI 兜底 provider 共享库。
- `include/xello.h`：共享兜底 ABI。
- `tools/build.py`：构建共享库、runner 和绑定模块。
- `tools/xello.py`：兼容入口，转到 Python runner。
- `tools/run_from.py`：按语言选择 runner 的辅助入口。
- `tests/test_xello.py`：矩阵、链条、bridge 和耗时测试。
