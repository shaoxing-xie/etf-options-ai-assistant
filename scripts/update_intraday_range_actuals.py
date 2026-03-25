#!/usr/bin/env python3
"""
收盘后回填：为日内波动区间预测补充 actual_range（high/low/close）并触发 hit 计算。

输入：
  data/prediction_records/predictions_YYYYMMDD.json
输出：
  更新同一份 predictions 文件中的 verified=true、actual_range、hit，并同步写入 SQLite。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pytz


def _pick_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _compute_actual_range_from_daily(df) -> Optional[Dict[str, float]]:
    if df is None or getattr(df, "empty", True):
        return None

    close_col = _pick_col(df, ["收盘", "close", "收盘价", "CLOSE"])
    high_col = _pick_col(df, ["最高", "high", "最高价", "HIGH"])
    low_col = _pick_col(df, ["最低", "low", "最低价", "LOW"])

    if not close_col or not high_col or not low_col:
        return None

    # 拉取时已限定到单日，取最后一行作为该日结果
    row = df.iloc[-1]
    actual_close = float(row[close_col])
    actual_high = float(row[high_col])
    actual_low = float(row[low_col])
    return {
        "actual_close": actual_close,
        "actual_high": actual_high,
        "actual_low": actual_low,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="交易日期 YYYYMMDD；默认今天(Asia/Shanghai)")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写回 verified/actual_range")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条未验证记录（0=不限制）")
    args = parser.parse_args()

    # 关键：record_prediction/update_actual_range 使用相对路径 data/ 下的存储目录
    # 统一切到仓库根目录，避免写入到错误工作目录
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(repo_root)

    tz = pytz.timezone("Asia/Shanghai")
    date_str = args.date
    if not date_str:
        date_str = datetime.now(tz).strftime("%Y%m%d")

    pred_file = os.path.join("data", "prediction_records", f"predictions_{date_str}.json")
    if not os.path.exists(pred_file):
        print(f"[skip] predictions file not found: {pred_file}")
        return 0

    from src.data_collector import fetch_etf_daily_em, fetch_index_daily_em
    from src.prediction_recorder import update_actual_range

    with open(pred_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        print("[error] predictions json format invalid (expected list).")
        return 2

    updated = 0
    skipped = 0

    for r in records:
        if r.get("verified", False):
            continue
        if args.limit and updated >= args.limit:
            break

        symbol = r.get("symbol")
        source = r.get("source")
        prediction_type = r.get("prediction_type")
        if not symbol or not source:
            skipped += 1
            continue

        # 仅支持预测类型为 etf/index 的回填
        daily_df = None
        try:
            if prediction_type == "etf":
                daily_df = fetch_etf_daily_em(symbol=str(symbol), period="daily", start_date=date_str, end_date=date_str)
            elif prediction_type == "index":
                daily_df = fetch_index_daily_em(symbol=str(symbol), period="daily", start_date=date_str, end_date=date_str)
            else:
                daily_df = None
        except Exception:
            daily_df = None

        actual_range = _compute_actual_range_from_daily(daily_df)
        if not actual_range:
            skipped += 1
            continue

        if args.dry_run:
            print(f"[dry-run] {symbol} source={source} -> {actual_range}")
            updated += 1
            continue

        ok = update_actual_range(
            date=date_str,
            symbol=str(symbol),
            source=str(source),
            actual_range=actual_range,
        )
        if ok:
            updated += 1
        else:
            skipped += 1

    print(f"[done] date={date_str} updated={updated} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

