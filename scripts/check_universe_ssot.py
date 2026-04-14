#!/usr/bin/env python3
"""Fail (exit 1) on Universe / contract SSOT hard violations (subset of cross_validate)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_system_config  # noqa: E402
from src.config_validate import universe_ssot_violations  # noqa: E402


def main() -> int:
    cfg = load_system_config(use_cache=False)
    bad = universe_ssot_violations(cfg)
    for m in bad:
        print(m, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
