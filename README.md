# SIPAUTO

**Configure SIP with Automation** for on-prem trunks on **Ameyo + Asterisk** and **FreePBX** (Rocky / Red Hat).

Carriers: **Tata · Jio · Airtel · Vodafone-Idea**

Author — Sagar Kumar (sk)

## Docs

**→ Full guide: [docs/HOW_TO_USE.md](docs/HOW_TO_USE.md)**

## 60-second start (no internet, no pip)

```bash
cd /path/to/SIPAUTO-main
dnf install -y python3.11 openssh-clients iproute ethtool
chmod +x scripts/*.sh
./scripts/bootstrap_rocky.sh

./scripts/run_offline.sh wizard --sheet examples/carrier_sheets/tata_sample.txt
```

Already on the Ameyo host? Answer **n** to SSH, then apply with `--local`.

## Common commands

```bash
# parse-sheet / preflight list real NICs and ask which one is for SIP
./scripts/run_offline.sh parse-sheet -s examples/carrier_sheets/tata_sample.txt -o out/inv.yaml --site mysite
./scripts/run_offline.sh generate -i out/inv.yaml          # asks SIP NIC
./scripts/run_offline.sh preflight -i out/inv.yaml         # asks SIP NIC if needed, saves it
./scripts/run_offline.sh apply-net -i out/inv.yaml --local --yes
./scripts/run_offline.sh apply-sip -i out/inv.yaml --ameyo-write --local --yes
./scripts/run_offline.sh registry-watch -i out/inv.yaml
./scripts/run_offline.sh rollback -i out/inv.yaml --dry-run
```

## Flow

```text
wizard  (or)  parse-sheet → generate → preflight → apply-net → apply-sip → reload → registry-watch
```

## Notes

- Runtime: Python **3.10+** stdlib + OpenSSH only  
- Rocky 8: use **python3.11** (not system python 3.6)  
- Design notes: [docs/SIPAUTO_PLAN.md](docs/SIPAUTO_PLAN.md)  
