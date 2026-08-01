"""SSH apply for network + SIP files and service reload."""

from __future__ import annotations

from pathlib import Path

from sipauto.models import Inventory, Platform
from sipauto.network.rhel import apply_paths, render_hosts_snippet, render_ifcfg, render_route_file
from sipauto.platforms.ameyo import AMEYO_WRITE_WARNING, ameyo_write_plan
from sipauto.platforms.asterisk import network_reload_commands, reload_commands
from sipauto.providers import get_provider
from sipauto.ssh import SSHClient, SSHResult
from sipauto.workflow.rollback import write_apply_manifest


def _require_ssh(inv: Inventory) -> None:
    if not inv.ssh:
        raise ValueError("inventory.ssh is required for apply/reload")


def apply_network(inv: Inventory, *, dry_run: bool = False) -> list[str]:
    """Write ifcfg + route files and reload interface."""
    _require_ssh(inv)
    artifacts = get_provider(inv).build(inv)
    paths = apply_paths(inv)
    ifcfg = render_ifcfg(inv)
    routes = render_route_file(inv)

    plan = [
        f"WRITE {paths['ifcfg']} (backup *.sipauto.bak)",
        f"WRITE {paths['route']} (backup *.sipauto.bak)",
    ]
    if artifacts.hosts_entries:
        plan.append(f"APPEND unique hosts entries to {paths['hosts']} (backup once)")
    plan.extend(network_reload_commands(inv.network.interface))

    if dry_run:
        return plan

    logs: list[str] = []
    written: list[str] = []
    with SSHClient(inv.ssh) as client:  # type: ignore[arg-type]
        client.write_file(paths["ifcfg"], ifcfg)
        logs.append(f"wrote {paths['ifcfg']}")
        written.append(paths["ifcfg"])
        client.write_file(paths["route"], routes)
        logs.append(f"wrote {paths['route']}")
        written.append(paths["route"])
        if artifacts.hosts_entries:
            r = client.append_unique_hosts(artifacts.hosts_entries)
            logs.append(r.stdout + r.stderr)
            written.append(paths["hosts"])
        for cmd in network_reload_commands(inv.network.interface):
            r = client.run(cmd)
            logs.append(f"$ {cmd}\n{r.stdout}{r.stderr}")
        write_apply_manifest(client, inv, written)
        logs.append("wrote apply manifest /var/tmp/sipauto-last-apply.json")
    return logs


def apply_sip(
    inv: Inventory,
    artifacts_dir: str | Path,
    *,
    ameyo_write: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """
    Apply SIP artifacts over SSH.

    For Ameyo: only writes Asterisk include snippets when ameyo_write=True
    (caller must confirm interactively).
    """
    _require_ssh(inv)
    out = Path(artifacts_dir)
    if not out.exists():
        raise FileNotFoundError(f"Artifacts dir not found: {out}. Run generate first.")

    provider = get_provider(inv)
    artifacts = provider.build(inv)
    logs: list[str] = [f"Using artifacts from {out}"]

    if inv.platform == Platform.FREEPBX:
        etc = inv.freepbx.asterisk_etc.rstrip("/")
        trunk = inv.freepbx.trunk_name or f"{inv.provider.value}siptrunk"
        remote_files = {}
        local_pjsip = out / "freepbx" / f"pjsip_{trunk}.conf"
        local_sip = out / "freepbx" / f"sip_{trunk}.conf"
        if local_pjsip.exists():
            remote_files[f"{etc}/sipauto_{trunk}_pjsip.conf"] = local_pjsip.read_text()
        if local_sip.exists():
            remote_files[f"{etc}/sipauto_{trunk}_sip.conf"] = local_sip.read_text()
        rtp = out / "asterisk" / "rtp.conf.snippet"
        if rtp.exists():
            remote_files[f"{etc}/sipauto_rtp.snippet"] = rtp.read_text()
    else:
        if not ameyo_write:
            return [
                AMEYO_WRITE_WARNING,
                "Ameyo write skipped (ameyo_write=False). "
                "Pass confirmation to write Asterisk include snippets.",
                f"Paste packs are in {out}/ameyo/",
            ]
        remote_files = ameyo_write_plan(inv, artifacts)
        logs.append(AMEYO_WRITE_WARNING)

    if dry_run:
        return logs + [f"WRITE {p} (backup *.sipauto.bak)" for p in remote_files]

    written: list[str] = []
    with SSHClient(inv.ssh) as client:  # type: ignore[arg-type]
        for remote, content in remote_files.items():
            client.write_file(remote, content)
            logs.append(f"wrote {remote}")
            written.append(remote)
            # ensure include line for peer files
            if remote.endswith("_peer.conf"):
                logs.append(
                    _ensure_include(client, f"{inv.ameyo.asterisk_etc}/sip.conf", Path(remote).name).stdout
                )
            if remote.endswith("_pjsip.conf"):
                pjsip_conf = f"{inv.ameyo.asterisk_etc if inv.platform != Platform.FREEPBX else inv.freepbx.asterisk_etc}/pjsip.conf"
                logs.append(_ensure_include(client, pjsip_conf, Path(remote).name).stdout)
        # merge with any prior network apply manifest
        write_apply_manifest(client, inv, written)
        logs.append("updated apply manifest /var/tmp/sipauto-last-apply.json")
    return logs


def _ensure_include(client: SSHClient, conf_path: str, include_name: str) -> SSHResult:
    cmd = (
        f"if [ -f {conf_path} ]; then "
        f"grep -q '{include_name}' {conf_path} || echo '#include \"{include_name}\"' >> {conf_path}; "
        f"echo INCLUDE_OK {include_name}; "
        f"else echo MISSING {conf_path}; fi"
    )
    return client.run(cmd)


def reload_services(inv: Inventory, *, dry_run: bool = False) -> list[str]:
    _require_ssh(inv)
    cmds = reload_commands(inv)
    if dry_run:
        return cmds
    logs: list[str] = []
    with SSHClient(inv.ssh) as client:  # type: ignore[arg-type]
        for cmd in cmds:
            r = client.run(cmd)
            logs.append(f"$ {cmd}\n{r.stdout}{r.stderr}")
    return logs
