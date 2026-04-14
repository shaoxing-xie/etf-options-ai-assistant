"""
标的历史复合面板：多标的、多窗口 HV、可选波动率锥、可选近月 ATM IV（SSE ETF）。

工具 ID：tool_underlying_historical_snapshot / tool_historical_snapshot（runner 双键）。
IV 口径见项目计划「IV 口径」：近月 ATM、认购/认沽平均（可配）、iv_eq_30d_pct 方差时间缩放。
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

# SSE ETF 期权标的（与 plugins/data_collection/utils/get_contracts.py 一致）
SSE_ETF_OPTION_UNDERLYINGS = frozenset(
    {"510050", "510300", "510500", "588000", "588080"}
)


def _parse_symbols(symbols: Any) -> List[str]:
    if symbols is None:
        return []
    if isinstance(symbols, str):
        parts = re.split(r"[\s,;]+", symbols.strip())
        return [p.strip() for p in parts if p.strip()]
    if isinstance(symbols, Sequence):
        return [str(s).strip() for s in symbols if str(s).strip()]
    return []


def _close_column(df: Any) -> Optional[str]:
    if df is None or not hasattr(df, "columns"):
        return None
    if "收盘" in df.columns:
        return "收盘"
    if "close" in df.columns:
        return "close"
    return None


def _normalize_daily_df(df: Any) -> Any:
    """升序按日期、统一出「日期」列便于 as_of。"""
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    date_col = None
    for c in ("日期", "date", "Date"):
        if c in out.columns:
            date_col = c
            break
    if date_col:
        out["_dt"] = pd.to_datetime(out[date_col], errors="coerce")
        out = out.sort_values("_dt").dropna(subset=["_dt"])
        out = out.drop(columns=["_dt"], errors="ignore")
    if "收盘" not in out.columns and "close" in out.columns:
        out["收盘"] = out["close"]
    return out


def _as_of_yyyymmdd(df: Any) -> str:
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return datetime.now().strftime("%Y%m%d")
    for c in ("日期", "date", "Date"):
        if c in df.columns:
            last = df[c].iloc[-1]
            ts = pd.to_datetime(last, errors="coerce")
            if pd.notna(ts):
                return ts.strftime("%Y%m%d")
    return datetime.now().strftime("%Y%m%d")


def _fetch_daily_em_or_stock(
    symbol: str,
    asset_type: str,
    start_ymd: str,
    end_ymd: str,
) -> Tuple[Any, Optional[str]]:
    """返回 (df, error_message)。"""
    from src.data_collector import fetch_index_daily_em, fetch_stock_daily_hist

    sym = str(symbol).strip()
    at = (asset_type or "auto").strip().lower()
    if at == "stock":
        df = fetch_stock_daily_hist(sym, start_ymd, end_ymd, adjust="")
        if df is None or getattr(df, "empty", True):
            return None, f"no_stock_daily_data:{sym}"
        return df, None
    if at in ("etf", "index"):
        df = fetch_index_daily_em(symbol=sym, period="daily", start_date=start_ymd, end_date=end_ymd)
        if df is None or getattr(df, "empty", True):
            return None, f"no_index_etf_daily_data:{sym}"
        return df, None
    # auto
    df = fetch_index_daily_em(symbol=sym, period="daily", start_date=start_ymd, end_date=end_ymd)
    if df is not None and not getattr(df, "empty", True):
        return df, None
    df2 = fetch_stock_daily_hist(sym, start_ymd, end_ymd, adjust="")
    if df2 is None or getattr(df2, "empty", True):
        return None, f"no_daily_data_auto:{sym}"
    return df2, None


def _underlying_spot_from_df(df: Any, close_col: str) -> Tuple[Optional[float], str]:
    if df is None or getattr(df, "empty", True) or close_col not in df.columns:
        return None, "missing"
    try:
        v = float(df[close_col].iloc[-1])
        if v > 0:
            return v, "daily_last_close"
    except (TypeError, ValueError):
        pass
    return None, "missing"


def _iv_snapshot_sse(
    underlying: str,
    spot: float,
    as_of: datetime,
    iv_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """
    近月 ATM IV（%%）与 iv_eq_30d。失败返回 iv_skip_reason。
    """
    from src.config_loader import verify_contract_strike_price
    from src.data_collector import fetch_option_expiry_date, fetch_option_greeks_sina
    from src.signal_generator import extract_iv_from_greeks

    out: Dict[str, Any] = {
        "iv_atm_front_pct": None,
        "iv_eq_30d_pct": None,
        "iv_rank": None,
        "iv_rank_note": "requires_daily_iv_series_v2",
        "expiry": None,
        "strike": None,
        "underlying_px_used": spot,
        "underlying_px_source": "daily_last_close",
        "convention": "atm_front_annualized_pct",
    }
    if underlying not in SSE_ETF_OPTION_UNDERLYINGS:
        out["iv_skip_reason"] = "no_sse_options_underlying"
        return out

    try:
        from plugins.data_collection.utils.get_contracts import get_option_contracts
    except ImportError:
        out["iv_skip_reason"] = "import_get_option_contracts_failed"
        return out

    res = get_option_contracts(underlying=underlying, option_type="all")
    if not res.get("success") or not res.get("data"):
        out["iv_skip_reason"] = "option_contracts_fetch_failed"
        return out

    contracts: List[Dict[str, Any]] = res["data"].get("contracts") or []
    if not contracts:
        out["iv_skip_reason"] = "empty_contract_list"
        return out

    min_days = int(iv_cfg.get("near_month_min_days") or 7)
    atm_method = str(iv_cfg.get("atm_method") or "average_call_put").strip().lower()
    eq_30 = bool(iv_cfg.get("eq_30d_enabled", True))

    # 按 trade_month 分组
    months_order: List[str] = []
    seen = set()
    for c in contracts:
        m = str(c.get("trade_month") or "")
        if m and m not in seen:
            seen.add(m)
            months_order.append(m)
    months_order.sort()

    chosen_month: Optional[str] = None
    sample_call: Optional[str] = None
    expiry_dt: Optional[datetime] = None

    for m in months_order:
        calls = [
            c["contract_code"]
            for c in contracts
            if c.get("option_type") == "call" and str(c.get("trade_month")) == m
        ]
        if not calls:
            continue
        exp = fetch_option_expiry_date(str(calls[0]))
        if exp is None:
            continue
        days_left = (exp.date() - as_of.date()).days
        if days_left >= min_days:
            chosen_month = m
            sample_call = str(calls[0])
            expiry_dt = exp
            break

    if chosen_month is None or sample_call is None:
        out["iv_skip_reason"] = "no_valid_front_month"
        return out

    calls = [
        str(c["contract_code"])
        for c in contracts
        if c.get("option_type") == "call" and str(c.get("trade_month")) == chosen_month
    ]
    puts = [
        str(c["contract_code"])
        for c in contracts
        if c.get("option_type") == "put" and str(c.get("trade_month")) == chosen_month
    ]

    strike_to_call: Dict[float, str] = {}
    max_probe = min(80, len(calls))
    for code in calls[:max_probe]:
        k = verify_contract_strike_price(code, 0.0)
        if k is not None and k > 0:
            strike_to_call[float(k)] = code

    if not strike_to_call:
        out["iv_skip_reason"] = "no_strikes_resolved"
        return out

    strikes_sorted = sorted(strike_to_call.keys())
    atm_k = min(strikes_sorted, key=lambda x: abs(x - spot))
    call_code = strike_to_call[atm_k]

    strike_to_put: Dict[float, str] = {}
    for code in puts[:max_probe]:
        k = verify_contract_strike_price(code, 0.0)
        if k is not None and k > 0:
            strike_to_put[float(k)] = code
    put_code = strike_to_put.get(atm_k)

    iv_call: Optional[float] = None
    iv_put: Optional[float] = None
    g_call = fetch_option_greeks_sina(call_code)
    if g_call is not None and not g_call.empty:
        iv_call = extract_iv_from_greeks(g_call)
    if put_code:
        g_put = fetch_option_greeks_sina(put_code)
        if g_put is not None and not g_put.empty:
            iv_put = extract_iv_from_greeks(g_put)

    iv_front: Optional[float] = None
    if atm_method == "call_only":
        iv_front = iv_call
    elif atm_method == "put_only":
        iv_front = iv_put
    else:
        if iv_call is not None and iv_put is not None:
            iv_front = (iv_call + iv_put) / 2.0
        elif iv_call is not None:
            iv_front = iv_call
        else:
            iv_front = iv_put

    if iv_front is None:
        out["iv_skip_reason"] = "greeks_iv_missing"
        return out

    out["iv_atm_front_pct"] = float(iv_front)
    out["strike"] = float(atm_k)
    if expiry_dt is not None:
        out["expiry"] = expiry_dt.strftime("%Y%m%d")

    if eq_30 and expiry_dt is not None:
        t30 = 30.0 / 365.0
        days_left = max(0, (expiry_dt.date() - as_of.date()).days)
        t_near = days_left / 365.0
        if t_near >= t30 > 0:
            out["iv_eq_30d_pct"] = float(iv_front) * math.sqrt(t_near / t30)
        else:
            out["iv_eq_30d_pct"] = None
            out["iv_eq_30d_skip_reason"] = "tenor_shorter_than_30d"
    return out


def tool_underlying_historical_snapshot(
    symbols: Any = None,
    windows: Any = None,
    include_vol_cone: Optional[bool] = None,
    include_iv: Optional[bool] = None,
    max_symbols: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    asset_type: str = "auto",
    **_: Any,
) -> Dict[str, Any]:
    """
    多标的历史波动快照。参数可省略，默认读合并后配置 `historical_snapshot`（来源：config/domains/analytics.yaml）。
    """
    from src.realized_vol_panel import (
        merge_historical_snapshot_config,
        realized_vol_windows,
        volatility_cone_for_windows,
    )

    cfg = merge_historical_snapshot_config()
    if not cfg.get("enabled", True):
        return {
            "success": False,
            "message": "historical_snapshot is disabled in config (historical_snapshot.enabled=false)",
            "data": None,
        }

    sym_list = _parse_symbols(symbols)
    if not sym_list:
        return {"success": False, "message": "symbols is required (list or comma-separated string)", "data": None}

    max_sym = int(max_symbols if max_symbols is not None else cfg.get("max_symbols") or 20)
    if len(sym_list) > max_sym:
        sym_list = sym_list[:max_sym]

    win_cfg = cfg.get("default_windows") or [5, 10, 20, 60, 252]
    if windows is not None:
        if isinstance(windows, (list, tuple)):
            win_list = [int(x) for x in windows]
        else:
            win_list = [int(windows)]
    else:
        win_list = [int(x) for x in win_cfg]

    if include_vol_cone is None:
        include_vol_cone = bool(cfg.get("include_vol_cone_default", False))
    if include_iv is None:
        include_iv = bool(cfg.get("include_iv_default", False))

    cone_days = int(cfg.get("cone_history_calendar_days") or 756)
    iv_cfg = cfg.get("iv") if isinstance(cfg.get("iv"), dict) else {}

    tz_now = datetime.now()
    if end_date:
        end_ymd = str(end_date)[:8]
    else:
        end_ymd = tz_now.strftime("%Y%m%d")

    max_w = max(win_list) if win_list else 60
    cal_span = max(cone_days if include_vol_cone else 0, max_w * 3, 120)
    if start_date:
        start_ymd = str(start_date)[:8]
    else:
        start_ymd = (tz_now - timedelta(days=cal_span)).strftime("%Y%m%d")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results: List[Dict[str, Any]] = []

    for sym in sym_list:
        row: Dict[str, Any] = {"symbol": sym, "success": False}
        try:
            df_raw, err = _fetch_daily_em_or_stock(sym, asset_type, start_ymd, end_ymd)
            if err:
                row["error"] = err
                results.append(row)
                continue
            df = _normalize_daily_df(df_raw)
            close_col = _close_column(df)
            if not close_col:
                row["error"] = "missing_close_column"
                results.append(row)
                continue

            as_of = _as_of_yyyymmdd(df)
            as_of_dt = datetime.strptime(as_of, "%Y%m%d")

            hv_map = realized_vol_windows(df, win_list, close_col=close_col, data_period="day")
            # JSON 友好：键已为 str
            row["hv_by_window"] = {k: (float(v) if v is not None else None) for k, v in hv_map.items()}
            row["data_range"] = {
                "start": start_ymd,
                "end": end_ymd,
                "rows": int(len(df)),
            }
            row["as_of"] = as_of

            if include_vol_cone:
                row["vol_cone"] = volatility_cone_for_windows(
                    df, win_list, close_col=close_col, data_period="day"
                )

            if include_iv and iv_cfg.get("sse_only", True):
                spot, src = _underlying_spot_from_df(df, close_col)
                if spot is None:
                    row["iv"] = {"iv_skip_reason": "underlying_spot_unavailable"}
                else:
                    row["iv"] = _iv_snapshot_sse(sym, spot, as_of_dt, iv_cfg)
            elif include_iv:
                row["iv"] = {"iv_skip_reason": "sse_only_disabled_not_supported"}

            row["success"] = True
        except Exception as e:
            row["error"] = str(e)
        results.append(row)

    all_ok = all(r.get("success") for r in results)
    return {
        "success": all_ok,
        "message": "underlying historical snapshot completed" if all_ok else "partial_or_full_failure",
        "data": {
            "as_of": end_ymd,
            "timestamp": ts,
            "windows": [str(w) for w in win_list],
            "results": results,
        },
    }


def tool_historical_snapshot(**kwargs: Any) -> Dict[str, Any]:
    """别名入口，与 tool_underlying_historical_snapshot 等价。"""
    return tool_underlying_historical_snapshot(**kwargs)
