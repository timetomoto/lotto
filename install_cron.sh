#!/usr/bin/env bash
# Install the 4×/day cron entries that refresh the lottery data.
#
# Texas Lottery draw times (Central Time):
#   Morning ~10:00 AM  → refresh at 10:15 AM
#   Day     ~12:27 PM  → refresh at 12:45 PM
#   Evening ~ 6:00 PM  → refresh at  6:15 PM
#   Night   ~10:12 PM  → refresh at 10:30 PM   (catches the once-nightly games)
#
# Assumes the Mac's timezone is Central Time. If yours isn't, edit the times
# in the CRON_LINES block below.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REFRESH="$SCRIPT_DIR/refresh_data.sh"
MARKER="# lotto-app refresh"

CRON_LINES="\
15 10 * * * $REFRESH  $MARKER
45 12 * * * $REFRESH  $MARKER
15 18 * * * $REFRESH  $MARKER
30 22 * * * $REFRESH  $MARKER"

# Preserve any existing crontab lines that are NOT ours, then append ours.
existing=$(crontab -l 2>/dev/null | grep -v "$MARKER" || true)
new_crontab="$existing
$CRON_LINES"

echo "$new_crontab" | crontab -
echo "Installed 4 cron entries. Verify with:  crontab -l | grep '$MARKER'"
echo ""
crontab -l | grep "$MARKER"
