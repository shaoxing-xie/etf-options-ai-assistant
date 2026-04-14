"""
ETF 轮动策略简化回测：月度调仓、等权 Top-K、可选换手成本。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analysis.etf_rotation_core import (
    load_etf_daily_df,
    resolve_etf_pool,
    run_rotation_pipeline,
)
from src.rotation_config_loader import load_rotation_config


def _parse_yyyymmdd(s: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.strptime(s, "%Y%m%d"))


def _build_daily_returns_close(
    symbols: List[str],
    start_yyyymmdd: str,
    end_yyyymmdd: str,
) -> tuple[Optional[pd.DataFrame], List[str]]:
    """各标的日收益对齐到日期交集（允许缓存部分命中）。"""
    closes: Dict[str, pd.Series] = {}
    errs: List[str] = []
    for sym in symbols:
        df, msg = load_etf_daily_df(sym, start_yyyymmdd=start_yyyymmdd, end_yyyymmdd=end_yyyymmdd)
        if df is None or df.empty:
            errs.append(f"{sym}:{msg}")
            continue
        if msg:
            errs.append(f"{sym}:partial:{msg}")
        cols = {c.lower(): c for c in df.columns}
        cc = cols.get("close") or cols.get("收盘") or cols.get("收盘价")
        dc = None
        for c in df.columns:
            if str(c).lower() in ("date", "日期", "trade_date", "datetime"):
                dc = c
                break
        if cc is None:
            errs.append(f"{sym}:no_close")
            continue
        if dc:
            dt = pd.to_datetime(df[dc], errors="coerce")
            v = pd.to_numeric(df[cc], errors="coerce")
            s = pd.Series(v.values, index=dt).dropna()
            s = s[~s.index.duplicated(keep="last")].sort_index()
        else:
            s = pd.to_numeric(df[cc], errors="coerce").dropna()
            s.index = pd.RangeIndex(len(s))
        closes[sym] = s

    if not closes:
        return None, errs

    if all(isinstance(closes[s].index, pd.DatetimeIndex) for s in closes):
        common = None
        for s in symbols:
            if s not in closes:
                continue
            common = closes[s].index if common is None else common.intersection(closes[s].index)
        if common is None or len(common) < 30:
            return None, errs + ["align_fail"]
        aligned = {s: closes[s].reindex(common).ffill().dropna() for s in closes}
        min_len = min(len(v) for v in aligned.values())
        if min_len < 30:
            return None, errs + ["short_align"]
        frame = pd.DataFrame({s: aligned[s].iloc[-min_len:].values for s in aligned}, index=list(common)[-min_len:])
    else:
        min_len = min(len(closes[s]) for s in closes)
        frame = pd.DataFrame({s: closes[s].iloc[-min_len:].values for s in closes})

    rets = frame.pct_change().dropna()
    return rets, errs


def tool_backtest_etf_rotation(
    *,
    etf_pool: str = "",
    start_date: str = "20190101",
    end_date: str = "",
    rebalance: str = "M",
    top_k: int = 3,
    commission_bps: float = 0.0,
    lookback_days: int = 120,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    回测 ETF 轮动：按 `run_rotation_pipeline` 与配置一致的评分，月度末调仓，等权持有 Top-K。

    Args:
        etf_pool: 留空则用 rotation_config + symbols.json
        start_date / end_date: YYYYMMDD，end 默认今日
        rebalance: 目前仅支持 M（月末交易日近似为日历月末与数据交集）
        top_k: 每次持有标的数
        commission_bps: 每次调仓双边成本（bps），从当期收益中扣减一次
        lookback_days: 传给 pipeline
        config_path: rotation 配置路径
    """
    cfg = load_rotation_config(config_path)
    symbols = resolve_etf_pool(etf_pool if (etf_pool or "").strip() else None, cfg)
    if not symbols:
        return {"success": False, "message": "etf_pool 为空", "data": None}

    end_s = end_date.strip() or datetime.now().strftime("%Y%m%d")
    start_s = start_date.strip()
    if len(start_s) != 8 or len(end_s) != 8:
        return {"success": False, "message": "start_date/end_date 须为 YYYYMMDD", "data": None}

    daily_rets, load_errs = _build_daily_returns_close(symbols, start_s, end_s)
    if daily_rets is None or daily_rets.empty:
        return {
            "success": False,
            "message": "无法构建日收益序列",
            "data": {"errors": load_errs},
        }

    idx = daily_rets.index
    if not isinstance(idx, pd.DatetimeIndex):
        return {
            "success": False,
            "message": "回测需要日期索引日线数据",
            "data": {"errors": load_errs},
        }

    start_ts = _parse_yyyymmdd(start_s)
    end_ts = _parse_yyyymmdd(end_s)
    month_ends = pd.date_range(start=start_ts, end=end_ts, freq="ME")
    rebalance_dates = [d for d in month_ends if d in idx]
    if not rebalance_dates:
        rebalance_dates = [idx[idx >= start_ts][0]] if len(idx) else []

    all_returns: List[float] = []
    dates_list: List[pd.Timestamp] = []
    holdings_log: List[Dict[str, Any]] = []

    comm = float(commission_bps) / 10000.0

    for i, t in enumerate(rebalance_dates):
        t_str = t.strftime("%Y%m%d")
        pipe = run_rotation_pipeline(symbols, cfg, lookback_days=lookback_days, as_of_yyyymmdd=t_str)
        ranked = pipe.get("ranked_active") or []
        if not ranked:
            ranked = pipe.get("ranked_all_for_display") or []
        k = max(1, min(int(top_k), len(ranked)))
        held = [r.symbol for r in ranked[:k]]
        if not held:
            continue

        t_next = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else end_ts
        mask = (idx > t) & (idx <= t_next)
        sub = daily_rets.loc[mask]
        if sub.empty:
            continue
        avail = [h for h in held if h in sub.columns]
        if not avail:
            continue
        port = sub[avail].mean(axis=1)
        if comm > 0 and len(port) > 0:
            port = port.copy()
            port.iloc[0] -= comm
        all_returns.extend(port.tolist())
        dates_list.extend(port.index.tolist())
        holdings_log.append({"date": t_str, "holdings": avail, "n": len(avail)})

    if not all_returns:
        return {
            "success": False,
            "message": "回测区间无有效调仓段",
            "data": {"load_errors": load_errs, "rebalance_count": len(rebalance_dates)},
        }

    r = np.array(all_returns, dtype=float)
    equity = np.cumprod(1.0 + r)
    total_ret = float(equity[-1] - 1.0)
    vol_ann = float(np.std(r, ddof=0) * np.sqrt(252)) if len(r) > 1 else 0.0
    sharpe = float((np.mean(r) / (np.std(r, ddof=0) + 1e-12)) * np.sqrt(252)) if len(r) > 1 else 0.0

    peak = np.maximum.accumulate(equity)
    dd = (equity / peak) - 1.0
    max_dd = float(dd.min())

    return {
        "success": True,
        "message": "etf_rotation backtest ok",
        "data": {
            "start_date": start_s,
            "end_date": end_s,
            "symbols": symbols,
            "rebalance_dates": [d.strftime("%Y%m%d") for d in rebalance_dates],
            "total_return": total_ret,
            "max_drawdown": max_dd,
            "volatility_annual": vol_ann,
            "sharpe_approx": sharpe,
            "n_daily_returns": len(r),
            "holdings_log": holdings_log[-6:],
            "load_errors": load_errs,
        },
    }


__all__ = ["tool_backtest_etf_rotation"]
