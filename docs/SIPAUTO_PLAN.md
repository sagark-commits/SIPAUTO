# SIPAUTO — SIP Configuration Automation Plan

**Status:** MVP implemented (`sipauto` CLI)  
**Scope (phase 1):** On-prem **Ameyo+Asterisk** and **FreePBX** on **Rocky/RHEL** with Indian carrier Ethernet SIP trunks (**Tata / Jio / Airtel / Vodafone-Idea**)  
**Flow:** `generate → verify → SSH apply-net/apply-sip/reload` (Ameyo write optional, prompted)  
**Ports:** SIP TCP+UDP; RTP UDP **10000–40000** both sides  
**Later:** Cloud / shared deployment modes

---

## 1. What we learned from your docs + public research

Your nine internal PDFs (Ameyo GKB / oldsites) describe **one repeatable pipeline**, not nine different products:

```text
Provider handoff sheet
  → dedicate NIC (Customer IP / mask / gateway)
  → host routes to SBC (+ Media IPs)
  → optional /etc/hosts (Airtel IMS FQDN)
  → Ameyo Global SIP (`register => …`, codecs, expiry)
  → Ameyo Call Entity / Call Context (host, port, custom SIP flags, PPI)
  → Asterisk verify: `sip show registry` + test call
```

| Source | Confirms |
|--------|----------|
| Internal Tata / Jio / Airtel runbooks | NIC + routes + register + peer custom config pattern |
| Internal Global SIP doc | Asterisk `sip.conf` `[general]` + register grammar |
| Internal ATA/ethernet + duplex notes | L1/L2 mux speed/duplex often needs **carrier** action |
| Internal 407/403/480 notes | Authuser / PPI / register presence are failure-specific |
| Internal `sipregister` engg doc | Prefer UI **Register to remote party** over duplicate manual `register =>` |
| Public Tata/Jio Kamailio & FreePBX guides | Same L3 model: dual-NIC, static routes to SBC/media |
| Public Airtel Asterisk guides | `ims.airtel.in` (+ regional variants), hosts map, PPI for outbound |

**Target system in docs:** Ameyo Call Manager (Voice Resource / Call Context) on Asterisk — not a generic cloud SIP portal.  
**Handoff model:** Carrier-provisioned **private Ethernet** into the call server (dual-NIC), not public internet SIP for these on-prem setups.

---

## 2. Goal of SIPAUTO

Build a tool that takes a **provider inventory** (IPs, pilot/DID, credentials, NIC name) and:

1. Validates prerequisites (link, duplex, reachability).
2. Applies **safe, reviewable** OS network config (or dry-runs it).
3. Generates **provider-correct** Ameyo/Asterisk SIP artifacts (register + peer/custom).
4. Optionally applies them (CLI / DB / API when available) and verifies registration.
5. Produces a **run report** with exact next human/carrier steps when automation cannot finish.

Success metric for phase 1: an engineer can go from “provider sheet filled” → “Registered + audio path routed” in one guided run, with dry-run and rollback.

---

## 3. What is automatable vs not

### High confidence (automate in MVP)

| Layer | Action | Accuracy driver |
|-------|--------|-----------------|
| Inventory schema | Validate required fields per provider | Template completeness |
| NIC / IP | Render `ifcfg-*` / netplan / NetworkManager profiles | Distro adapter correctness |
| Routes | Persist SBC (+ media) host routes via gateway on SIP NIC | Exact IPs from provider |
| Hosts | Airtel `SBC_IP ims.airtel.in` (and regional FQDN if supplied) | Circle-specific FQDN |
| Config generate | Register string, global SIP snippet, peer custom block, PPI | Provider template unit tests |
| Verify | `ethtool`, ping gateway/SBC, `asterisk -rx "sip show registry"` | CLI access on call server |
| Diagnostics | Map 407 / 403 / 480 / no-audio to known playbooks | Doc-encoded decision tree |

### Medium confidence (phase 1.5 — needs Ameyo access path)

| Layer | Reality | Approach |
|-------|---------|----------|
| Call Entity / Call Context create | Docs are **UI-first**; public Ameyo admin docs do not expose a stable public SIP CRUD API | Prefer: generate + apply via known DB tables / VR settings if internal APIs exist; else generate “paste pack” + optional Selenium/UI runner **behind a flag** |
| Auto `register` flag | Engg doc: “Register to remote party” writes `sip.conf` and can conflict with manual Global SIP | Prefer auto-register path; detect/remove redundant lines in `global_sip_config` / `sip.conf` |
| DID dialplan / random CLI JS | Documented but site-specific | Template generators with human review |

### Low confidence / human or carrier only (never fake as automated)

| Item | Why |
|------|-----|
| Obtaining pilot, password, Customer/SBC/Media IPs, VLAN | Only carrier can provision |
| Physical cable to correct NIC | On-site |
| Tata mux 100↔1000 / duplex / VLAN enable | Carrier NOC |
| Full Airtel media IP sprawl for one-way audio | Often incomplete in sheet; discovered via Wireshark / carrier |
| Campaign Caller ID assignment | Product/ops decision |
| Legal / interconnect compliance | Out of scope |

---

## 4. Proposed architecture (on-prem first)

```text
┌─────────────────────────────────────────────────────────────┐
│  sipauto CLI (Python)                                        │
│  sipauto validate | plan | apply-net | render-sip | verify   │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
     ┌──────────▼──────────┐         ┌──────────▼──────────┐
     │ Provider templates  │         │ Platform adapters   │
     │  tata.yaml          │         │  os: rhel7/8, ubuntu│
     │  jio.yaml           │         │  pbx: asterisk-sip  │
     │  airtel.yaml        │         │  ameyo: generate /  │
     │  (extensible)       │         │        apply (opt)  │
     └──────────┬──────────┘         └──────────┬──────────┘
                │                               │
                └──────────► inventory.yaml ◄───┘
                             (secrets via env / vault)
```

### 4.1 Inventory (single source of truth)

Example shape (illustrative):

```yaml
site:
  name: cashify-cc
  mode: onprem          # later: cloud | shared
provider: tata          # tata | jio | airtel
network:
  interface: eth1
  customer_ip: 10.0.80.98
  prefix: 30            # or netmask
  gateway_ip: 10.0.80.97
  vlan_id: null         # optional
  sbc_ip: 10.0.76.11
  sbc_port: 5060
  media_ips: []         # required for jio/airtel audio
sip:
  pilot: "8068167000"
  username: null        # derived per template if omitted
  password: "****"
  auth_user: null
  domain: null          # airtel: ims.airtel.in
  codecs: [alaw, ulaw, g729]
  register_expiry: 300
ameyo:
  voice_resource: DefaultVR
  entity_name: tata
  context_name: tata-ctx
  apply_mode: generate_only   # generate_only | apply_files | apply_ameyo
```

### 4.2 Provider templates (the accuracy core)

Encode **deltas** explicitly (from your docs + public guides):

| Aspect | Tata | Jio | Airtel |
|--------|------|-----|--------|
| Auth | Usually password (often `1234`); pilot as user | Often register **without** secret; “No authentication” may still work | Real password; IMS user `+91…@ims.airtel.in` |
| Register | `pilot:pass@sbc/pilot` or authuser form for 407 | `pilot@sbc/pilot~1800` | `+91…@ims.airtel.in:pass:+91…@ims.airtel.in@sbc/+91…[~1800]` |
| Host / fromdomain | SBC IP (sometimes `SIP-<pilot>`) | SBC IP | `ims.airtel.in` + `/etc/hosts` |
| fromuser | Local DID (STD stripped per recipe) | `+91` + number | `+91…` |
| PPI | Often required; Customer IP in some 480 fixes | Optional / fromuser driven | Usually required for outbound |
| Media routes | Add if no audio | **Required** Media IP | **Many** media IPs common |
| L1 extras | VLAN, mux speed/duplex | `ethtool` link checks | IMS hostname |

Templates must be **unit-tested** against golden strings from your PDFs (sanitized).

### 4.3 Execution modes (safety)

1. **`validate`** — schema + IP consistency + required fields for provider.  
2. **`plan`** — print exact files/commands that would change (diff).  
3. **`apply-net`** — write network config (with backup + rollback).  
4. **`render-sip`** — write artifacts under `out/<site>/` (Global SIP, peer custom, hosts, dialplan snippets).  
5. **`apply-sip`** — optional; copy into Asterisk/Ameyo paths or call internal apply hook.  
6. **`verify`** — link, ping, registry state, optional SIP OPTIONS/REGISTER capture guidance.  
7. **`diagnose`** — given error code/log snippet → recommended fix (407/403/480/no-audio).

Default for first release: **generate + verify**; apply-net behind `--i-know-this-host`.

### 4.4 Ameyo integration strategy (phased)

| Phase | Integration | Risk |
|-------|-------------|------|
| P0 | Generate paste-ready Global SIP + Call Entity custom config matching UI fields | Lowest |
| P1 | Apply Asterisk files (`sip.conf` peer / global) + `asterisk -rx "sip reload"` on call server SSH | Medium (must avoid clobbering unrelated peers) |
| P2 | Write Ameyo-backed settings if internal service/DB contracts are available (`asterisk_voice_resource_settings.global_sip_config`, entity custom config) | Needs engg confirmation |
| P3 | Official/internal Ameyo API or Admin command path for Call Context create | Best long-term |

**Do not** depend on brittle UI automation for MVP unless P2/P3 are blocked for months.

---

## 5. Effectiveness & accuracy (honest estimate)

Assuming **complete, correct provider sheet** and **SSH/root on the Ameyo call server**:

| Outcome | Estimated success rate | Notes |
|---------|------------------------|-------|
| Correct config **artifacts** (register/peer/hosts/routes) for Tata/Jio/Airtel recipes in your docs | **~90–95%** | Template + golden tests; edge cases: non-5060 SBC, regional Airtel FQDN (`mh.ims…`, `ap.ims…`) |
| Network applied + SBC pingable | **~80–90%** | Drops when cable/mux/VLAN/duplex wrong (carrier) |
| `sip show registry` → Registered (or Jio “works without auth”) | **~70–85%** | Auth format / 403-vs-register policy / wrong pilot formatting |
| Two-way audio on first try | **~55–75%** | Media IP lists incomplete especially Airtel/Jio |
| Full “hands-off including Ameyo UI entity create” without DB/API | **~30–50%** | UI/API gap |

**Net:** Automation is highly effective for the **repeatable, error-prone string/route work** engineers do today. It is **not** a substitute for carrier provisioning or L1 issues. The biggest accuracy win is **provider templates + verify/diagnose**, not magic Ameyo clicks.

### Accuracy controls

- Golden-file tests from sanitized internal examples (Tata 407 fix, Airtel IMS register, Jio `~1800`).
- Dry-run diffs before any write.
- Backup of `ifcfg`/`route-*`/`hosts`/`sip.conf` snippets before apply.
- Explicit “confidence” in report: `GREEN` (registered + media routes present) / `YELLOW` (registered, media unknown) / `RED` (blocked + next action).

---

## 6. Failure playbooks encoded in the tool

| Symptom | Automated check | Suggested action |
|---------|-----------------|------------------|
| No link | `ethtool` speed/duplex | Escalate carrier mux (your ATA/ethernet doc) |
| No ping gateway/SBC | route table + iface IP | Fix/apply routes; check cable/VLAN |
| 407 | REGISTER/authuser shape | Apply Tata authuser register + peer PPI recipe |
| 403 outbound | registry present? | Offer “unregister / remove register” path per Tata GKB |
| 480 after 407 fix | PPI host | Set PPI to Customer IP form |
| Registered, no audio | media routes missing | Prompt for media IPs; add routes; suggest `sngrep`/Wireshark |
| Airtel DNS | resolve `ims.airtel.in` | Ensure `/etc/hosts` |
| Duplicate register | parse global_sip + sip.conf | Prefer auto-register; remove redundant manual lines |

---

## 7. Delivery phases

### Phase 1 — On-prem MVP (this repo)

**Ship:** Python CLI + YAML inventory + Tata/Jio/Airtel templates + `validate/plan/render-sip/verify/diagnose` + optional `apply-net`.

**Out of scope for MVP:** Cloud SBC, multi-tenant shared trunking, full Ameyo UI automation, PJSIP migration (docs are `chan_sip`; support PJSIP later as adapter).

**Hello-world demo (lab):**  
Use a mock “provider fixture” + local Asterisk container or dry-run against golden outputs (real carrier Ethernet cannot be simulated in CI).

### Phase 2 — Ameyo apply path

Wire `apply-sip` to whatever internal mechanism engg confirms (DB/API/SSH file merge). Add redundant-register cleanup from `sipregister` doc.

### Phase 3 — Cloud / on-prem / shared

| Mode | Difference |
|------|------------|
| `onprem` | Dual-NIC + private routes (phase 1) |
| `cloud` | Often public/VPN SBC, NAT/`externip`, no carrier mux NIC; different inventory |
| `shared` | Multi-tenant routing, DID→tenant mapping, stricter isolation |

Same template engine; different **network + platform adapters**.

### Phase 4 — Platform expansion (optional)

Adapters: FreePBX/Vicidial PJSIP, Kamailio `uacreg` (public guides already show Tata/Jio patterns). Keep Ameyo as primary.

---

## 8. Security & ops requirements

- Never commit real passwords from PDFs; treat examples as compromised in docs copies.
- Secrets via env / HashiCorp Vault / Ansible vault.
- Idempotent applies; audit log of every change.
- Run as root only for network apply; SIP render can be unprivileged.
- Support air-gapped on-prem: vendor templates bundled in package (no internet required at apply time).

---

## 9. Recommended tech stack (MVP)

| Piece | Choice | Why |
|-------|--------|-----|
| Language | Python 3.11+ | Fast CLI, YAML, SSH, easy ops adoption |
| CLI | `typer` or `click` | Subcommands match workflow |
| Config | Pydantic models + YAML | Strict validation per provider |
| Tests | `pytest` golden files | Accuracy gate |
| Remote | optional `paramiko`/SSH | Apply/verify on call server |
| Packaging | `pipx` / wheel | Simple on-prem install |

Web UI later if desired; CLI first matches on-prem engineer workflow.

---

## 10. Decisions (locked)

1. **Primary target:** Ameyo + Asterisk **and** FreePBX.  
2. **Apply depth:** generate + verify + **SSH apply + reload**.  
3. **Ameyo write:** optional — **ask before write**; generate/verify first. Writes Asterisk include snippets (not full Call Manager UI/DB rows yet).  
4. **Distros:** Rocky / Red Hat (`ifcfg` + `route-*`).  
5. **Providers:** Tata, Jio, Airtel, and Vodafone-Idea (Vi; public guides — IP-auth/PJSIP identify; medium confidence).  
6. **Ports:** check SIP TCP/UDP; RTP UDP range **10000–40000** both sides.  
7. **PJSIP:** FreePBX/Vi default PJSIP; Ameyo docs remain `chan_sip` with PJSIP artifacts also generated.

---

## 11. Implemented high-impact features (MVP+)

| Feature | Command |
|---------|---------|
| Guided wizard | `sipauto wizard` |
| Carrier sheet parser | `sipauto parse-sheet` |
| Preflight scores | `sipauto preflight` |
| Registry + OPTIONS + playbooks | `sipauto registry-watch` / `diagnose` |
| Rollback `*.sipauto.bak` | `sipauto rollback` |

## 11. Suggested next implementation slice (after approval)

1. Scaffold Python package `sipauto` with inventory schema + three provider templates.  
2. Golden tests from sanitized PDF examples.  
3. `validate` / `plan` / `render-sip` / `diagnose` working offline.  
4. `apply-net` + `verify` behind safety flags.  
5. Document field mapping UI ↔ generated artifacts for Ameyo operators.  
6. Later: Ameyo apply adapter once write path is confirmed.

---

## 12. Bottom line

| Question | Answer |
|----------|--------|
| Is automation possible? | **Yes** for the core on-prem Ethernet SIP recipe your docs describe. |
| Where is the value? | Eliminate copy-paste register mistakes, missing routes, wrong PPI/fromuser, and missing verification. |
| What remains manual? | Carrier provisioning, physical/L1, incomplete media IP lists, campaign-level Caller ID. |
| Accuracy if inputs are good? | **High for config generation (~90%+)**; **good for register (~70–85%)**; **audio depends on media routes**. |
| Cloud later? | Same engine; swap network/auth adapters — do not block MVP on it. |
