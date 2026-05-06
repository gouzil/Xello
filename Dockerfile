ARG XELLO_DOCKER_PLATFORM=linux/amd64
FROM --platform=${XELLO_DOCKER_PLATFORM} golang:bookworm AS go-toolchain

FROM --platform=${XELLO_DOCKER_PLATFORM} rust:bookworm AS rust-toolchain

FROM --platform=${XELLO_DOCKER_PLATFORM} kassany/alpine-ziglang:0.16.0 AS zig-toolchain

FROM --platform=${XELLO_DOCKER_PLATFORM} python:3.11-bookworm AS xello-build

ARG ZIG_VERSION=0.16.0
ARG KOTLIN_NATIVE_VERSION=1.9.24
ARG WASM_TOOLS_VERSION=1.246.2

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl default-jre-headless g++ xz-utils \
    && ln -sf "/opt/zig-x86_64-linux-${ZIG_VERSION}/zig" /usr/local/bin/zig \
    && curl --retry 5 --retry-delay 10 --retry-connrefused --retry-all-errors -fsSL \
        -o /tmp/kotlin-native.tar.gz \
        "https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-native-prebuilt/${KOTLIN_NATIVE_VERSION}/kotlin-native-prebuilt-${KOTLIN_NATIVE_VERSION}-linux-x86_64.tar.gz" \
    && tar -xzf /tmp/kotlin-native.tar.gz -C /opt \
    && curl --retry 5 --retry-delay 10 --retry-connrefused --retry-all-errors -fsSL \
        -o /tmp/wasm-tools.tar.gz \
        "https://github.com/bytecodealliance/wasm-tools/releases/download/v${WASM_TOOLS_VERSION}/wasm-tools-${WASM_TOOLS_VERSION}-x86_64-linux.tar.gz" \
    && tar -xzf /tmp/wasm-tools.tar.gz -C /usr/local/bin --strip-components=1 "wasm-tools-${WASM_TOOLS_VERSION}-x86_64-linux/wasm-tools" \
    && rm -rf /var/lib/apt/lists/* /tmp/kotlin-native.tar.gz /tmp/wasm-tools.tar.gz

COPY --from=zig-toolchain /zig/0.16.0/files /opt/zig-x86_64-linux-0.16.0
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
COPY --from=go-toolchain /usr/local/go /usr/local/go
ENV PATH="/usr/local/cargo/bin:/usr/local/go/bin:/opt/kotlin-native-prebuilt-linux-x86_64-1.9.24/bin:${PATH}" \
    RUSTUP_HOME="/usr/local/rustup" \
    CARGO_HOME="/usr/local/cargo" \
    KONAN_DATA_DIR="/tmp/konan"

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
