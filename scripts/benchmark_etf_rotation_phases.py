#!/usr/bin/env python3
"""
分段计时：轮动池「读日线 + trim + extract_58」与整管 run_rotation_pipeline。

用法（仓库根目录）:
  PYTHONPATH=plugins:. python3 scripts/benchmark_etf_rotation_phases.py
  PYTHONPATH=plugins:. python3 scripts/benchmark_etf_rotation_phases.py --full-pipeline

不修改生产逻辑；用于评估「指标/行情缓存」是否值得做。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 仓库根
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PLUGINS = ROOT / "plugins"
if str(PLUGINS) not in sys.path:
    sys.path.insert(0, str(PLUGINS))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-pipeline", action="store_true", help="额外跑一轮完整 run_rotation_pipeline（较慢）")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="仅测前 N 个标的（0 表示全池；用于热缓存后快速复测）",
    )
    args = parser.parse_args()

    from src.rotation_config_loader import load_rotation_config

    from analysis.etf_rotation_core import (
        compute_data_need,
        default_load_date_range,
        extract_58_features,
        load_etf_daily_df,
        resolve_etf_pool,
        run_rotation_pipeline,
        trim_dataframe,
    )

    cfg = load_rotation_config(None)
    symbols = resolve_etf_pool(None, cfg)
    if int(args.max_symbols) > 0:
        symbols = symbols[: int(args.max_symbols)]
    lookback = int(args.lookback_days)
    data_need = compute_data_need(cfg, lookback)
    cal_back = max(365, int(data_need) * 3)
    cal_back = min(cal_back, 1200)
    start_d, end_d = default_load_date_range(calendar_days_back=cal_back)

    print("=== ETF rotation benchmark ===")
    print(f"symbols_count={len(symbols)}")
    print(f"lookback_days={lookback} data_need={data_need} load_range=({start_d},{end_d})")
    print(f"sample_symbols={symbols[:5]}...")

    t_load = 0.0
    t_trim = 0.0
    t_58 = 0.0
    n_ok = 0
    n_fail = 0
    macd_factor = float((cfg.get("alignment") or {}).get("macd_factor") or 2.0)

    t0 = time.perf_counter()
    for sym in symbols:
        t_a = time.perf_counter()
        df, msg, src = load_etf_daily_df(sym, start_yyyymmdd=start_d, end_yyyymmdd=end_d)
        t_load += time.perf_counter() - t_a
        if df is None or getattr(df, "empty", True):
            n_fail += 1
            continue
        t_b = time.perf_counter()
        dft = trim_dataframe(df, lookback, data_need)
        t_trim += time.perf_counter() - t_b
        t_c = time.perf_counter()
        feats, _warn = extract_58_features(
            dft,
            symbol=sym,
            engine_preference="auto",
            macd_factor=macd_factor,
        )
        t_58 += time.perf_counter() - t_c
        if feats:
            n_ok += 1
        else:
            n_fail += 1
    t_loop = time.perf_counter() - t0

    print(f"per_symbol_loop: total={t_loop:.2f}s  load={t_load:.2f}s  trim={t_trim:.3f}s  extract_58={t_58:.2f}s")
    print(f"ok_symbols={n_ok} fail_or_no_feats={n_fail}")

    if args.full_pipeline:
        t_fp = time.perf_counter()
        out = run_rotation_pipeline(symbols, cfg, lookback_days=lookback, score_engine="58")
        dt = time.perf_counter() - t_fp
        ranked = out.get("ranked_active") or []
        print(f"run_rotation_pipeline(score_engine=58): {dt:.2f}s  ranked_active={len(ranked)}")
        errs = out.get("errors") or []
        if errs:
            print(f"errors_count={len(errs)} (first 3): {errs[:3]}")


if __name__ == "__main__":
    main()
