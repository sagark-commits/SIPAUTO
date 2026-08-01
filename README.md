# SIPAUTO

Automate on-prem SIP trunk configuration for **Ameyo + Asterisk** and **FreePBX** on **Rocky / Red Hat**, for Indian carriers **Tata, Jio, Airtel, Vodafone-Idea**.

## How to use

**Full guide with every command and examples:**  
**[docs/HOW_TO_USE.md](docs/HOW_TO_USE.md)**

## Quick start

```bash
pip install -e ".[dev]"
export PATH="$HOME/.local/bin:$PATH"

# Guided wizard (recommended)
sipauto wizard --sheet examples/carrier_sheets/tata_sample.txt

# Or step-by-step
sipauto parse-sheet -s examples/carrier_sheets/tata_sample.txt -o out/inv.yaml --site mysite -I eth1
sipauto generate -i out/inv.yaml -I eth1
sipauto preflight -i out/inv.yaml          # add ssh: then use --ssh
sipauto apply-net -i out/inv.yaml          # needs ssh:
sipauto apply-sip -i out/inv.yaml          # asks before Ameyo write
sipauto registry-watch -i out/inv.yaml
sipauto rollback -i out/inv.yaml --dry-run # if needed
```

```text
wizard  (or)  parse-sheet → generate → preflight → apply-net → apply-sip → registry-watch
                                                              ↘ rollback if needed
```

## Command cheat sheet

| Command | Purpose |
|---------|---------|
| `sipauto wizard` | Full guided setup |
| `sipauto parse-sheet -s sheet.txt -o inv.yaml` | Carrier email/sheet → inventory |
| `sipauto ifaces` | List NICs (ask which one for SIP on generate) |
| `sipauto generate -i inv.yaml` | Build ifcfg/routes/SIP artifacts |
| `sipauto preflight -i inv.yaml [--ssh]` | GREEN/YELLOW/RED before apply |
| `sipauto apply-net` / `apply-sip` / `reload` | SSH apply + Asterisk reload |
| `sipauto registry-watch -i inv.yaml` | Registry + OPTIONS + dial test |
| `sipauto diagnose "407 …"` | Map SIP errors to fixes |
| `sipauto rollback -i inv.yaml` | Restore `*.sipauto.bak` |

## Examples in repo

| Path | What |
|------|------|
| `examples/carrier_sheets/` | Sample Tata/Jio/Airtel delivery text |
| `examples/inventories/` | Ready inventory YAML per provider |
| `scripts/demo.sh` | Local demo (no real SSH/carrier) |

## Docs

- **[docs/HOW_TO_USE.md](docs/HOW_TO_USE.md)** — commands & examples  
- [docs/SIPAUTO_PLAN.md](docs/SIPAUTO_PLAN.md) — architecture / accuracy  
- [AGENTS.md](AGENTS.md) — notes for cloud agents  

## Tests

```bash
pytest -q
./scripts/demo.sh
```
