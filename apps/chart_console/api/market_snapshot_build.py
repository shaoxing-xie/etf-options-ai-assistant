"""
Build L4 semantic snapshots for global market dashboard and QDII futures MVP.

Reads A-share index spot via AkShare; global indices and futures via
openclaw-data-china-stock plugin tools.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from zoneinfo import ZoneInfo


def _repo_root() -> Path:
    for key in ("ETF_OPTIONS_ASSISTANT_ROOT", "CHART_CONSOLE_REPO_ROOT"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.is_dir():
                return p
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
_EM_FUTURES_CACHE: dict[str, Any] = {"ts": 0.0, "rows": None}
_SOURCE_LAST_CALL_TS: dict[str, float] = {}
_YF_MIN_INTERVAL_SEC = 0.6
_GLOBAL_SPOT_MIN_INTERVAL_SEC = 0.8
_PACE_LOCK = threading.Lock()
_A50_ITEM_CACHE: dict[str, Any] = {"ts": 0.0, "item": None}
_A50_CACHE_TTL_SEC = 30.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _finalize_item_quality(item: dict[str, Any], semantics: str) -> dict[str, Any]:
    out = dict(item)
    now_iso = _utc_now_iso()
    as_of_raw = out.get("as_of") or now_iso
    as_of_dt = _parse_ts(as_of_raw)
    now_dt = _parse_ts(now_iso)
    age_sec: Optional[int] = None
    if as_of_dt and now_dt:
        age_sec = max(0, int((now_dt - as_of_dt).total_seconds()))

    out["data_semantics"] = semantics
    out["as_of"] = as_of_dt.isoformat().replace("+00:00", "Z") if as_of_dt else str(as_of_raw)
    out["fetched_at"] = now_iso
    out["freshness_age_sec"] = age_sec

    last = _safe_float(out.get("last_price"))
    if last is None:
        out["quality_status"] = "error"
        out["degraded_reason"] = str(out.get("degraded_reason") or "no_price")
        return out

    base_quality = str(out.get("quality_status") or "ok")
    reason = str(out.get("degraded_reason") or "")
    if semantics == "daily_close":
        out["quality_status"] = "degraded"
        out["degraded_reason"] = reason or "daily_close_snapshot"
        return out
    if semantics == "realtime_quote" and isinstance(age_sec, int) and age_sec > 120:
        out["quality_status"] = "degraded"
        out["degraded_reason"] = reason or "stale_realtime_quote"
        return out
    if semantics == "minute_bar" and isinstance(age_sec, int) and age_sec > 600:
        out["quality_status"] = "degraded"
        out["degraded_reason"] = reason or "stale_minute_bar"
        return out

    out["quality_status"] = "ok" if base_quality == "ok" else base_quality
    out["degraded_reason"] = reason
    return out


def _pace_source(source: str, min_interval_sec: float) -> None:
    if min_interval_sec <= 0:
        return
    with _PACE_LOCK:
        now = time.monotonic()
        last = float(_SOURCE_LAST_CALL_TS.get(source) or 0.0)
        wait = min_interval_sec - (now - last)
        if wait > 0:
            time.sleep(wait)
        _SOURCE_LAST_CALL_TS[source] = time.monotonic()


def _load_market_proxy_config() -> dict[str, Any]:
    p = ROOT / "config" / "domains" / "market_data.yaml"
    if not p.is_file():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def _meta_block(
    *,
    schema_name: str,
    task_id: str,
    trade_date: str,
    quality: str,
    source_tools: list[str],
    lineage_refs: list[str],
) -> dict[str, Any]:
    rid = str(uuid.uuid4())
    return {
        "schema_name": schema_name,
        "schema_version": "1.0.0",
        "task_id": task_id,
        "run_id": rid,
        "data_layer": "L4",
        "generated_at": _utc_now_iso(),
        "trade_date": trade_date,
        "quality_status": quality,
        "source_tools": source_tools,
        "lineage_refs": lineage_refs,
    }


def _lineage_event(lineage: list[str], stage: str, ok: bool, elapsed_ms: int, detail: str = "") -> None:
    suffix = f":{detail}" if detail else ""
    lineage.append(f"{stage}|ok={1 if ok else 0}|ms={elapsed_ms}{suffix}")


def _normalize_sina_index_code(raw: str) -> str:
    s = str(raw or "").strip().lower()
    for pfx in ("sh", "sz", "bj"):
        if s.startswith(pfx) and len(s) > len(pfx):
            s = s[len(pfx) :]
            break
    if s.isdigit():
        return s.zfill(6)
    return s


def _row_get(row: Any, *names: str) -> Any:
    if hasattr(row, "get"):
        for n in names:
            if n in row and row.get(n) is not None:
                return row.get(n)
    return None


# Yahoo 符号兜底（AkShare 无行/无网络时）；同一指数可多候选
_CN_INDEX_YF_FALLBACK: dict[str, list[str]] = {
    "000001": ["000001.SS"],
    "399001": ["399001.SZ"],
    "000300": ["000300.SS"],
    "000905": ["000905.SS"],
    "000852": ["000852.SS"],
    "000016": ["000016.SS"],
    "000688": ["000688.SS"],
    "399006": ["399006.SZ"],
    "399673": ["399673.SZ"],
    "899050": ["899050.BJ", "159790.SZ"],
}


def _cn_hist_metrics(
    index_code: str,
    trade_date: str,
) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """A-share specific fallback via local index_daily cache (fast), else historical tool."""
    cache_resp: Optional[dict[str, Any]] = None
    try:
        # Prefer local parquet cache to avoid repeated online calls during refresh polling.
        from plugins.data_access.read_cache_data import read_cache_data  # type: ignore

        td = datetime.strptime(trade_date, "%Y-%m-%d")
        end = td.strftime("%Y%m%d")
        # Calendar window; cache loader will internally filter to trading days.
        start = (td - timedelta(days=15)).strftime("%Y%m%d")
        cache_resp = read_cache_data(
            data_type="index_daily",
            symbol=index_code,
            start_date=start,
            end_date=end,
            return_df=False,
            skip_online_refill=True,
        )
    except Exception:
        cache_resp = None

    # If cache layer exists but misses/incomplete, return None and let outer fallbacks (yfinance/proxy) handle.
    if isinstance(cache_resp, dict):
        if not bool(cache_resp.get("success")):
            return None, None, None, f"cn_hist_cache_miss:{cache_resp.get('message') or 'miss'}"
        records = (cache_resp.get("data") or {}).get("records") or []
        if not isinstance(records, list) or not records:
            return None, None, None, "cn_hist_cache_empty"

        # Expect records like {'日期': 'YYYY-MM-DD', '收盘': ...}
        rows = [r for r in records if isinstance(r, dict)]
        rows.sort(key=lambda r: str(r.get("日期") or r.get("date") or ""))

        closes: list[float] = []
        for r in rows[-8:]:
            c = _safe_float(r.get("收盘") if "收盘" in r else r.get("close"))
            if c is None or (math.isnan(c) or math.isinf(c)) or float(c) <= 0:
                continue
            closes.append(float(c))

        if not closes:
            return None, None, None, "cn_hist_cache_no_closes"

        last = closes[-1]
        if len(closes) >= 2:
            prev = closes[-2]
            if prev not in (None, 0):
                chg_a = last - prev
                chg_p = (last / prev - 1.0) * 100.0
            else:
                chg_a, chg_p = None, None
        else:
            chg_a, chg_p = None, None
        return last, chg_a, chg_p, "cn_hist_cache_daily"

    # Fallback: unified historical index tool.
    try:
        from plugins.merged.fetch_index_data import tool_fetch_index_data  # type: ignore
    except Exception as e:
        return None, None, None, f"cn_hist_import:{e}"
    try:
        resp = tool_fetch_index_data(
            data_type="historical",
            index_code=index_code,
            period="daily",
            lookback_days=5,
            mode="production",
        )
    except Exception as e:
        return None, None, None, f"cn_hist_err:{e}"
    if not isinstance(resp, dict) or not bool(resp.get("success")):
        return None, None, None, f"cn_hist_err:{(resp or {}).get('message') or 'failed'}"
    data = resp.get("data")
    if not isinstance(data, dict):
        return None, None, None, "cn_hist_empty"
    rows = data.get("klines")
    if not isinstance(rows, list) or not rows:
        return None, None, None, "cn_hist_empty"
    closes: list[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        c = _safe_float(r.get("close"))
        if c is None or (math.isnan(c) or math.isinf(c)) or float(c) <= 0:
            continue
        closes.append(float(c))
    if not closes:
        return None, None, None, "cn_hist_empty"
    last = closes[-1]
    if len(closes) >= 2 and closes[-2] not in (None, 0):
        prev = closes[-2]
        chg_a = last - prev
        chg_p = (last / prev - 1.0) * 100.0
    else:
        chg_a = None
        chg_p = None
    return last, chg_a, chg_p, "cn_hist_daily"


def _cn_proxy_etf_metrics(etf_code: str) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """Last-resort proxy for unsupported indices (e.g. 北证50 via ETF proxy)."""
    try:
        from plugins.data_collection.etf.fetch_realtime import fetch_etf_realtime  # type: ignore
    except Exception as e:
        return None, None, None, f"cn_proxy_import:{e}"
    try:
        resp = fetch_etf_realtime(etf_code=etf_code)
    except Exception as e:
        return None, None, None, f"cn_proxy_err:{e}"
    if not isinstance(resp, dict) or not bool(resp.get("success")):
        return None, None, None, f"cn_proxy_err:{(resp or {}).get('message') or 'failed'}"
    data = resp.get("data")
    if not isinstance(data, dict):
        return None, None, None, "cn_proxy_empty"
    last = _safe_float(data.get("current_price"))
    chg_a = _safe_float(data.get("change"))
    chg_p = _safe_float(data.get("change_percent"))
    if last is None:
        return None, None, None, "cn_proxy_empty"
    return last, chg_a, chg_p, "cn_proxy_etf"


def _build_cn_index_items(trade_date: str) -> Tuple[list[dict[str, Any]], str, list[str]]:
    specs: list[tuple[str, str]] = [
        ("000001", "上证指数"),
        ("399001", "深证成指"),
        ("000300", "沪深300"),
        ("000905", "中证500"),
        ("000852", "中证1000"),
        ("000016", "上证50"),
        ("000688", "科创50"),
        ("399006", "创业板指"),
        ("399673", "创业板50"),
        ("899050", "北证50"),
    ]
    cfg = _load_market_proxy_config()
    tools: list[str] = []
    lineage: list[str] = []
    by_code: dict[str, dict[str, Any]] = {}
    proxy_etf_map = {
        "899050": "159790",  # 北证50
        "000688": "588080",  # 科创50ETF（同口径代理）
        "399673": "159915",  # 创业板50 -> 创业板ETF 近似代理
    }
    realtime_supported = {
        "000001",
        "399001",
        "000300",
        "000905",
        "000852",
        "000016",
        "399006",
        "000688",
        "399673",
    }
    rt_codes = [c for c, _ in specs if c in realtime_supported]
    src = "tool_fetch_index_data:realtime"
    try:
        from plugins.merged.fetch_index_data import tool_fetch_index_data  # type: ignore

        resp = tool_fetch_index_data(
            data_type="realtime",
            index_code=",".join(rt_codes),
            mode="production",
        )
        tools.append(src)
        if isinstance(resp, dict) and bool(resp.get("success")) and isinstance(resp.get("data"), list):
            for row in resp.get("data") or []:
                if not isinstance(row, dict):
                    continue
                k = _normalize_sina_index_code(row.get("index_code") or row.get("code") or row.get("symbol"))
                if k:
                    by_code[k] = row
        else:
            src = f"{src}:{(resp or {}).get('message') or 'failed'}"
    except Exception as e:
        src = f"tool_fetch_index_data_err:{e}"
        tools.append(src)

    items: list[dict[str, Any]] = []
    worst = "ok"
    for code, title in specs:
        row = by_code.get(code)
        last = _safe_float(_row_get(row, "最新价", "现价", "price", "close", "current_price")) if row is not None else None
        chg_a = _safe_float(_row_get(row, "涨跌额", "涨跌", "change", "change_abs")) if row is not None else None
        chg_p = _safe_float(_row_get(row, "涨跌幅", "涨跌幅%", "pct", "change_pct")) if row is not None else None
        # Some realtime paths may return "fallback" values with last_price=0/amount=0.
        # Treat non-positive price as missing so we can do historical/proxy fallback.
        if last is not None and float(last) <= 0:
            last, chg_a, chg_p = None, None, None
        if chg_p is not None and abs(chg_p) > 50:
            chg_p = chg_p / 100.0
        q = "ok" if last is not None else "degraded"
        sid = "openclaw" if row is not None else "unknown"
        raw = src
        if last is None:
            h_last, h_ca, h_cp, h_tag = _cn_hist_metrics(code, trade_date)
            if h_last is not None:
                last, chg_a, chg_p = h_last, h_ca, h_cp
                q = "ok"
                sid = "openclaw"
                raw = f"{src}|{h_tag}"
                tools.append("tool_fetch_index_data:historical")
            else:
                for ysym in _CN_INDEX_YF_FALLBACK.get(code, []):
                    y_last, y_ca, y_cp, tag = _yf_hist_metrics(ysym, cfg)
                    if y_last is not None:
                        last, chg_a, chg_p = y_last, y_ca, y_cp
                        q = "ok"
                        sid = "yfinance"
                        raw = f"{src}|yf:{ysym}:{tag}"
                        tools.append("yfinance")
                        break
            if last is None and code in proxy_etf_map:
                p_last, p_ca, p_cp, p_tag = _cn_proxy_etf_metrics(proxy_etf_map[code])
                if p_last is not None:
                    last, chg_a, chg_p = p_last, p_ca, p_cp
                    q = "degraded"
                    sid = "openclaw"
                    raw = f"{src}|{p_tag}:{proxy_etf_map[code]}"
                    tools.append("fetch_etf_realtime")
        if q != "ok":
            worst = "degraded"
        semantics = "realtime_quote" if sid == "openclaw" else "daily_close"
        item = {
            "instrument_id": f"cn.index.{code}",
            "instrument_code": code,
            "display_name": title,
            "subtitle": "",
            "category": "cn_index",
            "last_price": last,
            "change_abs": chg_a,
            "change_pct": chg_p,
            "display_price_role": "index",
            "quality_status": q,
            "degraded_reason": "" if q == "ok" else "cn_index_row_missing",
            "source_id": sid,
            "source_raw": raw,
            "as_of": _utc_now_iso(),
        }
        items.append(_finalize_item_quality(item, semantics))
    return items, worst, tools


def _import_global_spot() -> Optional[Callable[..., Any]]:
    try:
        from plugins.data_collection.index.fetch_global import tool_fetch_global_index_spot

        return tool_fetch_global_index_spot
    except Exception:
        return None


def _yf_hist_metrics(
    symbol: str,
    cfg: dict[str, Any],
    *,
    fast_path: bool = False,
) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    # Prefer yfinance when available (fast path for chart console); fallback to plugin hist tool.
    del cfg, fast_path
    try:
        import yfinance as yf  # type: ignore

        from plugins.utils.proxy_env import proxy_env_for_source  # type: ignore

        with proxy_env_for_source("yfinance"):
            t = yf.Ticker(str(symbol))
            hist = t.history(period="7d", interval="1d")
        if hist is None or getattr(hist, "empty", True):
            raise RuntimeError("empty_history")
        try:
            last = float(hist["Close"].iloc[-1])  # type: ignore[index]
            prev = float(hist["Close"].iloc[-2]) if len(hist.index) >= 2 else None  # type: ignore[index]
        except Exception:
            return None, None, None, "yfinance_parse_err"
        if last is None or math.isnan(last) or math.isinf(last):
            return None, None, None, "yfinance_nan"
        if prev in (None, 0) or math.isnan(prev) or math.isinf(prev):
            return last, None, None, "yfinance_prev_bad"
        chg_a = last - prev
        chg_p = (last / prev - 1.0) * 100.0
        return last, chg_a, chg_p, "yfinance"
    except Exception:
        pass

    try:
        from plugins.data_collection.index.fetch_global_hist_sina import (  # type: ignore
            tool_fetch_global_index_hist_sina,
        )
    except Exception as e:
        return None, None, None, f"global_hist_import:{e}"
    try:
        _pace_source("tool_fetch_global_index_hist_sina", _YF_MIN_INTERVAL_SEC)
        resp = tool_fetch_global_index_hist_sina(symbol=symbol, limit=5)
    except Exception as e:
        return None, None, None, f"global_hist_err:{e}"
    if not isinstance(resp, dict) or not bool(resp.get("success")):
        return None, None, None, f"global_hist_err:{(resp or {}).get('message') or 'failed'}"
    rows = resp.get("data")
    if not isinstance(rows, list) or not rows:
        return None, None, None, "global_hist_empty"
    closes: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        c = _safe_float(row.get("close"))
        if c is None:
            c = _safe_float(row.get("Close"))
        if c is None:
            c = _safe_float(row.get("收盘"))
        if c is not None and not (math.isnan(c) or math.isinf(c)):
            closes.append(c)
    if not closes:
        return None, None, None, "global_hist_empty"
    last = closes[-1]
    if len(closes) >= 2:
        prev = closes[-2]
        if prev == 0:
            return last, None, None, "global_hist_prev_bad"
        chg_a = last - prev
        chg_p = (last / prev - 1.0) * 100.0
    else:
        chg_a = None
        chg_p = None
    return last, chg_a, chg_p, "global_hist_sina"


def _yf_intraday_metrics(symbol: str, cfg: dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    del cfg
    try:
        from plugins.merged.fetch_index_data import tool_fetch_index_data  # type: ignore
    except Exception as e:
        return None, None, None, f"global_spot_import:{e}"
    try:
        _pace_source("tool_fetch_index_data.global_spot", _YF_MIN_INTERVAL_SEC)
        resp = tool_fetch_index_data(data_type="global_spot", index_codes=symbol, mode="production")
    except Exception as e:
        return None, None, None, f"global_spot_err:{e}"
    if not isinstance(resp, dict) or not bool(resp.get("success")):
        return None, None, None, f"global_spot_err:{(resp or {}).get('message') or 'failed'}"
    rows = resp.get("data")
    if not isinstance(rows, list) or not rows:
        return None, None, None, "global_spot_empty"
    row = None
    target = str(symbol or "").strip().upper()
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = str(r.get("code") or r.get("symbol") or "").strip().upper()
        if code == target:
            row = r
            break
    if row is None:
        row = rows[0] if isinstance(rows[0], dict) else None
    if not isinstance(row, dict):
        return None, None, None, "global_spot_empty"
    last = _safe_float(row.get("price"))
    if last is None:
        last = _safe_float(row.get("latest_price"))
    chg_a = _safe_float(row.get("change"))
    chg_p = _safe_float(row.get("change_pct"))
    if chg_p is None:
        prev = _safe_float(row.get("prev_close"))
        if prev not in (None, 0) and last is not None:
            chg_p = (last / prev - 1.0) * 100.0
            chg_a = (last - prev) if chg_a is None else chg_a
    if last is None:
        return None, None, None, "global_spot_empty"
    return last, chg_a, chg_p, "global_spot_intraday"


def _em_futures_rows_cached(ttl_sec: int = 120) -> Optional[list[dict[str, Any]]]:
    del ttl_sec
    # Deprecated: keep plugin-first discipline; futures path uses unified tools in _yf_intraday_metrics/_yf_hist_metrics.
    return None


def _em_future_quote(instrument_id: str) -> Optional[dict[str, Any]]:
    rows = _em_futures_rows_cached()
    if not rows:
        return None
    code_patterns: dict[str, list[str]] = {
        "future.nq": [r"^NQ00Y$"],
        "future.es": [r"^ES00Y$"],
        "future.ym": [r"^YM00Y$"],
        "future.nkd": [r"^NKD00Y$", r"^N22500Y$", r"^JP22500Y$"],
    }
    name_patterns: dict[str, list[str]] = {
        "future.nq": [r"纳指.*当月连续", r"纳斯达克.*当月连续"],
        "future.es": [r"标普.*当月连续"],
        "future.ym": [r"道指.*当月连续", r"道琼斯.*当月连续"],
        "future.nkd": [r"日经.*当月连续", r"日本.*225.*当月连续"],
    }
    cps = [re.compile(p, re.I) for p in code_patterns.get(instrument_id, [])]
    nps = [re.compile(p, re.I) for p in name_patterns.get(instrument_id, [])]
    for row in rows:
        code = str(row.get("代码") or row.get("code") or "").strip()
        name = str(row.get("名称") or row.get("name") or "").strip()
        by_code = any(p.search(code) for p in cps) if cps else False
        by_name = any(p.search(name) for p in nps) if nps else False
        if not (by_code or by_name):
            continue
        last = _safe_float(row.get("最新价") if "最新价" in row else row.get("latest"))
        if last is None:
            continue
        chg_a = _safe_float(row.get("涨跌额") if "涨跌额" in row else row.get("change"))
        chg_p = _safe_float(row.get("涨跌幅") if "涨跌幅" in row else row.get("change_pct"))
        if chg_p is not None and abs(chg_p) > 100:
            chg_p = chg_p / 100.0
        return {
            "instrument_code": code,
            "last_price": last,
            "change_abs": chg_a,
            "change_pct": chg_p,
            "source_id": "akshare",
            "source_raw": f"akshare.futures_global_spot_em:{code}",
            "as_of": _utc_now_iso(),
        }
    return None


def _global_spot_map(symbols: str) -> Tuple[dict[str, dict[str, Any]], list[str], str]:
    fn = _import_global_spot()
    if not fn:
        return {}, [], "plugin_import_failed"
    try:
        _pace_source("tool_fetch_global_index_spot", _GLOBAL_SPOT_MIN_INTERVAL_SEC)
        raw = fn(index_codes=symbols)
    except Exception as e:
        return {}, [], f"tool_fetch_global_index_spot:{e}"
    tools = ["tool_fetch_global_index_spot"]
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict) or not raw.get("success"):
        return out, tools, str((raw or {}).get("message") or "spot_failed")
    for row in raw.get("data") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if code:
            out[code] = row
    return out, tools, "ok"


def _global_spot_map_with_retry(symbols: list[str], retry_rounds: int = 1) -> Tuple[dict[str, dict[str, Any]], list[str], str]:
    """Pull global spot with batch + missing retry.

    Goal: reduce provider burst/rate-limit and avoid partially missing symbol sets.
    Still strictly relies on `tool_fetch_global_index_spot` for the indicator.
    """
    uniq_symbols: list[str] = []
    seen: set[str] = set()
    for s in symbols:
        k = str(s or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        uniq_symbols.append(k)
    if not uniq_symbols:
        return {}, [], "empty_symbols"
    tools: list[str] = []
    out: dict[str, dict[str, Any]] = {}

    def _chunk(arr: list[str], n: int) -> list[list[str]]:
        if n <= 0:
            return [arr]
        return [arr[i : i + n] for i in range(0, len(arr), n)]

    # A smaller batch reduces the chance of tool-side partial responses.
    batch_size = 3
    pending = list(uniq_symbols)
    for round_idx in range(max(0, int(retry_rounds)) + 1):
        if not pending:
            break
        for batch in _chunk(pending, batch_size):
            one, t, msg = _global_spot_map(",".join(batch))
            tools.extend(t)
            if msg != "ok":
                # Keep going: a failed batch shouldn't poison the whole indicator.
                continue
            out.update(one)
        pending = [s for s in uniq_symbols if s not in out]
        if not pending:
            break

    # Final attempt: retry remaining missing symbols individually.
    pending = [s for s in uniq_symbols if s not in out]
    for sym in pending:
        one, t, one_msg = _global_spot_map(sym)
        tools.extend(t)
        if one_msg == "ok":
            out.update(one)

    return out, tools, "ok"


def _pick_spot_row(spot_map: dict[str, dict[str, Any]], codes_try: list[str]) -> Optional[dict[str, Any]]:
    for c in codes_try:
        key = str(c or "").strip()
        if key and key in spot_map:
            return spot_map.get(key)
    return None


def _item_from_spot_row(
    instrument_id: str,
    display_name: str,
    code: str,
    row: Optional[dict[str, Any]],
    *,
    category: str,
) -> dict[str, Any]:
    if not row:
        raw = {
            "instrument_id": instrument_id,
            "instrument_code": code,
            "display_name": display_name,
            "subtitle": "",
            "category": category,
            "last_price": None,
            "change_abs": None,
            "change_pct": _safe_float(None),
            "display_price_role": "index",
            "quality_status": "degraded",
            "degraded_reason": "global_spot_missing",
            "source_id": "unknown",
            "source_raw": "",
            "as_of": _utc_now_iso(),
        }
        return _finalize_item_quality(raw, "realtime_quote")
    last = _safe_float(row.get("price"))
    chg_a = _safe_float(row.get("change"))
    chg_p = _safe_float(row.get("change_pct"))
    src = str(row.get("source_id") or row.get("source") or "mixed")
    as_of = row.get("timestamp") or row.get("as_of") or _utc_now_iso()
    raw = {
        "instrument_id": instrument_id,
        "instrument_code": code,
        "display_name": display_name,
        "subtitle": "",
        "category": category,
        "last_price": last,
        "change_abs": chg_a,
        "change_pct": chg_p,
        "display_price_role": "index",
        "quality_status": "ok",
        "degraded_reason": "",
        "source_id": str(row.get("source_id") or "fmp"),
        "source_raw": src,
        "as_of": as_of,
    }
    return _finalize_item_quality(raw, "realtime_quote")


def _global_index_item_spot_only(
    instrument_id: str,
    display_name: str,
    primary_code: str,
    codes_try: list[str],
    row: Optional[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Strict spot-only index item: do not synthesize from other fallback series."""
    item = _item_from_spot_row(instrument_id, display_name, primary_code, row, category="global_index")
    if item.get("last_price") is not None:
        return item
    if codes_try:
        item["degraded_reason"] = f"global_spot_missing:{'|'.join(codes_try)}"
        item["quality_status"] = "error"
    return item


def _future_item(
    *,
    instrument_id: str,
    display_name: str,
    subtitle: str,
    symbols_try: list[str],
    cfg: dict[str, Any],
    index_fallback: Optional[tuple[str, str]] = None,
    same_future_fallback: Optional[dict[str, Any]] = None,
    same_future_fallback_getter: Optional[Callable[[], Optional[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    last = chg_a = chg_p = None
    src = ""
    role = "future"
    code_out = symbols_try[0] if symbols_try else ""
    if last is None and same_future_fallback_getter:
        try:
            same_future_fallback = same_future_fallback_getter()
        except Exception:
            same_future_fallback = None
    if last is None and same_future_fallback:
        last = _safe_float(same_future_fallback.get("last_price"))
        chg_a = _safe_float(same_future_fallback.get("change_abs"))
        chg_p = _safe_float(same_future_fallback.get("change_pct"))
        if last is not None:
            src = str(same_future_fallback.get("source_raw") or "akshare.futures_global_spot_em")
            code_out = str(same_future_fallback.get("instrument_code") or code_out)
            role = "future"
    if last is None:
        for sym in symbols_try:
            # Phase 1: intraday minute bars first
            last, chg_a, chg_p, tag = _yf_intraday_metrics(sym, cfg)
            src = tag
            if last is not None:
                code_out = sym
                break
    if last is None:
        # Phase 2: daily bars fallback for remaining misses
        for sym in symbols_try:
            last, chg_a, chg_p, tag = _yf_hist_metrics(sym, cfg, fast_path=False)
            src = tag
            if last is not None:
                code_out = sym
                break
    # 注意：严禁用指数替代指数期货（不同指标不可替换）
    if last is None:
        q = "error"
        reason = "no_price"
    else:
        q = "ok"
        reason = ""
    semantics = "daily_close"
    if "akshare.futures_global_spot_em" in src:
        semantics = "realtime_quote"
    elif "yfinance_intraday" in src or "global_spot_intraday" in src:
        semantics = "minute_bar"
    raw = {
        "instrument_id": instrument_id,
        "instrument_code": code_out,
        "display_name": display_name,
        "subtitle": subtitle,
        "category": "index_future",
        "last_price": last,
        "change_abs": chg_a,
        "change_pct": chg_p,
        "display_price_role": role,
        "quality_status": q,
        "degraded_reason": reason,
        "source_id": (
            "yfinance"
            if "yfinance" in src
            else ("akshare" if "akshare.futures_global_spot_em" in src else ("openclaw" if "global_spot_intraday" in src else "unknown"))
        ),
        "source_raw": src,
        "as_of": _utc_now_iso(),
    }
    return _finalize_item_quality(raw, semantics)


def _build_future_item_from_spec(spec: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return _future_item(
        instrument_id=spec["id"],
        display_name=spec["title"],
        subtitle=str(spec["sub"]),
        symbols_try=list(spec["try"]),
        cfg=cfg,
        index_fallback=None,
        same_future_fallback_getter=lambda iid=spec["id"]: _em_future_quote(iid),
    )


def _future_item_a50_plugin_then_yf(cfg: dict[str, Any]) -> dict[str, Any]:
    """A50 fixed route: cache -> openclaw tool -> yfinance fallback."""
    now = time.time()
    cached = _A50_ITEM_CACHE.get("item")
    if (
        isinstance(cached, dict)
        and str(cached.get("quality_status")) == "ok"
        and (now - float(_A50_ITEM_CACHE.get("ts") or 0.0)) <= _A50_CACHE_TTL_SEC
    ):
        return _finalize_item_quality(dict(cached), str(cached.get("data_semantics") or "realtime_quote"))

    base = {
        "instrument_id": "future.a50",
        "instrument_code": "XINA50=F",
        "display_name": "富时A50",
        "subtitle": "期指连续",
        "category": "index_future",
        "last_price": None,
        "change_abs": None,
        "change_pct": None,
        "display_price_role": "future",
        "quality_status": "error",
        "degraded_reason": "no_price",
        "source_id": "openclaw",
        "source_raw": "a50_tool_unavailable",
        "as_of": _utc_now_iso(),
    }
    try:
        from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data  # type: ignore
    except Exception as e:
        base["source_raw"] = f"a50_tool_import_err:{e}"
        # 插件不可用时才走 yfinance 兜底，避免常态下多余探测
        fb = _future_item(
            instrument_id="future.a50",
            display_name="富时A50",
            subtitle="期指连续",
            symbols_try=["XINA50=F", "CN=F", "2823.HK"],
            cfg=cfg,
            index_fallback=None,
        )
        return fb
    try:
        raw = tool_fetch_a50_data(symbol="A50期指", data_type="spot", use_cache=True)
    except Exception as e:
        base["source_raw"] = f"a50_tool_err:{e}"
        fb = _future_item(
            instrument_id="future.a50",
            display_name="富时A50",
            subtitle="期指连续",
            symbols_try=["XINA50=F", "CN=F", "2823.HK"],
            cfg=cfg,
            index_fallback=None,
        )
        if fb.get("last_price") is not None:
            return fb
        return base
    if not isinstance(raw, dict):
        fb = _future_item(
            instrument_id="future.a50",
            display_name="富时A50",
            subtitle="期指连续",
            symbols_try=["XINA50=F", "CN=F", "2823.HK"],
            cfg=cfg,
            index_fallback=None,
        )
        if fb.get("last_price") is not None:
            return fb
        return base
    spot = raw.get("spot_data") if isinstance(raw.get("spot_data"), dict) else {}
    cur = _safe_float(spot.get("current_price"))
    if cur is None:
        fb = _future_item(
            instrument_id="future.a50",
            display_name="富时A50",
            subtitle="期指连续",
            symbols_try=["XINA50=F", "CN=F", "2823.HK"],
            cfg=cfg,
            index_fallback=None,
        )
        if fb.get("last_price") is not None:
            return fb
        base["source_raw"] = str(raw.get("source") or "tool_fetch_a50_data_empty")
        return base
    pct = _safe_float(spot.get("change_pct"))
    chg_a = None
    if pct is not None:
        try:
            chg_a = cur * pct / (100.0 + pct) if (100.0 + pct) != 0 else None
        except Exception:
            chg_a = None
    source_raw = str(raw.get("source") or "tool_fetch_a50_data")
    item = {
        **base,
        "instrument_code": str(spot.get("code") or base.get("instrument_code") or "A50"),
        "last_price": cur,
        "change_abs": chg_a,
        "change_pct": pct,
        "display_price_role": "future",
        "quality_status": "ok",
        "degraded_reason": "",
        "source_id": "openclaw",
        "source_raw": source_raw,
        "as_of": str(spot.get("timestamp") or _utc_now_iso()),
    }
    item = _finalize_item_quality(item, "realtime_quote")
    _A50_ITEM_CACHE["ts"] = time.time()
    _A50_ITEM_CACHE["item"] = dict(item)
    return item


def build_global_market_snapshot(trade_date: str) -> dict[str, Any]:
    """Assemble full L4 document for global_market_snapshot_v1."""
    cfg = _load_market_proxy_config()
    tools: list[str] = []
    lineage: list[str] = []

    t0 = time.perf_counter()
    cn_items, cn_q, cn_tools = _build_cn_index_items(trade_date)
    _lineage_event(lineage, "cn_index", True, int((time.perf_counter() - t0) * 1000), f"items={len(cn_items)}")
    tools.extend(cn_tools)

    # Global indices — strict same-index mapping and one-round retry for misses.
    apac_specs: list[tuple[str, list[str], str]] = [
        ("HSI", ["^HSI"], "恒生指数"),
        ("HSCEI", ["^HSCEI", "^HSCE", "2828.HK"], "国企指数"),
        ("N225", ["^N225"], "日经225"),
        ("KOSPI", ["^KS11"], "韩国KOSPI"),
        ("ASX200", ["^AXJO"], "澳大利亚标普200"),
        ("STI", ["^STI"], "新加坡海峡时报"),
        ("SENSEX", ["^BSESN"], "印度SENSEX"),
        ("TAIEX", ["^TWII"], "台湾加权"),
    ]
    us_specs: list[tuple[str, list[str], str]] = [
        ("DJI", ["^DJI"], "道琼斯工业"),
        ("IXIC", ["^IXIC"], "纳斯达克综合"),
        ("SPX", ["^GSPC"], "标普500"),
        ("FTSE", ["^FTSE"], "英国富时100"),
        ("GDAXI", ["^GDAXI"], "德国DAX"),
        ("FCHI", ["^FCHI"], "法国CAC40"),
        ("SX5E", ["^STOXX50E"], "欧洲斯托克50"),
    ]
    apac_codes = [code for _, codes, _ in apac_specs for code in codes]
    us_eu_codes = [code for _, codes, _ in us_specs for code in codes]
    t1s = time.perf_counter()
    apac_map, t1, apac_msg = _global_spot_map_with_retry(apac_codes, retry_rounds=2)
    _lineage_event(lineage, "global_spot_apac", apac_msg == "ok", int((time.perf_counter() - t1s) * 1000), apac_msg)
    t2s = time.perf_counter()
    us_map, t2, us_msg = _global_spot_map_with_retry(us_eu_codes, retry_rounds=2)
    _lineage_event(lineage, "global_spot_us_eu", us_msg == "ok", int((time.perf_counter() - t2s) * 1000), us_msg)
    tools.extend(t1)
    tools.extend(t2)
    apac_items = [
        _global_index_item_spot_only(
            f"global.apac.{symbol_id}",
            name,
            codes[0],
            codes,
            _pick_spot_row(apac_map, codes),
            cfg,
        )
        for symbol_id, codes, name in apac_specs
    ]
    us_items = [
        _global_index_item_spot_only(
            f"global.us_eu.{symbol_id}",
            name,
            codes[0],
            codes,
            _pick_spot_row(us_map, codes),
            cfg,
        )
        for symbol_id, codes, name in us_specs
    ]

    # Keep futures block focused on always-available legs.
    # Items that frequently show empty/ambiguous futures legs are intentionally excluded from UI for now:
    # - MSCI中国A50 / EURO STOXX 50 / DAX / VIX / 恒生指数期指
    fut_specs: list[dict[str, Any]] = [
        {
            "id": "future.nq",
            "title": "迷你纳指",
            "sub": "期指连续",
            "try": ["NQ=F"],
        },
        {
            "id": "future.es",
            "title": "迷你标普",
            "sub": "期指连续",
            "try": ["ES=F"],
        },
        {
            "id": "future.ym",
            "title": "迷你道指",
            "sub": "期指连续",
            "try": ["YM=F"],
        },
        {
            "id": "future.nkd",
            "title": "日经225",
            "sub": "期指主连",
            "try": ["NKD=F"],
        },
        {
            "id": "future.a50",
            "title": "富时A50",
            "sub": "期指连续",
            "try": ["XINA50=F", "CN=F", "2823.HK"],
        },
    ]
    fut_items: list[dict[str, Any]] = []
    tf = time.perf_counter()
    # 受控并发：期货腿并行 2 路，降低阶段总耗时，同时通过 _pace_source 保持源内节流。
    normal_specs = [s for s in fut_specs if s["id"] != "future.a50"]
    idx_map = {s["id"]: i for i, s in enumerate(fut_specs)}
    fut_by_idx: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        fs = [ex.submit(_build_future_item_from_spec, s, cfg) for s in normal_specs]
        for f in fs:
            it = f.result()
            fut_by_idx[idx_map[str(it.get("instrument_id") or "")]] = it

    a50_item = _future_item_a50_plugin_then_yf(cfg)
    fut_by_idx[idx_map["future.a50"]] = a50_item
    if str(a50_item.get("source_id")) == "openclaw":
        tools.append("tool_fetch_a50_data")
    fut_items = [fut_by_idx[i] for i in sorted(fut_by_idx.keys())]
    fut_ok = sum(1 for x in fut_items if str(x.get("quality_status")) == "ok")
    _lineage_event(lineage, "index_futures", fut_ok == len(fut_items), int((time.perf_counter() - tf) * 1000), f"ok={fut_ok}/{len(fut_items)}")

    qualities = [cn_q]
    for it in apac_items + us_items + fut_items:
        q = str(it.get("quality_status") or "ok")
        if q == "error":
            qualities.append("error")
        elif q == "degraded":
            qualities.append("degraded")
    overall = "ok"
    if "error" in qualities:
        overall = "degraded"
    elif "degraded" in qualities:
        overall = "degraded"

    doc: dict[str, Any] = {
        "trade_date": trade_date,
        "fetched_at": _utc_now_iso(),
        "summary": {"overall_quality": overall},
        "groups": [
            {"group_id": "cn_index", "title": "A股指数", "items": cn_items},
            {
                "group_id": "global_index",
                "title": "全球指数",
                "subgroups": [
                    {"subgroup_id": "apac", "title": "亚太市场", "items": apac_items},
                    {"subgroup_id": "us_eu", "title": "欧美市场", "items": us_items},
                ],
            },
            {"group_id": "index_futures", "title": "股指期货", "items": fut_items},
        ],
        "_meta": _meta_block(
            schema_name="global_market_snapshot_v1",
            task_id="global-market-snapshot",
            trade_date=trade_date,
            quality=overall,
            source_tools=sorted(set(tools)),
            lineage_refs=lineage,
        ),
    }
    return doc


def build_qdii_futures_snapshot(trade_date: str) -> dict[str, Any]:
    """Smaller L4 for research sub-tab: US / HK / global futures legs."""
    cfg = _load_market_proxy_config()
    tools = ["tool_fetch_global_index_spot", "yfinance"]

    t_us = time.perf_counter()
    us_items = [
        _future_item(
            instrument_id="qdii.us.nq",
            display_name="纳斯达克100期货",
            subtitle="NQ",
            symbols_try=["NQ=F"],
            cfg=cfg,
            index_fallback=None,
            same_future_fallback_getter=lambda: _em_future_quote("future.nq"),
        ),
        _future_item(
            instrument_id="qdii.us.es",
            display_name="标普500期货",
            subtitle="ES",
            symbols_try=["ES=F"],
            cfg=cfg,
            index_fallback=None,
            same_future_fallback_getter=lambda: _em_future_quote("future.es"),
        ),
        _future_item(
            instrument_id="qdii.us.ym",
            display_name="道琼斯期货",
            subtitle="YM",
            symbols_try=["YM=F"],
            cfg=cfg,
            index_fallback=None,
            same_future_fallback_getter=lambda: _em_future_quote("future.ym"),
        ),
    ]
    lineage: list[str] = []
    _lineage_event(lineage, "qdii_us", True, int((time.perf_counter() - t_us) * 1000), f"items={len(us_items)}")
    t_hk = time.perf_counter()
    hk_items = [
        _future_item(
            instrument_id="qdii.hk.hsi",
            display_name="恒生指数期货",
            subtitle="HSI",
            symbols_try=["HSI=F", "HSImain.HK"],
            cfg=cfg,
            index_fallback=None,
        ),
        _future_item(
            instrument_id="qdii.hk.hti",
            display_name="恒生科技期货",
            subtitle="HTI",
            symbols_try=["HTI=F", "HSTECH=F"],
            cfg=cfg,
            index_fallback=None,
        ),
    ]
    _lineage_event(lineage, "qdii_hk", True, int((time.perf_counter() - t_hk) * 1000), f"items={len(hk_items)}")
    t_gl = time.perf_counter()
    gl_items = [
        _future_item(
            instrument_id="qdii.global.nkd",
            display_name="日经225期货",
            subtitle="NKD",
            symbols_try=["NKD=F"],
            cfg=cfg,
            index_fallback=None,
            same_future_fallback_getter=lambda: _em_future_quote("future.nkd"),
        ),
        _future_item(
            instrument_id="qdii.global.dax",
            display_name="德国DAX期货",
            subtitle="FDX",
            symbols_try=["FDX=F", "DAX=F"],
            cfg=cfg,
            index_fallback=None,
        ),
    ]
    _lineage_event(lineage, "qdii_global", True, int((time.perf_counter() - t_gl) * 1000), f"items={len(gl_items)}")

    all_items = us_items + hk_items + gl_items
    overall = "ok"
    for it in all_items:
        if it.get("quality_status") == "error":
            overall = "degraded"
        elif it.get("quality_status") == "degraded" and overall == "ok":
            overall = "degraded"

    return {
        "trade_date": trade_date,
        "fetched_at": _utc_now_iso(),
        "summary": {"overall_quality": overall},
        "groups": [
            {"group_id": "us_equity", "title": "美股相关期指", "items": us_items},
            {"group_id": "hk_equity", "title": "港股相关期指", "items": hk_items},
            {"group_id": "global", "title": "其他", "items": gl_items},
        ],
        "_meta": _meta_block(
            schema_name="qdii_futures_snapshot_v1",
            task_id="qdii-futures-aggregation",
            trade_date=trade_date,
            quality=overall,
            source_tools=tools,
            lineage_refs=lineage,
        ),
    }


def persist_snapshot(root: Path | None, dataset: str, trade_date: str, doc: dict[str, Any]) -> Path:
    base = root or _repo_root()
    out_dir = base / "data" / "semantic" / dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{trade_date}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def persist_qdii_futures_l3_events(root: Path | None, trade_date: str, l4_doc: dict[str, Any]) -> Path:
    """Append one L3 quote event per instrument after L4 qdii snapshot build (contract: jsonl)."""
    base = root or _repo_root()
    meta_top = l4_doc.get("_meta") if isinstance(l4_doc.get("_meta"), dict) else {}
    run_id = str(meta_top.get("run_id") or uuid.uuid4())
    task_id = "qdii-futures-aggregation"
    st = meta_top.get("source_tools") if isinstance(meta_top.get("source_tools"), list) else []
    snap_ref = f"data/semantic/qdii_futures_snapshot/{trade_date}.json"
    out_dir = base / "data" / "semantic" / "qdii_futures_quote_events"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{trade_date}.jsonl"
    lines: list[str] = []
    for group in l4_doc.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("instrument_id") or "").strip()
            if not iid:
                continue
            q = str(item.get("quality_status") or meta_top.get("quality_status") or "ok")
            ev_id = f"{run_id}:{iid}"
            row_meta = {
                "schema_name": "qdii_futures_quote_event_v1",
                "schema_version": "1.0.0",
                "task_id": task_id,
                "run_id": run_id,
                "data_layer": "L3",
                "generated_at": _utc_now_iso(),
                "trade_date": trade_date,
                "quality_status": q,
                "source_tools": st,
                "lineage_refs": [snap_ref],
            }
            row = {
                "_meta": row_meta,
                "event_id": ev_id,
                "instrument_id": iid,
                "payload": item,
            }
            lines.append(json.dumps(row, ensure_ascii=False))
    with path.open("a", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    return path
