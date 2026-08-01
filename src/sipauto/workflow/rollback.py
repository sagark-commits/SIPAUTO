"""Rollback files restored from *.sipauto.bak created during apply."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sipauto.models import Inventory, Platform
from sipauto.network.rhel import apply_paths
from sipauto.platforms.asterisk import network_reload_commands, reload_commands
from sipauto.ssh import SSHClient

REMOTE_MANIFEST = "/var/tmp/sipauto-last-apply.json"


@dataclass
class RollbackPlan:
    backups: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


def expected_backup_paths(inv: Inventory) -> list[str]:
    """Paths we typically create .sipauto.bak for."""
    paths = apply_paths(inv)
    bak = [
        paths["ifcfg"] + ".sipauto.bak",
        paths["route"] + ".sipauto.bak",
        paths["hosts"] + ".sipauto.bak",
    ]
    etc = (
        inv.freepbx.asterisk_etc
        if inv.platform == Platform.FREEPBX
        else inv.ameyo.asterisk_etc
    ).rstrip("/")
    entity = inv.ameyo.entity_name or inv.provider.value
    trunk = inv.freepbx.trunk_name or f"{inv.provider.value}siptrunk"
    for name in (
        f"sipauto_{entity}_peer.conf",
        f"sipauto_{entity}_pjsip.conf",
        f"sipauto_{entity}_global_sip.snippet",
        f"sipauto_rtp.snippet",
        f"sipauto_{trunk}_pjsip.conf",
        f"sipauto_{trunk}_sip.conf",
    ):
        bak.append(f"{etc}/{name}.sipauto.bak")
    return bak


def write_apply_manifest(client: SSHClient, inv: Inventory, written: list[str]) -> None:
    existing: dict = {}
    raw = client.run(f"cat {REMOTE_MANIFEST} 2>/dev/null || true").stdout
    if raw.strip():
        try:
            existing = json.loads(raw)
        except json.JSONDecodeError:
            existing = {}
    prev_written = list(existing.get("written", []))
    merged = list(dict.fromkeys(prev_written + written))
    payload = {
        "site": inv.site.name,
        "provider": inv.provider.value,
        "interface": inv.network.interface,
        "written": merged,
        "backups": [f"{p}.sipauto.bak" for p in merged],
    }
    # write_file would backup the manifest itself; use shell for atomic replace
    content = json.dumps(payload, indent=2) + "\n"
    client.run(f"cat > {REMOTE_MANIFEST} <<'EOF'\n{content}EOF")


def plan_rollback(inv: Inventory, *, use_manifest: bool = True) -> RollbackPlan:
    """Build rollback plan (dry-run friendly). Requires SSH to inspect remote."""
    if not inv.ssh:
        raise ValueError("inventory.ssh required for rollback")
    plan = RollbackPlan()
    with SSHClient(inv.ssh) as client:
        candidates = expected_backup_paths(inv)
        if use_manifest:
            man = client.run(f"cat {REMOTE_MANIFEST} 2>/dev/null || true").stdout
            if man.strip():
                try:
                    data = json.loads(man)
                    candidates = list(dict.fromkeys(data.get("backups", []) + candidates))
                except json.JSONDecodeError:
                    pass
        for bak in candidates:
            exists = client.run(f"test -f {bak} && echo YES || echo NO").stdout
            if "YES" in exists:
                target = bak[: -len(".sipauto.bak")]
                plan.backups.append(bak)
                plan.actions.append(f"RESTORE {bak} -> {target}")
        if not plan.backups:
            # wildcard scan
            scan = client.run(
                "ls -1 /etc/sysconfig/network-scripts/*.sipauto.bak "
                "/etc/asterisk/*.sipauto.bak /etc/hosts.sipauto.bak 2>/dev/null || true"
            ).stdout
            for bak in [ln.strip() for ln in scan.splitlines() if ln.strip()]:
                target = bak[: -len(".sipauto.bak")]
                plan.backups.append(bak)
                plan.actions.append(f"RESTORE {bak} -> {target}")
        plan.actions.append("reload network iface + asterisk sip/pjsip/rtp")
    return plan


def rollback(inv: Inventory, *, dry_run: bool = False) -> list[str]:
    """Restore *.sipauto.bak files and reload services."""
    plan = plan_rollback(inv)
    if dry_run:
        return plan.actions or ["No backups found"]

    if not plan.backups:
        return ["No *.sipauto.bak backups found to restore"]

    logs: list[str] = []
    with SSHClient(inv.ssh) as client:  # type: ignore[arg-type]
        for bak in plan.backups:
            target = bak[: -len(".sipauto.bak")]
            r = client.run(f"cp -a {bak} {target} && echo RESTORED {target}")
            logs.append((r.stdout + r.stderr).strip())
        for cmd in network_reload_commands(inv.network.interface):
            r = client.run(cmd)
            logs.append(f"$ {cmd}\n{r.stdout}{r.stderr}")
        for cmd in reload_commands(inv):
            r = client.run(cmd)
            logs.append(f"$ {cmd}\n{r.stdout}{r.stderr}")
        client.run(
            f"mv {REMOTE_MANIFEST} {REMOTE_MANIFEST}.rolledback 2>/dev/null || true"
        )
    return logs


def save_local_rollback_note(artifacts_dir: str | Path, plan: RollbackPlan) -> Path:
    out = Path(artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "rollback_plan.txt"
    path.write_text("\n".join(plan.actions) + "\n", encoding="utf-8")
    return path
