from pathlib import Path

from sipauto.models import Inventory
from sipauto.providers import get_provider
from sipauto.util import simple_yaml
from sipauto.workflow.generate import generate

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "inventories"


def _load(name: str) -> Inventory:
    data = simple_yaml.loads_file(str(EXAMPLES / name))
    return Inventory.model_validate(data)


def test_tata_provider_and_generate(tmp_path):
    inv = _load("tata_ameyo.yaml")
    arts = get_provider(inv).build(inv)
    assert arts.global_sip
    out = generate(inv, tmp_path / "tata")
    assert any("MANIFEST.json" in a.path for a in out)


def test_jio_provider(tmp_path):
    inv = _load("jio_ameyo.yaml")
    arts = get_provider(inv).build(inv)
    assert inv.network.media_ips
    generate(inv, tmp_path / "jio")


def test_airtel_provider(tmp_path):
    inv = _load("airtel_ameyo.yaml")
    arts = get_provider(inv).build(inv)
    assert arts.hosts_entries or inv.sip.domain
    generate(inv, tmp_path / "airtel")


def test_vodafone_freepbx(tmp_path):
    inv = _load("vodafone_freepbx.yaml")
    arts = get_provider(inv).build(inv)
    assert arts
    generate(inv, tmp_path / "vi")
