"""Pre-flight checklist with GREEN / YELLOW / RED scoring before apply."""

from __future__ import annotations

from sipauto.models import CheckResult, Inventory, Provider, RunReport
from sipauto.network.interfaces import discover_interfaces
from sipauto.network.ports import PortChecker
from sipauto.providers import get_provider
from sipauto.ssh import SSHClient, SSHError


def run_preflight(inv: Inventory, *, use_ssh: bool = False) -> RunReport:
    """
    Score readiness before apply-net / apply-sip.

    Checks: NIC link, ping GW/SBC, SIP TCP/UDP, RTP policy/firewall hints,
    Airtel hosts, media routes present, inventory completeness.
    """
    checks: list[CheckResult] = []
    next_actions: list[str] = []

    # Inventory completeness
    arts = get_provider(inv).build(inv)
    if inv.provider in (Provider.JIO, Provider.AIRTEL, Provider.VODAFONE) and not inv.network.media_ips:
        checks.append(
            CheckResult(
                name="media_ips",
                ok=False,
                detail="media_ips empty",
                severity="warn",
            )
        )
        next_actions.append("Add Media IP(s) from carrier sheet before expecting two-way audio")
    else:
        checks.append(
            CheckResult(
                name="media_ips",
                ok=True,
                detail=f"{len(inv.network.media_ips)} media IP(s)",
                severity="info",
            )
        )

    if inv.provider == Provider.AIRTEL and not inv.sip.password:
        checks.append(
            CheckResult(name="airtel_password", ok=False, detail="sip.password missing")
        )
        next_actions.append("Set Airtel password in inventory / wizard")
    if inv.provider == Provider.AIRTEL:
        domain = inv.sip.domain or "ims.airtel.in"
        checks.append(
            CheckResult(
                name="airtel_hosts_plan",
                ok=bool(arts.hosts_entries),
                detail=f"Will ensure {inv.network.sbc_ip} {domain}",
                severity="warn",
            )
        )

    ssh_cfg = inv.ssh if use_ssh and inv.ssh else None

    # NIC link
    try:
        nics = discover_interfaces(ssh=ssh_cfg, include_virtual=False)
        selected = next((n for n in nics if n.name == inv.network.interface), None)
        if selected is None:
            checks.append(
                CheckResult(
                    name="nic_present",
                    ok=False,
                    detail=f"Interface {inv.network.interface} not found",
                )
            )
            next_actions.append(
                f"Pick a real SIP NIC (sipauto ifaces); inventory has {inv.network.interface}"
            )
        else:
            link_ok = selected.link != "no"
            checks.append(
                CheckResult(
                    name="nic_link",
                    ok=link_ok,
                    detail=selected.summary,
                    severity="error" if selected.link == "no" else "info",
                )
            )
            if selected.link == "no":
                next_actions.append(
                    "Cable/mux/VLAN: link is down — escalate carrier for mux speed/duplex if needed"
                )
            if selected.speed and selected.speed.lower().startswith("100m"):
                checks.append(
                    CheckResult(
                        name="nic_speed",
                        ok=True,
                        detail=f"Speed {selected.speed} — confirm carrier mux matches",
                        severity="warn",
                    )
                )
                next_actions.append("Confirm 100 vs 1000 Mbps mux negotiation with carrier (Tata)")
    except Exception as exc:  # noqa: BLE001
        checks.append(
            CheckResult(
                name="nic_discovery",
                ok=False,
                detail=str(exc),
                severity="warn",
            )
        )

    # Reachability + ports + firewall via SSH when available
    checker = PortChecker(inv)
    if ssh_cfg:
        try:
            with SSHClient(ssh_cfg) as client:
                script = "\n".join(
                    [
                        f"ping -c 2 -W 2 {inv.network.gateway_ip} || true",
                        "echo __SEP__",
                        f"ping -c 2 -W 2 {inv.network.sbc_ip} || true",
                        "echo __SEP__",
                        *checker.remote_check_commands(),
                        "echo __SEP__",
                        f"ip route get {inv.network.sbc_ip} 2>/dev/null || true",
                        "echo __SEP__",
                        *[
                            f"ip route get {mip} 2>/dev/null || echo MISSING_ROUTE {mip}"
                            for mip in inv.network.media_ips[:20]
                        ],
                        "echo __SEP__",
                        "grep -E 'ims\\.airtel\\.in' /etc/hosts 2>/dev/null || echo NO_AIRTEL_HOSTS",
                    ]
                )
                out = client.run(script).stdout
                parts = out.split("__SEP__")
                gw_out = parts[0] if parts else ""
                sbc_out = parts[1] if len(parts) > 1 else ""
                port_blob = parts[2] if len(parts) > 2 else out
                route_blob = "\n".join(parts[3:]) if len(parts) > 3 else ""

                checks.append(
                    CheckResult(
                        name="ping_gateway",
                        ok=_ping_ok(gw_out),
                        detail=f"ping {inv.network.gateway_ip}",
                    )
                )
                if not _ping_ok(gw_out):
                    next_actions.append("Fix SIP NIC IP/mask or cable — gateway not reachable")

                checks.append(
                    CheckResult(
                        name="ping_sbc",
                        ok=_ping_ok(sbc_out),
                        detail=f"ping {inv.network.sbc_ip}",
                    )
                )
                if not _ping_ok(sbc_out):
                    next_actions.append("Add/fix host route to SBC via gateway on SIP NIC")

                remote_ports = checker.parse_remote_output(port_blob)
                checks.extend(remote_ports.checks)

                for mip in inv.network.media_ips:
                    missing = f"MISSING_ROUTE {mip}" in route_blob
                    ok = (not missing) and (
                        mip in route_blob or inv.network.gateway_ip in route_blob
                    )
                    checks.append(
                        CheckResult(
                            name=f"route_media_{mip}",
                            ok=ok,
                            detail="media host route",
                            severity="warn",
                        )
                    )
                    if not ok:
                        next_actions.append(
                            f"Add media route: {mip}/32 via {inv.network.gateway_ip}"
                        )

                if inv.provider == Provider.AIRTEL:
                    hosts_ok = (
                        "NO_AIRTEL_HOSTS" not in route_blob and "ims.airtel.in" in route_blob
                    )
                    checks.append(
                        CheckResult(
                            name="airtel_hosts_file",
                            ok=hosts_ok,
                            detail="/etc/hosts ims.airtel.in",
                            severity="warn",
                        )
                    )
                    if not hosts_ok:
                        next_actions.append(
                            f"Add hosts entry: {inv.network.sbc_ip} "
                            f"{inv.sip.domain or 'ims.airtel.in'}"
                        )

                rtp_open_hint = (
                    str(inv.network.rtp_start) in port_blob
                    or "rtpstart" in port_blob
                    or "firewall-cmd" in port_blob
                )
                checks.append(
                    CheckResult(
                        name="rtp_firewall_hint",
                        ok=True,
                        detail=(
                            f"Ensure UDP {inv.network.rtp_start}-{inv.network.rtp_end} "
                            f"BOTH sides. Remote scan hint={'seen' if rtp_open_hint else 'unclear'}"
                        ),
                        severity="info",
                    )
                )
        except (SSHError, ValueError) as exc:
            checks.append(
                CheckResult(name="ssh", ok=False, detail=str(exc), severity="warn")
            )
            next_actions.append("Fix SSH or run preflight locally on the call server")
            local = checker.check_local()
            checks.extend(local.checks)
    else:
        local = checker.check_local()
        checks.extend(local.checks)
        next_actions.append("Run preflight with --ssh on the call server for ping/link/firewall")

    next_actions.extend(
        [
            f"SIP signaling TCP/UDP {inv.network.sbc_port} both sides",
            f"RTP UDP {inv.network.rtp_start}-{inv.network.rtp_end} both sides",
        ]
    )
    # dedupe next actions
    next_actions = list(dict.fromkeys(next_actions))

    hard = [c for c in checks if not c.ok and c.severity == "error"]
    warn = [c for c in checks if not c.ok and c.severity == "warn"]
    if hard:
        confidence = "RED"
    elif warn:
        confidence = "YELLOW"
    else:
        confidence = "GREEN"

    return RunReport(
        site=inv.site.name,
        provider=inv.provider.value,
        platform=inv.platform.value,
        confidence=confidence,
        checks=checks,
        next_actions=next_actions,
    )


def _ping_ok(text: str) -> bool:
    t = text or ""
    return (
        "bytes from" in t
        or "1 received" in t
        or "2 received" in t
        or "1 packets received" in t
        or "2 packets received" in t
    )
