#!/usr/bin/env bash
# Download the product demo MP4 from the product-demo release into docs/assets/
# for local preview. It is not tracked in git.
set -euo pipefail
cd "$(dirname "$0")"
REPO="${GITHUB_REPOSITORY:-lianyixin/citycity-agent}"
TAG="${MEDIA_RELEASE_TAG:-product-demo}"
ASSET="${MEDIA_ASSET_NAME:-product-demo.mp4}"
URL="https://github.com/${REPO}/releases/download/${TAG}/${ASSET}"

echo "Downloading ${URL}"
curl -fsSL -o "${ASSET}" "${URL}"
echo "done: $(ls -lh "${ASSET}" | awk '{print $5}') ${ASSET}"
