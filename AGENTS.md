# AGENTS.md

## Cursor Cloud specific instructions

### Product

`sipauto` is a Python CLI that generates/verifies/applies on-prem SIP trunk config for Ameyo+Asterisk and FreePBX (Rocky/RHEL) for Tata/Jio/Airtel/Vodafone-Idea.

### Setup

```bash
pip install -e ".[dev]"
```

### Standard commands

- Lint/tests: `pytest -q`
- Generate: `sipauto generate -i examples/inventories/tata_ameyo.yaml`
- Full local demo without SSH: `sipauto run -i examples/inventories/tata_ameyo.yaml`
- SSH apply requires `ssh:` in inventory and network access to the call server

### Gotchas

- Example SBC IPs are private RFC1918 — local `verify` port probes to them will often fail (expected). Use `--ssh` on a real call server.
- Ameyo write is interactive by design; non-interactive only with `--yes` and `SIPAUTO_AMEYO_WRITE=1`.
- Vodafone template targets **Vi India** Ethernet/IP-auth (public guides), not German Vodafone Anlagen-Anschluss.
- Do not put real carrier passwords in git; example Airtel inventory uses `CHANGE_ME`.
