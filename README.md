# SIPAUTO

**Configure SIP with Automation** — interactive CLI to provision on-prem SIP trunks for **Ameyo + Asterisk** and **FreePBX** on **Rocky / Red Hat**, for **Tata, Jio, Airtel, and Vodafone-Idea**.

Paste a carrier sheet → pick the SIP NIC → generate configs → preflight (GREEN/YELLOW/RED) → apply/reload (SSH or local) → watch registry → roll back if needed.

Author — Sagar Kumar (sk)

## Offline / air-gapped (no internet, no pip)

Runtime needs only **Python 3.10+** and **OpenSSH clients**. Copy the repo (or zip) onto the call server:

```bash
dnf install -y python3.11 openssh-clients iproute ethtool
cd /path/to/SIPAUTO-main
chmod +x scripts/run_offline.sh scripts/bootstrap_rocky.sh
./scripts/bootstrap_rocky.sh
./scripts/run_offline.sh wizard --sheet examples/carrier_sheets/tata_sample.txt
```

Or:

```bash
export PYTHONPATH=$PWD/src
python3.11 -m sipauto version
python3.11 -m sipauto parse-sheet -s examples/carrier_sheets/tata_sample.txt -o /tmp/inv.yaml --site mysite -I eth1
python3.11 -m sipauto generate -i /tmp/inv.yaml -I eth1 --no-ask-iface
python3.11 -m sipauto preflight -i /tmp/inv.yaml
```

## How to use

**Full guide:** **[docs/HOW_TO_USE.md](docs/HOW_TO_USE.md)**

## Quick start

```bash
# Guided wizard (recommended) — skip SSH if you are already on the Ameyo host
./scripts/run_offline.sh wizard --sheet examples/carrier_sheets/tata_sample.txt

# Step-by-step
./scripts/run_offline.sh parse-sheet -s examples/carrier_sheets/tata_sample.txt -o out/inv.yaml --site mysite -I eth1
./scripts/run_offline.sh generate -i out/inv.yaml -I eth1 --no-ask-iface
./scripts/run_offline.sh preflight -i out/inv.yaml
./scripts/run_offline.sh apply-net -i out/inv.yaml --local   # when running ON the call server
./scripts/run_offline.sh apply-sip -i out/inv.yaml --ameyo-write --local
./scripts/run_offline.sh registry-watch -i out/inv.yaml
./scripts/run_offline.sh rollback -i out/inv.yaml --dry-run
```

## Intelligence / safety

- Validates SSH hosts (rejects typos like `10.192.168.56.10`)
- Wizard **never crashes** on bad SSH — falls back to **LOCAL** mode
- Detects `/etc/asterisk` and prefers local apply on the call server
- Auto-picks the only physical NIC when unambiguous
- Aligns generate interface with inventory used by preflight

## Docs

- [docs/HOW_TO_USE.md](docs/HOW_TO_USE.md)
- [docs/SIPAUTO_PLAN.md](docs/SIPAUTO_PLAN.md)
