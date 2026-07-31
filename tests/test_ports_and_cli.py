from pathlib import Path

import yaml
from typer.testing import CliRunner

from sipauto.cli import app
from sipauto.models import Inventory
from sipauto.network.ports import PortChecker

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "inventories"
runner = CliRunner()


def test_port_checker_rtp_policy():
    data = yaml.safe_load((EXAMPLES / "tata_ameyo.yaml").read_text())
    inv = Inventory.model_validate(data)
    report = PortChecker(inv).check_local()
    names = {c.name for c in report.checks}
    assert "RTP range policy" in names
    assert any("SIP UDP" in n for n in names)
    assert any("SIP TCP" in n for n in names)


def test_cli_generate_validate(tmp_path):
    inv = EXAMPLES / "tata_ameyo.yaml"
    out = tmp_path / "out"
    r = runner.invoke(app, ["validate", "-i", str(inv)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["generate", "-i", str(inv), "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert (out / "MANIFEST.json").exists()
    assert (out / "ameyo" / "ameyo_global_sip.conf.txt").exists()
    r = runner.invoke(app, ["verify", "-i", str(inv), "-o", str(out)])
    # verify may exit 1 if local probes to private SBC fail — accept 0 or 1 with report
    assert (out / "verify_report.json").exists()
