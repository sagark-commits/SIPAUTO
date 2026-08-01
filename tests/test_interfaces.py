from sipauto.models import Inventory, NetworkConfig, Provider, SipConfig, Site
from sipauto.network.interfaces import (
    NicInfo,
    choose_interface,
    parse_ethtool,
    parse_ip_addr,
    parse_ip_link,
)

# Matches typical `ip -o link show` (single line per iface; \ separates sections)
SAMPLE_LINK = (
    "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN "
    "mode DEFAULT group default qlen 1000\\    link/loopback 00:00:00:00:00:00 "
    "brd 00:00:00:00:00:00\n"
    "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP "
    "mode DEFAULT group default qlen 1000\\    link/ether aa:bb:cc:dd:ee:01 "
    "brd ff:ff:ff:ff:ff:ff\n"
    "3: eth1: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN "
    "mode DEFAULT group default qlen 1000\\    link/ether aa:bb:cc:dd:ee:02 "
    "brd ff:ff:ff:ff:ff:ff\n"
)

SAMPLE_ADDR = (
    "1: lo    inet 127.0.0.1/8 scope host lo\n"
    "2: eth0    inet 10.10.10.5/24 brd 10.10.10.255 scope global eth0\n"
)

SAMPLE_ETHTOOL = """\
Settings for eth1:
	Supported ports: [ TP ]
	Speed: 1000Mb/s
	Duplex: Full
	Auto-negotiation: on
	Link detected: yes
"""


def test_parse_ip_link_and_addr():
    nics = parse_ip_link(SAMPLE_LINK)
    assert "eth0" in nics and "eth1" in nics
    assert nics["eth0"].state == "UP"
    assert nics["eth1"].state == "DOWN"
    assert nics["eth0"].mac == "aa:bb:cc:dd:ee:01"
    parse_ip_addr(SAMPLE_ADDR, nics)
    assert "10.10.10.5/24" in nics["eth0"].ipv4


def test_parse_ethtool():
    nic = NicInfo(name="eth1")
    parse_ethtool(SAMPLE_ETHTOOL, nic)
    assert nic.link == "yes"
    assert nic.speed == "1000Mb/s"
    assert nic.duplex == "Full"


def test_choose_interface_explicit_noninteractive():
    inv = Inventory(
        site=Site(name="t"),
        provider=Provider.TATA,
        network=NetworkConfig(
            interface="eth1",
            customer_ip="10.0.0.2",
            gateway_ip="10.0.0.1",
            sbc_ip="10.0.0.3",
        ),
        sip=SipConfig(pilot="1234", password="1234"),
    )
    chosen = choose_interface(inv, ask=False, interface="eno3", non_interactive_default=True)
    assert chosen == "eno3"
    assert inv.network.interface == "eno3"


def test_prompt_sip_interface_noninteractive_fallback(monkeypatch):
    from sipauto.network import interfaces as iface_mod
    from sipauto.network.interfaces import NicInfo, prompt_sip_interface

    fake = [
        NicInfo(name="ens192", state="UP", ipv4=["10.1.1.2/30"], link="yes", speed="1000Mb/s"),
        NicInfo(name="ens224", state="UP", ipv4=[], link="yes", speed="100Mb/s"),
    ]
    monkeypatch.setattr(iface_mod, "discover_interfaces", lambda **kwargs: fake)
    # prefer missing → pick first UP
    chosen = prompt_sip_interface(prefer="eth9", interactive=False)
    assert chosen == "ens192"
