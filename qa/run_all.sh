#!/usr/bin/env bash
# Run every scenario on a fresh server each: qa/run_all.sh [scenario ...]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PW="uv run --group qa python"
cd "$ROOT"
scenarios=("$@")
[ ${#scenarios[@]} -eq 0 ] && scenarios=(home loner goons 24xx settings create mobile burst requests endure pokemon)
for name in "${scenarios[@]}"; do
  qa/serve.sh > /dev/null || exit 1
  echo "### $name"
  $PW "qa/s_$name.py" 2>&1 | grep -E "^(ISSUE|NOTE|==| - )|Error|Traceback|File \"/home.*qa/|waiting for" | grep -v "GL Driver"
done
