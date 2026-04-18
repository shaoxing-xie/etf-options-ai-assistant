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
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ensure_path() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _recent_trading_window_calendar_days(days: int = 5) -> tuple[str, str]:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
    return start, end


def _rotation_aligned_daily_window_calendar_days() -> tuple[str, str]:
    """
    与 `etf_rotation_core.run_rotation_pipeline` 的日线加载窗对齐量级（cal_back 上限约 1200 日历日），
    保证采集写入的 parquet 覆盖轮动/回测常见 lookback+corr+MA，避免盘中任务纯读缓存时仍大量补拉。
    """
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=850)).strftime("%Y-%m-%d")
    return start, end


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

    import pytz

    from src.config_loader import load_system_config
    from src.data_cache_universe import get_data_cache_universe

    config = load_system_config(use_cache=True)
    u = get_data_cache_universe(config)

    summary: dict = {"phase": args.phase, "universe": u, "steps": []}

    def _run_daily_historical_block() -> None:
        from plugins.data_collection.index.fetch_historical import tool_fetch_index_historical
        from plugins.data_collection.etf.fetch_historical import tool_fetch_etf_historical
        from plugins.data_collection.stock.fetch_historical import tool_fetch_stock_historical

        start, end = _rotation_aligned_daily_window_calendar_days()
        if u["index_codes"]:
            r = tool_fetch_index_historical(
                index_code=",".join(u["index_codes"]),
                period="daily",
                start_date=start,
                end_date=end,
                use_cache=True,
            )
            summary["steps"].append({"tool": "index_historical", "success": r.get("success"), "message": r.get("message")})
        if u["etf_codes"]:
            r = tool_fetch_etf_historical(
                etf_code=",".join(u["etf_codes"]),
                period="daily",
                start_date=start,
                end_date=end,
                use_cache=True,
            )
            summary["steps"].append({"tool": "etf_historical", "success": r.get("success"), "message": r.get("message")})
        if u["stock_codes"]:
            r = tool_fetch_stock_historical(
                stock_code=",".join(u["stock_codes"]),
                period="daily",
                start_date=start,
                end_date=end,
                use_cache=True,
            )
            summary["steps"].append({"tool": "stock_historical", "success": r.get("success"), "message": r.get("message")})

    if args.phase == "morning_daily":
        _run_daily_historical_block()

    elif args.phase in ("intraday_minute", "close_minute"):
        from plugins.data_collection.index.fetch_minute import tool_fetch_index_minute
        from plugins.data_collection.etf.fetch_minute import tool_fetch_etf_minute
        from plugins.data_collection.stock.fetch_minute import tool_fetch_stock_minute

        tz = pytz.timezone("Asia/Shanghai")
        now = datetime.now(tz)
        minute = now.minute

        if u["index_codes"]:
            r = tool_fetch_index_minute(
                index_code=",".join(u["index_codes"]),
                period="5,15,30",
                use_cache=True,
            )
            summary["steps"].append({"tool": "index_minute", "success": r.get("success"), "message": r.get("message")})
        if u["etf_codes"]:
            r = tool_fetch_etf_minute(
                etf_code=",".join(u["etf_codes"]),
                period="5,15,30",
                use_cache=True,
            )
            summary["steps"].append({"tool": "etf_minute", "success": r.get("success"), "message": r.get("message")})

        do_stock = bool(u["stock_codes"])
        if args.phase == "intraday_minute" and args.throttle_stock:
            do_stock = do_stock and minute in (1, 31)
        if do_stock:
            r = tool_fetch_stock_minute(
                stock_code=",".join(u["stock_codes"]),
                period="5,15,30",
                use_cache=True,
            )
            summary["steps"].append({"tool": "stock_minute", "success": r.get("success"), "message": r.get("message")})
        elif u["stock_codes"]:
            summary["steps"].append({"tool": "stock_minute", "skipped": True, "reason": "throttle_stock"})

        if args.phase == "close_minute":
            # 收盘后补写当日及近期日 K，与轮动 read_cache_data 区间重叠，利于纯读 parquet。
            summary["steps"].append({"tool": "daily_historical_after_close", "note": "etf/index/stock daily refresh"})
            _run_daily_historical_block()

    ok = all(
        s.get("success") is not False
        for s in summary["steps"]
        if isinstance(s.get("success"), bool)
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
