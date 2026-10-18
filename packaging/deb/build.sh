#!/bin/sh
# Build the beatballot-player .deb packages: ./packaging/deb/build.sh [amd64] [arm64]
# Needs Docker (with QEMU/binfmt for other architectures), uv and npm.
set -eu
cd "$(dirname "$0")/../.."
ARCHES=${*:-amd64 arm64}
VERSION=$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')

(cd web && npm ci --no-audit --no-fund --silent && npm run build --silent)
rm -rf dist
uv build --wheel --out-dir dist > /dev/null
ls dist/*.whl

for arch in $ARCHES; do
    docker run --rm --platform "linux/$arch" \
        -v "$PWD/packaging/deb:/src:ro" -v "$PWD/dist:/dist:ro" -v "$PWD/dist:/out" \
        debian:trixie sh /src/build-in-container.sh "$VERSION"
done
ls -l dist/*.deb
