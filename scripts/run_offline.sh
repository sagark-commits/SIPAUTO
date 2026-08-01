#!/usr/bin/env bash
# Run SIPAUTO with zero pip installs (stdlib + OpenSSH only).
# Usage: ./scripts/run_offline.sh version
#        ./scripts/run_offline.sh parse-sheet -s examples/carrier_sheets/tata_sample.txt -o /tmp/inv.yaml
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

pick_python() {
  for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver="$("$cand" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
      major="${ver%%.*}"; minor="${ver#*.}"
      if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; }; then
        echo "$cand"; return 0
      fi
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  echo "ERROR: Need Python 3.10+ (Rocky 8: dnf install -y python3.11)" >&2
  exit 1
fi
exec "$PY" -m sipauto "$@"
