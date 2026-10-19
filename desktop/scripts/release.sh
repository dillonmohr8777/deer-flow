#!/bin/sh
# One-command release (from desktop/): npm run release
# Checks, packages and smoke-tests the committed source, tags momobot-desktop-v<version>,
# and publishes it as the repository's latest GitHub release, which installed apps
# update from. Running this ships the update to everyone, so run it only once approved.
# ponytail: builds on this Mac because GitHub Actions is stalled on this account; move
# these steps into a tag-triggered workflow once Actions runs again.
set -eu
cd "$(dirname "$0")/.."
version=$(node -p "require('./package.json').version")
tag="momobot-desktop-v$version"
if [ -n "$(git status --porcelain -- .)" ]; then echo "Commit the desktop changes first." >&2; exit 1; fi
if git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then echo "$tag is already released; bump the version." >&2; exit 1; fi
repo=$(gh repo view "$(git remote get-url origin)" --json nameWithOwner -q .nameWithOwner)
base="https://github.com/$repo/releases/latest/download"

npm run check
npm test
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
MOMOBOT_RELEASE_DIR="$out" npm run package:mac
build=$(ls -d "$out"/build-*)
app=$(node -p "require('$build/build-paths.json').appPath")
"$app/Contents/MacOS/MomoBot" --smoke-test > "$out/smoke.json"
grep -q '"passed":true' "$out/smoke.json" || { echo "Launch smoke failed; nothing released:" >&2; cat "$out/smoke.json" >&2; exit 1; }

git tag -a "$tag" -m "MomoBot desktop $version"
git push origin "$tag"
{
  echo "MomoBot desktop $version for Apple Silicon Macs (ad-hoc signed, not notarized)."
  echo
  echo "Install or update: \`curl -fsSL $base/install.sh | sh -s -- $base\`"
  echo
  echo '```'
  cat "$build/SHA256SUMS"
  echo '```'
} > "$out/notes.md"
gh release create "$tag" --repo "$repo" --latest --title "MomoBot desktop $version" --notes-file "$out/notes.md" \
  "$build/MomoBot-mac-arm64.zip" "$build/MomoBot-mac-arm64.dmg" "$build/SHA256SUMS" "$build/release.json" "$build/install.sh"
echo "Released $tag. Install or update: curl -fsSL $base/install.sh | sh -s -- $base"
