#!/usr/bin/env bash
# Bootstrap SIPAUTO on Rocky/RHEL.
# Default: OFFLINE — no PyPI. Optional: SIPAUTO_ONLINE=1 to pip install editable.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

pick_python() {
  for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver="$("$cand" -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
      major="${ver%%.*}"
      minor="${ver#*.}"
      if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; }; then
        echo "$cand"
        return 0
      fi
    fi
  done
  return 1
}

echo "==> Looking for Python >= 3.10"
if ! PY="$(pick_python)"; then
  echo "ERROR: Need Python 3.10+ (system python3.6/3.8 is not enough)."
  echo "On Rocky 8/9 try:"
  echo "  dnf install -y python3.11 python3.11-pip python3.11-devel gcc openssh-clients iproute ethtool"
  exit 1
fi
echo "Using: $PY ($($PY --version))"

echo "==> Ensuring OpenSSH client (ssh/scp)"
if ! command -v ssh >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y openssh-clients iproute ethtool || true
  fi
fi

chmod +x "$ROOT/scripts/run_offline.sh" 2>/dev/null || true

if [[ "${SIPAUTO_ONLINE:-0}" == "1" ]]; then
  echo "==> ONLINE mode: pip install -e . (optional; not required)"
  TRUST=(
    --trusted-host pypi.org
    --trusted-host files.pythonhosted.org
    --trusted-host pypi.python.org
  )
  $PY -m ensurepip --upgrade 2>/dev/null || true
  $PY -m pip install "${TRUST[@]}" -U pip setuptools wheel
  $PY -m pip install "${TRUST[@]}" -e ".[dev]"
  export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
  hash -r || true
fi

echo "==> Offline smoke test"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
$PY -m sipauto version
$PY -m sipauto parse-sheet -s examples/carrier_sheets/tata_sample.txt -o /tmp/sipauto-smoke.yaml --site smoke -I eth1
echo
echo "DONE — no internet required for daily use:"
echo "  export PYTHONPATH=$ROOT/src"
echo "  $PY -m sipauto wizard --sheet examples/carrier_sheets/tata_sample.txt"
echo "  # or: $ROOT/scripts/run_offline.sh wizard --sheet examples/carrier_sheets/tata_sample.txt"
