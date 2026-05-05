.PHONY: all build matrix matrix-from fanout fanout-from chain chain-from benchmark benchmark-from docker-benchmark docker-benchmark-from fmt prek python c cpp go rust zig kotlin_native wasm test clean

PYTHON ?= python3
RUNNER ?= python
FROM ?= python
CHAIN ?= python:c,c:rust,rust:go,go:c
BENCH ?= matrix
BENCH_ARGS ?=

all: build

build:
	$(PYTHON) tools/build.py

matrix: build
	$(PYTHON) tools/xello.py matrix

matrix-from: build
	$(PYTHON) tools/run_from.py $(RUNNER) matrix

fanout: build
	$(PYTHON) tools/xello.py fanout $(FROM)

fanout-from: build
	$(PYTHON) tools/run_from.py $(RUNNER) fanout $(FROM)

chain: build
	$(PYTHON) tools/xello.py chain --edges "$(CHAIN)"

chain-from: build
	$(PYTHON) tools/run_from.py $(RUNNER) chain --edges "$(CHAIN)"

benchmark: build
	$(PYTHON) tools/benchmark.py $(BENCH_ARGS) $(BENCH)

benchmark-from: build
	$(PYTHON) tools/benchmark.py $(BENCH_ARGS) fanout $(FROM)

docker-benchmark:
	docker build -t xello .
	docker run --rm xello make benchmark BENCH="$(BENCH)" BENCH_ARGS="$(BENCH_ARGS)"

docker-benchmark-from:
	docker build -t xello .
	docker run --rm xello make benchmark-from FROM="$(FROM)" BENCH_ARGS="$(BENCH_ARGS)"

fmt:
	prek run --all-files

prek: fmt

python: build
	$(PYTHON) runners/python/xello_python.py chain --edges "$(CHAIN)"

c: build
	./build/bin/xello_c chain --edges "$(CHAIN)"

cpp: build
	./build/bin/xello_cpp chain --edges "$(CHAIN)"

go: build
	./build/bin/xello_go chain --edges "$(CHAIN)"

rust: build
	./build/bin/xello_rust chain --edges "$(CHAIN)"

zig: build
	./build/bin/xello_zig chain --edges "$(CHAIN)"

kotlin_native: build
	./build/bin/xello_kotlin_native.kexe chain --edges "$(CHAIN)"

wasm: build
	$(PYTHON) runners/wasm/xello_wasm.py chain --edges "$(CHAIN)"

test:
	$(PYTHON) -m unittest discover -s tests

clean:
	rm -rf build
