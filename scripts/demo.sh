#!/usr/bin/env bash
# Local SIPAUTO demo — offline (no pip). Optional: INSTALL_DEPS=1 for pytest via pip.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${HOME}/.local/bin:${PATH}"

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
PY="$(pick_python)"
RUN=("$PY" -m sipauto)

ARTIFACT_DIR="${ARTIFACT_DIR:-/opt/cursor/artifacts/sipauto-demo}"
mkdir -p "$ARTIFACT_DIR"
LOG="$ARTIFACT_DIR/demo_run.log"
exec > >(tee "$LOG") 2>&1

echo "=============================================="
echo "SIPAUTO DEMO RUN — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="

echo "### version"
"${RUN[@]}" version

if command -v pytest >/dev/null 2>&1; then
  echo "### tests"
  pytest -q
else
  echo "### tests skipped (pytest not installed; offline OK)"
fi

echo "### generate (non-interactive iface)"
for inv in examples/inventories/*.yaml; do
  "${RUN[@]}" generate -i "$inv" --no-ask-iface
done
echo "### ifaces (local discovery)"
"${RUN[@]}" ifaces -i examples/inventories/tata_ameyo.yaml || true

echo "### parse-sheet"
"${RUN[@]}" parse-sheet -s examples/carrier_sheets/tata_sample.txt -o "$ARTIFACT_DIR/parsed-tata.yaml" --site demo-parsed-tata
"${RUN[@]}" parse-sheet -s examples/carrier_sheets/jio_sample.txt -o "$ARTIFACT_DIR/parsed-jio.yaml" --site demo-parsed-jio --provider jio
"${RUN[@]}" parse-sheet -s examples/carrier_sheets/airtel_sample.txt -o "$ARTIFACT_DIR/parsed-airtel.yaml" --site demo-parsed-airtel --provider airtel

echo "### preflight (local)"
"${RUN[@]}" preflight -i examples/inventories/tata_ameyo.yaml || true

echo "### diagnose"
"${RUN[@]}" diagnose "SIP/2.0 407 Proxy Authentication Required" || true
"${RUN[@]}" diagnose "outbound 403 Forbidden" || true

echo "### validate + verify"
for inv in examples/inventories/*.yaml; do
  "${RUN[@]}" validate -i "$inv" || true
done
"${RUN[@]}" verify -i examples/inventories/tata_ameyo.yaml || true

echo "### dry-run apply/reload"
"$PY" - <<'PY'
from pathlib import Path
from sipauto.models import Inventory, SSHConfig
from sipauto.util import simple_yaml
from sipauto.workflow.apply import apply_sip, apply_network, reload_services

inv = Inventory.model_validate(simple_yaml.loads_file("examples/inventories/tata_ameyo.yaml"))
inv.ssh = SSHConfig(host="127.0.0.1", user="root", password="unused")
print("--- apply-net dry-run ---")
print("\n".join(apply_network(inv, dry_run=True)))
print("--- apply-sip dry-run ---")
print("\n".join(apply_sip(inv, "out/demo-tata", ameyo_write=True, dry_run=True)))
print("--- reload dry-run ---")
print("\n".join(reload_services(inv, dry_run=True)))
PY

echo "### full run generate+verify"
"${RUN[@]}" run -i examples/inventories/tata_ameyo.yaml -o "$ARTIFACT_DIR/tata-out" --no-ask-iface

cp -a out/demo-tata out/demo-jio out/demo-airtel out/demo-vodafone "$ARTIFACT_DIR/" 2>/dev/null || true
echo "DEMO COMPLETE — log: $LOG"
