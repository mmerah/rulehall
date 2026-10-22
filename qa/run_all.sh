#!/usr/bin/env bash
# Run every scenario on a fresh server each: qa/run_all.sh [scenario ...]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PW="uv run --group qa python"
cd "$ROOT"
scenarios=("$@")
[ ${#scenarios[@]} -eq 0 ] && scenarios=(home loner goons 24xx settings create mobile burst requests pokemon champions lite5e long)
for name in "${scenarios[@]}"; do
  flags=()
  [ "$name" = long ] && flags=(--speech)
  qa/serve.sh "${flags[@]}" > /dev/null || exit 1
  echo "### $name"
  $PW "qa/s_$name.py" 2>&1 | grep -E "^(ISSUE|NOTE|==| - )|Error|Traceback|File \"/home.*qa/|waiting for" | grep -v "GL Driver"
done
