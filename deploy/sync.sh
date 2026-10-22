#!/bin/bash
# Runs on the VM every 15 minutes (/etc/cron.d/aidailygrind, as user aidailygrind).
# If the `published` branch on GitHub changed, download it and copy it into the
# nginx web root. Then email today's edition to subscribers (only once per day).
# Installed as /usr/local/bin/aidailygrind-sync
set -euo pipefail

REPO="langecornu2027/aidailygrind"
BRANCH="published"
WEB_ROOT="/var/www/aidailygrind/public"
STATE="/var/www/aidailygrind/.published-sha"

send_email() {
  set -a; . /etc/aidailygrind/env; set +a
  /usr/bin/python3 /opt/aidailygrind/mailer.py send-latest 2>&1 | logger -t aidailygrind-mail
}

sha=$(curl -fsS "https://api.github.com/repos/$REPO/commits/$BRANCH" | jq -r .sha)
if [ -z "$sha" ] || [ "$sha" = "null" ]; then
  echo "Could not read the $BRANCH branch" >&2
  exit 1
fi
if [ "$sha" = "$(cat "$STATE" 2>/dev/null || true)" ]; then
  send_email  # nothing new to copy, but today's email may still be waiting
  exit 0
fi

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
send_email
