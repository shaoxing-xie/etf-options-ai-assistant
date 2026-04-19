#!/usr/bin/env python3
"""
按分层配置中的 data_cache 节批量拉数并写入本地缓存（与 OpenClaw tool_fetch_* 同一套 plugins 实现）。

用法（项目根目录）:
  PYTHONPATH=. python3 scripts/run_data_cache_collection.py morning_daily
  PYTHONPATH=. python3 scripts/run_data_cache_collection.py intraday_minute [--throttle-stock]
  PYTHONPATH=. python3 scripts/run_data_cache_collection.py close_minute
  # close_minute：先拉 5/15/30 分钟线，再跑与 morning_daily 相同的长窗日 K（含当日收盘 bar）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ensure_path() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def main() -> int:
    _ensure_path()

    parser = argparse.ArgumentParser(description="data_cache 标的批量采集写缓存")
    parser.add_argument(
        "phase",
        choices=("morning_daily", "intraday_minute", "close_minute"),
        help="morning_daily=日K；intraday/close=分钟 5/15/30 批量缓存模式",
    )
    parser.add_argument(
        "--throttle-stock",
        action="store_true",
        help="intraday 时仅当当前分钟为 1 或 31 才拉股票分钟（与 Cron 错峰一致）",
    )
    args = parser.parse_args()

    from src.data_cache_collection_core import run_data_cache_collection, summary_success, summary_to_json_line

    summary = run_data_cache_collection(
        args.phase,
        throttle_stock=args.throttle_stock,
    )
    print(summary_to_json_line(summary))
    return 0 if summary_success(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
