#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.analysis.predictors.kronos_enhancer import SUPPORTED_INDEXES, train_and_persist_kronos


def main() -> int:
    parser = argparse.ArgumentParser(description="Train local Kronos artifacts for six-index prediction.")
    parser.add_argument("--index-code", action="append", default=[], help="Specific index code, e.g. 000688.SH")
    args = parser.parse_args()
    codes = args.index_code or sorted(SUPPORTED_INDEXES)
    results = [train_and_persist_kronos(code) for code in codes]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
