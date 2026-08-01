# SIPAUTO — How to Use

Automate on-prem SIP trunks for **Ameyo + Asterisk** and **FreePBX** on **Rocky / Red Hat**.

Supported carriers: **Tata · Jio · Airtel · Vodafone-Idea**

---

## What you need

| Requirement | Notes |
|-------------|--------|
| Python **3.10+** | On Rocky 8 use `python3.11` (system `python3` is often 3.6 — too old) |
| OpenSSH client | `ssh` / `scp` (`dnf install openssh-clients`) |
| `iproute` + `ethtool` | NIC discovery (`dnf install iproute ethtool`) |
| This repo / zip | **No internet and no `pip` required** |

---

## 1. Install (copy folder → run)

On the call server (or a jump host):

```bash
# unzip SIPAUTO-main.zip  (or git clone / copy the tree)
cd /dacx/SIPAUTO-main

dnf install -y python3.11 openssh-clients iproute ethtool

chmod +x scripts/*.sh
./scripts/bootstrap_rocky.sh

# smoke test
./scripts/run_offline.sh version
```

That is enough. Nothing is downloaded from PyPI.

### Daily command form

Use either style (same tool):

```bash
./scripts/run_offline.sh <command> …

# or
export PYTHONPATH=/dacx/SIPAUTO-main/src
python3.11 -m sipauto <command> …
```

Below, `sipauto` means one of those two.

---

## 2. Recommended flow

```text
wizard
  → pick provider
  → load carrier sheet
  → pick SIP NIC
  → generate configs
  → preflight (GREEN / YELLOW / RED)
  → optional apply + reload
  → registry-watch
  → rollback if needed
```

**Already on the Ameyo call server?** Answer **n** to SSH in the wizard, then apply with `--local`.

**Driving a remote call server?** Configure SSH (key preferred). Invalid hosts (e.g. `10.192.168.56.10`) are rejected; auth failures fall back to local mode instead of crashing.

---

## 3. Fastest path — wizard

```bash
cd /dacx/SIPAUTO-main
./scripts/run_offline.sh wizard --sheet examples/carrier_sheets/tata_sample.txt
```

Non-interactive:

```bash
./scripts/run_offline.sh wizard --yes \
  --sheet examples/carrier_sheets/tata_sample.txt \
  --provider tata \
  --site my-tata \
  --interface eth1 \
  --out out
```

Creates:

```text
out/my-tata/
  inventory.yaml
  network/ifcfg
  network/route
  ameyo/…                  # Global SIP, peers, UI checklist
  asterisk/rtp.conf.snippet
  MANIFEST.json
  preflight_report.json
  verify_report.json
```

---

## 4. Step-by-step (manual)

### A) Parse carrier sheet → inventory

```bash
./scripts/run_offline.sh parse-sheet \
  -s examples/carrier_sheets/tata_sample.txt \
  -o out/tata/inventory.yaml \
  --site prod-tata \
  -I eth1
```

Other providers:

```bash
./scripts/run_offline.sh parse-sheet -s examples/carrier_sheets/jio_sample.txt \
  -o out/jio/inventory.yaml --provider jio --site prod-jio -I eth1

./scripts/run_offline.sh parse-sheet -s examples/carrier_sheets/airtel_sample.txt \
  -o out/airtel/inventory.yaml --provider airtel --site prod-airtel -I eth1
```

Sample sheet shape:

```text
Customer IP: 10.0.80.98
Subnet Mask: 255.255.255.252
Gateway IP: 10.0.80.97
SBC IP: 10.0.76.11
Pilot no.: 8068167000
Password: 1234
Media IP: 10.0.76.12
```

### B) List / pick SIP NIC

```bash
./scripts/run_offline.sh ifaces
./scripts/run_offline.sh ifaces -i out/tata/inventory.yaml --ssh   # remote
```

### C) Generate artifacts

```bash
./scripts/run_offline.sh generate -i out/tata/inventory.yaml -I eth1 -o out/tata --no-ask-iface
```

### D) Preflight (before you change the server)

```bash
./scripts/run_offline.sh preflight -i out/tata/inventory.yaml
# with SSH configured in inventory:
./scripts/run_offline.sh preflight -i out/tata/inventory.yaml --ssh
echo $?    # 0 = GREEN, 3 = YELLOW, 1 = RED
```

### E) Apply (on the call server)

**Local (you are on Ameyo):**

```bash
./scripts/run_offline.sh apply-net -i out/tata/inventory.yaml -I eth1 --local --yes
./scripts/run_offline.sh apply-sip -i out/tata/inventory.yaml --ameyo-write --local --yes
./scripts/run_offline.sh reload -i out/tata/inventory.yaml --local
```

**Remote SSH** — add to inventory:

```yaml
ssh:
  host: 192.168.56.10
  user: root
  key_path: ~/.ssh/id_rsa
```

Then:

```bash
./scripts/run_offline.sh apply-net -i out/tata/inventory.yaml -I eth1 --yes
./scripts/run_offline.sh apply-sip -i out/tata/inventory.yaml --ameyo-write --yes
./scripts/run_offline.sh reload -i out/tata/inventory.yaml
```

Ameyo write only adds Asterisk include snippets (`*.sipauto.bak` backups).  
It does **not** create Call Manager UI rows — follow `ameyo/ameyo_ui_checklist.md`.

### F) Confirm registration

```bash
./scripts/run_offline.sh registry-watch -i out/tata/inventory.yaml
./scripts/run_offline.sh diagnose "SIP/2.0 407 Proxy Authentication Required"
```

### G) Rollback if needed

```bash
./scripts/run_offline.sh rollback -i out/tata/inventory.yaml --dry-run
./scripts/run_offline.sh rollback -i out/tata/inventory.yaml --yes
```

---

## 5. Inventory YAML (reference)

Ready examples under `examples/inventories/`:

| File | Provider | Platform |
|------|----------|----------|
| `tata_ameyo.yaml` | Tata | Ameyo + Asterisk |
| `jio_ameyo.yaml` | Jio | Ameyo + Asterisk |
| `airtel_ameyo.yaml` | Airtel | Ameyo + Asterisk |
| `vodafone_freepbx.yaml` | Vodafone-Idea | FreePBX (PJSIP) |

Minimal shape:

```yaml
site:
  name: my-site
  mode: onprem

provider: tata                 # tata | jio | airtel | vodafone
platform: ameyo_asterisk       # ameyo_asterisk | freepbx | asterisk
sip_driver: chan_sip           # chan_sip | pjsip

network:
  interface: eth1
  customer_ip: 10.0.80.98
  gateway_ip: 10.0.80.97
  netmask: 255.255.255.252
  sbc_ip: 10.0.76.11
  sbc_port: 5060
  media_ips:
    - 10.0.76.12
  sip_transport: both          # udp | tcp | both
  rtp_start: 10000
  rtp_end: 40000

sip:
  pilot: "8068167000"
  username: "68167000"         # Tata: often pilot without STD
  password: "1234"
  codecs: [alaw, ulaw, g729]

ameyo:
  voice_resource: DefaultVR
  entity_name: tata
  context_name: tata-ctx
  asterisk_etc: /etc/asterisk

# Optional — only if applying from a jump host
# ssh:
#   host: 192.168.56.10
#   user: root
#   key_path: ~/.ssh/id_rsa
```

```bash
./scripts/run_offline.sh validate -i examples/inventories/tata_ameyo.yaml
```

---

## 6. Ports (both sides)

| Traffic | Proto | Ports |
|---------|-------|-------|
| SIP signaling | UDP and/or TCP | `5060` (or carrier SBC port) |
| RTP media | UDP | **`10000–40000`** |

Open on the call-server firewall **and** the carrier side.  
Generated `asterisk/rtp.conf.snippet` sets `rtpstart` / `rtpend` to match.

---

## 7. Common SIP errors

```bash
./scripts/run_offline.sh diagnose "407 Proxy Authentication Required"
./scripts/run_offline.sh diagnose "403 Forbidden"
./scripts/run_offline.sh diagnose "480 Temporarily Unavailable"
./scripts/run_offline.sh diagnose -f /tmp/asterisk.log
```

| Code | Typical fix |
|------|-------------|
| **407** | Authuser register form + `fromuser`; PPI |
| **403** | Remove register (some Tata GKB paths), reload, re-check |
| **480** | PPI with **Customer IP** |
| **408** | Route / firewall to SBC |
| No audio | Media IP host routes; RTP `10000–40000` both sides |

---

## 8. Command cheat sheet

```bash
./scripts/run_offline.sh version
./scripts/run_offline.sh wizard [--sheet FILE] [--yes -p PROVIDER -I IFACE]
./scripts/run_offline.sh parse-sheet -s FILE -o inv.yaml [--provider tata] [--site NAME] [-I eth1]
./scripts/run_offline.sh ifaces [-i inv.yaml] [--ssh]
./scripts/run_offline.sh validate -i inv.yaml
./scripts/run_offline.sh generate -i inv.yaml [-o DIR] [-I eth1] [--no-ask-iface]
./scripts/run_offline.sh verify -i inv.yaml [--ssh]
./scripts/run_offline.sh preflight -i inv.yaml [--ssh]
./scripts/run_offline.sh apply-net -i inv.yaml [--local] [--dry-run] [-I eth1] [--yes]
./scripts/run_offline.sh apply-sip -i inv.yaml [--local] [--ameyo-write] [--yes]
./scripts/run_offline.sh reload -i inv.yaml [--local]
./scripts/run_offline.sh run -i inv.yaml [--ssh] [--apply] [--yes] [-I eth1]
./scripts/run_offline.sh registry-watch -i inv.yaml [--polls N] [--dial NUMBER]
./scripts/run_offline.sh diagnose "407 …"
./scripts/run_offline.sh rollback -i inv.yaml [--dry-run] [--yes]
```

---

## 9. End-to-end example (Tata on Ameyo host)

```bash
cd /dacx/SIPAUTO-main
export PATH_S=./scripts/run_offline.sh

$PATH_S parse-sheet -s examples/carrier_sheets/tata_sample.txt \
  -o out/tata/inventory.yaml --site prod-tata -I eth1

$PATH_S generate -i out/tata/inventory.yaml -I eth1 -o out/tata --no-ask-iface
$PATH_S preflight -i out/tata/inventory.yaml

# review out/tata/ameyo/* then apply locally
$PATH_S apply-net -i out/tata/inventory.yaml -I eth1 --local --yes
$PATH_S apply-sip -i out/tata/inventory.yaml --ameyo-write --local --yes
$PATH_S reload -i out/tata/inventory.yaml --local
$PATH_S registry-watch -i out/tata/inventory.yaml

# if something goes wrong
$PATH_S rollback -i out/tata/inventory.yaml --dry-run
```

---

## 10. Safety

- Prefer **preflight GREEN/YELLOW** before apply.
- Ameyo file write is **opt-in** (`--ameyo-write` or interactive confirm).
- Every apply creates `*.sipauto.bak` — use `rollback` if needed.
- Do not commit real carrier passwords.
- Jio/Vi may show odd registry states and still pass calls — run a test call.
- L1 issues (mux 100 vs 1000, duplex, VLAN) still need the carrier.

---

## 11. Troubleshooting

| Problem | Fix |
|---------|-----|
| `python3` is 3.6 | `dnf install -y python3.11` and use `python3.11 -m sipauto` / `run_offline.sh` |
| `sipauto: command not found` | Use `./scripts/run_offline.sh` or `PYTHONPATH=src python3.11 -m sipauto` |
| `pip` / SSL / PyPI errors | Ignore — offline path needs no pip |
| Wizard SSH “label too long” | Host typo (e.g. five octets). Enter a real IPv4 like `192.168.56.10` |
| SSH “No authentication methods” | Provide a real key path, use agent, or skip SSH and run `--local` on the call server |
| Preflight RED `Interface ethX not found` | Run `ifaces`, pick a real NIC, regenerate with `-I <name>` |
| Want optional pip install | `SIPAUTO_ONLINE=1 ./scripts/bootstrap_rocky.sh` (needs internet) |

---

## 12. Related

- [../README.md](../README.md) — quick start  
- [SIPAUTO_PLAN.md](SIPAUTO_PLAN.md) — design notes  
- Sample sheets: `examples/carrier_sheets/`  
- Sample inventories: `examples/inventories/`  
