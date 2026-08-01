"""Discover and select the SIP network interface (local or via SSH)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sipauto.models import Inventory, SSHConfig
from sipauto.ssh import SSHClient, SSHError
from sipauto.util.console import ask, confirm, console, print_table
from sipauto.util import simple_yaml

# Skip virtual/loopback noise by default
_SKIP_PREFIXES = (
    "lo",
    "docker",
    "br-",
    "veth",
    "virbr",
    "tun",
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
    link: Optional[str] = None
    speed: Optional[str] = None
    duplex: Optional[str] = None
    raw_ethtool: str = ""

    @property
    def summary(self) -> str:
        addrs = ",".join(self.ipv4) if self.ipv4 else "-"
        return (
            f"{self.name} state={self.state} ipv4={addrs} "
            f"link={self.link or '?'} {self.speed or '?'} {self.duplex or '?'}"
        )


def _should_skip(name: str, include_virtual: bool) -> bool:
    if include_virtual:
        return name == "lo"
    for p in _SKIP_PREFIXES:
        if name == p or name.startswith(p):
            return True
    return False


def parse_ip_link(text: str) -> dict[str, NicInfo]:
    nics: dict[str, NicInfo] = {}
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

    result = [n for n in nics.values() if not _should_skip(n.name, include_virtual)]
    result.sort(key=lambda n: n.name)
    return result


def print_interfaces(nics: list[NicInfo], default: Optional[str] = None) -> None:
    rows = []
    for idx, nic in enumerate(nics, start=1):
        marker = " *" if default and nic.name == default else ""
        rows.append(
            [
                str(idx),
                nic.name + marker,
                nic.state,
                ",".join(nic.ipv4) or "-",
                nic.link or "?",
                nic.speed or "?",
                nic.duplex or "?",
            ]
        )
    print_table(
        "Network interfaces (candidate SIP NICs)",
        ["#", "Name", "State", "IPv4", "Link", "Speed", "Duplex"],
        rows,
    )
    if default:
        console.print(f"* inventory default: {default}")


def choose_interface(
    inv: Inventory,
    *,
    ask: bool = True,
    interface: Optional[str] = None,
    use_ssh: bool = False,
    include_virtual: bool = False,
    non_interactive_default: bool = False,
) -> str:
    if interface:
        inv.network.interface = interface
        return interface

    default = inv.network.interface
    if not ask or non_interactive_default or not console.is_terminal:
        return default

    ssh_cfg = inv.ssh if use_ssh and inv.ssh else None
    where = f"SSH {ssh_cfg.host}" if ssh_cfg else "local host"
    console.print(f"Discovering interfaces on {where}…")
    try:
        nics = discover_interfaces(ssh=ssh_cfg, include_virtual=include_virtual)
    except (SSHError, Exception) as exc:  # noqa: BLE001
        console.print(f"Could not discover interfaces ({exc}). Using inventory: {default}")
        # fall back to local if SSH failed
        if ssh_cfg:
            try:
                nics = discover_interfaces(ssh=None, include_virtual=include_virtual)
                console.print("Falling back to LOCAL interface list.")
            except Exception:
                return default
        else:
            return default

    if not nics:
        console.print(f"No interfaces found. Using inventory: {default}")
        return default

    # Auto-select when only one physical NIC and default missing/wrong
    if len(nics) == 1:
        chosen = nics[0].name
        console.print(f"Only one candidate NIC — auto-selected: {chosen}")
        inv.network.interface = chosen
        console.print(nics[0].summary)
        return chosen

    print_interfaces(nics, default=default)
    for nic in nics:
        if nic.name == default and nic.link == "no":
            console.print(
                f"Warning: inventory iface {default} has link=no "
                "(check cable / mux speed / duplex with carrier)."
            )

    names = {n.name for n in nics}
    # prefer default if present, else first UP+link yes
    if default not in names:
        up = next((n.name for n in nics if n.state == "UP" and n.link != "no"), nics[0].name)
        default = up

    while True:
        raw = ask("Which interface should be used for SIP?", default=default)
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(nics):
                chosen = nics[idx - 1].name
                break
            console.print(f"Pick a number 1–{len(nics)} or an interface name.")
            continue
        if raw in names:
            chosen = raw
            break
        if re.match(r"^[A-Za-z0-9._-]+$", raw):
            if confirm(f"{raw} not in list. Use it anyway?", default=False):
                chosen = raw
                break
            continue
        console.print("Invalid interface name.")

    inv.network.interface = chosen
    selected = next((n for n in nics if n.name == chosen), None)
    if selected:
        console.print(f"Selected SIP interface: {selected.summary}")
        if selected.link == "no":
            console.print(
                "Link is down on selected NIC — carrier mux/cable/VLAN may need attention."
            )
    else:
        console.print(f"Selected SIP interface: {chosen}")
    return chosen


def save_interface_to_inventory(path: str, interface: str) -> None:
    p = Path(path)
    data = simple_yaml.loads_file(str(p)) or {}
    data.setdefault("network", {})["interface"] = interface
    p.write_text(simple_yaml.dump(data) + "\n", encoding="utf-8")
