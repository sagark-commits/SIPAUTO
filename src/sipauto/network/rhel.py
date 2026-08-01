"""Rocky Linux / RHEL network config renderers (ifcfg + route-* files)."""

from __future__ import annotations

from sipauto.models import Inventory
from sipauto.providers.base import SipArtifacts


def _prefix_from_netmask(netmask: str) -> int:
    parts = [int(x) for x in netmask.split(".")]
    return sum(bin(p).count("1") for p in parts)


def render_ifcfg(inv: Inventory) -> str:
    """Render NetworkManager/ifcfg-style file for Rocky/RHEL."""
    net = inv.network
    prefix = net.prefix if net.prefix is not None else _prefix_from_netmask(net.netmask)
    iface = net.interface
    lines = [
        f"DEVICE={iface}",
        "BOOTPROTO=none",
        "ONBOOT=yes",
        "NM_CONTROLLED=yes",
        "TYPE=Ethernet",
        f"IPADDR={net.customer_ip}",
        f"PREFIX={prefix}",
        f"NETMASK={net.netmask}",
        # Do NOT set GATEWAY here — use host routes on SIP NIC to avoid stealing default route
    ]
    if net.vlan_id is not None:
        lines.append(f"VLAN=yes")
        lines.append(f"# VLAN_ID={net.vlan_id} — ensure parent + vlan iface naming matches site standard")
    lines.append("")
    return "\n".join(lines)


def render_route_file(inv: Inventory) -> str:
    """Render /etc/sysconfig/network-scripts/route-<iface> content."""
    net = inv.network
    iface = net.interface
    gw = net.gateway_ip
    lines = [
        f"{net.sbc_ip}/32 via {gw} dev {iface}",
    ]
    for mip in net.media_ips:
        lines.append(f"{mip}/32 via {gw} dev {iface}")
    lines.append("")
    return "\n".join(lines)


def render_hosts_snippet(artifacts: SipArtifacts) -> str:
    if not artifacts.hosts_entries:
        return "# (no hosts entries for this provider)\n"
    return "\n".join(artifacts.hosts_entries) + "\n"


def apply_paths(inv: Inventory) -> dict[str, str]:
    """Remote paths for Rocky/RHEL network scripts."""
    iface = inv.network.interface
    return {
        "ifcfg": f"/etc/sysconfig/network-scripts/ifcfg-{iface}",
        "route": f"/etc/sysconfig/network-scripts/route-{iface}",
        "hosts": "/etc/hosts",
    }
