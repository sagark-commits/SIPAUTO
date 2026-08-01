"""Live SIP registry watch, OPTIONS probe, and SIP error playbooks."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from sipauto.models import CheckResult, Inventory, SipDriver
from sipauto.platforms.asterisk import registry_check_command
from sipauto.ssh import SSHClient

# Doc-backed playbooks (Tata 407/403/480, Airtel/Jio notes)
ERROR_PLAYBOOKS: dict[str, dict[str, str]] = {
    "407": {
        "title": "407 Proxy Authentication Required",
        "fix": (
            "Use authuser register form: "
            "register => user:pass:authuser@sbc/ext; set fromuser/fromname; "
            "PPI with Customer IP (Tata)."
        ),
    },
    "403": {
        "title": "403 Forbidden (often outbound)",
        "fix": (
            "Tata GKB: remove register string from Global SIP and sip.conf, "
            "reload Asterisk, re-check sip show registry; verify CLI/DID."
        ),
    },
    "480": {
        "title": "480 Temporarily Unavailable (after 407 fix)",
        "fix": (
            "Set P-Preferred-Identity using Customer IP "
            "(setvar=SIPADDHEADER=P-Preferred-Identity:<sip:PILOT@CUSTOMER_IP>)."
        ),
    },
    "401": {
        "title": "401 Unauthorized",
        "fix": "Check username/password/domain (Airtel IMS user@ims.airtel.in).",
    },
    "408": {
        "title": "408 Request Timeout",
        "fix": "SBC unreachable — verify NIC IP, host route, ping SBC, firewall SIP UDP/TCP.",
    },
    "503": {
        "title": "503 Service Unavailable",
        "fix": "Carrier/SBC side or wrong transport; confirm port/TCP vs UDP with provider.",
    },
}


@dataclass
class RegistryWatchResult:
    registered: bool
    raw: str
    polls: int
    checks: list[CheckResult] = field(default_factory=list)
    errors_seen: list[str] = field(default_factory=list)
    playbooks: list[str] = field(default_factory=list)
    options_ok: bool | None = None


def watch_registry(
    inv: Inventory,
    *,
    polls: int = 5,
    interval: float = 3.0,
    options_probe: bool = True,
    dial_test: str | None = None,
) -> RegistryWatchResult:
    """Poll Asterisk registry via SSH; optional OPTIONS and originate dial test."""
    if not inv.ssh:
        raise ValueError("inventory.ssh required for registry watch")

    reg_cmd = registry_check_command(inv)
    peers_cmd = (
        "asterisk -rx 'pjsip show endpoints'"
        if inv.sip_driver == SipDriver.PJSIP
        else "asterisk -rx 'sip show peers'"
    )
    result = RegistryWatchResult(registered=False, raw="", polls=polls)

    with SSHClient(inv.ssh) as client:
        blobs: list[str] = []
        for i in range(polls):
            r = client.run(f"{reg_cmd}; echo ---; {peers_cmd}")
            blob = r.stdout + r.stderr
            blobs.append(blob)
            if _is_registered(blob, inv):
                result.registered = True
                result.raw = blob
                break
            if i < polls - 1:
                time.sleep(interval)
        else:
            result.raw = blobs[-1] if blobs else ""

        # Scan messages for SIP codes
        codes = set(re.findall(r"\b(401|403|407|408|480|503)\b", result.raw))
        # Also pull recent Asterisk verbose if available
        log = client.run(
            "asterisk -rx 'sip set debug on' >/dev/null 2>&1; "
            "timeout 2 journalctl -u asterisk -n 80 --no-pager 2>/dev/null "
            "|| tail -80 /var/log/asterisk/full 2>/dev/null "
            "|| tail -80 /var/log/asterisk/messages 2>/dev/null "
            "|| true"
        ).stdout
        codes |= set(re.findall(r"\b(401|403|407|408|480|503)\b", log))
        result.errors_seen = sorted(codes)
        for code in result.errors_seen:
            pb = ERROR_PLAYBOOKS.get(code)
            if pb:
                result.playbooks.append(f"{code} {pb['title']}: {pb['fix']}")

        result.checks.append(
            CheckResult(
                name="sip_registry",
                ok=result.registered,
                detail="Registered" if result.registered else "Not Registered (see raw)",
                severity="warn"
                if inv.provider.value in ("jio", "vodafone") and not result.registered
                else "error",
            )
        )

        if options_probe:
            result.options_ok = _options_probe(client, inv)
            result.checks.append(
                CheckResult(
                    name="sip_options_probe",
                    ok=bool(result.options_ok),
                    detail=f"OPTIONS toward {inv.network.sbc_ip}:{inv.network.sbc_port}",
                    severity="warn",
                )
            )

        if dial_test:
            # Best-effort originate; channel name depends on driver/trunk
            trunk = inv.ameyo.entity_name or inv.provider.value
            if inv.sip_driver == SipDriver.PJSIP:
                chan = f"PJSIP/{dial_test}@{trunk}"
            else:
                chan = f"SIP/{dial_test}@{trunk}"
            orig = client.run(
                f"asterisk -rx 'channel originate {chan} application Playback hello-world' || "
                f"asterisk -rx 'originate {chan} extension s@default' || true"
            )
            result.checks.append(
                CheckResult(
                    name="dial_test",
                    ok=orig.exit_code == 0,
                    detail=f"originate {chan}: {(orig.stdout + orig.stderr)[:300]}",
                    severity="warn",
                )
            )

    if not result.registered and inv.provider.value in ("jio", "vodafone"):
        result.playbooks.append(
            "Jio/Vi may work without classic Registered state — run a test call anyway."
        )
    return result


def diagnose_text(text: str) -> list[str]:
    """Map free-form log/error text to playbooks."""
    out: list[str] = []
    for code, pb in ERROR_PLAYBOOKS.items():
        if re.search(rf"\b{code}\b", text) or pb["title"].split("(")[0].strip() in text:
            out.append(f"{code} {pb['title']}: {pb['fix']}")
    return out


def _is_registered(text: str, inv: Inventory) -> bool:
    t = text.lower()
    if "registered" in t and "unregistered" not in t.split("registered")[0][-20:]:
        # crude: look for Registered state lines
        if re.search(r"Registered", text):
            return True
    if inv.sip_driver == SipDriver.PJSIP and re.search(
        r"Registered\s+until|Status\s*:\s*Registered", text, re.I
    ):
        return True
    return False


def _options_probe(client: SSHClient, inv: Inventory) -> bool:
    """Send a minimal SIP OPTIONS via netcat/bash udp/tcp."""
    host = inv.network.sbc_ip
    port = inv.network.sbc_port
    # Prefer sipsak/sngrep if present; else UDP OPTIONS datagram
    script = f"""
if command -v sipsak >/dev/null; then
  sipsak -s sip:{host}:{port} -v && echo OPTIONS_OK
elif command -v nmap >/dev/null; then
  nmap -sU -p {port} --script sip-methods {host} 2>/dev/null | tee /tmp/sipauto_opt.out
  grep -qi options /tmp/sipauto_opt.out && echo OPTIONS_OK || echo OPTIONS_UNCLEAR
else
  MSG=$'OPTIONS sip:{host} SIP/2.0\\r\\nVia: SIP/2.0/UDP {inv.network.customer_ip}:5060;branch=z9hG4bKsipauto\\r\\nFrom: <sip:sipauto@{inv.network.customer_ip}>;tag=sipauto\\r\\nTo: <sip:{host}>\\r\\nCall-ID: sipauto@local\\r\\nCSeq: 1 OPTIONS\\r\\nContact: <sip:sipauto@{inv.network.customer_ip}>\\r\\nMax-Forwards: 70\\r\\nContent-Length: 0\\r\\n\\r\\n'
  echo -n "$MSG" > /dev/udp/{host}/{port} && echo OPTIONS_SENT || echo OPTIONS_FAIL
fi
"""
    r = client.run(script)
    out = r.stdout + r.stderr
    return "OPTIONS_OK" in out or "OPTIONS_SENT" in out
