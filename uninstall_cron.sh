#!/usr/bin/env bash
# Remove the lotto-app cron entries. Leaves any other crontab entries alone.
set -euo pipefail
MARKER="# lotto-app refresh"

before=$(crontab -l 2>/dev/null | grep -c "$MARKER" || true)
if [ "$before" -eq 0 ]; then
    echo "No lotto-app cron entries found. Nothing to remove."
    exit 0
fi

crontab -l 2>/dev/null | grep -v "$MARKER" | crontab -
after=$(crontab -l 2>/dev/null | grep -c "$MARKER" || true)

echo "Removed $before lotto-app cron entries."
if [ "$after" -gt 0 ]; then
    echo "WARNING: $after entries still remain — check permissions."
    exit 1
fi
echo "Verified: none remaining."
