#!/usr/bin/env python3
"""
预测命中滚动统计与「相对自身基线」告警（不做单一全局准确率<50%告警）。

读取 data/prediction_records/predictions_*.json 中已 verified 的记录，
按 (symbol, method) 对比：
  - 近 rolling_days 日历日窗口
  - 紧邻的前 baseline_rolling_days 日历日窗口
若近期样本量足够且命中率较基线下降 ≥ hit_rate_drop_alert_pp（百分点），输出 WARN。

配置：config.yaml → prediction_monitoring

用法：
  python scripts/prediction_metrics_weekly.py --end-date 20260328
  python scripts/prediction_metrics_weekly.py   # 默认上海日历当天
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Tuple

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import load_system_config
from src.logger_config import get_module_logger

logger = get_module_logger(__name__)

PRED_DIR = project_root / "data" / "prediction_records"
RE_FILE = re.compile(r"^predictions_(\d{8})\.json$")
REPORT_DIR = project_root / "data" / "verification_reports"


def _daterange_days(end: datetime, n: int) -> List[str]:
    out = []
    for i in range(n):
        d = end - timedelta(days=i)
        out.append(d.strftime("%Y%m%d"))
    return out


def load_verified_hits(
    dates_needed: List[str],
) -> List[Tuple[str, str, str, bool]]:
    """(date_str, symbol, method, hit)"""
    rows: List[Tuple[str, str, str, bool]] = []
    for ds in dates_needed:
        path = PRED_DIR / f"predictions_{ds}.json"
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                recs = json.load(f)
        except Exception as e:
            logger.warning("跳过 %s: %s", path, e)
            continue
        if not isinstance(recs, list):
            continue
        for r in recs:
            if not r.get("verified"):
                continue
            ar = r.get("actual_range") or {}
            if "hit" not in ar:
                continue
            sym = str(r.get("symbol", ""))
            pred = r.get("prediction") or {}
            method = str(pred.get("method", "unknown"))
            hit = bool(ar.get("hit"))
            rows.append((ds, sym, method, hit))
    return rows


def summarize_window(rows: List[Tuple[str, str, str, bool]], date_set: set) -> DefaultDict[Tuple[str, str], List[bool]]:
    by: DefaultDict[Tuple[str, str], List[bool]] = defaultdict(list)
    for ds, sym, method, hit in rows:
        if ds in date_set:
            by[(sym, method)].append(hit)
    return by


def hit_rate(hits: List[bool]) -> float:
    if not hits:
        return float("nan")
    return sum(1 for h in hits if h) / len(hits)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly-style prediction metrics and drop alerts")
    parser.add_argument("--end-date", type=str, default=None, help="YYYYMMDD，默认上海当天")
    args = parser.parse_args()

    cfg = load_system_config(use_cache=True)
    mon = cfg.get("prediction_monitoring") or {}
    rolling = int(mon.get("rolling_days", 20))
    baseline = int(mon.get("baseline_rolling_days", 20))
    min_n = int(mon.get("min_samples_for_alert", 8))
    drop_pp = float(mon.get("hit_rate_drop_alert_pp", 25.0))

    if args.end_date:
        end = datetime.strptime(args.end_date, "%Y%m%d")
    else:
        end = datetime.now(tz=None)
        end = end.replace(hour=0, minute=0, second=0, microsecond=0)

    span = rolling + baseline
    all_dates = _daterange_days(end, span)
    recent_dates = set(all_dates[:rolling])
    prior_dates = set(all_dates[rolling : rolling + baseline])

    rows = load_verified_hits(all_dates)
    recent_by = summarize_window(rows, recent_dates)
    prior_by = summarize_window(rows, prior_dates)

    keys = sorted(set(recent_by.keys()) | set(prior_by.keys()))
    lines: List[str] = []
    lines.append(f"## 预测命中滚动对比（近 {rolling} 日 vs 前 {baseline} 日）")
    lines.append("")
    lines.append(f"| symbol | method | n_recent | hit% recent | n_prior | hit% prior | 告警 |")
    lines.append("|--------|--------|----------|-------------|---------|------------|------|")

    alerts: List[str] = []
    for sym, method in keys:
        r_hits = recent_by.get((sym, method), [])
        p_hits = prior_by.get((sym, method), [])
        nr, np_ = len(r_hits), len(p_hits)
        hr, hp = hit_rate(r_hits), hit_rate(p_hits)
        hr_s = f"{hr:.1%}" if not math.isnan(hr) else "-"
        hp_s = f"{hp:.1%}" if not math.isnan(hp) else "-"
        warn = ""
        if (
            nr >= min_n
            and np_ >= min_n
            and not (math.isnan(hr) or math.isnan(hp))
            and (hp - hr) * 100.0 >= drop_pp
        ):
            warn = f"WARN 下降≥{drop_pp:.0f}pp"
            alerts.append(f"- {sym}/{method}: prior {hp:.1%} → recent {hr:.1%} (n {np_}/{nr})")
        lines.append(
            f"| {sym} | {method} | {nr} | {hr_s} | {np_} | {hp_s} | {warn or '-'} |"
        )

    lines.append("")
    if alerts:
        lines.append("### 告警（相对基线大幅下滑，非全局固定阈值）")
        lines.extend(alerts)
    else:
        lines.append("### 告警：无（或样本不足 / 无 verified 数据）")

    report = "\n".join(lines) + "\n"
    print(report)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"weekly_metrics_{end.strftime('%Y%m%d')}.md"
    out_path.write_text(report, encoding="utf-8")
    logger.info("报告已写入 %s", out_path)


if __name__ == "__main__":
    main()
