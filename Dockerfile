FROM --platform=linux/amd64 golang:bookworm AS go-toolchain

FROM --platform=linux/amd64 rust:bookworm AS rust-toolchain

FROM --platform=linux/amd64 python:3.11-bookworm AS xello-build

ARG ZIG_VERSION=0.15.1
ARG KOTLIN_NATIVE_VERSION=1.9.24
ARG WASM_TOOLS_VERSION=1.246.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl default-jre-headless g++ xz-utils \
    && curl -fsSL "https://ziglang.org/download/${ZIG_VERSION}/zig-x86_64-linux-${ZIG_VERSION}.tar.xz" \
        | tar -xJ -C /opt \
    && ln -s "/opt/zig-x86_64-linux-${ZIG_VERSION}/zig" /usr/local/bin/zig \
    && curl -fsSL "https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-native-prebuilt/${KOTLIN_NATIVE_VERSION}/kotlin-native-prebuilt-${KOTLIN_NATIVE_VERSION}-linux-x86_64.tar.gz" \
        | tar -xz -C /opt \
    && curl -fsSL "https://github.com/bytecodealliance/wasm-tools/releases/download/v${WASM_TOOLS_VERSION}/wasm-tools-${WASM_TOOLS_VERSION}-x86_64-linux.tar.gz" \
        | tar -xz -C /usr/local/bin --strip-components=1 "wasm-tools-${WASM_TOOLS_VERSION}-x86_64-linux/wasm-tools" \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
COPY --from=go-toolchain /usr/local/go /usr/local/go
ENV PATH="/usr/local/cargo/bin:/usr/local/go/bin:/opt/kotlin-native-prebuilt-linux-x86_64-1.9.24/bin:${PATH}" \
    RUSTUP_HOME="/usr/local/rustup" \
    CARGO_HOME="/usr/local/cargo"

WORKDIR /app
COPY . .

RUN python3 tools/build.py \
    && python3 - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("build/xello_languages.json").read_text())
expected = {"python", "c", "go", "rust", "cpp", "zig", "kotlin_native", "wasm"}
actual = set(manifest["languages"])
missing = sorted(expected - actual)
if missing:
    raise SystemExit(f"missing full Docker matrix languages: {missing}; manifest={manifest}")
PY

FROM xello-build AS xello-smoke
RUN python3 tools/xello.py --json chain --edges "python:zig,zig:kotlin_native,kotlin_native:wasm,wasm:c" >/tmp/xello-smoke.json

CMD ["make", "matrix"]
