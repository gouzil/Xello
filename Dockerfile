FROM golang:bookworm AS go-toolchain

FROM rust:bookworm AS rust-toolchain

FROM python:3.11-bookworm

COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
COPY --from=go-toolchain /usr/local/go /usr/local/go
ENV PATH="/usr/local/cargo/bin:/usr/local/go/bin:${PATH}" \
    RUSTUP_HOME="/usr/local/rustup" \
    CARGO_HOME="/usr/local/cargo"

WORKDIR /app
COPY . .

RUN python3 tools/build.py
RUN make test

CMD ["make", "matrix"]
