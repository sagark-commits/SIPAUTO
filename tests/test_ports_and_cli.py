from pathlib import Path

from sipauto.cli import invoke
from sipauto.models import Inventory
from sipauto.network.ports import PortChecker
from sipauto.util import simple_yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "inventories"


def test_port_checker_rtp_policy():
    data = simple_yaml.loads_file(str(EXAMPLES / "tata_ameyo.yaml"))
    inv = Inventory.model_validate(data)
    report = PortChecker(inv).check_local()
    names = {c.name for c in report.checks}
    assert "RTP range policy" in names
    assert any("SIP UDP" in n for n in names)
    assert any("SIP TCP" in n for n in names)


def test_cli_generate_validate(tmp_path):
    inv = EXAMPLES / "tata_ameyo.yaml"
    out = tmp_path / "out"
    r = invoke(["validate", "-i", str(inv)])
    assert r.exit_code == 0, r.output
    r = invoke(["generate", "-i", str(inv), "-o", str(out), "--no-ask-iface"])
    assert r.exit_code == 0, r.output
    assert (out / "MANIFEST.json").exists()
    assert (out / "ameyo" / "ameyo_global_sip.conf.txt").exists()
    r = invoke(["verify", "-i", str(inv), "-o", str(out)])
    assert (out / "verify_report.json").exists()


def test_offline_module_version():
    r = invoke(["version"])
    assert r.exit_code == 0
    assert "0.1.0" in r.output
