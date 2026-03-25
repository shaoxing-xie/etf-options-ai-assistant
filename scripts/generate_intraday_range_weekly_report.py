#!/usr/bin/env python3
"""
生成周报：基于 data/prediction_records 下的 verified 预测记录计算覆盖率/区间宽度等指标，
并落盘到 data/prediction_reports/。
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta

import pytz


def _week_start_monday(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y%m%d").date()
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y%m%d")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--week-start", type=str, default=None, help="周起始日期 YYYYMMDD（默认：当天所在周的周一）")
    parser.add_argument("--dry-run", action="store_true", help="不调用生成逻辑，只打印参数")
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(repo_root)

    tz = pytz.timezone("Asia/Shanghai")
    today_str = datetime.now(tz).strftime("%Y%m%d")
    week_start = args.week_start or _week_start_monday(today_str)

    if args.dry_run:
        print(f"[dry-run] generate weekly report week_start={week_start}")
        return 0

    from src.prediction_reporter import generate_weekly_report

    report = generate_weekly_report(week_start_date=week_start)
    # generate_weekly_report 内部会落盘文件；这里只做输出便于观察
    print(f"[done] week_start={week_start} report_keys={list(report.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

