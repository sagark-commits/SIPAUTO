"""Apply network + SIP files and service reload (SSH or local on call server)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sipauto.models import Inventory, Platform
from sipauto.network.rhel import apply_paths, render_ifcfg, render_route_file
from sipauto.platforms.ameyo import AMEYO_WRITE_WARNING, ameyo_write_plan
from sipauto.platforms.asterisk import network_reload_commands, reload_commands
from sipauto.providers import get_provider
from sipauto.ssh import SSHClient, SSHError, SSHResult
from sipauto.util.netcheck import looks_like_local_call_server
from sipauto.workflow.rollback import write_apply_manifest


class LocalClient:
    """Minimal local stand-in for SSHClient (already on call server)."""

    def __enter__(self) -> "LocalClient":
        return self

    def __exit__(self, *args) -> None:
        return None

    def run(self, command: str, timeout: int = 120, check: bool = False) -> SSHResult:
        _ = check
        try:
            proc = subprocess.run(
                ["bash", "-lc", command],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return SSHResult(124, "", "command timed out")
        return SSHResult(proc.returncode, proc.stdout or "", proc.stderr or "")

    def write_file(self, remote_path: str, content: str, mode: int = 0o644) -> None:
        p = Path(remote_path)
        if p.exists():
            bak = Path(str(p) + ".sipauto.bak")
            if not bak.exists():
                bak.write_bytes(p.read_bytes())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        try:
            p.chmod(mode)
        except OSError:
            pass

    def append_unique_hosts(self, entries: list[str]) -> SSHResult:
        hosts = Path("/etc/hosts")
        if hosts.exists() and not Path("/etc/hosts.sipauto.bak").exists():
            Path("/etc/hosts.sipauto.bak").write_bytes(hosts.read_bytes())
        existing = hosts.read_text(encoding="utf-8") if hosts.exists() else ""
        added = []
        for line in entries:
            _ip, _, name = line.partition(" ")
            name = name.strip()
            if name and name not in existing:
                existing += ("" if existing.endswith("\n") or not existing else "\n") + line + "\n"
                added.append(line)
        hosts.write_text(existing, encoding="utf-8")
        return SSHResult(0, f"added {len(added)} hosts lines", "")


def _client(inv: Inventory, *, allow_local: bool = False):
    if inv.ssh:
        return SSHClient(inv.ssh)
    if allow_local or looks_like_local_call_server():
        return LocalClient()
    raise ValueError(
        "inventory.ssh is required for apply/reload (or run on the call server / pass allow_local)"
    )


def apply_network(
    inv: Inventory, *, dry_run: bool = False, allow_local: bool = False
) -> list[str]:
    """Write ifcfg + route files and reload interface."""
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
    try:
        with _client(inv, allow_local=allow_local) as client:
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
    except SSHError as e:
        raise ValueError(str(e)) from e
    return logs


def apply_sip(
    inv: Inventory,
    artifacts_dir: str | Path,
    *,
    ameyo_write: bool = False,
    dry_run: bool = False,
    allow_local: bool = False,
) -> list[str]:
    """Apply SIP artifacts over SSH or locally."""
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
    try:
        with _client(inv, allow_local=allow_local) as client:
            for remote, content in remote_files.items():
                client.write_file(remote, content)
                logs.append(f"wrote {remote}")
                written.append(remote)
                if remote.endswith("_peer.conf"):
                    logs.append(
                        _ensure_include(
                            client, f"{inv.ameyo.asterisk_etc}/sip.conf", Path(remote).name
                        ).stdout
                    )
                if remote.endswith("_pjsip.conf"):
                    etc = (
                        inv.ameyo.asterisk_etc
                        if inv.platform != Platform.FREEPBX
                        else inv.freepbx.asterisk_etc
                    )
                    logs.append(_ensure_include(client, f"{etc}/pjsip.conf", Path(remote).name).stdout)
            write_apply_manifest(client, inv, written)
            logs.append("updated apply manifest /var/tmp/sipauto-last-apply.json")
    except SSHError as e:
        raise ValueError(str(e)) from e
    return logs


def _ensure_include(client, conf_path: str, include_name: str) -> SSHResult:
    cmd = (
        f"if [ -f {conf_path} ]; then "
        f"grep -q '{include_name}' {conf_path} || echo '#include \"{include_name}\"' >> {conf_path}; "
        f"echo INCLUDE_OK {include_name}; "
        f"else echo MISSING {conf_path}; fi"
    )
    return client.run(cmd)


def reload_services(
    inv: Inventory, *, dry_run: bool = False, allow_local: bool = False
) -> list[str]:
    cmds = reload_commands(inv)
    if dry_run:
        return cmds
    logs: list[str] = []
    try:
        with _client(inv, allow_local=allow_local) as client:
            for cmd in cmds:
                r = client.run(cmd)
                logs.append(f"$ {cmd}\n{r.stdout}{r.stderr}")
    except SSHError as e:
        raise ValueError(str(e)) from e
    return logs
