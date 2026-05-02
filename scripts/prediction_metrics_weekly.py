#!/usr/bin/env python3
"""
预测命中滚动统计与「相对自身基线」告警（不做单一全局准确率<50%告警）。

读取 data/prediction_records/predictions_*.json 中已 verified 的记录，
按 (symbol, method) 对比：
  - 近 rolling_days 日历日窗口
  - 紧邻的前 baseline_rolling_days 日历日窗口
若近期样本量足够且命中率较基线下降 ≥ hit_rate_drop_alert_pp（百分点），输出 WARN。

配置：合并后配置 → prediction_monitoring（域文件：`config/domains/risk_quality.yaml`）

用法（须在仓库根目录执行，勿在 ~ 下直接跑 scripts/）：
  cd /path/to/etf-options-ai-assistant
  python scripts/prediction_metrics_weekly.py --end-date 20260328
  python scripts/prediction_metrics_weekly.py   # 默认上海日历当天

  # 或任意目录下用绝对路径：
  python /path/to/etf-options-ai-assistant/scripts/prediction_metrics_weekly.py --end-date 20260328
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
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
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
            pred = r.get("prediction") or {}
            if pred.get("usable") is False:
                continue
            sym = str(r.get("symbol", ""))
            method = str(pred.get("method", "unknown"))
            if bool(pred.get("iv_hv_fusion")):
                method = f"{method}|iv_hv_fusion"
            if r.get("prediction_type") == "index_direction":
                dv = r.get("direction_verification") or {}
                if "hit" not in dv:
                    continue
                hit = bool(dv.get("hit"))
                target_date = str(r.get("target_date") or "")
                ds_use = target_date.replace("-", "") if target_date else ds
                predicted_direction = str(pred.get("direction") or "")
                probability = float(pred.get("probability") or 50.0)
                if predicted_direction == "down":
                    prob_up = max(0.0, min(1.0, (100.0 - probability) / 100.0))
                elif predicted_direction == "up":
                    prob_up = max(0.0, min(1.0, probability / 100.0))
                else:
                    prob_up = 0.5
                actual_direction = str(dv.get("actual_direction") or "")
                actual_up = 1.0 if actual_direction == "up" else 0.5 if actual_direction == "neutral" else 0.0
                quality_status = str(pred.get("quality_status") or "unknown")
                rows.append(
                    {
                        "date": ds_use,
                        "symbol": sym,
                        "method": method,
                        "hit": hit,
                        "prediction_type": "index_direction",
                        "prob_up": prob_up,
                        "actual_up": actual_up,
                        "quality_status": quality_status,
                        "signal_strength": abs(prob_up - 0.5) * 2.0,
                    }
                )
                continue
            if not r.get("verified"):
                continue
            ar = r.get("actual_range") or {}
            if "hit" not in ar:
                continue
            hit = bool(ar.get("hit"))
            rows.append(
                {
                    "date": ds,
                    "symbol": sym,
                    "method": method,
                    "hit": hit,
                    "prediction_type": str(r.get("prediction_type") or ""),
                    "prob_up": None,
                    "actual_up": None,
                    "quality_status": str(pred.get("quality_status") or "unknown"),
                    "signal_strength": None,
                }
            )
    return rows


def summarize_window(rows: List[Dict[str, Any]], date_set: set) -> DefaultDict[Tuple[str, str], List[Dict[str, Any]]]:
    by: DefaultDict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["date"] in date_set:
            by[(row["symbol"], row["method"])].append(row)
    return by


def hit_rate(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return float("nan")
    return sum(1 for row in rows if row["hit"]) / len(rows)


def brier_score(rows: List[Dict[str, Any]]) -> float:
    pairs = [(row["prob_up"], row["actual_up"]) for row in rows if row.get("prob_up") is not None and row.get("actual_up") is not None]
    if not pairs:
        return float("nan")
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def degraded_ratio(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return float("nan")
    return sum(1 for row in rows if row.get("quality_status") not in {"ok", ""}) / len(rows)


def signal_concentration(rows: List[Dict[str, Any]]) -> float:
    vals = [float(row["signal_strength"]) for row in rows if row.get("signal_strength") is not None]
    if not vals:
        return float("nan")
    return sum(vals) / len(vals)


def calibration_error(rows: List[Dict[str, Any]], bins: int = 5) -> float:
    pairs = [(row["prob_up"], row["actual_up"]) for row in rows if row.get("prob_up") is not None and row.get("actual_up") is not None]
    if not pairs:
        return float("nan")
    bucket_sum = 0.0
    total = len(pairs)
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        bucket = [(p, y) for p, y in pairs if (p >= lo and p < hi) or (i == bins - 1 and p <= hi)]
        if not bucket:
            continue
        avg_p = sum(p for p, _ in bucket) / len(bucket)
        avg_y = sum(y for _, y in bucket) / len(bucket)
        bucket_sum += abs(avg_p - avg_y) * len(bucket) / total
    return bucket_sum


def main() -> int:
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
    lines.append(f"| symbol | method | n_recent | hit_rate_20d | brier_score_20d | coverage | degraded_ratio | signal_concentration | calibration_error | n_prior | hit% prior | 告警 |")
    lines.append("|--------|--------|----------|--------------|----------------|----------|----------------|----------------------|-------------------|---------|------------|------|")

    alerts: List[str] = []
    for sym, method in keys:
        r_hits = recent_by.get((sym, method), [])
        p_hits = prior_by.get((sym, method), [])
        nr, np_ = len(r_hits), len(p_hits)
        hr, hp = hit_rate(r_hits), hit_rate(p_hits)
        hr_s = f"{hr:.1%}" if not math.isnan(hr) else "-"
        hp_s = f"{hp:.1%}" if not math.isnan(hp) else "-"
        brier_s = f"{brier_score(r_hits):.4f}" if not math.isnan(brier_score(r_hits)) else "-"
        coverage_s = f"{(nr / rolling):.1%}" if rolling else "-"
        degraded_s = f"{degraded_ratio(r_hits):.1%}" if not math.isnan(degraded_ratio(r_hits)) else "-"
        signal_s = f"{signal_concentration(r_hits):.3f}" if not math.isnan(signal_concentration(r_hits)) else "-"
        calib_s = f"{calibration_error(r_hits):.4f}" if not math.isnan(calibration_error(r_hits)) else "-"
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
            f"| {sym} | {method} | {nr} | {hr_s} | {brier_s} | {coverage_s} | {degraded_s} | {signal_s} | {calib_s} | {np_} | {hp_s} | {warn or '-'} |"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
