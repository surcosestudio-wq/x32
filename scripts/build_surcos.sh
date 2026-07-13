#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/build-work"
OUT="$ROOT/dist"
OMC_COMMIT="0291d836758b3bc36831dca5014c319c7048e59c"
BASE_TAG="${BASE_TAG:-beta-2026-06-09--5}"

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$OUT"

# Build the modified OpenMixerControl for ARM/X32.
git clone https://github.com/OpenMixerProject/OpenMixerControl.git "$WORK/OpenMixerControl"
git -C "$WORK/OpenMixerControl" checkout "$OMC_COMMIT"
cp "$ROOT/overrides/OpenMixerControl/src/config.cpp" "$WORK/OpenMixerControl/src/config.cpp"
cp "$ROOT/overrides/OpenMixerControl/src/dsp1.cpp" "$WORK/OpenMixerControl/src/dsp1.cpp"
cp "$ROOT/overrides/OpenMixerControl/src/page-eq.h" "$WORK/OpenMixerControl/src/page-eq.h"
bash "$WORK/OpenMixerControl/compile-docker.sh" TARGET_XM32
OMC_BIN="$WORK/OpenMixerControl/build/xm32/omc"
test -s "$OMC_BIN"

# Download the pinned official OpenX32 release used as safe packaging base.
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

sudo -E python3 "$ROOT/scripts/repack_firmware.py" \
  --base-run "$WORK/base-openx32.run" \
  --omc "$OMC_BIN" \
  --dsp1 "$ROOT/prebuilt/dsp1.ldr" \
  --dsp2 "$ROOT/prebuilt/dsp2.ldr" \
  --scripts-dir "$ROOT/scripts" \
  --output "$OUT/Surcos-X32-EQ2404.run"

sha256sum "$OUT/Surcos-X32-EQ2404.run" > "$OUT/SHA256SUMS.txt"
ls -lh "$OUT"
