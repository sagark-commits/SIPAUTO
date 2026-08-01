"""Verification: ports, reachability, Asterisk registry (local or SSH)."""

from __future__ import annotations

from pathlib import Path

from sipauto.models import CheckResult, Inventory, RunReport
from sipauto.network.ports import PortChecker
from sipauto.platforms.asterisk import registry_check_command
from sipauto.ssh import SSHClient, SSHError


def verify(
    inv: Inventory,
    *,
    use_ssh: bool = False,
    artifacts_dir: str | Path | None = None,
) -> RunReport:
    checks: list[CheckResult] = []
    next_actions: list[str] = []

    # Inventory sanity
    if inv.provider.value in ("jio", "airtel", "vodafone") and not inv.network.media_ips:
        checks.append(
            CheckResult(
                name="media_ips present",
                ok=False,
                detail="media_ips empty — two-way audio likely to fail",
                severity="warn",
            )
        )
        next_actions.append("Collect Media IP(s) from provider sheet and re-run generate/apply-net")
    else:
        checks.append(
            CheckResult(
                name="media_ips present",
                ok=True,
                detail=f"{len(inv.network.media_ips)} media IP(s) configured",
                severity="info",
            )
        )

    if inv.provider.value == "airtel" and not inv.sip.password:
        checks.append(
            CheckResult(
                name="airtel password",
                ok=False,
                detail="Airtel requires sip.password",
            )
        )

    # Port checks
    checker = PortChecker(inv)
    if use_ssh and inv.ssh:
        try:
            with SSHClient(inv.ssh) as client:
                script = "\n".join(checker.remote_check_commands())
                script = (
                    f"ping -c 2 -W 2 {inv.network.gateway_ip}; "
                    f"ping -c 2 -W 2 {inv.network.sbc_ip}; "
                    + script
                    + f"; {registry_check_command(inv)} || true"
                )
                result = client.run(script)
                remote_report = checker.parse_remote_output(result.stdout + "\n" + result.stderr)
                checks.extend(remote_report.checks)
                checks.append(
                    CheckResult(
                        name="gateway ping",
                        ok="1 received" in result.stdout
                        or "2 received" in result.stdout
                        or " bytes from " in result.stdout,
                        detail=f"ping {inv.network.gateway_ip}",
                    )
                )
                checks.append(
                    CheckResult(
                        name="sbc ping",
                        ok=result.stdout.count("bytes from") >= 1
                        or "1 received" in result.stdout
                        or "2 received" in result.stdout,
                        detail=f"ping {inv.network.sbc_ip}",
                    )
                )
                reg_out = result.stdout
                registered = "Registered" in reg_out or "registered" in reg_out
                checks.append(
                    CheckResult(
                        name="sip registry",
                        ok=registered,
                        detail="Looked for Registered in Asterisk registry output",
                        severity="warn"
                        if inv.provider.value in ("jio", "vodafone") and not registered
                        else "error",
                    )
                )
                if not registered and inv.provider.value in ("jio", "vodafone"):
                    next_actions.append(
                        "Jio/Vi may work without classic Registered state — run a test call"
                    )
        except (SSHError, ValueError) as exc:
            checks.append(
                CheckResult(
                    name="ssh",
                    ok=False,
                    detail=str(exc),
                    severity="warn",
                )
            )
            next_actions.append("Fix SSH auth or run locally on the call server without --ssh")
            local = checker.check_local()
            checks.extend(local.checks)
    else:
        local = checker.check_local()
        checks.extend(local.checks)
        next_actions.append(
            "Re-run with --ssh after inventory.ssh is set for on-box ping/registry/firewall checks"
        )

    if artifacts_dir and Path(artifacts_dir).exists():
        checks.append(
            CheckResult(
                name="artifacts exist",
                ok=True,
                detail=str(artifacts_dir),
                severity="info",
            )
        )
    elif artifacts_dir:
        checks.append(
            CheckResult(
                name="artifacts exist",
                ok=False,
                detail=f"Missing {artifacts_dir} — run generate first",
            )
        )
        next_actions.append("Run: sipauto generate -i <inventory.yaml>")

    # Confidence
    hard_fail = [c for c in checks if not c.ok and c.severity == "error"]
    warn = [c for c in checks if not c.ok and c.severity == "warn"]
    if hard_fail:
        confidence = "RED"
    elif warn:
        confidence = "YELLOW"
    else:
        confidence = "GREEN"

    next_actions.extend(
        [
            f"Ensure UDP {inv.network.rtp_start}-{inv.network.rtp_end} open BOTH sides",
            "Ensure SIP UDP/TCP signaling port open BOTH sides to SBC",
        ]
    )

    return RunReport(
        site=inv.site.name,
        provider=inv.provider.value,
        platform=inv.platform.value,
        confidence=confidence,
        checks=checks,
        artifacts=[str(artifacts_dir)] if artifacts_dir else [],
        next_actions=next_actions,
    )
