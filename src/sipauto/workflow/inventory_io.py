"""Load / save inventory YAML or JSON (stdlib)."""

from __future__ import annotations

from pathlib import Path

from sipauto.models import Inventory
from sipauto.util import simple_yaml


def load_inventory(path: str | Path) -> Inventory:
    data = simple_yaml.loads_file(str(path))
    if not isinstance(data, dict):
        raise ValueError("Inventory must be a mapping/object")
    return Inventory.from_dict(data)


def save_inventory(path: str | Path, inv: Inventory) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = simple_yaml.dump(inv.model_dump())
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text, encoding="utf-8")


def write_inventory(inv: Inventory, path: str | Path) -> None:
    """Alias used by wizard."""
    save_inventory(path, inv)
