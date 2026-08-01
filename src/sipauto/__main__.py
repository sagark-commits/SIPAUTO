"""Allow `python3 -m sipauto` with PYTHONPATH=src (no pip install)."""

from __future__ import annotations

import sys

from sipauto.cli import main

if __name__ == "__main__":
    sys.exit(main())
