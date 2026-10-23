#!/bin/bash
# Starts the daily GitHub job ("The AI Daily Grind" workflow) from the VM's cron,
# because GitHub's own scheduler sometimes skips runs. GitHub runs a started job right away.
# Does nothing if today's edition is already online (so the retry is free).
# Installed as /usr/local/bin/aidailygrind-trigger, run by /etc/cron.d/aidailygrind.
# Needs GH_TRIGGER_TOKEN in /etc/aidailygrind/env: a fine-grained token limited to
# langecornu2027/aidailygrind with "Actions: Read and write".
set -euo pipefail

set -a; . /etc/aidailygrind/env; set +a
REPO="langecornu2027/aidailygrind"
TODAY=$(TZ=America/Toronto date +%F)

if curl -fsS -o /dev/null "https://aidailygrind.com/${TODAY}.html"; then
  exit 0  # already published today
fi

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GH_TRIGGER_TOKEN}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${REPO}/actions/workflows/daily.yml/dispatches" \
  -d '{"ref":"main"}')
logger -t aidailygrind-trigger "started daily job for ${TODAY}: GitHub answered ${code}"
[ "$code" = "204" ]
