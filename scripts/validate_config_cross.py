#!/usr/bin/env python3
"""Cross-validate merged config: hard errors exit 1; soft (e.g. holiday Q4 hint) print to stderr only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config_loader import load_system_config  # noqa: E402
from src.config_validate import (  # noqa: E402
    classify_validation_messages,
    cross_validate_runtime_config,
)


def main() -> int:
    cfg = load_system_config(use_cache=False)
    msgs = cross_validate_runtime_config(cfg)
    hard, soft = classify_validation_messages(msgs)
    for m in soft:
        print(m, file=sys.stderr)
    for m in hard:
        print(m, file=sys.stderr)
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
