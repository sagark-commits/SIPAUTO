from pathlib import Path

from sipauto.models import Provider
from sipauto.parser.carrier_sheet import parse_carrier_sheet
from sipauto.workflow.registry import diagnose_text

ROOT = Path(__file__).resolve().parents[1]
SHEETS = ROOT / "examples" / "carrier_sheets"


def test_parse_tata_sheet():
    text = (SHEETS / "tata_sample.txt").read_text()
    p = parse_carrier_sheet(text)
    assert p.provider == Provider.TATA
    assert p.customer_ip == "10.0.80.98"
    assert p.gateway_ip == "10.0.80.97"
    assert p.sbc_ip == "10.0.76.11"
    assert p.pilot == "8068167000"
    assert p.did_start == "8068167000"
    assert "10.0.76.12" in p.media_ips
    assert not p.missing_required()
    inv = p.to_inventory(site_name="t1", interface="eth1")
    assert inv.network.customer_ip == "10.0.80.98"


def test_parse_jio_sheet():
    p = parse_carrier_sheet((SHEETS / "jio_sample.txt").read_text())
    assert p.provider == Provider.JIO
    assert p.sbc_ip == "100.64.216.4"
    assert p.pilot == "4435048777"


def test_parse_airtel_sheet():
    p = parse_carrier_sheet((SHEETS / "airtel_sample.txt").read_text())
    assert p.provider == Provider.AIRTEL
    assert p.domain == "ims.airtel.in"
    assert p.password == "CHANGE_ME"
    assert "10.232.130.171" in p.media_ips


def test_diagnose_407_480():
    hits = diagnose_text("SIP/2.0 407 Proxy Authentication Required then 480")
    assert any(h.startswith("407") for h in hits)
    assert any(h.startswith("480") for h in hits)
