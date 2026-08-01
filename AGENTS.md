# AGENTS.md

## Cursor Cloud specific instructions

### Product

`sipauto` is a Python CLI that automates on-prem SIP trunk setup for Ameyo+Asterisk and FreePBX (Rocky/RHEL) for Tata/Jio/Airtel/Vodafone-Idea. It includes a guided wizard, carrier-sheet parser, NIC picker, preflight scoring, SSH apply/reload, registry watch with SIP error playbooks, and `*.sipauto.bak` rollback. Operator docs: `docs/HOW_TO_USE.md`.

### Setup

```bash
pip install -e ".[dev]"
```

### Standard commands

- Lint/tests: `pytest -q`
- Wizard: `sipauto wizard --sheet examples/carrier_sheets/tata_sample.txt`
- Parse sheet: `sipauto parse-sheet -s examples/carrier_sheets/tata_sample.txt -o out/inv.yaml`
- Generate: `sipauto generate -i …` (asks SIP NIC by default; use `--no-ask-iface` in CI)
- Preflight: `sipauto preflight -i … [--ssh]` (exit 1=RED, 3=YELLOW)
- Registry: `sipauto registry-watch -i …` (needs SSH)
- Rollback: `sipauto rollback -i … --dry-run` then `--yes`
- SSH apply requires `ssh:` in inventory and network access to the call server

### Gotchas

- Example SBC IPs are private RFC1918 — local `verify` port probes to them will often fail (expected). Use `--ssh` on a real call server.
- Ameyo write is interactive by design; non-interactive only with `--yes` and `SIPAUTO_AMEYO_WRITE=1`.
- Vodafone template targets **Vi India** Ethernet/IP-auth (public guides), not German Vodafone Anlagen-Anschluss.
- Do not put real carrier passwords in git; example Airtel inventory uses `CHANGE_ME`.
