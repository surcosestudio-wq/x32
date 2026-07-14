#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/build-work"
OUT="$ROOT/dist"
BASE_TAG="${BASE_TAG:-beta-2026-06-09--5}"
OPENX32_COMMIT="c06abdb60fb0f03201faf46a5bccad0bd20630ef"
OMC_COMMIT="8c4677de6d27bb7b813f9911dce4b13e5027a15b"

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$OUT"

test -s "$ROOT/prebuilt/dsp1.ldr" || {
  echo "Falta prebuilt/dsp1.ldr. Ejecuta preparar_github.ps1 después de compilar DSP1 en CrossCore." >&2
  exit 1
}

# Exact OpenMixerControl revision used by the official base firmware source.
git clone https://github.com/OpenMixerProject/OpenMixerControl.git "$WORK/OpenMixerControl"
git -C "$WORK/OpenMixerControl" checkout "$OMC_COMMIT"
cp "$ROOT/overrides/OpenMixerControl/src/x32config.cpp" "$WORK/OpenMixerControl/src/x32config.cpp"
cp "$ROOT/overrides/OpenMixerControl/src/dsp1.cpp" "$WORK/OpenMixerControl/src/dsp1.cpp"
cp "$ROOT/overrides/OpenMixerControl/src/page-eq.h" "$WORK/OpenMixerControl/src/page-eq.h"

# Fetch the exact ARM toolchain blob from the matching OpenX32 commit.
curl -fL \
  "https://raw.githubusercontent.com/OpenMixerProject/OpenX32/${OPENX32_COMMIT}/toolchains/cross-arm-arm926ej.tar.xz" \
  -o "$WORK/cross-arm-arm926ej.tar.xz"

# Build OMC in an isolated environment. The old compatible revision predates
# compile-docker.sh, therefore this builder reproduces its required toolchain.
docker build -t surcos-omc-compatible:latest - <<'DOCKERFILE'
FROM debian:trixie
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf automake build-essential ca-certificates git libtool make pkg-config xz-utils \
    && rm -rf /var/lib/apt/lists/*
DOCKERFILE

docker run --rm \
  -v "$WORK:/work" \
  -w /work/OpenMixerControl \
  surcos-omc-compatible:latest \
  bash -euo pipefail -c '
    tar -xf /work/cross-arm-arm926ej.tar.xz -C /
    export PATH=/opt/cross/bin:$PATH

    mkdir -p lib_ext
    git clone --depth 1 --branch v9.5.0 https://github.com/lvgl/lvgl.git lib_ext/lvgl
    git clone --depth 1 --branch v7.7.1 https://github.com/stephenberry/glaze.git lib_ext/glaze
    git clone --depth 1 https://github.com/OpenLightingProject/libartnet.git lib_ext/libartnet

    cd lib_ext/libartnet
    autoreconf -fi
    ./configure \
      --host=arm-linux-gnueabi \
      --prefix=/opt/cross \
      ac_cv_func_malloc_0_nonnull=yes \
      ac_cv_func_realloc_0_nonnull=yes \
      CC=arm-linux-gnueabi-gcc \
      CXX=arm-linux-gnueabi-g++ \
      AR=arm-linux-gnueabi-ar \
      RANLIB=arm-linux-gnueabi-ranlib \
      CFLAGS="-U_TIME_BITS -Wno-error"
    make -j"$(nproc)"
    make install
    cd ../..

    make BUILD_DIR=build -j"$(nproc)"
  '

OMC_BIN="$WORK/OpenMixerControl/build/omc"
test -s "$OMC_BIN"

# Download the exact official release used as the known-working hardware base.
RELEASE_JSON="$WORK/release.json"
curl -fsSL \
  "https://api.github.com/repos/OpenMixerProject/OpenX32/releases/tags/${BASE_TAG}" \
  -o "$RELEASE_JSON"
ASSET_URL="$(jq -r '.assets[] | select(.name | endswith(".run")) | .browser_download_url' "$RELEASE_JSON" | head -n1)"
if [[ -z "$ASSET_URL" || "$ASSET_URL" == "null" ]]; then
  echo "No .run asset found for release tag: $BASE_TAG" >&2
  exit 1
fi
curl -fL "$ASSET_URL" -o "$WORK/base-openx32.run"

# IMPORTANT: replace only OMC and DSP1. Keep DSP2, FPGA, kernel and board files.
sudo -E python3 "$ROOT/scripts/repack_firmware.py" \
  --base-run "$WORK/base-openx32.run" \
  --omc "$OMC_BIN" \
  --dsp1 "$ROOT/prebuilt/dsp1.ldr" \
  --scripts-dir "$ROOT/scripts" \
  --output "$OUT/Surcos-X32-EQ2404-Compatible.run"

sha256sum "$OUT/Surcos-X32-EQ2404-Compatible.run" > "$OUT/SHA256SUMS.txt"
ls -lh "$OUT"
