# Xello 贡献指南

Xello 是一个跨语言 Hello World 调用矩阵。贡献代码时最重要的约束是：一个语言只有在同时具备可构建的 `runner` 和可被调用的 `provider` 后，才应该进入完整矩阵。

## 项目结构

- `runners/*`：每种语言自己的入口程序。runner 必须支持 `call`、`fanout`、`chain`、`matrix`，并支持 `--json` 输出。
- `providers/*`：每种语言暴露给其他语言调用的实现。当前兜底 ABI 是 `include/xello.h` 定义的 C ABI。
- `bindings/*`：成熟语言桥接绑定。比如 `bindings/rust_python` 是 Python 调 Rust 的 PyO3 扩展。
- `include/xello.h`：共享 C ABI，provider 至少要暴露 `xello_hello` 和 `xello_language`。
- `tools/build.py`：统一构建入口，负责生成共享库、runner、语言绑定和 `build/xello_languages.json`。
- `tools/xello_registry.py`：语言列表、runner/provider 路径、bridge 描述和 manifest 读取逻辑。
- `tools/xello.py`：兼容入口，转到 Python runner。
- `tools/run_from.py`：按指定语言选择 runner。
- `tools/benchmark.py`：跨语言调用耗时 benchmark。
- `tests/test_xello.py`：矩阵、链条、bridge、耗时、benchmark 和规划语言状态测试。
- `build/xello_languages.json`：构建后生成的实际语言 manifest。不要手写或提交这个文件。

## Runner 约束

每个 runner 至少要支持：

```sh
<runner> call <callee>
<runner> fanout <caller>
<runner> chain --edges "caller:callee,caller:callee"
<runner> matrix
<runner> --json call <callee>
```

输出语义必须和现有 runner 对齐：

- JSON 输出是数组。
- 每条结果包含 `caller`、`callee`、`bridge`、`duration_ns`、`message`、`output`。
- `duration_ns` 必须是正整数。
- `message` 使用 `hello world from <callee> implementation, called by <caller>`。
- `output` 使用 `<caller> runner -> <callee> implementation via <bridge>: <message>`。

如果一个 runner 不能直接执行某条边，可以委托到该边 caller 对应的 runner。当前 `chain` 的语义是：每条 `caller:callee` 都由该 `caller` 的 runner 执行。

## Provider 约束

provider 的默认兜底边界是 C ABI：

```c
const char *xello_hello(const char *caller);
const char *xello_language(void);
```

新增 provider 时要保证：

- 共享库名称符合 `build/lib/libxello_<language>.<ext>`。
- `xello_language()` 返回语言标识，比如 `cpp`、`zig`、`kotlin_native`。
- `xello_hello()` 返回稳定可读的字符串，内容和测试约定一致。
- 跨语言调用优先使用成熟桥接库；只有没有合适桥接时才使用 C ABI/FFI 兜底。

## 新增语言流程

新增语言不要只加 provider，也不要只加 runner。建议按这个顺序做：

1. 在 `providers/<language>/` 增加 provider。
2. 在 `runners/<language>/` 增加 runner。
3. 在 `tools/build.py` 增加工具链探测和构建步骤。
4. 在 `tools/xello_registry.py` 增加 bridge 描述。
5. 让语言只有在 provider 和 runner 都能构建时才进入 `languages`。
6. 如果工具链缺失或集成未完成，写入 `planned_languages`，不要让它半接入矩阵。
7. 更新 README 的当前支持语言、技术路线和项目结构。
8. 增加或调整 `tests/test_xello.py`。

当前 C++ 已完整进入矩阵。Zig、Kotlin/Native、WebAssembly 已有源码和构建探测，但在完整动态矩阵接入前继续记录在 `planned_languages`。

## 常用命令

构建：

```sh
make build
```

跑完整矩阵：

```sh
make matrix
```

从指定 runner 启动：

```sh
make matrix-from RUNNER=cpp
make fanout-from RUNNER=rust FROM=go
make chain-from RUNNER=c CHAIN=c:python,python:rust,rust:go,go:cpp
```

测试：

```sh
make test
```

Benchmark：

```sh
make benchmark
make benchmark-from FROM=cpp BENCH_ARGS="--iterations 50 --warmup 5"
python3 tools/benchmark.py --json call python rust
```

查看实际构建语言：

```sh
cat build/xello_languages.json
```

## 格式化和检查

项目使用 `prek`：

```sh
prek install
make fmt
```

`prek` 会处理：

- EOF、LF 行尾、尾随空白。
- TOML/YAML/JSON 基础检查。
- Ruff Python lint/format。
- C/C++/Objective-C、Go、Rust 格式化。
- Zig、Kotlin、WebAssembly text 等可选 formatter。缺少对应工具时会跳过可选 formatter。

提交前至少跑：

```sh
PREK_HOME=.cache/prek prek run --all-files
make test
```

## 测试要求

影响矩阵行为时，需要覆盖：

- 完整 caller/callee 组合。
- 每个 runner 的 `call`。
- `fanout` 和 `chain`。
- `--json` 结构化输出。
- 关键 bridge 选择，例如 `python -> rust` 走 PyO3。
- `duration_ns` 存在且为正。
- 新增 planned 语言的工具链缺失路径。

如果本机缺少某个可选工具链，不要让测试失败；应该通过 `build/xello_languages.json` 明确记录跳过原因。

## 不要提交的内容

- `build/`
- `.cache/`
- `.ruff_cache/`
- `__pycache__/`
- `*.pyc`
- 本地工具链缓存或临时 benchmark 输出

## 设计原则

- 每种语言都应该能作为入口，而不是依赖 Python 作为唯一真实入口。
- 语言桥接优先选择成熟库；C ABI/FFI 是兜底方案。
- 构建要可探测、可跳过、可解释。缺少可选工具链时，记录 planned/skipped，不要破坏现有矩阵。
- 文档、测试、构建脚本要一起更新，避免出现“代码能跑但贡献者不知道怎么接”的状态。
