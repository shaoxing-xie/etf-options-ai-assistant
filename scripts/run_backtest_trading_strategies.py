#!/usr/bin/env python3
"""
Stable entrypoint for OpenClaw exec: one `python3` process, no `cd &&`.

Delegates to skills/backtesting-trading-strategies/scripts/backtest.py (same argv tail).

Example:
  python3 /path/to/etf-options-ai-assistant/scripts/run_backtest_trading_strategies.py \\
    --strategy sma_crossover --symbol 510300.SS --period 1y
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKTEST = ROOT / "skills/backtesting-trading-strategies/scripts/backtest.py"


def main() -> None:
    if not BACKTEST.is_file():
        print(f"Missing backtest script: {BACKTEST}", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(subprocess.call([sys.executable, str(BACKTEST)] + sys.argv[1:]))


if __name__ == "__main__":
    main()
