# The mail engine, Stalwart, built from its open-source code (AGPL-3.0) without the Enterprise
# parts, for Someless Mail to copy into its image. Built by .github/workflows/stalwart.yml,
# for the version in stalwart/VERSION.
FROM rust:slim-trixie AS build
ARG STALWART_VERSION
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libclang-19-dev git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${STALWART_VERSION}" https://github.com/stalwartlabs/stalwart /src
WORKDIR /src
# The default features are rocks and enterprise; rocks alone leaves the Enterprise code out
RUN cargo build --release -p stalwart --no-default-features --features "rocks"
RUN mkdir -p /out/doc \
 && cp target/release/stalwart /out/stalwart \
 && mkdir -p /out/doc/LICENSES && cp LICENSES/AGPL-3.0-only.txt /out/doc/LICENSES/ \
 && cp Cargo.lock /out/doc/Cargo.lock \
 && printf 'Stalwart %s, built from https://github.com/stalwartlabs/stalwart/tree/%s (commit %s)\nwithout the enterprise feature: cargo build --release -p stalwart --no-default-features --features rocks\nLicence: AGPL-3.0-only (LICENSES/AGPL-3.0-only.txt). Third-party crates and their versions: Cargo.lock\n' \
    "${STALWART_VERSION}" "${STALWART_VERSION}" "$(git rev-parse HEAD)" > /out/doc/SOURCE

FROM debian:trixie-slim
COPY --from=build /out/stalwart /usr/local/bin/stalwart
COPY --from=build /out/doc /usr/share/doc/stalwart
