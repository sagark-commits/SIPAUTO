# SIPAUTO — How to Use

End-to-end guide with commands and examples for on-prem SIP trunk setup
(**Ameyo + Asterisk** / **FreePBX** on **Rocky / Red Hat**; carriers **Tata, Jio, Airtel, Vodafone-Idea**).

---

## 1. Install

### Rocky / Red Hat (recommended for call servers)

`pip` is often missing by default. Install Python tooling first:

```bash
# as root (or sudo)
dnf install -y python3 python3-pip python3-devel gcc libffi-devel openssl-devel

cd /path/to/SIPAUTO-main   # or SIPAUTO
python3 -m pip install -U pip setuptools wheel
python3 -m pip install -e ".[dev]"

# CLI lands in ~/.local/bin for non-root, or /usr/local/bin depending on pip
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
hash -r
sipauto version
# if still not found:
python3 -m sipauto.cli version
# or
python3 -c "from sipauto.cli import app; print('ok')"
```

Prefer **`python3 -m pip`** over bare `pip` / `pip3` (avoids “command not found” and wrong Python).

Optional system packages used by discovery/verify on the box:

```bash
dnf install -y iproute ethtool
```

### Generic (any Linux with pip already available)

```bash
cd /path/to/SIPAUTO
python3 -m pip install -e ".[dev]"
export PATH="$HOME/.local/bin:$PATH"
sipauto version
```

Run the local demo (no real carrier/SSH required):

```bash
./scripts/demo.sh
# or
pytest -q
```

### Troubleshoot: `-bash: pip: command not found`

| Cause | Fix |
|-------|-----|
| `pip` not installed | `dnf install -y python3-pip` then use `python3 -m pip …` |
| `pip` installed but not on PATH | `export PATH="$HOME/.local/bin:$PATH"` **after** a successful pip install |
| Wrong command | Use `python3 -m pip install -e ".[dev]"` not `pip install …` |
| `sipauto: command not found` after install | Same PATH export, or run `python3 -m sipauto.cli --help` |

---

## 2. Concepts (short)

| Piece | Meaning |
|-------|---------|
| **Inventory YAML** | Site inputs: provider, NIC, IPs, pilot, password, SSH |
| **Carrier sheet** | Text from provider email/PDF (Customer IP, Gateway, SBC, Pilot, Media IPs…) |
| **Artifacts** | Generated files under `out/<site>/` (ifcfg, routes, Global SIP, peers…) |
| **Apply** | SSH-write configs to the call server (creates `*.sipauto.bak`) |
| **Preflight** | Score readiness **GREEN / YELLOW / RED** before apply |
| **Rollback** | Restore from `*.sipauto.bak` |

**Typical flow:**

```text
wizard
  └─ provider → paste sheet → pick NIC → generate → preflight → ask apply
       → registry-watch → rollback (if needed)
```

**Manual flow:**

```text
parse-sheet → generate → preflight → apply-net → apply-sip → reload → registry-watch
```

---

## 3. Fastest path — Guided wizard

### Interactive

```bash
sipauto wizard
# 1) pick provider (Tata/Jio/Airtel/Vi)
# 2) paste carrier sheet, then type END
# 3) pick SIP NIC from the list
# 4) generate + verify + preflight
# 5) confirm before network/SIP apply (Ameyo write asked separately)
```

### From a saved sheet file

```bash
sipauto wizard --sheet examples/carrier_sheets/tata_sample.txt
```

### Non-interactive (CI / scripted)

```bash
sipauto wizard --yes \
  --sheet examples/carrier_sheets/tata_sample.txt \
  --provider tata \
  --site my-tata-site \
  --interface eth1 \
  --platform ameyo_asterisk \
  --out out
```

Creates:

- `out/my-tata-site/inventory.yaml`
- `out/my-tata-site/ameyo/…` (Global SIP, custom config, peers, UI checklist)
- `out/my-tata-site/network/ifcfg`, `route`, …
- `out/my-tata-site/preflight_report.json`, `verify_report.json`

---

## 4. Carrier sheet → inventory

Paste provider delivery text (or use samples under `examples/carrier_sheets/`).

```bash
# Tata
sipauto parse-sheet \
  -s examples/carrier_sheets/tata_sample.txt \
  -o out/tata-inv.yaml \
  --site cashify-tata \
  -I eth1 \
  --platform ameyo_asterisk

# Jio
sipauto parse-sheet \
  -s examples/carrier_sheets/jio_sample.txt \
  -o out/jio-inv.yaml \
  --provider jio \
  --site site-jio \
  -I eno3

# Airtel
sipauto parse-sheet \
  -s examples/carrier_sheets/airtel_sample.txt \
  -o out/airtel-inv.yaml \
  --provider airtel \
  --site site-airtel \
  -I eth1

# From stdin
cat my_carrier_email.txt | sipauto parse-sheet -o out/inv.yaml --site from-email
```

**Example sheet (Tata):**

```text
Customer IP: 10.0.80.98
Subnet Mask: 255.255.255.252
Gateway IP: 10.0.80.97
SBC IP: 10.0.76.11
Pilot no.: 8068167000
DID Range: 8068167000 to 8068167399
Password: 1234
Media IP: 10.0.76.12
```

Parser extracts IPs, pilot, DID range, password, VLAN, media IPs, and detects provider when possible.

---

## 5. Inventory YAML

Ready-made examples:

| File | Provider | Platform |
|------|----------|----------|
| `examples/inventories/tata_ameyo.yaml` | Tata | Ameyo + Asterisk |
| `examples/inventories/jio_ameyo.yaml` | Jio | Ameyo + Asterisk |
| `examples/inventories/airtel_ameyo.yaml` | Airtel | Ameyo + Asterisk |
| `examples/inventories/vodafone_freepbx.yaml` | Vodafone-Idea | FreePBX (PJSIP) |

**Minimal shape:**

```yaml
site:
  name: my-site
  mode: onprem

provider: tata          # tata | jio | airtel | vodafone
platform: ameyo_asterisk  # ameyo_asterisk | freepbx | asterisk
sip_driver: chan_sip      # chan_sip | pjsip

network:
  interface: eth1
  customer_ip: 10.0.80.98
  gateway_ip: 10.0.80.97
  netmask: 255.255.255.252
  sbc_ip: 10.0.76.11
  sbc_port: 5060
  media_ips:
    - 10.0.76.12
  sip_transport: both     # udp | tcp | both
  rtp_start: 10000
  rtp_end: 40000

sip:
  pilot: "8068167000"
  username: "68167000"    # Tata: often pilot without STD
  password: "1234"
  codecs: [alaw, ulaw, g729]

ameyo:
  voice_resource: DefaultVR
  entity_name: tata
  context_name: tata-ctx
  asterisk_etc: /etc/asterisk

# Required for apply / preflight --ssh / registry-watch / rollback
ssh:
  host: 10.10.10.50
  user: root
  key_path: ~/.ssh/id_rsa
  # password: "..."       # optional if not using key
```

Validate:

```bash
sipauto validate -i examples/inventories/tata_ameyo.yaml
```

---

## 6. Network interfaces

List NICs (local or on call server) with link/speed when `ethtool` is available:

```bash
sipauto ifaces
sipauto ifaces -i examples/inventories/tata_ameyo.yaml --ssh
sipauto ifaces --all    # include virtual NICs
```

Example output:

```text
 #  Name   State  IPv4            Link  Speed
 1  eth0   UP     10.10.10.5/24   yes   1000Mb/s
 2  eth1   DOWN   -               no    ?
* inventory default: eth1
```

`generate`, `apply-net`, and `run` **ask which interface to use for SIP** by default.

```bash
# answer interactively
sipauto generate -i out/tata-inv.yaml

# skip prompt
sipauto generate -i out/tata-inv.yaml --no-ask-iface
sipauto generate -i out/tata-inv.yaml -I eth1

# save choice back into YAML
sipauto generate -i out/tata-inv.yaml -I eth1 --save-iface
```

---

## 7. Generate artifacts

```bash
sipauto generate -i examples/inventories/tata_ameyo.yaml
# → out/demo-tata/

sipauto generate -i examples/inventories/vodafone_freepbx.yaml -o out/vf
```

**What you get (Ameyo example):**

```text
out/demo-tata/
  MANIFEST.json
  network/ifcfg                 # Rocky/RHEL ifcfg
  network/route                 # SBC + media host routes
  network/hosts.snippet         # Airtel ims.airtel.in etc.
  asterisk/rtp.conf.snippet     # rtpstart=10000 / rtpend=40000
  ameyo/ameyo_global_sip.conf.txt
  ameyo/ameyo_call_entity_custom.conf.txt
  ameyo/asterisk_peer_tata.conf
  ameyo/asterisk_pjsip_tata.conf
  ameyo/ameyo_ui_checklist.md
  ameyo/NOTES.md
```

**Example generated Global SIP (Tata):**

```text
disallow=all
allow=alaw
allow=ulaw
allow=g729
register => 68167000:1234@10.0.76.11/68167000
defaultexpiry=300
```

**Example routes:**

```text
10.0.76.11/32 via 10.0.80.97 dev eth1
10.0.76.12/32 via 10.0.80.97 dev eth1
```

---

## 8. Verify & preflight

### Verify (ports / artifacts)

```bash
sipauto verify -i examples/inventories/tata_ameyo.yaml
sipauto verify -i examples/inventories/tata_ameyo.yaml --ssh
```

Checks SIP UDP/TCP toward SBC, RTP sample ports, RTP range policy `10000–40000`.

### Preflight (score before apply)

```bash
sipauto preflight -i examples/inventories/tata_ameyo.yaml
sipauto preflight -i examples/inventories/tata_ameyo.yaml --ssh
echo $?   # 0=GREEN, 3=YELLOW, 1=RED
```

Preflight covers:

- NIC present / link up / speed hints  
- Ping gateway + SBC (SSH)  
- SIP TCP/UDP  
- RTP range + firewall hints  
- Media routes  
- Airtel `/etc/hosts`  
- Exact **next actions** when something fails  

---

## 9. Apply on the call server (SSH)

Inventory must include `ssh:`.

### Network (ifcfg + routes + hosts)

```bash
# dry plan
python - <<'PY'
# or use apply-net after confirming
PY

sipauto apply-net -i out/tata-inv.yaml --dry-run
sipauto apply-net -i out/tata-inv.yaml -I eth1
# prompts: confirm host + iface
```

### SIP files

```bash
# Ameyo: asks before writing Asterisk include snippets
sipauto apply-sip -i out/tata-inv.yaml

# skip Ameyo write (paste pack only)
sipauto apply-sip -i out/tata-inv.yaml --no-ameyo-write

# force Ameyo write
sipauto apply-sip -i out/tata-inv.yaml --ameyo-write --yes
```

Ameyo write:

- Backs up targets as `*.sipauto.bak`
- Writes `/etc/asterisk/sipauto_*` includes
- Does **not** create Call Manager UI rows (use `ameyo_ui_checklist.md`)

### Reload

```bash
sipauto reload -i out/tata-inv.yaml
sipauto reload -i out/tata-inv.yaml --dry-run
```

Runs (as applicable):

```bash
asterisk -rx 'rtp reload'
asterisk -rx 'sip reload'
asterisk -rx 'sip show registry'
# or pjsip equivalents for FreePBX/PJSIP
```

### One-shot run

```bash
sipauto run -i out/tata-inv.yaml --ssh --apply
# picks NIC → generate → verify → apply-net → ask Ameyo write → reload
```

Non-interactive Ameyo write:

```bash
SIPAUTO_AMEYO_WRITE=1 sipauto run -i out/tata-inv.yaml --ssh --apply --yes -I eth1
```

---

## 10. Registry watch, dial test, diagnose

After apply/reload:

```bash
# poll registry + OPTIONS probe
sipauto registry-watch -i out/tata-inv.yaml

# more polls / faster
sipauto registry-watch -i out/tata-inv.yaml --polls 10 --interval 2

# optional originate test call
sipauto registry-watch -i out/tata-inv.yaml --dial 9XXXXXXXXXX
```

Maps common failures to documented fixes:

```bash
sipauto diagnose "SIP/2.0 407 Proxy Authentication Required"
sipauto diagnose "outbound call 403 Forbidden"
sipauto diagnose "480 Temporarily Unavailable"
sipauto diagnose -f /tmp/asterisk_snippet.log
```

| Code | Typical fix (from internal docs) |
|------|----------------------------------|
| **407** | Authuser register form + fromuser; PPI |
| **403** | Remove register (Tata GKB), reload, re-check |
| **480** | PPI with **Customer IP** |
| **408** | Route/firewall to SBC |
| No audio | Add **media IP** routes; RTP `10000–40000` both sides |

---

## 11. Rollback

Every apply backs up prior files to `*.sipauto.bak` and records a manifest at  
`/var/tmp/sipauto-last-apply.json`.

```bash
# see what would be restored
sipauto rollback -i out/tata-inv.yaml --dry-run

# restore ifcfg/routes/hosts/asterisk includes + reload
sipauto rollback -i out/tata-inv.yaml --yes
```

---

## 12. End-to-end examples

### A) Tata on Ameyo (from sheet)

```bash
# 1) Parse sheet
sipauto parse-sheet \
  -s examples/carrier_sheets/tata_sample.txt \
  -o out/tata/inventory.yaml \
  --site prod-tata \
  -I eth1

# 2) Add SSH block to out/tata/inventory.yaml, then:

# 3) Generate (will ask NIC unless -I)
sipauto generate -i out/tata/inventory.yaml -I eth1 -o out/tata

# 4) Preflight on server
sipauto preflight -i out/tata/inventory.yaml --ssh

# 5) Apply
sipauto apply-net -i out/tata/inventory.yaml --yes -I eth1
sipauto apply-sip -i out/tata/inventory.yaml --ameyo-write --yes
sipauto reload -i out/tata/inventory.yaml

# 6) Confirm registration
sipauto registry-watch -i out/tata/inventory.yaml

# 7) If bad — roll back
sipauto rollback -i out/tata/inventory.yaml --yes
```

### B) Airtel (hosts + IMS register)

```bash
sipauto parse-sheet \
  -s examples/carrier_sheets/airtel_sample.txt \
  -o out/airtel/inventory.yaml \
  --provider airtel \
  --site prod-airtel \
  -I eth1

# Edit password away from CHANGE_ME, add ssh:, then:
sipauto generate -i out/airtel/inventory.yaml --no-ask-iface -o out/airtel
sipauto preflight -i out/airtel/inventory.yaml --ssh
# apply-net will also append: <SBC_IP> ims.airtel.in to /etc/hosts
```

### C) FreePBX + Vodafone-Idea (PJSIP, often no register)

```bash
sipauto generate -i examples/inventories/vodafone_freepbx.yaml --no-ask-iface
# review out/demo-vodafone/freepbx/pjsip_vodafonesiptrunk.conf
# identify/match on SBC IP — IP-auth style
```

### D) Full wizard on a jump host

```bash
sipauto wizard --sheet /tmp/provider.txt
# when prompted, configure SSH to the Ameyo call server
# confirm apply-net / Ameyo write / registry-watch
```

---

## 13. Ports & firewall (both sides)

| Traffic | Proto | Ports |
|---------|-------|-------|
| SIP signaling | UDP and/or TCP | `5060` (or provider SBC port) |
| RTP media | UDP | **`10000–40000`** |

Must be open on **call server firewall** and **carrier** side.  
Asterisk `rtp.conf` should match (`rtpstart` / `rtpend` snippets are generated).

---

## 14. Command cheat sheet

```bash
sipauto version
sipauto wizard [--sheet FILE] [--yes -p PROVIDER -I IFACE]
sipauto parse-sheet -s FILE -o inv.yaml [--provider tata] [--site NAME] [-I eth1]
sipauto ifaces [-i inv.yaml] [--ssh] [--all]
sipauto validate -i inv.yaml
sipauto generate -i inv.yaml [-o DIR] [--ask-iface|--no-ask-iface] [-I eth1] [--save-iface]
sipauto verify -i inv.yaml [--ssh]
sipauto preflight -i inv.yaml [--ssh]
sipauto apply-net -i inv.yaml [--dry-run] [-I eth1] [--yes]
sipauto apply-sip -i inv.yaml [--ameyo-write|--no-ameyo-write] [--dry-run] [--yes]
sipauto reload -i inv.yaml [--dry-run]
sipauto run -i inv.yaml [--ssh] [--apply] [--yes] [-I eth1]
sipauto registry-watch -i inv.yaml [--polls N] [--dial NUMBER] [--no-options]
sipauto diagnose "407 …" | sipauto diagnose -f log.txt
sipauto rollback -i inv.yaml [--dry-run] [--yes]
```

---

## 15. Safety notes

- Prefer **preflight GREEN/YELLOW** before `--apply`.
- Ameyo file write is **opt-in** (prompt / `--ameyo-write`).
- Real carrier passwords must not be committed; examples use placeholders.
- Rollback needs prior apply (backups). `--dry-run` first.
- Jio/Vi may show odd registry states and still pass calls — use a test call.
- Physical/L1 issues (mux 100 vs 1000, duplex, VLAN) still need carrier action.

---

## 16. Related docs

- [SIPAUTO_PLAN.md](SIPAUTO_PLAN.md) — architecture & accuracy notes  
- [../README.md](../README.md) — quick start  
- [../AGENTS.md](../AGENTS.md) — cloud-agent notes  
- Sample sheets: `examples/carrier_sheets/`  
- Sample inventories: `examples/inventories/`  
