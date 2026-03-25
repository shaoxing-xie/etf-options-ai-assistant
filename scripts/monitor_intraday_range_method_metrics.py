#!/usr/bin/env python3
"""
方法分组与回退比例监控：
  - 统计最近 N 天的预测记录中，fallback_daily vs minute_multi_period 的占比
  - 对已 verified 的记录，计算各组 coverage_rate 与 average_width

输出：
  data/prediction_reports/intraday_range_method_metrics_{start}_{end}.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import pytz


def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y%m%d")


def _classify_group(record: Dict[str, Any]) -> str:
    pred = record.get("prediction", {}) or {}
    method = str(pred.get("method", "") or "")
    # 优先按 method 文本分类（fallback_daily 的 method 含“降级方案”）
    if "降级方案" in method or "fallback_daily" in method:
        return "fallback_daily"
    return "minute_multi_period"


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="回看天数（包含起止两端日期）")
    parser.add_argument("--start-date", type=str, default=None, help="起始日期 YYYYMMDD（默认：today-days+1）")
    parser.add_argument("--end-date", type=str, default=None, help="结束日期 YYYYMMDD（默认：today）")
    parser.add_argument("--dry-run", action="store_true", help="不写文件，只打印摘要")
    args = parser.parse_args()
    tz = pytz.timezone("Asia/Shanghai")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(repo_root)

    today_str = datetime.now(tz).strftime("%Y%m%d")
    end_date = args.end_date or today_str
    if args.start_date:
        start_date = args.start_date
    else:
        d_end = _parse_date(end_date)
        start_date = (d_end - timedelta(days=max(int(args.days) - 1, 0))).strftime("%Y%m%d")

    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    if start_dt > end_dt:
        print("[error] start-date > end-date")
        return 2

    pred_dir = os.path.join("data", "prediction_records")
    all_records: List[Dict[str, Any]] = []

    cur = start_dt
    while cur <= end_dt:
        date_str = cur.strftime("%Y%m%d")
        fp = os.path.join(pred_dir, f"predictions_{date_str}.json")
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    records = json.load(f)
                if isinstance(records, list):
                    all_records.extend(records)
            except Exception:
                pass
        cur += timedelta(days=1)

    if not all_records:
        print("[skip] no prediction_records found in range.")
        return 0

    total = len(all_records)
    group_counts = {"fallback_daily": 0, "minute_multi_period": 0}
    group_verified = {"fallback_daily": [], "minute_multi_period": []}

    for r in all_records:
        g = _classify_group(r)
        group_counts[g] += 1
        if r.get("verified", False):
            group_verified[g].append(r)

    fallback_ratio = group_counts["fallback_daily"] / total if total > 0 else 0.0

    def _calc_verified_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not records:
            return {"verified_count": 0, "coverage_rate": 0.0, "average_width_pct": 0.0}
        hit_count = 0
        widths: List[float] = []
        for r in records:
            if r.get("actual_range", {}).get("hit", False):
                hit_count += 1
            widths.append(_safe_float(r.get("prediction", {}).get("range_pct")))
        coverage = hit_count / len(records) if records else 0.0
        avg_width = sum(widths) / len(widths) if widths else 0.0
        return {
            "verified_count": len(records),
            "coverage_rate": coverage,
            "average_width_pct": avg_width,
        }

    metrics = {
        "start_date": start_date,
        "end_date": end_date,
        "total_records": total,
        "group_counts": group_counts,
        "fallback_ratio": fallback_ratio,
        "verified_metrics": {
            "fallback_daily": _calc_verified_metrics(group_verified["fallback_daily"]),
            "minute_multi_period": _calc_verified_metrics(group_verified["minute_multi_period"]),
        },
    }

    out_dir = os.path.join("data", "prediction_reports")
    os.makedirs(out_dir, exist_ok=True)
    out_fp = os.path.join(out_dir, f"intraday_range_method_metrics_{start_date}_{end_date}.json")

    if args.dry_run:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0

    with open(out_fp, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(f"[done] wrote: {out_fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

