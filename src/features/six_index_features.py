from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from zoneinfo import ZoneInfo

from plugins.data_collection.a_share_fund_flow import tool_fetch_a_share_fund_flow
from plugins.data_collection.limit_up.fetch_limit_up import tool_fetch_limit_up_stocks
from plugins.data_collection.macro.tools import tool_fetch_macro_snapshot
from plugins.data_collection.northbound import tool_fetch_northbound_flow
from plugins.data_collection.sector import tool_fetch_sector_data
from plugins.analysis.predictors.kronos_enhancer import load_kronos_signal
from plugins.utils.trading_day import is_trading_day
from src.config_loader import get_holidays_config, load_system_config
from src.data_collector import fetch_index_daily_em


ROOT = Path(__file__).resolve().parents[2]
TZ_SH = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class IndexSpec:
    code: str
    name: str


SIX_INDEX_SPECS: tuple[IndexSpec, ...] = (
    IndexSpec("000001", "上证指数"),
    IndexSpec("000300", "沪深300"),
    IndexSpec("000688", "科创50"),
    IndexSpec("399006", "创业板指"),
    IndexSpec("000905", "中证500"),
    IndexSpec("000852", "中证1000"),
)


def shanghai_today() -> str:
    return datetime.now(TZ_SH).strftime("%Y-%m-%d")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        # Normalize common numeric string formats like "1.23%", "1,234.5", "—"
        if isinstance(value, str):
            s = value.strip()
            if s in {"—", "-", "--", "N/A", "NA", "null", "None"}:
                return None
            # Remove thousand separators
            s = s.replace(",", "")
            # Strip trailing percent sign
            if s.endswith("%"):
                s = s[:-1].strip()
            if s == "":
                return None
            return float(s)
        return float(value)
    except Exception:
        return None


def _normalize_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("records"), list):
        return [r for r in payload["data"]["records"] if isinstance(r, dict)]
    if isinstance(payload.get("records"), list):
        return [r for r in payload["records"] if isinstance(r, dict)]
    if isinstance(payload.get("data"), list):
        return [r for r in payload["data"] if isinstance(r, dict)]
    if isinstance(payload.get("all_data"), list):
        return [r for r in payload["all_data"] if isinstance(r, dict)]
    sectors = payload.get("sectors")
    if isinstance(sectors, dict):
        merged: List[Dict[str, Any]] = []
        for rows in sectors.values():
            if isinstance(rows, list):
                merged.extend(r for r in rows if isinstance(r, dict))
        if merged:
            return merged
    return []


def _normalize_limit_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _normalize_northbound_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("records"), list):
        return [r for r in data["records"] if isinstance(r, dict)]
    if isinstance(payload.get("records"), list):
        return [r for r in payload["records"] if isinstance(r, dict)]
    return []


def _normalize_macro_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict) or not payload.get("success"):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _resolve_data_plugin_runner() -> tuple[Optional[Path], str]:
    root = (os.environ.get("OPENCLAW_DATA_CHINA_STOCK_ROOT") or "").strip()
    if root:
        runner = Path(root).expanduser().resolve() / "tool_runner.py"
    else:
        runner = Path.home() / ".openclaw" / "extensions" / "openclaw-data-china-stock" / "tool_runner.py"
    if not runner.is_file():
        return None, sys.executable
    py = (os.environ.get("OPENCLAW_DATA_CHINA_STOCK_PYTHON") or "").strip()
    if py:
        return runner, py
    venv_py = runner.parent / ".venv" / "bin" / "python"
    return runner, str(venv_py if venv_py.is_file() else sys.executable)


def _call_data_plugin_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    runner, py = _resolve_data_plugin_runner()
    if runner is None:
        return {"success": False, "message": "data-plugin-runner-missing"}
    try:
        proc = subprocess.run(
            [py, str(runner), tool_name, json.dumps(args, ensure_ascii=False)],
            text=True,
            capture_output=True,
            timeout=90,
        )
    except Exception as exc:
        return {"success": False, "message": f"data-plugin-runner-error:{type(exc).__name__}"}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"success": False, "message": (proc.stderr or proc.stdout or "").strip()[:200]}
    try:
        payload = json.loads(proc.stdout.strip())
        return payload if isinstance(payload, dict) else {"success": False, "message": "invalid-json-payload"}
    except Exception:
        return {"success": False, "message": "invalid-json"}


def _hotspot_metrics(trade_date: str) -> Dict[str, Any]:
    payload = _call_data_plugin_tool(
        "tool_hotspot_discovery",
        {
            "date": trade_date,
            "top_k": 5,
            "min_heat_score": 30,
        },
    )
    hotspots = payload.get("hotspots") if isinstance(payload, dict) else []
    rows = [x for x in hotspots if isinstance(x, dict)] if isinstance(hotspots, list) else []
    top_names = [str(x.get("name") or "") for x in rows if str(x.get("name") or "").strip()][:3]
    top_score = _safe_float(rows[0].get("heat_score")) if rows else None
    return {
        "quality_status": "info" if payload.get("success") else "degraded",
        "degraded_reason": None if payload.get("success") else "hotspot_discovery_unavailable",
        "top_hotspots": top_names,
        "top_hotspot_score": top_score,
        "snapshot": {
            "_meta": payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {},
            "trade_date": payload.get("trade_date"),
            "generated_at": payload.get("generated_at"),
            "quality_status": payload.get("quality_status"),
            "degraded_reason": payload.get("degraded_reason"),
            "hotspots": rows,
        },
    }


def _daily_df(symbol: str, lookback_days: int = 320) -> pd.DataFrame:
    end_dt = datetime.now(TZ_SH)
    start_dt = end_dt - timedelta(days=max(lookback_days * 2, 120))
    df = fetch_index_daily_em(
        symbol=symbol,
        start_date=start_dt.strftime("%Y%m%d"),
        end_date=end_dt.strftime("%Y%m%d"),
    )
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()
    out = df.copy()
    if "日期" in out.columns:
        out["date"] = pd.to_datetime(out["日期"], errors="coerce")
    elif "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    else:
        out["date"] = pd.NaT
    if "收盘" in out.columns:
        out["close"] = pd.to_numeric(out["收盘"], errors="coerce")
    elif "close" in out.columns:
        out["close"] = pd.to_numeric(out["close"], errors="coerce")
    else:
        out["close"] = pd.NA
    if "成交量" in out.columns:
        out["volume"] = pd.to_numeric(out["成交量"], errors="coerce")
    elif "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    else:
        out["volume"] = pd.NA
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _daily_df_from_cache(symbol: str, *, max_files: int = 320) -> pd.DataFrame:
    base = ROOT / "data" / "cache" / "index_daily" / symbol
    if not base.is_dir():
        return pd.DataFrame()
    files = sorted([p for p in base.glob("*.parquet") if p.is_file()])
    if not files:
        return pd.DataFrame()
    tail = files[-max_files:] if max_files > 0 else files
    frames: List[pd.DataFrame] = []
    for p in tail:
        try:
            frames.append(pd.read_parquet(p))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "日期" in out.columns:
        out["date"] = pd.to_datetime(out["日期"], errors="coerce")
    elif "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
    else:
        out["date"] = pd.NaT
    if "收盘" in out.columns:
        out["close"] = pd.to_numeric(out["收盘"], errors="coerce")
    elif "close" in out.columns:
        out["close"] = pd.to_numeric(out["close"], errors="coerce")
    else:
        out["close"] = pd.NA
    if "成交量" in out.columns:
        out["volume"] = pd.to_numeric(out["成交量"], errors="coerce")
    elif "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    else:
        out["volume"] = pd.NA
    return out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _load_dividend_index_df() -> pd.DataFrame:
    # 1) cache first
    cached = _daily_df_from_cache("000922", max_files=520)
    if len(cached) >= 120:
        return cached
    # 2) prefer OpenClaw Data China Stock tool (csindex) for 000922
    try:
        start = (datetime.now(TZ_SH) - timedelta(days=900)).strftime("%Y%m%d")
        end = datetime.now(TZ_SH).strftime("%Y%m%d")
        # Use the plugin tool to avoid embedding vendor-specific API logic here.
        runner = Path(os.environ.get("OPENCLAW_DATA_CHINA_STOCK_ROOT") or "").expanduser().resolve() / "tool_runner.py"
        if not runner.is_file():
            runner = Path.home() / ".openclaw" / "extensions" / "openclaw-data-china-stock" / "tool_runner.py"
        py = (os.environ.get("OPENCLAW_DATA_CHINA_STOCK_PYTHON") or "").strip()
        if not py:
            candidate = runner.parent / ".venv" / "bin" / "python"
            py = str(candidate) if candidate.is_file() else sys.executable

        if runner.is_file():
            proc = subprocess.run(
                [py, str(runner), "tool_fetch_csindex_index_daily", json.dumps({"symbol": "000922", "start_date": start, "end_date": end}, ensure_ascii=False)],
                text=True,
                capture_output=True,
                timeout=45,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                resp = json.loads(proc.stdout.strip())
                if resp.get("success") and isinstance(resp.get("data"), list):
                    rows = resp["data"]
                    out = pd.DataFrame(rows)
                    out["date"] = pd.to_datetime(out.get("date"), errors="coerce")
                    out["close"] = pd.to_numeric(out.get("close"), errors="coerce")
                    out["volume"] = pd.to_numeric(out.get("volume"), errors="coerce")
                    out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
                    if len(out) >= 120:
                        return out
    except Exception:
        pass
    # 3) final fallback (legacy collector path)
    return _daily_df("000922", lookback_days=200)


def _pct_change(df: pd.DataFrame, days: int) -> Optional[float]:
    if df.empty or len(df) <= days:
        return None
    now = _safe_float(df.iloc[-1]["close"])
    prev = _safe_float(df.iloc[-1 - days]["close"])
    if now is None or prev in (None, 0):
        return None
    return (now / prev) - 1.0


def _rolling_return_series(df: pd.DataFrame, days: int) -> List[float]:
    if df.empty or len(df) <= days:
        return []
    closes = pd.to_numeric(df["close"], errors="coerce")
    series = ((closes / closes.shift(days)) - 1.0).dropna()
    return [float(x) for x in series.tail(500).tolist()]


def _rolling_percentile(series: Iterable[float], current: Optional[float]) -> Optional[float]:
    if current is None:
        return None
    arr = sorted(float(x) for x in series if x is not None)
    if len(arr) < 20:
        return None
    le = sum(1 for x in arr if x <= float(current))
    return round((le / len(arr)) * 100.0, 4)


def next_trading_day(trade_date: str) -> str:
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    cfg = load_system_config(use_cache=True)
    holidays = get_holidays_config(cfg)
    while True:
        dt += timedelta(days=1)
        if dt.weekday() >= 5:
            continue
        if dt.strftime("%Y%m%d") in holidays:
            continue
        if is_trading_day(dt):
            return dt.strftime("%Y-%m-%d")


def _extract_sector_change(records: List[Dict[str, Any]], keywords: List[str]) -> Optional[float]:
    vals: List[float] = []
    for row in records:
        name = str(row.get("sector_name") or row.get("name") or "")
        if not any(k in name for k in keywords):
            continue
        change = _safe_float(row.get("change_percent") or row.get("涨跌幅") or row.get("pct_change"))
        if change is not None:
            vals.append(change / 100.0 if abs(change) > 1 else change)
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def _sector_top_momentum(records: List[Dict[str, Any]], topk: int = 5) -> List[Dict[str, Any]]:
    norm: List[Dict[str, Any]] = []
    for row in records:
        change = _safe_float(row.get("change_percent") or row.get("涨跌幅") or row.get("pct_change"))
        if change is None:
            continue
        name = str(row.get("sector_name") or row.get("name") or "").strip()
        if not name:
            continue
        norm.append(
            {
                "sector_name": name,
                "ret10_proxy": change / 100.0 if abs(change) > 1 else change,
                "weight": 1.0,
            }
        )
    norm.sort(key=lambda x: x["ret10_proxy"], reverse=True)
    return norm[:topk]


def _sector_leadership_score(records: List[Dict[str, Any]]) -> Optional[float]:
    top = _sector_top_momentum(records, topk=3)
    if not top:
        return None
    return round(sum(float(r["ret10_proxy"]) for r in top) / len(top), 6)


def _northbound_score(payload: Dict[str, Any]) -> Dict[str, Any]:
    records = _normalize_northbound_records(payload)
    latest = records[0] if records else {}
    inflow = (
        _safe_float(latest.get("net_inflow"))
        or _safe_float(latest.get("northbound_net"))
        or _safe_float(latest.get("当日净流入"))
        or 0.0
    )
    if abs(inflow) > 10000:
        inflow_e8 = inflow / 1e8
    else:
        inflow_e8 = inflow
    score = max(-1.0, min(1.0, inflow_e8 / 50.0))
    return {
        "net_inflow_e8": round(inflow_e8, 4),
        "northbound_intraday_score": round(score, 4),
        "quality_status": "info" if payload.get("success") else "degraded",
        "degraded_reason": None if payload.get("success") else "northbound_unavailable",
    }


def _macro_proxy(payload: Dict[str, Any]) -> Dict[str, Any]:
    snap = _normalize_macro_snapshot(payload)
    growth = snap.get("growth") if isinstance(snap.get("growth"), dict) else {}
    inflation = snap.get("inflation") if isinstance(snap.get("inflation"), dict) else {}
    credit = snap.get("credit") if isinstance(snap.get("credit"), dict) else {}

    pmi = _safe_float(growth.get("value") or growth.get("PMI") or growth.get("制造业PMI"))
    cpi = _safe_float(inflation.get("value") or inflation.get("cpi") or inflation.get("同比"))
    credit_val = _safe_float(
        credit.get("value")
        or credit.get("社会融资规模增量")
        or credit.get("社融增量")
        or credit.get("m2")
        or credit.get("同比")
    )
    growth_score = 0.3 if pmi is not None and pmi >= 50 else -0.2 if pmi is not None else 0.0
    inflation_score = 0.2 if cpi is not None and cpi <= 2.0 else -0.1 if cpi is not None and cpi >= 3.0 else 0.0
    credit_score = 0.3 if credit_val is not None and credit_val > 0 else -0.1 if credit_val is not None else 0.0
    score = growth_score + inflation_score + credit_score
    staleness = max(
        [
            x
            for x in (
                payload.get("data_lag_days"),
                growth.get("data_lag_days") if isinstance(growth, dict) else None,
                inflation.get("data_lag_days") if isinstance(inflation, dict) else None,
                credit.get("data_lag_days") if isinstance(credit, dict) else None,
            )
            if isinstance(x, int)
        ]
        or [0]
    )
    if staleness < 5:
        weight_multiplier = 1.0
    elif staleness <= 15:
        weight_multiplier = 0.5
    else:
        weight_multiplier = 0.0
    return {
        "macro_proxy_score": round(score, 4),
        "macro_staleness_days": staleness,
        "macro_weight_multiplier": weight_multiplier,
        "macro_payload": {
            "growth": growth,
            "inflation": inflation,
            "credit": credit,
        },
        "quality_status": "info" if payload.get("success") else "degraded",
        "degraded_reason": None if payload.get("success") else "macro_snapshot_unavailable",
    }


def _style_spread_metrics() -> Dict[str, Any]:
    # Style spread is a helpful auxiliary signal, but must not dominate runtime.
    # Limit lookback to reduce cache-miss fetches for non-core symbols (e.g. 000922).
    gem_df = _daily_df("399006", lookback_days=200)
    dividend_df = _load_dividend_index_df()
    if gem_df.empty or dividend_df.empty:
        return {"ret_spread_3m": None, "style_spread_percentile": None}
    gem_ret = _pct_change(gem_df, 60)
    div_ret = _pct_change(dividend_df, 60)
    if gem_ret is None or div_ret is None:
        return {"ret_spread_3m": None, "style_spread_percentile": None}
    merged = gem_df[["date", "close"]].rename(columns={"close": "gem_close"}).merge(
        dividend_df[["date", "close"]].rename(columns={"close": "div_close"}), on="date", how="inner"
    )
    if len(merged) <= 250:
        return {"ret_spread_3m": round(gem_ret - div_ret, 6), "style_spread_percentile": None}
    merged["gem_ret60"] = merged["gem_close"] / merged["gem_close"].shift(60) - 1.0
    merged["div_ret60"] = merged["div_close"] / merged["div_close"].shift(60) - 1.0
    merged["spread"] = merged["gem_ret60"] - merged["div_ret60"]
    hist = [float(x) for x in merged["spread"].dropna().tail(1250).tolist()]
    current = float(gem_ret - div_ret)
    return {
        "ret_spread_3m": round(current, 6),
        "style_spread_percentile": _rolling_percentile(hist, current),
    }


def _limit_up_metrics(trade_date: str) -> Dict[str, Any]:
    ymd = trade_date.replace("-", "")
    today = tool_fetch_limit_up_stocks(date=ymd)
    rows = _normalize_limit_rows(today)
    total = len(rows)
    sci = sum(1 for r in rows if str(r.get("code") or "").startswith(("688",)))
    small = sum(
        1 for r in rows if str(r.get("code") or "").startswith(("300", "301", "002", "003", "000"))
    )
    small_ratio = round(small / total, 4) if total else 0.0
    sci_ratio = round(sci / total, 4) if total else 0.0
    return {
        "limit_up_count": total,
        "limit_up_ratio_smallcap_proxy": small_ratio,
        "limit_up_ratio_kc50_proxy": sci_ratio,
        "quality_status": "info" if today.get("success") else "degraded",
        "degraded_reason": None if today.get("success") else "limit_up_unavailable",
    }


def _fund_flow_metrics() -> Dict[str, Any]:
    payload = tool_fetch_a_share_fund_flow(query_kind="market_history", max_days=5)
    records = _normalize_records(payload)
    latest = records[-1] if records else {}
    net = (
        _safe_float(latest.get("proxy_total_net"))
        or _safe_float(latest.get("主力净流入"))
        or _safe_float(latest.get("净流入"))
        or 0.0
    )
    score = max(-1.0, min(1.0, float(net) / 5e9)) if abs(net) > 1e5 else max(-1.0, min(1.0, float(net) / 50.0))
    return {
        "market_main_force_net": net,
        "market_main_force_score": round(score, 4),
        "quality_status": "info" if payload.get("success") else "degraded",
        "degraded_reason": None if payload.get("success") else "fund_flow_unavailable",
    }


def _margin_change_metrics() -> Dict[str, Any]:
    try:
        import akshare as ak
    except Exception as exc:  # pragma: no cover - import failure is environment-specific
        return {
            "margin_total": None,
            "margin_change_pct": None,
            "margin_change_proxy": None,
            "quality_status": "degraded",
            "degraded_reason": f"margin_import_failed:{type(exc).__name__}",
        }

    frames: List[pd.DataFrame] = []
    errors: List[str] = []
    for market, loader in (
        ("sh", ak.macro_china_market_margin_sh),
        ("sz", ak.macro_china_market_margin_sz),
    ):
        try:
            df = loader()
            if df is None or df.empty:
                errors.append(f"{market}_empty")
                continue
            local = df.copy()
            local["日期"] = pd.to_datetime(local["日期"], errors="coerce")
            local["融资融券余额"] = pd.to_numeric(local["融资融券余额"], errors="coerce")
            local["融资余额"] = pd.to_numeric(local.get("融资余额"), errors="coerce")
            frames.append(local[["日期", "融资融券余额", "融资余额"]].dropna(subset=["日期"]))
        except Exception as exc:  # pragma: no cover - network/source variance
            errors.append(f"{market}_{type(exc).__name__}")

    if not frames:
        return {
            "margin_total": None,
            "margin_change_pct": None,
            "margin_change_proxy": None,
            "quality_status": "degraded",
            "degraded_reason": "margin_data_unavailable" + (f":{'|'.join(errors[:4])}" if errors else ""),
        }

    merged = pd.concat(frames, ignore_index=True)
    grouped = (
        merged.groupby("日期", as_index=False)[["融资融券余额", "融资余额"]]
        .sum(min_count=1)
        .sort_values("日期")
        .reset_index(drop=True)
    )
    total_col = "融资融券余额" if grouped["融资融券余额"].notna().any() else "融资余额"
    grouped["margin_total"] = pd.to_numeric(grouped[total_col], errors="coerce")
    grouped = grouped.dropna(subset=["margin_total"]).reset_index(drop=True)
    if len(grouped) < 2:
        return {
            "margin_total": _safe_float(grouped.iloc[-1]["margin_total"]) if not grouped.empty else None,
            "margin_change_pct": None,
            "margin_change_proxy": None,
            "quality_status": "degraded",
            "degraded_reason": "margin_history_insufficient",
        }

    latest_total = _safe_float(grouped.iloc[-1]["margin_total"])
    prev_total = _safe_float(grouped.iloc[-2]["margin_total"])
    change_pct = None
    if latest_total is not None and prev_total not in (None, 0):
        change_pct = (latest_total / prev_total) - 1.0
    proxy = None
    if change_pct is not None:
        proxy = max(-0.3, min(0.3, change_pct * 10.0))
    return {
        "margin_total": latest_total,
        "margin_change_pct": round(float(change_pct), 6) if change_pct is not None else None,
        "margin_change_proxy": round(float(proxy), 6) if proxy is not None else None,
        "quality_status": "info" if proxy is not None else "degraded",
        "degraded_reason": None if proxy is not None else "margin_change_unavailable",
    }


def build_feature_snapshot(trade_date: Optional[str] = None) -> Dict[str, Any]:
    td = trade_date or shanghai_today()
    next_td = next_trading_day(td)
    sector_today = tool_fetch_sector_data(sector_type="industry", period="today")
    northbound = tool_fetch_northbound_flow(lookback_days=5)
    macro = tool_fetch_macro_snapshot(scope="monthly", include_quadrant=False)
    limit_up = _limit_up_metrics(td)
    fund_flow = _fund_flow_metrics()
    margin = _margin_change_metrics()
    hotspot = _hotspot_metrics(td)
    style = _style_spread_metrics()
    sector_records = _normalize_records(sector_today)
    northbound_metrics = _northbound_score(northbound)
    macro_metrics = _macro_proxy(macro)

    indices: Dict[str, Any] = {}
    for spec in SIX_INDEX_SPECS:
        df = _daily_df(spec.code, lookback_days=320)
        volume_ratio = None
        if not df.empty and "volume" in df.columns and len(df) >= 6:
            v = pd.to_numeric(df["volume"], errors="coerce")
            latest_v = _safe_float(v.iloc[-1])
            ma5 = _safe_float(v.tail(5).mean())
            if latest_v is not None and ma5 not in (None, 0):
                volume_ratio = latest_v / ma5
        ret5 = _pct_change(df, 5)
        ret10 = _pct_change(df, 10)
        ret20 = _pct_change(df, 20)
        ret60 = _pct_change(df, 60)
        ret_hist_10 = _rolling_return_series(df, 10)
        indices[spec.code] = {
            "index_code": spec.code,
            "index_name": spec.name,
            "ret5": ret5,
            "ret10": ret10,
            "ret20": ret20,
            "ret60": ret60,
            "ret10_percentile": _rolling_percentile(ret_hist_10, ret10),
            "volume_ratio_1d_5d": volume_ratio,
            "close_price": _safe_float(df.iloc[-1]["close"]) if not df.empty else None,
            "sector_leadership_score": _sector_leadership_score(sector_records),
            "top_sector_momentum": _sector_top_momentum(sector_records),
        }

    # index-specific enrichments
    sh = indices["000001"]
    broad_fin = _extract_sector_change(sector_records, ["金融"])
    bank_change = _extract_sector_change(sector_records, ["银行"])
    non_bank_change = _extract_sector_change(sector_records, ["证券", "保险", "多元金融"])
    if broad_fin is not None:
        # Backfill when upstream sector labels only provide broad "金融行业".
        if bank_change is None:
            bank_change = broad_fin * 0.55
        if non_bank_change is None:
            non_bank_change = broad_fin * 0.45
    sh["weight_sector_changes"] = {
        "bank": bank_change,
        "non_bank_fin": non_bank_change,
        "petro": _extract_sector_change(sector_records, ["石油", "石化"]),
    }

    csi300 = indices["000300"]
    close_hist = _rolling_return_series(_daily_df("000300", 320), 20)
    csi300["valuation_proxy_percentile"] = _rolling_percentile(close_hist, csi300.get("ret20"))
    csi300["northbound"] = northbound_metrics
    csi300["macro_proxy"] = macro_metrics

    kc50 = indices["000688"]
    kc50.update(load_kronos_signal("000688.SH", kc50))
    kc50["limit_up_ratio_proxy"] = limit_up["limit_up_ratio_kc50_proxy"]

    chinext = indices["399006"]
    chinext["style"] = style
    chinext["fund_flow"] = fund_flow

    csi500 = indices["000905"]
    csi500["sw_level1_top_sectors"] = _sector_top_momentum(sector_records)
    csi500["limit_signal_proxy"] = limit_up["limit_up_count"]

    csi1000 = indices["000852"]
    csi1000.update(load_kronos_signal("000852.SH", csi1000))
    csi1000["smallcap_limit_up_ratio"] = limit_up["limit_up_ratio_smallcap_proxy"]
    csi1000["market_main_force"] = fund_flow
    csi1000["margin_change_proxy"] = margin["margin_change_proxy"]
    csi1000["margin_snapshot"] = margin

    quality_reasons = [
        x
        for x in (
            northbound_metrics.get("degraded_reason"),
            macro_metrics.get("degraded_reason"),
            limit_up.get("degraded_reason"),
            fund_flow.get("degraded_reason"),
            margin.get("degraded_reason"),
            hotspot.get("degraded_reason"),
        )
        if x
    ]
    quality_status = "degraded" if quality_reasons else "info"
    run_id = datetime.now(TZ_SH).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    return {
        "_meta": {
            "schema_name": "six_index_next_day_features_v1",
            "schema_version": "1.0.0",
            "task_id": "six-index-next-day-prediction",
            "run_id": run_id,
            "data_layer": "L2",
            "generated_at": datetime.now(TZ_SH).isoformat(timespec="seconds"),
            "trade_date": td,
            "predict_for_trade_date": next_td,
            "quality_status": quality_status,
            "source_tools": [
                "tool_fetch_sector_data",
                "tool_fetch_northbound_flow",
                "tool_fetch_macro_snapshot",
                "tool_fetch_limit_up_stocks",
                "tool_fetch_a_share_fund_flow",
                "tool_hotspot_discovery",
                "fetch_index_daily_em",
            ],
            "lineage_refs": [],
        },
        "trade_date": td,
        "predict_for_trade_date": next_td,
        "global_features": {
            "sector_snapshot_quality": "info" if sector_today.get("success") else "degraded",
            "sector_count": len(sector_records),
            "northbound_intraday_score": northbound_metrics["northbound_intraday_score"],
            "northbound_net_inflow_e8": northbound_metrics["net_inflow_e8"],
            "macro_proxy_score": macro_metrics["macro_proxy_score"],
            "macro_staleness_days": macro_metrics["macro_staleness_days"],
            "macro_weight_multiplier": macro_metrics["macro_weight_multiplier"],
            "limit_up_count": limit_up["limit_up_count"],
            "market_main_force_score": fund_flow["market_main_force_score"],
            "margin_change_proxy": margin["margin_change_proxy"],
            "style_spread_percentile": style.get("style_spread_percentile"),
            "top_hotspots": hotspot.get("top_hotspots") or [],
            "top_hotspot_score": hotspot.get("top_hotspot_score"),
            "hotspot_snapshot": hotspot.get("snapshot"),
        },
        "indices": indices,
    }


def persist_feature_snapshot(doc: Dict[str, Any]) -> Path:
    td = str(doc.get("trade_date") or doc.get("_meta", {}).get("trade_date") or shanghai_today()).strip()
    path = ROOT / "data" / "features" / "six_index_next_day" / f"{td}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.setdefault("_meta", {}).setdefault("lineage_refs", []).append(str(path.relative_to(ROOT)))
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
