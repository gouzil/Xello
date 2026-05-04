# Xello

[中文 README](README.zh-CN.md)

Xello is a cross-language Hello World matrix where every supported language can be the entrypoint and every supported language can be the callee.

The current language set is:

- Python
- C
- Go
- Rust

Each language has a runner. A runner can execute one direct call, one caller fanning out to every supported callee, a selected chain, or the full matrix:

```sh
make matrix
make fanout FROM=c
make chain CHAIN=c:python,python:rust,rust:go,go:c
make fanout-from RUNNER=rust FROM=go
make chain-from RUNNER=rust CHAIN=c:python,python:rust,rust:go,go:c
```

The chain format is a comma-separated list of `caller:callee` edges. Each edge is executed by that edge's caller runner, so a chain can start from C, Go, Rust, or Python without requiring Python to be the only real entrypoint.

The fanout command is the fast path for "one language to all supported languages". For example, `make fanout FROM=c` runs `c -> python`, `c -> c`, `c -> go`, and `c -> rust`.

## Bridge Policy

Xello prefers mature language bridges over hand-written FFI. C ABI is kept as the fallback bridge when a direct mature bridge is not practical for this small demo.

Examples in the current matrix:

- `python -> rust`: PyO3 extension module.
- `python -> c`: Python `ctypes` standard library.
- `c -> python`: Python/C API.
- `rust -> c`: Rust `libloading` crate.
- `go -> c`: cgo over the C ABI.
- `go -> rust`, `rust -> go`, `python -> go`, `c -> rust`, `c -> go`: C ABI fallback.

Every result includes the selected bridge, caller, callee, hello message, and measured call duration:

```text
python runner -> rust implementation via PyO3: hello world from rust implementation, called by python (duration_ns=...)
```

For structured timing and bridge data:

```sh
python3 tools/xello.py --json matrix
```

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
make matrix-from RUNNER=c
make fanout-from RUNNER=rust FROM=go
make matrix-from RUNNER=go
make matrix-from RUNNER=rust
make chain-from RUNNER=c CHAIN=c:python,python:rust,rust:go,go:c
```

Direct runner examples:

```sh
python3 runners/python/xello_python.py call rust
python3 runners/python/xello_python.py fanout c
./build/bin/xello_c call python
./build/bin/xello_go fanout rust
./build/bin/xello_go call c
./build/bin/xello_rust call go
```

## Tests

```sh
make test
```

The tests verify:

- The full 4x4 caller/callee matrix.
- Fanout from one caller to every supported callee.
- Chains can be started through Python, C, Go, and Rust runners.
- Every runner can directly call every language.
- Per-edge duration is present.
- Important mature bridge selections, including `python -> rust` via PyO3.

## Docker

```sh
docker build -t xello .
docker run --rm xello make test
docker run --rm xello make fanout FROM=c
docker run --rm xello make chain-from RUNNER=rust CHAIN=c:python,python:rust,rust:go
```

## Project Layout

- `runners/*`: language entrypoints.
- `bindings/rust_python`: PyO3 Python extension for Python calling Rust.
- `providers/*`: C ABI provider fallback libraries.
- `include/xello.h`: shared fallback ABI.
- `tools/build.py`: builds shared libraries, runners, and bindings.
- `tools/xello.py`: compatibility entrypoint for the Python runner.
- `tools/run_from.py`: runner selection helper.
- `tests/test_xello.py`: matrix, chain, bridge, and timing tests.
