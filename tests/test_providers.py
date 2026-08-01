"""Golden-ish tests for provider register/peer generation."""

from pathlib import Path

import yaml

from sipauto.models import Inventory
from sipauto.providers import get_provider
from sipauto.workflow.generate import generate


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "inventories"


def _load(name: str) -> Inventory:
    data = yaml.safe_load((EXAMPLES / name).read_text())
    return Inventory.model_validate(data)


def test_tata_register_and_ppi():
    inv = _load("tata_ameyo.yaml")
    art = get_provider(inv).build(inv)
    assert art.register_line is not None
    assert "68167000" in art.register_line or "8068167000" in art.register_line
    assert "10.0.76.11" in art.register_line
    assert "P-Preferred-Identity" in art.custom_config
    assert "10.0.80.98" in art.custom_config
    assert "insecure=invite,port" in art.custom_config


def test_jio_register_without_password():
    inv = _load("jio_ameyo.yaml")
    art = get_provider(inv).build(inv)
    assert art.register_line is not None
    assert "4435048777@100.64.216.4/4435048777~1800" in art.register_line.replace(" ", "")
    assert "+91" in art.custom_config


def test_airtel_ims_register_and_hosts():
    inv = _load("airtel_ameyo.yaml")
    art = get_provider(inv).build(inv)
    assert art.register_line is not None
    assert "ims.airtel.in" in art.register_line
    assert "10.232.130.170" in art.register_line
    assert art.hosts_entries
    assert "ims.airtel.in" in art.hosts_entries[0]


def test_vodafone_ip_auth_no_register_by_default():
    inv = _load("vodafone_freepbx.yaml")
    art = get_provider(inv).build(inv)
    assert art.register_line is None
    assert "type=identify" in art.peer_pjsip
    assert "10.229.37.12" in art.peer_pjsip


def test_generate_writes_rtp_and_network(tmp_path):
    inv = _load("tata_ameyo.yaml")
    arts = generate(inv, tmp_path)
    paths = {Path(a.path).name for a in arts}
    assert "ifcfg" in paths
    assert "route" in paths
    assert "rtp.conf.snippet" in paths
    rtp = (tmp_path / "asterisk" / "rtp.conf.snippet").read_text()
    assert "rtpstart=10000" in rtp
    assert "rtpend=40000" in rtp
    route = (tmp_path / "network" / "route").read_text()
    assert "10.0.76.11/32" in route
    assert "10.0.76.12/32" in route
