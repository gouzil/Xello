from __future__ import annotations

import atexit
import ctypes
import json
import os
import sys
from functools import cache
from pathlib import Path

import py_mini_racer

ROOT = Path(__file__).resolve().parents[2]

if sys.platform == "linux":
    # Keep MiniRacer's V8 symbols separate from the Node runner's V8.
    _v8 = ctypes.CDLL(
        str(Path(py_mini_racer.__file__).with_name("libmini_racer.so")),
        mode=os.RTLD_NOW | os.RTLD_DEEPBIND,
    )


@cache
def runtime(backend: str) -> py_mini_racer.MiniRacer:
    context = py_mini_racer.MiniRacer()
    atexit.register(context.close)
    suffix = "cjs" if backend == "js" else "wasm"
    artifact = ROOT / f"build/lib/xello_moonbit_provider_{backend}.{suffix}"
    if backend == "js":
        context.eval("var module = {exports: {}}; var exports = module.exports;")
        context.eval(artifact.read_text(encoding="utf-8"))
        context.eval("var api = module.exports;")
        return context
    binary = json.dumps(list(artifact.read_bytes()))
    context.eval(f"var api = new WebAssembly.Instance(new WebAssembly.Module(new Uint8Array({binary}))).exports;")
    context.eval((ROOT / "providers/moonbit/byte_api.js").read_text(encoding="utf-8"))
    context.eval(
        "var bytesApi = xelloByteApi(api);"
        "function xelloHello(raw) {"
        "  const result = api.xello_moonbit_hello(bytesApi.make(raw));"
        "  const output = Array.from(bytesApi.read(result));"
        "  api.xello_bytes_release(result);"
        "  return output;"
        "}"
    )
    return context


def hello(backend: str, caller: str) -> str:
    if backend == "js":
        return runtime(backend).call("api.xello_moonbit_hello", caller)
    raw = runtime(backend).call("xelloHello", list(caller.encode("utf-8")))
    return bytes(raw).removesuffix(b"\0").decode("utf-8")
