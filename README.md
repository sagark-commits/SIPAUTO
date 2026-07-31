# SIPAUTO

Automate on-prem SIP trunk configuration for **Ameyo + Asterisk** and **FreePBX** on **Rocky / Red Hat**, for Indian carriers **Tata, Jio, Airtel, Vodafone-Idea**.

## Recommended flow

```text
generate → verify → apply-net (SSH) → apply-sip (SSH; Ameyo write asked) → reload
```

```bash
# install (dev)
pip install -e ".[dev]"

# List NICs (local or on call server)
sipauto ifaces
sipauto ifaces -i examples/inventories/tata_ameyo.yaml --ssh

# 1) Generate — ASKS which interface to use for SIP (default)
sipauto generate -i examples/inventories/tata_ameyo.yaml
# non-interactive / CI:
sipauto generate -i examples/inventories/tata_ameyo.yaml --no-ask-iface
# or pin iface and optionally save into YAML:
sipauto generate -i examples/inventories/tata_ameyo.yaml -I eth1 --save-iface

# 2) Verify (local port probes; use --ssh on the call server)
sipauto verify -i examples/inventories/tata_ameyo.yaml
sipauto verify -i examples/inventories/tata_ameyo.yaml --ssh

# 3) Apply network (asks SIP NIC again unless -I / --yes)
sipauto apply-net -i examples/inventories/tata_ameyo.yaml

# 4) Apply SIP — Ameyo write is OPTIONAL and prompted
sipauto apply-sip -i examples/inventories/tata_ameyo.yaml

# 5) Reload Asterisk SIP/PJSIP/RTP
sipauto reload -i examples/inventories/tata_ameyo.yaml

# Or one shot (asks SIP NIC, then Ameyo write)
sipauto run -i examples/inventories/tata_ameyo.yaml --ssh --apply
```

## Inventory

See `examples/inventories/`:

| File | Provider | Platform |
|------|----------|----------|
| `tata_ameyo.yaml` | Tata | Ameyo + Asterisk |
| `jio_ameyo.yaml` | Jio | Ameyo + Asterisk |
| `airtel_ameyo.yaml` | Airtel | Ameyo + Asterisk |
| `vodafone_freepbx.yaml` | Vodafone-Idea | FreePBX (PJSIP) |

Set `ssh:` in inventory for remote apply/verify/reload.

## Port checks

- **SIP signaling:** TCP and UDP to SBC port (default `5060`), both sides.
- **RTP:** UDP **10000–40000** both sides (local firewall + carrier). Sampled probes + `rtp.conf` / firewall inspection over SSH.

## Docs

- [docs/SIPAUTO_PLAN.md](docs/SIPAUTO_PLAN.md) — architecture, accuracy, phases

## Tests

```bash
pytest -q
```
