from pathlib import Path

from sipauto.cli import invoke
from sipauto.models import Inventory
from sipauto.util import simple_yaml
from sipauto.workflow.preflight import run_preflight
from sipauto.workflow.rollback import expected_backup_paths

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "inventories"


def test_preflight_local_tata():
    inv = Inventory.model_validate(simple_yaml.loads_file(str(EXAMPLES / "tata_ameyo.yaml")))
    report = run_preflight(inv, use_ssh=False)
    assert report.confidence in ("GREEN", "YELLOW", "RED")
    assert any(c.name == "media_ips" for c in report.checks)


def test_parse_sheet_cli(tmp_path):
    sheet = ROOT / "examples" / "carrier_sheets" / "tata_sample.txt"
    out = tmp_path / "inv.yaml"
    r = invoke(
        [
            "parse-sheet",
            "-s",
            str(sheet),
            "-o",
            str(out),
            "--site",
            "cli-tata",
            "-I",
            "eth1",
            "--no-ask-iface",
        ]
    )
    assert r.exit_code == 0, r.output
    data = simple_yaml.loads_file(str(out))
    assert data["network"]["customer_ip"]
    assert data["provider"] == "tata"


def test_expected_backup_paths():
    inv = Inventory.model_validate(simple_yaml.loads_file(str(EXAMPLES / "tata_ameyo.yaml")))
    paths = expected_backup_paths(inv)
    assert any("ifcfg" in p or "network-scripts" in p for p in paths)
