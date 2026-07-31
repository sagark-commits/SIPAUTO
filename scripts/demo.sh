#!/usr/bin/env bash
# Local SIPAUTO demo: tests → generate all providers → verify → dry-run apply/reload
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.local/bin:${PATH}"

pip install -e ".[dev]" -q
ARTIFACT_DIR="${ARTIFACT_DIR:-/opt/cursor/artifacts/sipauto-demo}"
mkdir -p "$ARTIFACT_DIR"
LOG="$ARTIFACT_DIR/demo_run.log"

exec > >(tee "$LOG") 2>&1

echo "=============================================="
echo "SIPAUTO DEMO RUN — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="

echo "### tests"
sipauto version
pytest -q

echo "### generate (non-interactive iface — use inventory value)"
for inv in examples/inventories/*.yaml; do
  sipauto generate -i "$inv" --no-ask-iface
done
echo "### ifaces (local discovery)"
sipauto ifaces -i examples/inventories/tata_ameyo.yaml || true

echo "### validate + verify"
for inv in examples/inventories/*.yaml; do
  sipauto validate -i "$inv" || true
done
sipauto verify -i examples/inventories/tata_ameyo.yaml || true
sipauto verify -i examples/inventories/vodafone_freepbx.yaml || true

echo "### dry-run apply/reload (no real SSH)"
python3 - <<'PY'
from pathlib import Path
import yaml
from sipauto.models import Inventory, SSHConfig
from sipauto.workflow.apply import apply_sip, apply_network, reload_services

inv = Inventory.model_validate(yaml.safe_load(Path("examples/inventories/tata_ameyo.yaml").read_text()))
inv.ssh = SSHConfig(host="127.0.0.1", user="root", password="unused")
print("--- apply-net dry-run ---")
print("\n".join(apply_network(inv, dry_run=True)))
print("--- apply-sip dry-run (ameyo write yes) ---")
print("\n".join(apply_sip(inv, "out/demo-tata", ameyo_write=True, dry_run=True)))
print("--- reload dry-run ---")
print("\n".join(reload_services(inv, dry_run=True)))
PY

echo "### full run generate+verify"
sipauto run -i examples/inventories/tata_ameyo.yaml -o "$ARTIFACT_DIR/tata-out" --no-ask-iface

cp -a out/demo-tata out/demo-jio out/demo-airtel out/demo-vodafone "$ARTIFACT_DIR/" 2>/dev/null || true
echo "DEMO COMPLETE — log: $LOG"
