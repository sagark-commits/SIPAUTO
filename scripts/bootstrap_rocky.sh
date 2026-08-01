#!/usr/bin/env bash
# Bootstrap SIPAUTO on Rocky/RHEL call servers with common SSL/proxy CA issues.
# Requires network to PyPI (or a mirror). Needs Python >= 3.10.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TRUST=(
  --trusted-host pypi.org
  --trusted-host files.pythonhosted.org
  --trusted-host pypi.python.org
)

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
  echo "  dnf install -y python3.11 python3.11-pip python3.11-devel gcc libffi-devel openssl-devel"
  echo "  # or: dnf module enable python311 && dnf install -y python3.11"
  exit 1
fi
echo "Using: $PY ($($PY --version))"

echo "==> Ensuring pip"
$PY -m ensurepip --upgrade 2>/dev/null || true
$PY -m pip install "${TRUST[@]}" -U pip setuptools wheel

echo "==> Installing SIPAUTO (editable + dev)"
$PY -m pip install "${TRUST[@]}" -e ".[dev]"

echo "==> PATH hint"
echo "export PATH=\"\$HOME/.local/bin:/usr/local/bin:\$PATH\""
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
hash -r || true
if command -v sipauto >/dev/null 2>&1; then
  sipauto version
else
  echo "sipauto not on PATH yet; run:"
  echo "  $PY -m sipauto.cli --help"
fi
echo "DONE"
