"""Load inventory YAML."""

from __future__ import annotations

from pathlib import Path

import yaml

from sipauto.models import Inventory


def load_inventory(path: str | Path) -> Inventory:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Inventory YAML must be a mapping")
    return Inventory.model_validate(data)
