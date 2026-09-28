#!/usr/bin/env bash
# Restart the QA server: qa/serve.sh [--art]; QA_DELAY=1.2 slows every role call for a demo
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${QA_PORT:-8123}"
WORK="${QA_WORK:-/tmp/rulehall-qa-work}"
LOG="${QA_LOG:-/tmp/rulehall-qa-server-$PORT.log}"
old=$(pgrep -f "qa/server.py --port $PORT " || true)
for pid in $old; do kill "$pid" 2>/dev/null || true; done
for pid in $old; do while kill -0 "$pid" 2>/dev/null; do sleep 0.1; done; done
cd "$ROOT"
nohup uv run python qa/server.py --port "$PORT" --work "$WORK" --fresh --delay "${QA_DELAY:-0}" "$@" > "$LOG" 2>&1 &
for _ in $(seq 1 100); do
  if curl -s -o /dev/null http://localhost:$PORT/; then echo "up"; exit 0; fi
  sleep 0.2
done
echo "server did not start"; tail -20 "$LOG"; exit 1
