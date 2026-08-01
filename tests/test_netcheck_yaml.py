from sipauto.util.netcheck import is_valid_host, validate_ssh_host
from sipauto.util import simple_yaml


def test_reject_bad_ipv4():
    assert not is_valid_host("10.192.168.56.10")
    ok, reason = validate_ssh_host("10.192.168.56.10")
    assert not ok
    assert "octet" in reason or "valid" in reason


def test_accept_good_host():
    assert is_valid_host("192.168.56.10")
    assert is_valid_host("call-server.local")
    ok, _ = validate_ssh_host("192.168.56.10")
    assert ok


def test_simple_yaml_roundtrip():
    text = """
site:
  name: demo
  mode: onprem
provider: tata
network:
  interface: eth1
  customer_ip: 10.0.80.98
  gateway_ip: 10.0.80.97
  sbc_ip: 10.0.76.11
  media_ips:
    - 10.0.76.12
sip:
  pilot: "8068167000"
  password: "1234"
"""
    data = simple_yaml.load(text)
    assert data["site"]["name"] == "demo"
    assert data["network"]["media_ips"] == ["10.0.76.12"]
    dumped = simple_yaml.dump(data)
    again = simple_yaml.load(dumped)
    assert again["provider"] == "tata"
