#!/usr/bin/env bash
# Upload docs/assets/product-demo.mp4 to the product-demo GitHub Release.
# Requires: gh auth login  (or GH_TOKEN / GITHUB_TOKEN)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSET="${ROOT}/docs/assets/product-demo.mp4"
REPO="${GITHUB_REPOSITORY:-lianyixin/citycity}"
TAG="${MEDIA_RELEASE_TAG:-product-demo}"

if [[ ! -f "$ASSET" ]]; then
  echo "missing $ASSET — place the mp4 there first (or run after encoding)." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install: https://cli.github.com/" >&2
  exit 1
fi

if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release upload "$TAG" "$ASSET" --repo "$REPO" --clobber
else
  gh release create "$TAG" "$ASSET" \
    --repo "$REPO" \
    --title "Product demo media" \
    --notes "Product walkthrough MP4 used by README. Not tracked in git — download locally with \`docs/assets/fetch-media.sh\`."
fi

echo "published: https://github.com/${REPO}/releases/tag/${TAG}"
