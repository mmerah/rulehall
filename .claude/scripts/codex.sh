#!/usr/bin/env bash
# codex.sh MODEL EFFORT SANDBOX < prompt  →  prints codex's final message; full event log path on stderr.
set -euo pipefail
log=$(mktemp /tmp/codex-XXXX.log)
echo "codex log: $log" >&2
codex exec -m "$1" -c "model_reasoning_effort=$2" -s "$3" -C "$PWD" --ephemeral -o "$log.last" - >"$log" 2>&1
cat "$log.last"
