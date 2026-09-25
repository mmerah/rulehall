#!/usr/bin/env bash
# Restart the QA server: qa/serve.sh [--delay 1.2]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${QA_WORK:-/tmp/rulehall-qa-work}"
LOG="${QA_LOG:-/tmp/rulehall-qa-server.log}"
for pid in $(pgrep -f "qa/server.py" || true); do kill "$pid" 2>/dev/null || true; done
sleep 1
cd "$ROOT"
nohup uv run python qa/server.py --port 8123 --work "$WORK" --fresh --delay "${QA_DELAY:-1.2}" "$@" > "$LOG" 2>&1 &
for _ in $(seq 1 40); do
  if curl -s -o /dev/null http://localhost:8123/; then echo "up"; exit 0; fi
  sleep 0.5
done
echo "server did not start"; tail -20 "$LOG"; exit 1
