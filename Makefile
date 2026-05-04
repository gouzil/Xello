.PHONY: all build matrix matrix-from fanout fanout-from chain chain-from python c go rust test clean

PYTHON ?= python3
RUNNER ?= python
FROM ?= python
CHAIN ?= python:c,c:rust,rust:go,go:c

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

python: build
	$(PYTHON) runners/python/xello_python.py chain --edges "$(CHAIN)"

c: build
	./build/bin/xello_c chain --edges "$(CHAIN)"

go: build
	./build/bin/xello_go chain --edges "$(CHAIN)"

rust: build
	./build/bin/xello_rust chain --edges "$(CHAIN)"

test:
	$(PYTHON) -m unittest discover -s tests

clean:
	rm -rf build
