from pathlib import Path

import yaml
from typer.testing import CliRunner

from sipauto.cli import app
from sipauto.models import Inventory
from sipauto.workflow.preflight import run_preflight
from sipauto.workflow.rollback import expected_backup_paths

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "inventories"
SHEETS = ROOT / "examples" / "carrier_sheets"
runner = CliRunner()


def test_preflight_local_scores():
    inv = Inventory.model_validate(yaml.safe_load((EXAMPLES / "tata_ameyo.yaml").read_text()))
    report = run_preflight(inv, use_ssh=False)
    assert report.confidence in ("GREEN", "YELLOW", "RED")
    assert report.checks
    assert report.next_actions


def test_parse_sheet_cli(tmp_path):
    out = tmp_path / "inv.yaml"
    r = runner.invoke(
        app,
        [
            "parse-sheet",
            "-s",
            str(SHEETS / "tata_sample.txt"),
            "-o",
            str(out),
            "--site",
            "cli-tata",
            "-I",
            "eth1",
        ],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(out.read_text())
    assert data["provider"] == "tata"
    assert data["network"]["sbc_ip"] == "10.0.76.11"


def test_diagnose_cli():
    r = runner.invoke(app, ["diagnose", "got 407 Proxy Authentication Required"])
    assert r.exit_code == 0
    assert "407" in r.output


def test_expected_backup_paths():
    inv = Inventory.model_validate(yaml.safe_load((EXAMPLES / "tata_ameyo.yaml").read_text()))
    paths = expected_backup_paths(inv)
    assert any("ifcfg-eth1.sipauto.bak" in p for p in paths)
