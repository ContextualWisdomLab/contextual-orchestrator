#!/bin/sh
set -eu

# Keep fuzz jobs on the same immutable PyO3 build environment as the runtime
# image. The extension is required by orchestration paths.
readonly MATURIN_BUILDER_IMAGE="ghcr.io/pyo3/maturin@sha256:b6c8b59a0170b77eb31a35b56034abd39972483ad0ebfff344deaa42a85f3bd3"
readonly WHEEL_DIRECTORY="$(mktemp -d)"
readonly PROJECT_DIRECTORY="$(pwd -P)"
trap 'rm -rf "${WHEEL_DIRECTORY}"' EXIT

docker build \
  --build-arg "MATURIN_BUILDER_IMAGE=${MATURIN_BUILDER_IMAGE}" \
  --target token-wheel \
  --output "type=local,dest=${WHEEL_DIRECTORY}" \
  "${PROJECT_DIRECTORY}"

set -- "${WHEEL_DIRECTORY}"/*.whl
test "$#" -eq 1 && test -f "$1" || {
  echo "pinned Rust token-packer build must produce exactly one wheel" >&2
  exit 1
}
python -m pip install "$1"
