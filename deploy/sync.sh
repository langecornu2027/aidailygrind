#!/bin/bash
# Runs on the VM every 15 minutes (cron). If the `published` branch on GitHub
# changed, download it and copy it into the nginx web root.
# Installed as /usr/local/bin/aidailygrind-sync
set -euo pipefail

REPO="langecornu2027/aidailygrind"
BRANCH="published"
WEB_ROOT="/var/www/aidailygrind/public"
STATE="/var/www/aidailygrind/.published-sha"

sha=$(curl -fsS "https://api.github.com/repos/$REPO/commits/$BRANCH" | jq -r .sha)
if [ -z "$sha" ] || [ "$sha" = "null" ]; then
  echo "Could not read the $BRANCH branch" >&2
  exit 1
fi
[ "$sha" = "$(cat "$STATE" 2>/dev/null || true)" ] && exit 0

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$sha" | tar -xz -C "$tmp" --strip-components=1

if [ ! -f "$tmp/index.html" ]; then
  echo "No index.html in $sha, not deploying" >&2
  exit 1
fi

rsync -rlt --delete --chmod=D755,F644 "$tmp"/ "$WEB_ROOT"/
echo "$sha" > "$STATE"
logger -t aidailygrind-sync "deployed $sha"
