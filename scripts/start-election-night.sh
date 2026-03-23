#!/usr/bin/env bash
# Auto-restarting wrapper for the election night runner.
# Restarts the runner if it crashes, with a 10-second backoff.
#
# Usage:
#   ./scripts/start-election-night.sh                # run in foreground
#   nohup ./scripts/start-election-night.sh &         # run in background, survives terminal close
#   caffeinate -i ./scripts/start-election-night.sh   # prevent macOS sleep

set -uo pipefail
cd "$(dirname "$0")/.."

log() { echo "[$(date '+%H:%M:%S')] WRAPPER: $*"; }

BACKOFF=10
MAX_BACKOFF=300

while true; do
    log "Starting election night runner..."
    ./scripts/election-night.sh "$@"
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        log "Runner exited cleanly (code 0) — stopping"
        break
    fi

    log "Runner crashed (exit code $EXIT_CODE) — restarting in ${BACKOFF}s"
    sleep "$BACKOFF"

    # Exponential backoff, capped
    BACKOFF=$((BACKOFF * 2))
    if [ $BACKOFF -gt $MAX_BACKOFF ]; then
        BACKOFF=$MAX_BACKOFF
    fi
done
