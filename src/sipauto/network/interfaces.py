"""Discover and select the SIP network interface (local or via SSH)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.table import Table

from sipauto.models import Inventory, SSHConfig
from sipauto.ssh import SSHClient

console = Console()

# Skip virtual/loopback noise by default (still shown if --all-ifaces)
_SKIP_PREFIXES = (
    "lo",
    "docker",
    "br-",
    "veth",
    "virbr",
    " tun",
    "tap",
    "cni",
    "flannel",
    "weave",
    "kube",
)


@dataclass
class NicInfo:
    name: str
    state: str = "UNKNOWN"
    mac: str = ""
    ipv4: list[str] = field(default_factory=list)
    link: Optional[str] = None  # yes / no
    speed: Optional[str] = None
    duplex: Optional[str] = None
    raw_ethtool: str = ""

    @property
    def summary(self) -> str:
        addrs = ",".join(self.ipv4) if self.ipv4 else "-"
        link = self.link or "?"
        speed = self.speed or "?"
        duplex = self.duplex or "?"
        return f"{self.name} state={self.state} ipv4={addrs} link={link} {speed} {duplex}"


def _should_skip(name: str, include_virtual: bool) -> bool:
    if include_virtual:
        return name == "lo"
    for p in _SKIP_PREFIXES:
        if name == p.strip() or name.startswith(p.strip()):
            return True
    return False


def parse_ip_link(text: str) -> dict[str, NicInfo]:
    """Parse `ip -o link show` output."""
    nics: dict[str, NicInfo] = {}
    # 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ... \    link/ether aa:bb:...
    line_pat = re.compile(
        r"^\d+:\s+([^:@]+)(?:@[^:]+)?:\s+<([^>]*)>",
        re.IGNORECASE | re.MULTILINE,
    )
    mac_pat = re.compile(r"link/ether\s+([0-9a-f:]+)", re.IGNORECASE)
    for line in text.splitlines():
        m = line_pat.search(line)
        if not m:
            continue
        name = m.group(1).strip()
        flags = m.group(2).upper()
        mac_m = mac_pat.search(line)
        mac = (mac_m.group(1) if mac_m else "").lower()
        state = "UP" if "UP" in flags.split(",") else "DOWN"
        nics[name] = NicInfo(name=name, state=state, mac=mac)
    return nics


def parse_ip_addr(text: str, nics: dict[str, NicInfo]) -> None:
    """Parse `ip -o -4 addr show` into nic.ipv4."""
    # 2: eth0    inet 10.0.0.5/30 brd ...
    pat = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\S+)", re.MULTILINE)
    for m in pat.finditer(text):
        name = m.group(1)
        addr = m.group(2)
        if name not in nics:
            nics[name] = NicInfo(name=name)
        nics[name].ipv4.append(addr)


def parse_ethtool(text: str, nic: NicInfo) -> None:
    nic.raw_ethtool = text
    link_m = re.search(r"Link detected:\s*(yes|no)", text, re.IGNORECASE)
    if link_m:
        nic.link = link_m.group(1).lower()
    speed_m = re.search(r"Speed:\s*(\S+)", text, re.IGNORECASE)
    if speed_m:
        nic.speed = speed_m.group(1)
    duplex_m = re.search(r"Duplex:\s*(\S+)", text, re.IGNORECASE)
    if duplex_m:
        nic.duplex = duplex_m.group(1)


def _run_local(cmd: str) -> str:
    try:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERROR: {exc}"


def discover_interfaces(
    *,
    ssh: Optional[SSHConfig] = None,
    include_virtual: bool = False,
    probe_ethtool: bool = True,
) -> list[NicInfo]:
    """List NICs on local machine or remote call server."""
    if ssh:
        with SSHClient(ssh) as client:
            link_out = client.run("ip -o link show").stdout
            addr_out = client.run("ip -o -4 addr show").stdout
            nics = parse_ip_link(link_out)
            parse_ip_addr(addr_out, nics)
            if probe_ethtool:
                for name, nic in list(nics.items()):
                    if _should_skip(name, include_virtual):
                        continue
                    et = client.run(
                        f"command -v ethtool >/dev/null && ethtool {name} 2>/dev/null || true"
                    ).stdout
                    if et.strip():
                        parse_ethtool(et, nic)
    else:
        nics = parse_ip_link(_run_local("ip -o link show"))
        parse_ip_addr(_run_local("ip -o -4 addr show"), nics)
        if probe_ethtool:
            for name, nic in list(nics.items()):
                if _should_skip(name, include_virtual):
                    continue
                et = _run_local(
                    f"command -v ethtool >/dev/null && ethtool {name} 2>/dev/null || true"
                )
                if "Link detected" in et or "Speed:" in et:
                    parse_ethtool(et, nic)

    result = [
        n for n in nics.values() if not _should_skip(n.name, include_virtual)
    ]
    result.sort(key=lambda n: n.name)
    return result


def print_interfaces(nics: list[NicInfo], default: Optional[str] = None) -> None:
    table = Table(title="Network interfaces (candidate SIP NICs)")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("State")
    table.add_column("IPv4")
    table.add_column("Link")
    table.add_column("Speed")
    table.add_column("Duplex")
    for idx, nic in enumerate(nics, start=1):
        marker = " *" if default and nic.name == default else ""
        table.add_row(
            str(idx),
            nic.name + marker,
            nic.state,
            ",".join(nic.ipv4) or "-",
            nic.link or "?",
            nic.speed or "?",
            nic.duplex or "?",
        )
    console.print(table)
    if default:
        console.print(f"[dim]* inventory default: {default}[/dim]")


def choose_interface(
    inv: Inventory,
    *,
    ask: bool = True,
    interface: Optional[str] = None,
    use_ssh: bool = False,
    include_virtual: bool = False,
    non_interactive_default: bool = False,
) -> str:
    """
    Resolve SIP interface.

    Priority:
      1) explicit --interface
      2) interactive prompt (if ask and TTY)
      3) inventory.network.interface
    """
    if interface:
        inv.network.interface = interface
        return interface

    default = inv.network.interface
    if not ask or non_interactive_default or not console.is_terminal:
        return default

    ssh_cfg = inv.ssh if use_ssh and inv.ssh else None
    where = f"SSH {ssh_cfg.host}" if ssh_cfg else "local host"
    console.print(f"[cyan]Discovering interfaces on {where}…[/cyan]")
    try:
        nics = discover_interfaces(ssh=ssh_cfg, include_virtual=include_virtual)
    except Exception as exc:  # noqa: BLE001 — show and fall back
        console.print(f"[yellow]Could not discover interfaces ({exc}). Using inventory: {default}[/yellow]")
        return default

    if not nics:
        console.print(f"[yellow]No interfaces found. Using inventory: {default}[/yellow]")
        return default

    print_interfaces(nics, default=default)

    # Highlight link-down warning for default
    for nic in nics:
        if nic.name == default and nic.link == "no":
            console.print(
                f"[yellow]Warning: inventory iface {default} has link=no "
                "(check cable / mux speed / duplex with carrier).[/yellow]"
            )

    names = {n.name for n in nics}
    while True:
        raw = console.input(
            f"Which interface should be used for SIP? [{default}]: "
        ).strip()
        if not raw:
            chosen = default
            break
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(nics):
                chosen = nics[idx - 1].name
                break
            console.print(f"[red]Pick a number 1–{len(nics)} or an interface name.[/red]")
            continue
        if raw in names:
            chosen = raw
            break
        # allow typing an iface not listed (vlan etc.)
        if re.match(r"^[A-Za-z0-9._-]+$", raw):
            if console.input(f"[yellow]{raw} not in list. Use it anyway? [y/N]: [/yellow]").strip().lower() in (
                "y",
                "yes",
            ):
                chosen = raw
                break
            continue
        console.print("[red]Invalid interface name.[/red]")

    inv.network.interface = chosen
    # Probe selected
    selected = next((n for n in nics if n.name == chosen), None)
    if selected:
        console.print(f"[green]Selected SIP interface:[/green] {selected.summary}")
        if selected.link == "no":
            console.print(
                "[yellow]Link is down on selected NIC — carrier mux/cable/VLAN may need attention "
                "before apply-net.[/yellow]"
            )
        if selected.speed and selected.speed.lower() not in (
            "1000mb/s",
            "1000mbps",
            "1gb/s",
            "unknown!",
            "unknown",
        ):
            # Tata docs: 100 vs 1000 mismatch is common
            console.print(
                f"[yellow]Speed is {selected.speed}. For Tata Ethernet SIP, confirm mux supports this.[/yellow]"
            )
    else:
        console.print(f"[green]Selected SIP interface:[/green] {chosen}")
    return chosen


def save_interface_to_inventory(path: str, interface: str) -> None:
    """Update network.interface in YAML inventory (preserves other keys best-effort)."""
    from pathlib import Path

    import yaml

    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("network", {})["interface"] = interface
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
