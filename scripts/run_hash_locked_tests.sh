#!/bin/sh
set -eu

readonly MATURIN_BUILDER_IMAGE="ghcr.io/pyo3/maturin@sha256:b6c8b59a0170b77eb31a35b56034abd39972483ad0ebfff344deaa42a85f3bd3"

if ! command -v docker >/dev/null 2>&1; then
    echo "make test requires Docker to build the pinned Rust token-packer wheel; start Docker and retry" >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "make test cannot reach the Docker daemon required for the pinned Rust token-packer build" >&2
    exit 1
fi

unset CDPATH
repository_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
docker build \
    --build-arg "MATURIN_BUILDER_IMAGE=$MATURIN_BUILDER_IMAGE" \
    --progress plain \
    --target test-runner \
    "$repository_root"
