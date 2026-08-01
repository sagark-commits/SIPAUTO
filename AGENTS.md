# AGENTS.md

## Cursor Cloud specific instructions

### Product

`sipauto` is a **stdlib-only** Python CLI that automates on-prem SIP trunk setup for Ameyo+Asterisk and FreePBX (Rocky/RHEL) for Tata/Jio/Airtel/Vodafone-Idea. Runtime deps: Python ≥3.10 + OpenSSH (`ssh`/`scp`). Optional `sshpass` for password auth. No PyPI packages required.

Operator docs: `docs/HOW_TO_USE.md`.

### Setup

```bash
# Preferred (offline):
export PYTHONPATH=$PWD/src
python3 -m sipauto version
# or:
./scripts/run_offline.sh version
./scripts/bootstrap_rocky.sh   # offline by default

# Optional (tests only):
python3 -m pip install pytest
pytest -q
```

### Standard commands

- Tests: `pytest -q` (with `PYTHONPATH=src`)
- Offline runner: `./scripts/run_offline.sh <cmd> …`
- Wizard: `python3 -m sipauto wizard --sheet examples/carrier_sheets/tata_sample.txt`
- Parse / generate / preflight / apply / registry / rollback — see README

### Gotchas

- Example SBC IPs are private RFC1918 — local `verify` port probes often fail (expected). Prefer running on the call server; use `--ssh` only with working keys.
- Invalid SSH hosts (e.g. `10.192.168.56.10`) are rejected; wizard degrades to LOCAL instead of crashing.
- Ameyo write is interactive; non-interactive only with `--yes` and `SIPAUTO_AMEYO_WRITE=1`.
- Apply on the call server: `--local` (or omit `ssh:` and run where `/etc/asterisk` exists).
- Vodafone template targets **Vi India** Ethernet/IP-auth, not German Anlagen-Anschluss.
- Do not put real carrier passwords in git; example Airtel inventory uses `CHANGE_ME`.
