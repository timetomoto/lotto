#!/usr/bin/env bash
# Wrapper around download_data.sh used by the cron job.
# 1. Download fresh CSVs.
# 2. Sleep briefly so the filesystem fully flushes new writes before any
#    downstream reader keys off mtimes.
# 3. Warm all MC-null and audit caches so users never wait on first render.
# Logs each run to logs/refresh.log with a timestamp; keeps the last 2000 lines.
set -uo pipefail  # no -e: we want to handle each step's failure explicitly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/refresh.log"
POST_DOWNLOAD_SLEEP="${POST_DOWNLOAD_SLEEP:-15}"   # seconds
mkdir -p "$LOG_DIR"

{
    echo ""
    echo "=== refresh_data.sh @ $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
    echo "[step 1/3] download"
    if "$SCRIPT_DIR/download_data.sh"; then
        echo "download OK"
    else
        echo "download FAILED with exit $? — skipping warm step"
        # Don't proceed to warm if download failed.
        # Still trim log and exit cleanly-ish.
    fi

    if [ -f "$SCRIPT_DIR/data/lotto_texas.csv" ]; then
        echo "[step 2/3] settle (${POST_DOWNLOAD_SLEEP}s so mtime is stable)"
        sleep "$POST_DOWNLOAD_SLEEP"

        echo "[step 3/3] warm caches"
        if python3 -u "$SCRIPT_DIR/warm_caches.py"; then
            echo "warm OK"
        else
            echo "warm FAILED with exit $? — CSVs are current but audit"
            echo "  caches may need to build on first user render."
        fi
    fi
} >> "$LOG_FILE" 2>&1

# Trim log to last 2000 lines
if [ -f "$LOG_FILE" ]; then
    tail -n 2000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi
