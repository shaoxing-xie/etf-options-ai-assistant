#!/usr/bin/env python3
"""
多范式尾盘选股：四独立候选池 + 综合分 Top5 ∪ 各池第 1 → recommended（source_tags、sector_name）。
配置：config/tail_screening_scoring.yaml；环境 TAIL_SCREENING_DEFAULT_REGIME 可覆盖 default_regime。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.data_layer import MetaEnvelope, append_contract_jsonl, write_contract_json
from src.feature_flags import legacy_write_allowed

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "tail_screening_scoring.yaml"

TOOL_TIMEOUT_STOCK_RANK = int((os.environ.get("TAIL_SCREENING_TIMEOUT_STOCK_RANK_SEC") or "90").strip() or "90")
TOOL_TIMEOUT_STOCK_HISTORY = int((os.environ.get("TAIL_SCREENING_TIMEOUT_STOCK_HISTORY_SEC") or "35").strip() or "35")
TOOL_TIMEOUT_MARKET = int((os.environ.get("TAIL_SCREENING_TIMEOUT_MARKET_SEC") or "35").strip() or "35")
TOOL_TIMEOUT_SECTOR = int((os.environ.get("TAIL_SCREENING_TIMEOUT_SECTOR_SEC") or "45").strip() or "45")
TOOL_TIMEOUT_REALTIME = int((os.environ.get("TAIL_SCREENING_TIMEOUT_REALTIME_SEC") or "25").strip() or "25")
TOOL_TIMEOUT_MINUTE = int((os.environ.get("TAIL_SCREENING_TIMEOUT_STOCK_MINUTE_SEC") or "20").strip() or "20")

PARADIGM_ORDER = ("fund_flow_follow", "tail_grab", "oversold_bounce", "sector_rotation")
_HISTORY_FEATURES_CACHE: dict[str, dict[str, Any]] = {}
DEGRADED_MIN_ENTRY_THRESHOLD = 40
_AK_NAME_MAP_CACHE: dict[str, str] | None = None
_AK_NAME_MAP_READY = False
_AK_NAME_LOOKUP_ENABLED = str(os.environ.get("TAIL_SCREENING_ENABLE_AK_NAME_LOOKUP", "1")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_A_SHARE_NAME_FALLBACK: dict[str, str] = {
    "002001": "新和成",
    "000157": "中联重科",
    "000617": "中油资本",
    "000425": "徐工机械",
    "000983": "山西焦煤",
    "000792": "盐湖股份",
    "000338": "潍柴动力",
    "000568": "泸州老窖",
    "000963": "华东医药",
    "000975": "山金国际",
    "000858": "五粮液",
    "000708": "中信特钢",
    "000895": "双汇发展",
    "000625": "长安汽车",
    "000651": "格力电器",
}


def _pool_row_sort_key(r: dict[str, Any]) -> tuple:
    """§4.2 池内排序：范式分降序 → 成交额降序 → 代码升序。"""
    return (-int(r.get("paradigm_score") or 0), -float(r.get("amount") or 0.0), str(r.get("symbol") or ""))


def _force_top10_pool(rows: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    """Fallback: keep pool non-empty by taking top10 scored candidates."""
    out = [dict(r) for r in rows if isinstance(r, dict)]
    for r in out:
        rs = list(r.get("reasons") or [])
        rs.append(reason)
        r["reasons"] = rs
    out.sort(key=_pool_row_sort_key)
    return out[:10]


def _today_shanghai() -> str:
    try:
        import pytz

        tz = pytz.timezone("Asia/Shanghai")
        return datetime.now(tz).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _run_tool(name: str, args: dict[str, Any], timeout_sec: int = 70) -> dict[str, Any]:
    env = dict(os.environ)
    env.setdefault("FUND_FLOW_ENABLE_EASTMONEY_FALLBACK", "true")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tool_runner.py"), name, json.dumps(args, ensure_ascii=False)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=max(5, int(timeout_sec)),
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or f"tool failed: {name}")
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def _send_feishu_abnormal(title: str, lines: list[str], mode: str = "prod") -> dict[str, Any]:
    message = "\n".join([title] + [f"- {x}" for x in lines if str(x).strip()])
    try:
        return _run_tool(
            "tool_send_feishu_message",
            {
                "title": "尾盘选股异常告警",
                "message": message,
                "mode": mode,
                "cooldown_key": "cron:intraday-tail-screening:abnormal",
                "cooldown_minutes": 10,
            },
            timeout_sec=30,
        )
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"feishu_send_exception: {e}"}


def _run_tool_retry(
    name: str,
    args: dict[str, Any],
    timeout_sec: int,
    retries: int = 1,
    retry_sleep_sec: float = 1.5,
) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for i in range(max(1, retries + 1)):
        try:
            res = _run_tool(name, args, timeout_sec=timeout_sec)
        except Exception as e:
            res = {"success": False, "error_code": "TOOL_CALL_EXCEPTION", "error_message": str(e)}
        last = res
        recs = _tool_records(res) if isinstance(res, dict) else []
        if bool(res.get("success")) and recs:
            return res
        if i < retries:
            time.sleep(retry_sleep_sec)
    return last or {"success": False, "error_code": "RETRY_EMPTY"}


def _tail_data_dir() -> Path:
    d = ROOT / "data" / "tail_screening"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _tool_payload(resp: dict[str, Any]) -> dict[str, Any]:
    data = resp.get("data")
    if isinstance(data, dict):
        return data
    return resp if isinstance(resp, dict) else {}


def _tool_records(resp: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _tool_payload(resp)
    recs = payload.get("records", [])
    if not isinstance(recs, list):
        return []
    return [r for r in recs if isinstance(r, dict)]


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _tool_regime_to_merge_key(raw: str) -> str:
    """tool_detect_market_regime.data.regime → regime_overrides 键。"""
    m = {
        "trending_up": "trend_up",
        "trending_down": "trend_down",
        "range": "oscillation",
        "high_vol_risk": "oscillation",
    }
    return m.get(str(raw).strip(), "oscillation")


def _detect_market_regime_profile(cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    auto 模式：调用 tool_detect_market_regime；失败则 fallback=oscillation。
    返回 (merge_key, meta)。
    """
    rd = cfg.get("regime_detection") if isinstance(cfg.get("regime_detection"), dict) else {}
    sym = str(rd.get("etf_symbol") or "510300")
    mode = str(rd.get("mode") or "production")
    meta: dict[str, Any] = {"notes": [], "fallback": False, "tool_data": {}, "raw_regime": ""}
    try:
        r = _run_tool("tool_detect_market_regime", {"symbol": sym, "mode": mode}, timeout_sec=TOOL_TIMEOUT_MARKET)
    except Exception as e:  # noqa: BLE001
        meta["fallback"] = True
        meta["notes"].append(f"detect_exception:{e}")
        return "oscillation", meta
    if not isinstance(r, dict) or not r.get("success"):
        meta["fallback"] = True
        meta["notes"].append(str(r.get("message") if isinstance(r, dict) else "detect_failed"))
        return "oscillation", meta
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    raw = str(data.get("regime") or "")
    meta["raw_regime"] = raw
    meta["tool_data"] = data
    meta["notes"].append(f"tool_detect_market_regime:{raw}")
    return _tool_regime_to_merge_key(raw), meta


def _sentiment_dispersion_optional() -> tuple[float | None, str]:
    for rel in (
        "data/sentiment/latest.json",
        "data/sentiment_context.json",
        "data/sentiment/sentiment_context.json",
    ):
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(j, dict):
                continue
            v = j.get("sentiment_dispersion")
            if v is not None and v != "":
                return float(v), rel
        except Exception:
            continue
    return None, ""


def _index_consecutive_down_days(index_code: str) -> tuple[int | None, dict[str, Any]]:
    """最近收盘连续下跌日数（含最近一日相对昨收跌）。"""
    trace: dict[str, Any] = {"index_code": index_code}
    try:
        import pytz

        tz = pytz.timezone("Asia/Shanghai")
        end = datetime.now(tz).date()
    except Exception:
        end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=45)
    try:
        ir = _run_tool(
            "tool_fetch_index_data",
            {
                "data_type": "historical",
                "index_code": index_code,
                "start_date": start.strftime("%Y%m%d"),
                "end_date": end.strftime("%Y%m%d"),
                "mode": "production",
            },
            timeout_sec=TOOL_TIMEOUT_MARKET,
        )
    except Exception as e:  # noqa: BLE001
        trace["error"] = str(e)
        return None, trace
    recs = _tool_records(ir) if isinstance(ir, dict) else []
    if len(recs) < 4:
        trace["reason"] = "insufficient_index_bars"
        return None, trace
    closes: list[tuple[str, float]] = []
    for row in recs:
        if not isinstance(row, dict):
            continue
        d = str(_pick_key(row, ["日期", "date", "trade_date"]) or "")
        c = _safe_float(_pick_key(row, ["收盘", "close", "收盘价"]), default=float("nan"))
        if d and c == c:
            closes.append((d, c))
    if len(closes) < 4:
        trace["reason"] = "no_close_series"
        return None, trace
    closes.sort(key=lambda x: x[0])
    vals = [x[1] for x in closes]
    streak = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] < vals[i - 1]:
            streak += 1
        else:
            break
    trace["consecutive_down"] = streak
    return streak, trace


def _evaluate_extra_gates_block(
    extra: dict[str, Any] | None,
    market_proxy_pct: float | None,
    cfg: dict[str, Any],
) -> tuple[bool, str, list[str]]:
    """震荡等 profile 的 extra_gates；任一触发则跳过当日选股。"""
    trace: list[str] = []
    if not isinstance(extra, dict) or not extra:
        return False, "", trace
    sub = extra.get("dispersion_pause_above")
    if isinstance(sub, dict) and sub.get("enabled"):
        lim = float(sub.get("value") or 0.6)
        d, src = _sentiment_dispersion_optional()
        if d is None:
            trace.append("dispersion_pause: skipped_no_source")
        elif d > lim:
            return True, f"sentiment_dispersion {d} > {lim} (source={src})", trace
    sub = extra.get("index_proxy_pause_below_pct")
    if isinstance(sub, dict) and sub.get("enabled") and market_proxy_pct is not None:
        lim = float(sub.get("value") or -1.5)
        if market_proxy_pct <= lim:
            return True, f"market_proxy_pct {market_proxy_pct:.3f} <= {lim}", trace
    sub = extra.get("index_consecutive_down_days")
    if isinstance(sub, dict) and sub.get("enabled"):
        mx = cfg.get("market_proxy") if isinstance(cfg.get("market_proxy"), dict) else {}
        code = str(mx.get("index_proxy_symbol") or "000300")
        need = int(sub.get("days") or 3)
        n, meta = _index_consecutive_down_days(code)
        trace.append(f"index_consecutive_down:{meta}")
        if n is not None and n >= need:
            return True, f"{code} consecutive_down_days {n} >= {need}", trace
    return False, "", trace


def _load_scoring_config() -> dict[str, Any]:
    if yaml is None or not CONFIG_PATH.is_file():
        return {
            "version": "embedded_fallback",
            "default_regime": "oscillation",
            "hard_gates": {
                "min_days_listed": 60,
                "min_amount_cny": 50_000_000,
                "exclude_st": True,
                "near_limit_abs_pct": 9.5,
            },
            "market_proxy": {"index_proxy_symbol": "000300"},
            "regime_detection": {"etf_symbol": "510300", "mode": "production"},
            "tail_grab": {
                "max_symbols": 30,
                "timeout_per_symbol_sec": 2,
                "total_timeout_sec": 60,
                "on_budget_exhausted": "skip_paradigm",
                "max_failure_ratio": 0.6,
            },
            "paradigms": {
                "fund_flow_follow": {"entry_threshold": 72},
                "tail_grab": {"entry_threshold": 72},
                "oversold_bounce": {"entry_threshold": 65},
                "sector_rotation": {"entry_threshold": 63, "rs_min_threshold_pct": 0.5, "sector_rank_limit": 60},
            },
            "confluence": {"bonus_per_paradigm": 4, "max_bonus": 12},
            "regime_overrides": {
                "neutral": {},
                "trend_up": {},
                "trend_down": {},
                "oscillation": {
                    "paradigms": {
                        "fund_flow_follow": {"entry_threshold": 68, "weight_multiplier": 0.8},
                        "tail_grab": {"entry_threshold": 70, "weight_multiplier": 0.9},
                        "oversold_bounce": {"entry_threshold": 60, "weight_multiplier": 1.2},
                        "sector_rotation": {"entry_threshold": 60, "weight_multiplier": 1.0, "rs_min_threshold_pct": 0.3},
                    },
                    "confluence": {"bonus_per_paradigm": 3, "max_bonus": 9},
                    "composite_caps": {"fund_flow_follow_max_in_top5": 2, "tail_grab_max_in_top5": 2},
                    "extra_gates": {
                        "dispersion_pause_above": {"enabled": False, "value": 0.6},
                        "index_proxy_pause_below_pct": {"enabled": False, "value": -1.5},
                        "index_consecutive_down_days": {"enabled": False, "days": 3},
                    },
                },
            },
        }
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _resolve_effective_params(
    cfg: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    返回 (applied_profile, eff, cfg, regime_meta)。
    regime_meta：market_regime、regime_detection_notes、default_regime_requested 等。
    """
    env_regime = (os.environ.get("TAIL_SCREENING_DEFAULT_REGIME") or "").strip().lower()
    requested = env_regime or str(cfg.get("default_regime") or "oscillation").strip().lower()
    ro = cfg.get("regime_overrides") if isinstance(cfg.get("regime_overrides"), dict) else {}
    base_paradigms = cfg.get("paradigms") if isinstance(cfg.get("paradigms"), dict) else {}
    base_conf = cfg.get("confluence") if isinstance(cfg.get("confluence"), dict) else {}
    notes: list[str] = []
    tool_det: dict[str, Any] = {}

    if requested == "auto":
        merge_key, det = _detect_market_regime_profile(cfg)
        notes.extend(list(det.get("notes") or []))
        tool_det = det.get("tool_data") if isinstance(det.get("tool_data"), dict) else {}
        if det.get("fallback"):
            merge_key = "oscillation"
            notes.append("auto: detection failed -> merge_key=oscillation (产品默认)")
            market_regime = "oscillation"
        else:
            raw_lbl = str(det.get("raw_regime") or merge_key)
            market_regime = raw_lbl
        semantic_merge = merge_key
    else:
        merge_key = requested
        market_regime = f"{requested} (static)"
        semantic_merge = merge_key

    if merge_key not in ro:
        notes.append(f"regime_overrides missing '{merge_key}'; merged base paradigms (neutral)")
        applied_profile = "neutral"
        block: dict[str, Any] = {}
    else:
        applied_profile = merge_key
        block = ro.get(merge_key) if isinstance(ro.get(merge_key), dict) else {}

    merged_p = _deep_merge_dict(base_paradigms, block.get("paradigms") or {})
    merged_c = _deep_merge_dict(base_conf, block.get("confluence") or {})
    caps = block.get("composite_caps") if isinstance(block.get("composite_caps"), dict) else {}
    extra_gates = block.get("extra_gates") if isinstance(block.get("extra_gates"), dict) else {}

    eff = {
        "paradigms": merged_p,
        "confluence": merged_c,
        "composite_caps": caps,
        "extra_gates": extra_gates,
        "hard_gates": cfg.get("hard_gates") if isinstance(cfg.get("hard_gates"), dict) else {},
        "tail_grab": cfg.get("tail_grab") if isinstance(cfg.get("tail_grab"), dict) else {},
    }
    regime_meta = {
        "market_regime": market_regime,
        "regime_detection_notes": notes,
        "default_regime_requested": requested,
        "semantic_merge_key": semantic_merge if requested == "auto" else merge_key,
        "regime_tool_features": tool_det.get("features") if tool_det else {},
        "applied_profile": applied_profile,
    }
    return applied_profile, eff, cfg, regime_meta


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if s.endswith("%"):
                return float(s[:-1])
            if s.endswith("亿"):
                return float(s[:-1]) * 1e8
            if s.endswith("万"):
                return float(s[:-1]) * 1e4
            return float(s)
        return float(v)
    except Exception:
        return default


def _pick_key(row: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _extract_code_name(row: dict[str, Any]) -> tuple[str, str]:
    code = str(_pick_key(row, ["代码", "股票代码", "symbol", "证券代码", "stock_code"]) or "").strip()
    name = str(_pick_key(row, ["名称", "股票简称", "name", "证券简称"]) or "").strip()
    return code, name


def _looks_like_code(value: Any) -> bool:
    s = str(value or "").strip()
    return bool(s) and len(s) == 6 and s.isdigit()


def _ak_name_map() -> dict[str, str]:
    if not _AK_NAME_LOOKUP_ENABLED:
        return {}
    global _AK_NAME_MAP_CACHE, _AK_NAME_MAP_READY
    if _AK_NAME_MAP_READY:
        return dict(_AK_NAME_MAP_CACHE or {})
    _AK_NAME_MAP_READY = True
    try:
        import akshare as ak  # type: ignore

        df = ak.stock_info_a_code_name()
        cmap: dict[str, str] = {}
        if hasattr(df, "iterrows"):
            for _, row in df.iterrows():
                code = str(row.get("code") or row.get("证券代码") or row.get("股票代码") or "").strip()
                name = str(row.get("name") or row.get("证券简称") or row.get("股票简称") or "").strip()
                if len(code) == 6 and code.isdigit() and name and not _looks_like_code(name):
                    cmap[code] = name
        _AK_NAME_MAP_CACHE = cmap
    except Exception:
        _AK_NAME_MAP_CACHE = {}
    return dict(_AK_NAME_MAP_CACHE or {})


def _ak_name_by_code(code: str) -> str:
    if not _AK_NAME_LOOKUP_ENABLED:
        return ""
    cmap = _ak_name_map()
    n = str(cmap.get(code) or "").strip()
    if n and not _looks_like_code(n):
        return n
    return ""


def _resolve_stock_name(code: str, rt: dict[str, Any] | None = None, hist: dict[str, Any] | None = None) -> str:
    if isinstance(rt, dict):
        n = _pick_key(rt, ["name", "股票简称", "名称", "sec_name", "证券简称", "stock_name", "display_name"])
        if n is not None and str(n).strip() and not _looks_like_code(n):
            return str(n).strip()
    if isinstance(hist, dict):
        n = _pick_key(hist, ["name", "股票简称", "名称", "sec_name", "证券简称", "stock_name", "display_name"])
        if n is not None and str(n).strip() and not _looks_like_code(n):
            return str(n).strip()
        last = hist.get("raw_last")
        if isinstance(last, dict):
            n = _pick_key(last, ["name", "股票简称", "名称", "sec_name", "证券简称", "stock_name", "display_name"])
            if n is not None and str(n).strip() and not _looks_like_code(n):
                return str(n).strip()
    ak_name = _ak_name_by_code(code)
    if ak_name:
        return ak_name
    return _A_SHARE_NAME_FALLBACK.get(code, code)


def _extract_net_inflow(row: dict[str, Any]) -> float:
    return _safe_float(
        _pick_key(
            row,
            [
                "今日主力净流入-净额",
                "主力净流入-净额",
                "净额",
                "主力净流入",
                "净流入",
            ],
        )
    )


def _sector_name_from_row(row: dict[str, Any]) -> str:
    return str(_pick_key(row, ["所属行业", "行业", "industry", "行业名称"]) or "").strip()


def _history_features(code: str) -> dict[str, Any]:
    cached = _HISTORY_FEATURES_CACHE.get(code)
    if isinstance(cached, dict):
        return dict(cached)

    def _fallback_from_realtime(reason: str) -> dict[str, Any]:
        rt = _fetch_realtime_one(code) or {}
        if not rt:
            # hard degraded fallback: keep pipeline alive when both history/realtime are unavailable
            return {
                "ok": True,
                "degraded": True,
                "degrade_reason": f"{reason}:no_realtime",
                "pct_change": 0.0,
                "close": 1.0,
                "ma5_distance": 0.0,
                "volume_ratio": 1.0,
                "amount": 60_000_000.0,
                "listed_days": 120,
                "ret_5d": 0.0,
                "raw_last": {},
            }
        pct = _safe_float(_pick_key(rt, ["change_percent", "涨跌幅", "pct_change"]), default=0.0)
        amount = _safe_float(_pick_key(rt, ["amount", "成交额"]), default=0.0)
        vol_ratio = _safe_float(_pick_key(rt, ["volume_ratio", "量比"]), default=1.3)
        if vol_ratio <= 0:
            vol_ratio = 1.3
        listed_days = int(_safe_float(_pick_key(rt, ["list_days", "上市天数"]), default=120))
        close = _safe_float(_pick_key(rt, ["price", "last_price", "最新价"]), default=0.0)
        return {
            "ok": True,
            "degraded": True,
            "degrade_reason": reason,
            "pct_change": pct,
            "close": close,
            "ma5_distance": 0.0,
            "volume_ratio": vol_ratio,
            "amount": amount,
            "listed_days": listed_days,
            "ret_5d": 0.0,
            "raw_last": rt,
        }

    try:
        hist = _run_tool(
            "tool_fetch_a_share_fund_flow",
            {"query_kind": "stock_history", "stock_code": code, "lookback_days": 8},
            timeout_sec=TOOL_TIMEOUT_STOCK_HISTORY,
        )
    except Exception:
        res = _fallback_from_realtime("stock_history_timeout")
        _HISTORY_FEATURES_CACHE[code] = dict(res)
        return res
    payload = hist.get("data", {}) if isinstance(hist, dict) else {}
    recs = payload.get("records", []) if isinstance(payload, dict) else []
    if (not recs) and isinstance(hist, dict):
        # tool_fetch_a_share_fund_flow(stock_history) may return records at top-level.
        top_recs = hist.get("records")
        if isinstance(top_recs, list):
            recs = top_recs
    recs = [r for r in recs if isinstance(r, dict)]
    if not recs:
        res = _fallback_from_realtime("empty_history")
        _HISTORY_FEATURES_CACHE[code] = dict(res)
        return res

    last = recs[-1]
    closes: list[float] = []
    vols: list[float] = []
    for r in recs:
        c = _safe_float(_pick_key(r, ["收盘价", "close", "最新价"]), default=float("nan"))
        v = _safe_float(_pick_key(r, ["成交量", "volume"]), default=float("nan"))
        if c == c:
            closes.append(c)
        if v == v and v > 0:
            vols.append(v)

    pct = _safe_float(_pick_key(last, ["涨跌幅", "pct_change"]), default=999.0)
    close = closes[-1] if closes else 0.0
    ma5 = sum(closes[-5:]) / min(5, len(closes)) if closes else 0.0
    ma5_distance = ((close - ma5) / ma5 * 100.0) if ma5 else 0.0
    volume_ratio = 1.0
    if len(vols) >= 6:
        base = sum(vols[-6:-1]) / 5.0
        if base > 0:
            volume_ratio = vols[-1] / base
    amount = _safe_float(_pick_key(last, ["成交额", "amount"]), default=0.0)
    if not closes and pct == 999.0 and amount <= 0:
        # stock_history may resolve to moneyflow-style rows without OHLCV fields.
        res = _fallback_from_realtime("history_schema_no_ohlcv")
        _HISTORY_FEATURES_CACHE[code] = dict(res)
        return res
    listed_days = int(_safe_float(_pick_key(last, ["上市天数", "list_days"]), default=120))
    ret_5d = 0.0
    if len(closes) >= 6 and closes[-6] > 0:
        ret_5d = (closes[-1] / closes[-6] - 1.0) * 100.0
    res = {
        "ok": True,
        "pct_change": pct,
        "close": close,
        "ma5_distance": ma5_distance,
        "volume_ratio": volume_ratio,
        "amount": amount,
        "listed_days": listed_days,
        "ret_5d": ret_5d,
        "raw_last": last,
    }
    _HISTORY_FEATURES_CACHE[code] = dict(res)
    return res


def _sector_strength_full(limit: int) -> tuple[dict[str, float], dict[str, Any]]:
    trace: dict[str, Any] = {"ok": False}
    try:
        sector = _run_tool(
            "tool_fetch_a_share_fund_flow",
            {"query_kind": "sector_rank", "sector_type": "industry", "rank_window": "immediate", "limit": limit},
            timeout_sec=TOOL_TIMEOUT_SECTOR,
        )
    except Exception as e:
        return {}, {"ok": False, "error": str(e)}
    recs = _tool_records(sector)
    out: dict[str, float] = {}
    for r in recs:
        name = str(_pick_key(r, ["名称", "行业名称", "板块名称", "name"]) or "").strip()
        change = _safe_float(_pick_key(r, ["涨跌幅", "涨跌幅%", "涨幅"]))
        if name:
            out[name] = change
    trace = {"ok": bool(out), "count": len(out), "success": sector.get("success")}
    return out, trace


def _industry_top_third_threshold(pcts: list[float]) -> float:
    if not pcts:
        return 999.0
    s = sorted(pcts)
    idx = max(0, int(math.ceil(len(s) * (2 / 3))) - 1)
    return s[idx]


def _market_proxy_day_pct(cfg: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    mx = cfg.get("market_proxy") if isinstance(cfg.get("market_proxy"), dict) else {}
    index_code = str(mx.get("index_proxy_symbol") or "000300")
    meta: dict[str, Any] = {"chain": [], "index_proxy_symbol": index_code}
    try:
        mk = _run_tool(
            "tool_fetch_a_share_fund_flow",
            {"query_kind": "market_history", "max_days": 5},
            timeout_sec=TOOL_TIMEOUT_MARKET,
        )
    except Exception as e:
        meta["error"] = str(e)
        mk = {}
    payload = _tool_payload(mk) if isinstance(mk, dict) else {}
    meta["chain"].append("market_history")
    recs = payload.get("records", [])
    if isinstance(recs, list) and recs:
        last = recs[-1] if isinstance(recs[-1], dict) else {}
        for k in ("涨跌幅", "pct_change", "涨跌", "全市场涨跌幅"):
            if k in last and last[k] is not None:
                v = _safe_float(last[k])
                meta["field"] = k
                return v, meta
    try:
        ir = _run_tool(
            "tool_fetch_index_data",
            {"data_type": "realtime", "index_code": index_code, "mode": "production"},
            timeout_sec=TOOL_TIMEOUT_MARKET,
        )
        meta["chain"].append(f"index_realtime_{index_code}")
        if isinstance(ir, dict) and ir.get("success"):
            data = ir.get("data")
            if isinstance(data, dict):
                for k in ("change_percent", "涨跌幅", "pct_chg"):
                    if k in data:
                        return _safe_float(data[k]), meta
    except Exception as e:
        meta["index_error"] = str(e)
    return None, meta


def _resolve_rank_rows(max_candidates: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diagnostics: dict[str, Any] = {"candidate_source": "stock_rank", "main_source_ok": False}
    try:
        stock_rank = _run_tool_retry(
            "tool_fetch_a_share_fund_flow",
            {"query_kind": "stock_rank", "rank_window": "immediate", "limit": max_candidates},
            timeout_sec=TOOL_TIMEOUT_STOCK_RANK,
            retries=1,
        )
    except Exception as e:
        stock_rank = {"success": False, "error_code": "STOCK_RANK_TIMEOUT", "error_message": str(e)}
    payload = _tool_payload(stock_rank)
    rows = _tool_records(stock_rank)
    diagnostics["stock_rank"] = {
        "success": bool(stock_rank.get("success")),
        "count": len(rows),
        "source": payload.get("source"),
        "error_code": stock_rank.get("error_code"),
        "error_message": stock_rank.get("error_message"),
    }
    if rows:
        diagnostics["main_source_ok"] = True
        return rows[:max_candidates], diagnostics
    # Fallback candidate source: realtime universe proxy.
    wl = _load_watchlist_symbols(max(max_candidates * 2, 80))
    rt_map = _fetch_realtime_many(wl)
    proxy_rows: list[dict[str, Any]] = []
    for code in wl:
        rt = rt_map.get(code) or {}
        if not rt:
            continue
        pct = _safe_float(_pick_key(rt, ["change_percent", "涨跌幅", "pct_change"]), default=0.0)
        amount = _safe_float(_pick_key(rt, ["amount", "成交额"]), default=0.0)
        name = _resolve_stock_name(code, rt=rt)
        sector = str(_pick_key(rt, ["industry", "所属行业", "行业"]) or "").strip()
        proxy_rows.append(
            {
                "代码": code,
                "名称": name,
                "所属行业": sector,
                "涨跌幅": pct,
                "成交额": amount,
                # proxy net inflow for ranking only
                "今日主力净流入-净额": amount * pct / 100.0,
            }
        )
    proxy_rows.sort(key=lambda r: (-_safe_float(r.get("成交额"), 0.0), str(r.get("代码") or "")))
    if proxy_rows:
        diagnostics["candidate_source"] = "realtime_proxy"
        diagnostics["fallback_used"] = True
        diagnostics["realtime_proxy"] = {"success": True, "count": len(proxy_rows)}
        return proxy_rows[:max_candidates], diagnostics
    if wl:
        weak_rows = [
            {
                "代码": code,
                "名称": code,
                "所属行业": "",
                "涨跌幅": 0.0,
                "成交额": 60_000_000.0,
                "今日主力净流入-净额": 10_000.0,
            }
            for code in wl[:max_candidates]
        ]
        diagnostics["candidate_source"] = "watchlist_weak_proxy"
        diagnostics["fallback_used"] = True
        diagnostics["watchlist_weak_proxy"] = {"success": True, "count": len(weak_rows)}
        return weak_rows, diagnostics
    return [], diagnostics


def _code_industry_map(rank_rows: list[dict[str, Any]]) -> dict[str, str]:
    m: dict[str, str] = {}
    for row in rank_rows:
        c, _ = _extract_code_name(row)
        if len(c) == 6 and c.isdigit():
            ind = _sector_name_from_row(row)
            if ind:
                m[c] = ind
    return m


def _load_watchlist_symbols(limit: int) -> list[str]:
    wl = _read_json(ROOT / "data" / "watchlist" / "default.json") or {}
    syms = wl.get("symbols", []) if isinstance(wl, dict) else []
    out: list[str] = []
    for s in syms:
        code = str(s or "").strip()
        if len(code) == 6 and code.isdigit():
            out.append(code)
        if len(out) >= limit:
            break
    return out


def _is_st_name(name: str) -> bool:
    n = (name or "").strip().upper()
    if not n:
        return False
    if n.startswith("*ST") or "*ST" in n:
        return True
    if n.startswith("ST"):
        return True
    return False


def _hard_gate_ok(
    *,
    name: str,
    listed_days: int,
    amount: float,
    pct_chg: float,
    gates: dict[str, Any],
) -> bool:
    if gates.get("exclude_st", True) and _is_st_name(name):
        return False
    if listed_days < int(gates.get("min_days_listed") or 60):
        return False
    if amount < float(gates.get("min_amount_cny") or 50_000_000):
        return False
    lim = float(gates.get("near_limit_abs_pct") or 9.5)
    if abs(pct_chg) >= lim:
        return False
    return True


def _score_fund_flow_pillars(net_inflow: float, pct: float, vol_ratio: float) -> tuple[int, dict[str, int]]:
    # 40 / 30 / 30
    p1 = 0
    if net_inflow >= 2e8:
        p1 = 40
    elif net_inflow >= 1e8:
        p1 = 32
    elif net_inflow >= 5e7:
        p1 = 24
    elif net_inflow > 0:
        p1 = 12
    p2 = 0
    if -3.0 <= pct <= 0:
        p2 = 30
    elif -4.0 < pct < -3.0:
        p2 = 20
    elif -5.0 <= pct <= -4.0:
        p2 = 10
    p3 = 0
    if vol_ratio >= 1.8:
        p3 = 30
    elif vol_ratio >= 1.5:
        p3 = 24
    elif vol_ratio >= 1.2:
        p3 = 15
    br = {"inflow": p1, "pct": p2, "vol": p3}
    return p1 + p2 + p3, br


def _score_tail_grab(last30_pct: float, vol_ratio: float, ma5_dist: float) -> tuple[int, dict[str, int]]:
    p1 = 0
    if last30_pct >= 2.0:
        p1 = 40
    elif last30_pct >= 1.0:
        p1 = 32
    elif last30_pct >= 0.5:
        p1 = 20
    p2 = 0
    if vol_ratio >= 2.0:
        p2 = 30
    elif vol_ratio >= 1.5:
        p2 = 24
    elif vol_ratio >= 1.2:
        p2 = 15
    p3 = 0
    if ma5_dist > 0 and ma5_dist <= 3.0:
        p3 = 30
    elif ma5_dist > 3.0:
        p3 = 22
    elif abs(ma5_dist) <= 0.5:
        p3 = 15
    br = {"last30": p1, "vol": p2, "ma5": p3}
    return p1 + p2 + p3, br


def _score_oversold(pct: float, vol_ratio: float, amount: float) -> tuple[int, dict[str, int]]:
    p1 = 0
    if -4.0 <= pct <= -2.0:
        p1 = 50
    elif -5.0 <= pct < -4.0:
        p1 = 38
    elif -5.5 < pct <= -5.0:
        p1 = 22
    p2 = 0
    if vol_ratio >= 1.5:
        p2 = 30
    elif vol_ratio >= 1.2:
        p2 = 22
    elif vol_ratio >= 1.0:
        p2 = 12
    p3 = 0
    if amount >= 2e8:
        p3 = 20
    elif amount >= 1e8:
        p3 = 16
    elif amount >= 5e7:
        p3 = 10
    br = {"dip": p1, "vol": p2, "amt": p3}
    return p1 + p2 + p3, br


def _score_sector_rotation(
    industry_pct: float,
    rs_extra: float | None,
    in_watchlist: bool,
    industry_in_top_third: bool,
    ret_5d: float,
    rs_min: float,
) -> tuple[int, dict[str, int]]:
    ind_m = 0
    if industry_pct >= 2.0:
        ind_m = 18
    elif industry_pct >= 1.0:
        ind_m = 14
    elif industry_pct >= 0.5:
        ind_m = 10
    elif industry_pct >= 0:
        ind_m = 6
    rs_pts = 0
    if rs_extra is not None and rs_extra >= rs_min:
        if rs_extra >= 0.5:
            rs_pts = 15
        elif rs_extra >= 0:
            rs_pts = 10
    elif rs_extra is not None and rs_extra >= -0.5:
        rs_pts = 5
    pillar_a = min(45, ind_m + rs_pts)
    p_b = 0
    if in_watchlist and industry_in_top_third:
        p_b = 35
    elif in_watchlist:
        p_b = 22
    elif industry_in_top_third:
        p_b = 12
    p_c = 0
    if ret_5d >= 2.0:
        p_c = 20
    elif ret_5d >= 1.0:
        p_c = 15
    elif ret_5d >= 0:
        p_c = 10
    elif ret_5d >= -1.0:
        p_c = 5
    br = {"mom_rs": pillar_a, "pool_q": p_b, "ret5d": p_c}
    return pillar_a + p_b + p_c, br


def _apply_multiplier(raw: int, mult: float) -> int:
    return int(min(100, max(0, round(raw * float(mult)))))


def _fetch_realtime_one(code: str) -> dict[str, Any] | None:
    try:
        r = _run_tool(
            "tool_fetch_stock_realtime",
            {"stock_code": code, "mode": "production"},
            timeout_sec=TOOL_TIMEOUT_REALTIME,
        )
    except Exception:
        return None
    if not r.get("success"):
        return None
    d = r.get("data")
    if isinstance(d, list) and d:
        return d[0] if isinstance(d[0], dict) else None
    if isinstance(d, dict):
        return d
    return None


def _fetch_realtime_many(codes: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    chunk = 40
    for i in range(0, len(codes), chunk):
        part = codes[i : i + chunk]
        try:
            r = _run_tool(
                "tool_fetch_stock_realtime",
                {"stock_code": ",".join(part), "mode": "production"},
                timeout_sec=TOOL_TIMEOUT_REALTIME + 10,
            )
        except Exception:
            continue
        if not r.get("success"):
            continue
        d = r.get("data")
        rows: list[dict[str, Any]] = []
        if isinstance(d, list):
            rows = [x for x in d if isinstance(x, dict)]
        elif isinstance(d, dict):
            rows = [d]
        for row in rows:
            c = str(row.get("stock_code") or "").strip()
            if len(c) == 6 and c.isdigit():
                out[c] = row
    return out


def _last_30m_return_pct(klines: list[dict[str, Any]]) -> float | None:
    if len(klines) < 2:
        return None
    tail = klines[-30:] if len(klines) >= 30 else klines
    if len(tail) < 2:
        return None
    o0 = _safe_float(tail[0].get("open"))
    c1 = _safe_float(tail[-1].get("close"))
    if o0 <= 0 or c1 <= 0:
        o0 = _safe_float(tail[0].get("close"))
    if o0 <= 0:
        return None
    return (c1 / o0 - 1.0) * 100.0


def _proxy_last30_from_realtime(pct_change: float) -> float:
    # Degraded proxy: intraday tail momentum as fraction of day change.
    return max(-3.0, min(3.0, pct_change * 0.25))


def _run_pool_fund_flow(
    rank_rows: list[dict[str, Any]],
    sector_strength: dict[str, float],
    eff: dict[str, Any],
    gates: dict[str, Any],
    candidate_source: str = "stock_rank",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trace: dict[str, Any] = {
        "status": "ok",
        "count": 0,
        "degraded_history": 0,
        "candidate_fetch_fail_count": 0,
        "scoring_reject_count": 0,
        "fallback_hit_count": 0,
        "hard_gate_reject_count": 0,
    }
    pconf = eff["paradigms"].get("fund_flow_follow", {}) if isinstance(eff["paradigms"], dict) else {}
    thr = int(pconf.get("entry_threshold") or 72)
    mult = float(pconf.get("weight_multiplier") or 1.0)
    pool: list[dict[str, Any]] = []
    candidates_scored: list[dict[str, Any]] = []
    for row in rank_rows:
        code, name = _extract_code_name(row)
        if len(code) != 6 or not code.isdigit():
            continue
        hist = _history_features(code)
        if not hist.get("ok"):
            trace["candidate_fetch_fail_count"] = int(trace.get("candidate_fetch_fail_count") or 0) + 1
            continue
        if hist.get("degraded"):
            trace["degraded_history"] = int(trace.get("degraded_history") or 0) + 1
            trace["fallback_hit_count"] = int(trace.get("fallback_hit_count") or 0) + 1
        pct = _safe_float(hist.get("pct_change"), 999.0)
        vol_ratio = _safe_float(hist.get("volume_ratio"), 0.0)
        ma5_dist = _safe_float(hist.get("ma5_distance"), 99.0)
        amount = _safe_float(hist.get("amount"), 0.0)
        listed_days = int(_safe_float(hist.get("listed_days"), 0))
        net_inflow = _extract_net_inflow(row)
        proxy_flow_used = False
        sector_name = _sector_name_from_row(row)
        nm = name or code
        if not _hard_gate_ok(name=nm, listed_days=listed_days, amount=amount, pct_chg=pct, gates=gates):
            trace["hard_gate_reject_count"] = int(trace.get("hard_gate_reject_count") or 0) + 1
            continue
        if net_inflow <= 0:
            # Realtime proxy rows don't carry true main-force net inflow.
            # Use a tiny positive proxy so the paradigm can still compete in degraded mode.
            if candidate_source == "realtime_proxy":
                net_inflow = max(amount * 0.00005, 1.0)
                proxy_flow_used = True
                trace["fallback_hit_count"] = int(trace.get("fallback_hit_count") or 0) + 1
            else:
                continue
        raw, br = _score_fund_flow_pillars(net_inflow, pct, vol_ratio)
        adj = _apply_multiplier(raw, mult)
        eff_thr = thr - 8 if hist.get("degraded") else thr
        if candidate_source == "realtime_proxy":
            eff_thr -= 6
        if hist.get("degraded"):
            eff_thr = max(DEGRADED_MIN_ENTRY_THRESHOLD, eff_thr)
        candidates_scored.append(
            {
                "symbol": code,
                "name": nm,
                "sector_name": sector_name,
                "paradigm": "fund_flow_follow",
                "paradigm_score": adj,
                "raw_paradigm_score": raw,
                "factor_breakdown": {"pillars": br, "weight_multiplier": mult},
                "pct_change": pct,
                "volume_ratio": vol_ratio,
                "ma5_distance": ma5_dist,
                "amount": amount,
                "net_inflow": net_inflow,
                "reasons": ["pre_threshold_candidate"],
                "position_suggestion": "轻仓(2-3%)",
                "stop_loss": "-3%",
            }
        )
        if adj < eff_thr:
            trace["scoring_reject_count"] = int(trace.get("scoring_reject_count") or 0) + 1
            continue
        reasons = [
            f"资金流范式{adj}分",
            f"净流入{net_inflow/1e8:.2f}亿",
            f"跌{pct:.2f}%量比{vol_ratio:.2f}",
        ]
        if hist.get("degraded"):
            reasons.append("history_degraded:realtime_proxy")
        if proxy_flow_used:
            reasons.append("flow_proxy_from_realtime_candidate")
        row_obj = {
            "symbol": code,
            "name": nm,
            "sector_name": sector_name,
            "paradigm": "fund_flow_follow",
            "paradigm_score": adj,
            "raw_paradigm_score": raw,
            "factor_breakdown": {"pillars": br, "weight_multiplier": mult},
            "pct_change": pct,
            "volume_ratio": vol_ratio,
            "ma5_distance": ma5_dist,
            "amount": amount,
            "net_inflow": net_inflow,
            "reasons": reasons,
            "position_suggestion": "轻仓(2-3%)",
            "stop_loss": "-3%",
        }
        pool.append(row_obj)
    pool.sort(key=_pool_row_sort_key)
    if not pool and candidates_scored:
        pool = _force_top10_pool(candidates_scored, "forced_top10_from_scored_candidates")
        trace["status"] = "degraded"
        trace["forced_top10"] = True
    trace["count"] = len(pool)
    return pool[:10], trace


def _run_pool_tail_grab(
    watchlist: list[str],
    eff: dict[str, Any],
    gates: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tg = eff.get("tail_grab") or {}
    max_sym = int(tg.get("max_symbols") or 30)
    per_sym_t = float(tg.get("timeout_per_symbol_sec") or 2)
    total_t = float(tg.get("total_timeout_sec") or 60)
    allow_proxy = bool(tg.get("allow_proxy_when_no_last30m", True))
    symbols = watchlist[:max_sym]
    trace: dict[str, Any] = {
        "status": "ok",
        "count": 0,
        "errors": [],
        "symbol_attempts": 0,
        "symbol_failures": 0,
        "degraded_history": 0,
        "scoring_reject_count": 0,
        "fallback_hit_count": 0,
        "hard_gate_reject_count": 0,
    }
    max_fail_ratio = float(tg.get("max_failure_ratio") or 0.6)
    pconf = eff["paradigms"].get("tail_grab", {}) if isinstance(eff["paradigms"], dict) else {}
    thr = int(pconf.get("entry_threshold") or 72)
    mult = float(pconf.get("weight_multiplier") or 1.0)
    pool: list[dict[str, Any]] = []
    candidates_scored: list[dict[str, Any]] = []
    t0 = time.monotonic()
    hard_fail = False
    for code in symbols:
        if time.monotonic() - t0 > total_t:
            hard_fail = True
            trace["errors"].append("total_timeout_sec_exceeded")
            break
        trace["symbol_attempts"] = int(trace.get("symbol_attempts") or 0) + 1
        try:
            mr = _run_tool(
                "tool_fetch_stock_minute",
                {
                    "stock_code": code,
                    "period": "1",
                    "lookback_days": 1,
                    "mode": "production",
                },
                timeout_sec=int(per_sym_t) + TOOL_TIMEOUT_MINUTE,
            )
        except Exception as e:
            trace["errors"].append(f"{code}:{e}")
            trace["symbol_failures"] = int(trace.get("symbol_failures") or 0) + 1
            continue
        if not mr.get("success"):
            trace["errors"].append(f"{code}:minute_fail")
            trace["symbol_failures"] = int(trace.get("symbol_failures") or 0) + 1
            continue
        data = mr.get("data")
        klines: list[dict[str, Any]] = []
        if isinstance(data, dict) and isinstance(data.get("klines"), list):
            klines = [x for x in data["klines"] if isinstance(x, dict)]
        last30 = _last_30m_return_pct(klines)
        hist = _history_features(code)
        if not hist.get("ok"):
            trace["errors"].append(f"{code}:history_fail")
            trace["symbol_failures"] = int(trace.get("symbol_failures") or 0) + 1
            continue
        if hist.get("degraded"):
            trace["degraded_history"] = int(trace.get("degraded_history") or 0) + 1
            trace["fallback_hit_count"] = int(trace.get("fallback_hit_count") or 0) + 1
        vol_ratio = _safe_float(hist.get("volume_ratio"), 0.0)
        ma5_dist = _safe_float(hist.get("ma5_distance"), 99.0)
        pct = _safe_float(hist.get("pct_change"), 999.0)
        amount = _safe_float(hist.get("amount"), 0.0)
        listed_days = int(_safe_float(hist.get("listed_days"), 0))
        rt = _fetch_realtime_one(code) or {}
        nm = _resolve_stock_name(code, rt=rt, hist=hist)
        used_proxy = False
        if last30 is None:
            if allow_proxy:
                last30 = _proxy_last30_from_realtime(pct)
                trace["errors"].append(f"{code}:no_last30m_bar_use_proxy")
                used_proxy = True
                trace["fallback_hit_count"] = int(trace.get("fallback_hit_count") or 0) + 1
            else:
                trace["errors"].append(f"{code}:no_last30m_bar")
                trace["symbol_failures"] = int(trace.get("symbol_failures") or 0) + 1
                continue
        if not _hard_gate_ok(name=nm, listed_days=listed_days, amount=amount, pct_chg=pct, gates=gates):
            trace["hard_gate_reject_count"] = int(trace.get("hard_gate_reject_count") or 0) + 1
            continue
        raw, br = _score_tail_grab(last30, vol_ratio, ma5_dist)
        adj = _apply_multiplier(raw, mult)
        eff_thr = thr - (8 if used_proxy or hist.get("degraded") else 0)
        if used_proxy or hist.get("degraded"):
            eff_thr = max(DEGRADED_MIN_ENTRY_THRESHOLD, eff_thr)
        candidates_scored.append(
            {
                "symbol": code,
                "name": nm,
                "sector_name": "",
                "paradigm": "tail_grab",
                "paradigm_score": adj,
                "raw_paradigm_score": raw,
                "factor_breakdown": {"pillars": br, "last_30m_pct": last30, "weight_multiplier": mult},
                "pct_change": pct,
                "volume_ratio": vol_ratio,
                "ma5_distance": ma5_dist,
                "amount": amount,
                "reasons": ["pre_threshold_candidate"],
                "position_suggestion": "轻仓(2-3%)",
                "stop_loss": "-3%",
            }
        )
        if adj < eff_thr:
            trace["scoring_reject_count"] = int(trace.get("scoring_reject_count") or 0) + 1
            continue
        row_obj = {
            "symbol": code,
            "name": nm,
            "sector_name": "",
            "paradigm": "tail_grab",
            "paradigm_score": adj,
            "raw_paradigm_score": raw,
            "factor_breakdown": {"pillars": br, "last_30m_pct": last30, "weight_multiplier": mult},
            "pct_change": pct,
            "volume_ratio": vol_ratio,
            "ma5_distance": ma5_dist,
            "amount": amount,
            "reasons": [f"尾盘抢筹{adj}分", f"近30分{last30:.2f}%", f"量比{vol_ratio:.2f}"],
            "position_suggestion": "轻仓(2-3%)",
            "stop_loss": "-3%",
        }
        pool.append(row_obj)
        if used_proxy:
            pool[-1]["reasons"].append("last30m_proxy_from_realtime")
        if hist.get("degraded"):
            pool[-1]["reasons"].append("history_degraded:realtime_proxy")
    if hard_fail:
        return [], {**trace, "status": "error", "count": 0}
    att = int(trace.get("symbol_attempts") or 0)
    fail_n = int(trace.get("symbol_failures") or 0)
    if (
        not hard_fail
        and att > 0
        and max_fail_ratio < 1.0
        and (fail_n / float(att)) > max_fail_ratio
    ):
        return [], {
            **trace,
            "status": "error",
            "count": 0,
            "errors": list(trace.get("errors") or []) + ["failure_ratio_exceeded"],
        }
    pool.sort(key=_pool_row_sort_key)
    if not pool and candidates_scored:
        pool = _force_top10_pool(candidates_scored, "forced_top10_from_scored_candidates")
        trace["status"] = "degraded"
        trace["forced_top10"] = True
    trace["count"] = len(pool)
    trace["status"] = "ok" if pool else "empty"
    return pool[:10], trace


def _run_pool_oversold(
    watchlist: list[str],
    eff: dict[str, Any],
    gates: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trace = {"status": "ok", "count": 0, "degraded_history": 0, "scoring_reject_count": 0, "hard_gate_reject_count": 0}
    pconf = eff["paradigms"].get("oversold_bounce", {}) if isinstance(eff["paradigms"], dict) else {}
    thr = int(pconf.get("entry_threshold") or 65)
    mult = float(pconf.get("weight_multiplier") or 1.0)
    rmap = _fetch_realtime_many(watchlist)
    if not rmap:
        # degraded fallback from history features when realtime is unavailable
        for code in watchlist:
            h = _history_features(code)
            if not h.get("ok"):
                continue
            nm = _resolve_stock_name(code, rt=None, hist=h)
            rmap[code] = {
                "name": nm,
                "change_percent": _safe_float(h.get("pct_change"), 0.0),
                "amount": _safe_float(h.get("amount"), 60_000_000.0),
            }
        if not rmap:
            return [], {"status": "error", "count": 0, "reason": "realtime_unavailable"}
    pool: list[dict[str, Any]] = []
    candidates_scored: list[dict[str, Any]] = []
    for code in watchlist:
        rt = rmap.get(code)
        if not rt:
            continue
        pct = _safe_float(rt.get("change_percent"))
        amount = _safe_float(rt.get("amount"))
        hist = _history_features(code)
        if not hist.get("ok"):
            continue
        nm = _resolve_stock_name(code, rt=rt, hist=hist)
        if hist.get("degraded"):
            trace["degraded_history"] = int(trace.get("degraded_history") or 0) + 1
        vol_ratio = _safe_float(hist.get("volume_ratio"), 0.0)
        listed_days = int(_safe_float(hist.get("listed_days"), 0))
        if amount <= 0 and _safe_float(hist.get("amount")) > 0:
            amount = _safe_float(hist.get("amount"))
        if not _hard_gate_ok(name=nm, listed_days=listed_days, amount=amount, pct_chg=pct, gates=gates):
            trace["hard_gate_reject_count"] = int(trace.get("hard_gate_reject_count") or 0) + 1
            continue
        raw, br = _score_oversold(pct, vol_ratio, amount)
        adj = _apply_multiplier(raw, mult)
        eff_thr = thr - 8 if hist.get("degraded") else thr
        if hist.get("degraded"):
            eff_thr = max(DEGRADED_MIN_ENTRY_THRESHOLD, eff_thr)
        candidates_scored.append(
            {
                "symbol": code,
                "name": nm,
                "sector_name": "",
                "paradigm": "oversold_bounce",
                "paradigm_score": adj,
                "raw_paradigm_score": raw,
                "factor_breakdown": {"pillars": br, "weight_multiplier": mult},
                "pct_change": pct,
                "volume_ratio": vol_ratio,
                "amount": amount,
                "reasons": ["pre_threshold_candidate"],
                "position_suggestion": "轻仓(2-3%)",
                "stop_loss": "-3%",
            }
        )
        if adj < eff_thr:
            trace["scoring_reject_count"] = int(trace.get("scoring_reject_count") or 0) + 1
            continue
        row_obj = {
            "symbol": code,
            "name": nm,
            "sector_name": "",
            "paradigm": "oversold_bounce",
            "paradigm_score": adj,
            "raw_paradigm_score": raw,
            "factor_breakdown": {"pillars": br, "weight_multiplier": mult},
            "pct_change": pct,
            "volume_ratio": vol_ratio,
            "amount": amount,
            "reasons": [f"超跌反弹{adj}分", f"跌{pct:.2f}%", f"量比{vol_ratio:.2f}"],
            "position_suggestion": "轻仓(2-3%)",
            "stop_loss": "-3%",
        }
        pool.append(row_obj)
        if hist.get("degraded"):
            pool[-1]["reasons"].append("history_degraded:realtime_proxy")
    pool.sort(key=_pool_row_sort_key)
    if not pool and candidates_scored:
        pool = _force_top10_pool(candidates_scored, "forced_top10_from_scored_candidates")
        trace["status"] = "degraded"
        trace["forced_top10"] = True
    trace["count"] = len(pool)
    return pool[:10], trace


def _run_pool_sector_rotation(
    watchlist: list[str],
    code_industry: dict[str, str],
    sector_strength: dict[str, float],
    market_proxy_pct: float | None,
    eff: dict[str, Any],
    gates: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trace = {"status": "ok", "count": 0, "degraded_history": 0, "hard_gate_reject_count": 0, "scoring_reject_count": 0}
    pconf = eff["paradigms"].get("sector_rotation", {}) if isinstance(eff["paradigms"], dict) else {}
    allow_sector_fallback = bool(pconf.get("allow_sector_proxy_fallback", True))
    if not sector_strength and not allow_sector_fallback:
        return [], {"status": "error", "count": 0, "reason": "no_sector_data"}
    thr = int(pconf.get("entry_threshold") or 63)
    mult = float(pconf.get("weight_multiplier") or 1.0)
    rs_min = float(pconf.get("rs_min_threshold_pct") or 0.5)
    pcts = list(sector_strength.values())
    qthr = _industry_top_third_threshold(pcts)
    watch_set = set(watchlist)
    pool: list[dict[str, Any]] = []
    candidates_scored: list[dict[str, Any]] = []
    for code in watchlist:
        industry = code_industry.get(code) or ""
        if sector_strength:
            if not industry:
                continue
            ind_pct = sector_strength.get(industry)
            if ind_pct is None:
                continue
        else:
            ind_pct = 0.0
        rs_ex = None
        if market_proxy_pct is not None:
            rs_ex = ind_pct - market_proxy_pct
        hist = _history_features(code)
        if not hist.get("ok"):
            continue
        if hist.get("degraded"):
            trace["degraded_history"] = int(trace.get("degraded_history") or 0) + 1
        pct = _safe_float(hist.get("pct_change"), 999.0)
        amount = _safe_float(hist.get("amount"), 0.0)
        listed_days = int(_safe_float(hist.get("listed_days"), 0))
        vol_ratio = _safe_float(hist.get("volume_ratio"), 0.0)
        ret_5d = _safe_float(hist.get("ret_5d"), 0.0)
        rt = _fetch_realtime_one(code) or {}
        nm = _resolve_stock_name(code, rt=rt, hist=hist)
        if not _hard_gate_ok(name=nm, listed_days=listed_days, amount=amount, pct_chg=pct, gates=gates):
            trace["hard_gate_reject_count"] = int(trace.get("hard_gate_reject_count") or 0) + 1
            continue
        in_wl = code in watch_set
        in_top = ind_pct >= qthr if sector_strength else False
        raw, br = _score_sector_rotation(ind_pct, rs_ex, in_wl, in_top, ret_5d, rs_min)
        if not sector_strength:
            # degraded: no sector rank, keep only watchlist + ret5d effect
            br["mom_rs"] = 0
            raw = br["pool_q"] + br["ret5d"]
        adj = _apply_multiplier(raw, mult)
        eff_thr = thr - (10 if (hist.get("degraded") or not sector_strength) else 0)
        if hist.get("degraded") or not sector_strength:
            eff_thr = max(DEGRADED_MIN_ENTRY_THRESHOLD, eff_thr)
        candidates_scored.append(
            {
                "symbol": code,
                "name": nm,
                "sector_name": industry,
                "paradigm": "sector_rotation",
                "paradigm_score": adj,
                "raw_paradigm_score": raw,
                "factor_breakdown": {
                    "pillars": br,
                    "industry_pct": ind_pct,
                    "rs_extra": rs_ex,
                    "weight_multiplier": mult,
                },
                "pct_change": pct,
                "volume_ratio": vol_ratio,
                "amount": amount,
                "reasons": ["pre_threshold_candidate"],
                "position_suggestion": "轻仓(2-3%)",
                "stop_loss": "-3%",
            }
        )
        if adj < eff_thr:
            trace["scoring_reject_count"] = int(trace.get("scoring_reject_count") or 0) + 1
            continue
        row_obj = {
            "symbol": code,
            "name": nm,
            "sector_name": industry,
            "paradigm": "sector_rotation",
            "paradigm_score": adj,
            "raw_paradigm_score": raw,
            "factor_breakdown": {
                "pillars": br,
                "industry_pct": ind_pct,
                "rs_extra": rs_ex,
                "weight_multiplier": mult,
            },
            "pct_change": pct,
            "volume_ratio": vol_ratio,
            "amount": amount,
            "reasons": [f"板块轮动{adj}分", industry or "sector_fallback", f"板块{ind_pct:.2f}%"],
            "position_suggestion": "轻仓(2-3%)",
            "stop_loss": "-3%",
        }
        pool.append(row_obj)
        if hist.get("degraded"):
            pool[-1]["reasons"].append("history_degraded:realtime_proxy")
    pool.sort(key=_pool_row_sort_key)
    if not pool and candidates_scored:
        pool = _force_top10_pool(candidates_scored, "forced_top10_from_scored_candidates")
        trace["status"] = "degraded"
        trace["forced_top10"] = True
    trace["count"] = len(pool)
    if not sector_strength:
        trace["status"] = "degraded"
        trace["reason"] = "no_sector_data_use_proxy_fallback"
    return pool[:10], trace


def _primary_paradigm(scores: dict[str, int]) -> str:
    best_p = ""
    best_s = -1
    for p in PARADIGM_ORDER:
        s = scores.get(p, 0)
        if s > best_s:
            best_s = s
            best_p = p
    return best_p or "fund_flow_follow"


def _merge_recommended(
    paradigm_pools: dict[str, list[dict[str, Any]]],
    eff: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Returns (recommended, meta)。meta.composite_top5_count = min(5, |A|)。"""
    conf = eff.get("confluence") or {}
    bonus_per = int(conf.get("bonus_per_paradigm") or 4)
    max_bonus = int(conf.get("max_bonus") or 12)
    caps = eff.get("composite_caps") or {}
    cap_ff = int(caps.get("fund_flow_follow_max_in_top5") or 99)
    cap_tg = int(caps.get("tail_grab_max_in_top5") or 99)

    sym_scores: dict[str, dict[str, int]] = {}
    sym_rows: dict[str, dict[str, Any]] = {}
    for pid, rows in paradigm_pools.items():
        for r in rows:
            s = str(r.get("symbol") or "")
            if not s:
                continue
            sym_scores.setdefault(s, {})[pid] = int(r.get("paradigm_score") or 0)
            prev = sym_rows.get(s)
            sc = int(r.get("paradigm_score") or 0)
            if not prev or sc > int(prev.get("paradigm_score") or 0):
                sym_rows[s] = dict(r)

    amounts: list[float] = []
    for s in sym_scores:
        amounts.append(float((sym_rows.get(s, {}) or {}).get("amount") or 0.0))
    min_amt = min(amounts) if amounts else 0.0
    max_amt = max(amounts) if amounts else 0.0

    def _liquidity_bonus(symbol: str) -> float:
        amt = float((sym_rows.get(symbol, {}) or {}).get("amount") or 0.0)
        if max_amt <= min_amt:
            return 0.0
        # 0~2 的小幅加分，只用于打散同分，不改变主排序逻辑（范式分优先）
        ratio = (amt - min_amt) / (max_amt - min_amt)
        return round(2.0 * max(0.0, min(1.0, ratio)), 2)

    composites: list[tuple[str, float, dict[str, int]]] = []
    for s, pmap in sym_scores.items():
        if not pmap:
            continue
        m = max(pmap.values())
        k = len(pmap)
        comp = float(m + min(max_bonus, bonus_per * max(0, k - 1)) + _liquidity_bonus(s))
        composites.append((s, comp, pmap))
    composites.sort(key=lambda x: (-x[1], -sym_rows.get(x[0], {}).get("amount", 0), x[0]))

    picked: list[tuple[str, float, dict[str, int], int]] = []
    c_ff = c_tg = 0
    rank = 0
    for s, comp, pmap in composites:
        if len(picked) >= 5:
            break
        prim = _primary_paradigm(pmap)
        if prim == "fund_flow_follow" and c_ff >= cap_ff:
            continue
        if prim == "tail_grab" and c_tg >= cap_tg:
            continue
        rank += 1
        if prim == "fund_flow_follow":
            c_ff += 1
        if prim == "tail_grab":
            c_tg += 1
        picked.append((s, comp, pmap, rank))

    pool_first: dict[str, str] = {}
    for pid in PARADIGM_ORDER:
        rows = paradigm_pools.get(pid) or []
        if rows:
            pool_first[rows[0]["symbol"]] = pid

    rec: list[dict[str, Any]] = []
    seen: set[str] = set()

    for s, comp, pmap, cr in picked:
        base = sym_rows.get(s, {}).copy()
        base.pop("paradigm", None)
        tags = ["composite_top5"]
        src_tags = list(tags)
        base["composite_score"] = round(comp, 2)
        base["score"] = int(round(comp))
        base["composite_rank"] = cr
        base["paradigm_scores"] = pmap
        base["source_tags"] = src_tags
        base["primary_display"] = "composite"
        rec.append(base)
        seen.add(s)

    for pid in PARADIGM_ORDER:
        rows = paradigm_pools.get(pid) or []
        if not rows:
            continue
        top = rows[0]
        s = top["symbol"]
        if s in seen:
            for r in rec:
                if r.get("symbol") == s:
                    st = list(r.get("source_tags") or [])
                    tag = f"pool_first:{pid}"
                    if tag not in st:
                        st.append(tag)
                    r["source_tags"] = st
                    r["primary_display"] = "mixed"
            continue
        row = top.copy()
        row.pop("paradigm", None)
        pmap = sym_scores.get(s, {pid: int(top.get("paradigm_score") or 0)})
        comp = float(
            max(pmap.values()) + min(max_bonus, bonus_per * max(0, len(pmap) - 1)) + _liquidity_bonus(s)
        )
        row["composite_score"] = round(comp, 2)
        row["score"] = int(round(comp))
        row["composite_rank"] = None
        row["paradigm_scores"] = pmap
        row["source_tags"] = [f"pool_first:{pid}"]
        row["primary_display"] = "pool_first"
        rec.append(row)
        seen.add(s)

    meta = {
        "composite_top5_count": min(5, len(picked)),
        "composite_top5_caps_note": (
            "composite_caps 仅作用于综合分 Top5（集合 A），各范式池第一（集合 B）不受 cap。"
        ),
    }
    return rec, meta


def _weekly_recommend_limit_hit(today: str, max_count: int = 5) -> bool:
    out_dir = _tail_data_dir()
    hit = 0
    start = datetime.strptime(today, "%Y-%m-%d").date() - timedelta(days=6)
    for p in sorted(out_dir.glob("20*.json")):
        if p.name == "latest.json":
            continue
        key = p.stem
        try:
            d = datetime.strptime(key, "%Y-%m-%d").date()
        except Exception:
            continue
        if d < start:
            continue
        j = _read_json(p) or {}
        summ = j.get("summary", {}) if isinstance(j, dict) else {}
        if int(_safe_float(summ.get("recommended_count"), 0)) > 0:
            hit += 1
    return hit >= max_count


def _is_pause_active() -> tuple[bool, str]:
    from src.screening_quality_gate import screening_should_skip_due_to_pause

    blocked, reason = screening_should_skip_due_to_pause()
    return bool(blocked), str(reason or "")


def _northbound_net_latest() -> tuple[float | None, dict[str, Any]]:
    trace: dict[str, Any] = {"tool": "tool_fetch_northbound_flow"}
    try:
        r = _run_tool("tool_fetch_northbound_flow", {"lookback_days": 5}, timeout_sec=TOOL_TIMEOUT_MARKET)
    except Exception as e:  # noqa: BLE001
        trace["error"] = str(e)
        return None, trace
    if not isinstance(r, dict) or not r.get("success"):
        trace["message"] = r.get("message") if isinstance(r, dict) else "failed"
        return None, trace
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    v = data.get("total_net")
    if v is None and isinstance(data.get("records"), list) and data["records"]:
        last = data["records"][-1]
        if isinstance(last, dict):
            v = last.get("net") or last.get("total_net") or last.get("净流入")
    try:
        net = float(v) if v is not None else None
    except Exception:
        net = None
    trace["total_net"] = net
    return net, trace


def _attach_northbound_soft_tags(recommended: list[dict[str, Any]]) -> dict[str, Any]:
    """§1.5.8 软标签，不阻塞。"""
    if not recommended:
        return {"status": "skip", "reason": "no_recommended"}
    net, tr = _northbound_net_latest()

    def align_for(row: dict[str, Any]) -> str:
        if net is None:
            return "na"
        ff = int((row.get("paradigm_scores") or {}).get("fund_flow_follow") or 0)
        if ff <= 0:
            return "na"
        if net > 0:
            return "yes"
        if net < 0:
            return "no"
        return "na"

    for row in recommended:
        row["northbound_align"] = align_for(row)
        fb = row.get("factor_breakdown")
        if not isinstance(fb, dict):
            fb = {}
        else:
            fb = dict(fb)
        fb["northbound_align"] = row["northbound_align"]
        row["factor_breakdown"] = fb
    aligns = [str(x.get("northbound_align") or "na") for x in recommended]
    tr.update(
        {
            "status": "ok" if net is not None else "degraded",
            "align_counts": {
                "yes": aligns.count("yes"),
                "no": aligns.count("no"),
                "na": aligns.count("na"),
            },
        }
    )
    return tr


def _build_rescue_pick(watchlist: list[str], gates: dict[str, Any]) -> dict[str, Any] | None:
    """When all pools are empty under degraded data, pick one conservative oversold-style fallback."""
    rmap = _fetch_realtime_many(watchlist[:30])
    best: dict[str, Any] | None = None
    best_score = -10**9
    for code in watchlist[:30]:
        rt = rmap.get(code)
        if not rt:
            continue
        hist = _history_features(code)
        nm = _resolve_stock_name(code, rt=rt, hist=hist)
        pct = _safe_float(rt.get("change_percent"))
        amount = _safe_float(rt.get("amount"))
        if not hist.get("ok"):
            continue
        listed_days = int(_safe_float(hist.get("listed_days"), 0))
        vol_ratio = _safe_float(hist.get("volume_ratio"), 0.0)
        if amount <= 0:
            amount = _safe_float(hist.get("amount"), 0.0)
        if not _hard_gate_ok(name=nm, listed_days=listed_days, amount=amount, pct_chg=pct, gates=gates):
            continue
        raw, br = _score_oversold(pct, vol_ratio, amount)
        if raw > best_score:
            best_score = raw
            direction = "涨" if pct >= 0 else "跌"
            reasons = [f"兜底补位{int(raw)}分", f"{direction}{abs(pct):.2f}%", f"量比{vol_ratio:.2f}", "rescue_from_degraded_empty"]
            if hist.get("degraded"):
                reasons.append("history_degraded:realtime_proxy")
            best = {
                "symbol": code,
                "name": nm,
                "sector_name": "",
                "paradigm_score": int(raw),
                "raw_paradigm_score": int(raw),
                "composite_score": float(int(raw)),
                "score": int(raw),
                "composite_rank": None,
                "paradigm_scores": {"oversold_bounce": int(raw)},
                "source_tags": ["rescue_fallback"],
                "primary_display": "rescue",
                "factor_breakdown": {"pillars": br, "rescue": True},
                "pct_change": pct,
                "volume_ratio": vol_ratio,
                "amount": amount,
                "reasons": reasons,
                "position_suggestion": "轻仓(2-3%)",
                "stop_loss": "-3%",
                "display_order": 1,
            }
    return best


def _build_forced_pick(watchlist: list[str], gates: dict[str, Any]) -> dict[str, Any] | None:
    """Last-line safety: never return empty when realtime candidates exist."""
    rmap = _fetch_realtime_many(watchlist[:80])
    best: dict[str, Any] | None = None
    best_amount = -1.0
    near_limit_abs = float(gates.get("near_limit_abs_pct") or 9.5)
    for code in watchlist[:80]:
        rt = rmap.get(code)
        if not rt:
            continue
        nm = _resolve_stock_name(code, rt=rt, hist=None)
        if gates.get("exclude_st", True) and _is_st_name(nm):
            continue
        pct = _safe_float(_pick_key(rt, ["change_percent", "涨跌幅", "pct_change"]), default=0.0)
        if abs(pct) >= near_limit_abs:
            continue
        amount = _safe_float(_pick_key(rt, ["amount", "成交额"]), default=0.0)
        vol_ratio = _safe_float(_pick_key(rt, ["volume_ratio", "量比"]), default=1.0)
        if amount > best_amount:
            best_amount = amount
            best = {
                "symbol": code,
                "name": nm,
                "sector_name": str(_pick_key(rt, ["industry", "所属行业", "行业"]) or "").strip(),
                "paradigm_score": 35,
                "raw_paradigm_score": 35,
                "composite_score": 35.0,
                "score": 35,
                "composite_rank": None,
                "paradigm_scores": {"forced_fallback": 35},
                "source_tags": ["forced_fallback"],
                "primary_display": "forced",
                "factor_breakdown": {"forced_fallback": True},
                "pct_change": pct,
                "volume_ratio": vol_ratio,
                "amount": amount,
                "reasons": ["强制兜底补位", "四池为空但存在可交易候选", f"成交额{amount:.0f}"],
                "position_suggestion": "轻仓(1-2%)",
                "stop_loss": "-3%",
                "display_order": 1,
            }
    return best


def run_tail_screening(max_candidates: int, notify_mode: str) -> dict[str, Any]:
    today = _today_shanghai()
    _HISTORY_FEATURES_CACHE.clear()
    run_id = uuid.uuid4().hex[:12]
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = _load_scoring_config()
    applied_profile, eff, _raw_cfg, regime_meta = _resolve_effective_params(cfg)
    scoring_version = str(cfg.get("version") or "unknown")
    market_regime_lbl = str(regime_meta.get("market_regime") or applied_profile)

    blocked, reason = _is_pause_active()
    if blocked:
        return {
            "run_id": run_id,
            "run_date": today,
            "generated_at": now_utc,
            "scoring_version": scoring_version,
            "applied_profile": applied_profile,
            "market_regime": market_regime_lbl,
            "regime_detection_notes": regime_meta.get("regime_detection_notes") or [],
            "stage": "skip",
            "skip_reason": reason or "pause_active",
            "recommended": [],
            "paradigm_pools": {p: [] for p in PARADIGM_ORDER},
            "watch": [],
            "ignored": [],
            "summary": {
                "recommended_count": 0,
                "data_quality": "partial",
            },
        }

    mpx, mpx_trace = _market_proxy_day_pct(cfg)
    extra_skip, extra_reason, extra_trace = _evaluate_extra_gates_block(
        eff.get("extra_gates"), mpx, cfg
    )
    if extra_skip:
        return {
            "run_id": run_id,
            "run_date": today,
            "generated_at": now_utc,
            "scoring_version": scoring_version,
            "applied_profile": applied_profile,
            "market_regime": market_regime_lbl,
            "regime_detection_notes": list(regime_meta.get("regime_detection_notes") or []) + extra_trace,
            "stage": "skip",
            "skip_reason": f"extra_gates:{extra_reason}",
            "recommended": [],
            "paradigm_pools": {p: [] for p in PARADIGM_ORDER},
            "watch": [],
            "ignored": [],
            "summary": {
                "recommended_count": 0,
                "data_quality": "partial",
                "no_candidate_reason": extra_reason,
            },
            "tool_trace": {
                "extra_gates_eval": extra_trace,
                "market_proxy_pct": mpx,
                "market_proxy": mpx_trace,
            },
        }

    gates = eff.get("hard_gates") or {}
    rank_rows, source_diag = _resolve_rank_rows(max_candidates)
    lim_sec = int(eff["paradigms"].get("sector_rotation", {}).get("sector_rank_limit") or 60) if isinstance(eff["paradigms"], dict) else 60
    sector_strength, sector_trace = _sector_strength_full(lim_sec)
    code_industry = _code_industry_map(rank_rows)
    wl = _load_watchlist_symbols(80)

    paradigm_pools: dict[str, list[dict[str, Any]]] = {p: [] for p in PARADIGM_ORDER}
    p_trace: dict[str, Any] = {}

    candidate_source = str(source_diag.get("candidate_source") or "stock_rank")
    if source_diag.get("main_source_ok"):
        paradigm_pools["fund_flow_follow"], p_trace["fund_flow_follow"] = _run_pool_fund_flow(
            rank_rows, sector_strength, eff, gates, candidate_source=candidate_source
        )
    else:
        if rank_rows:
            paradigm_pools["fund_flow_follow"], p_trace["fund_flow_follow"] = _run_pool_fund_flow(
                rank_rows, sector_strength, eff, gates, candidate_source=candidate_source
            )
            p_trace["fund_flow_follow"]["status"] = "degraded" if paradigm_pools["fund_flow_follow"] else "empty"
            p_trace["fund_flow_follow"]["reason"] = "stock_rank_failed_use_realtime_proxy"
        else:
            p_trace["fund_flow_follow"] = {"status": "empty", "reason": "stock_rank_failed"}

    paradigm_pools["tail_grab"], p_trace["tail_grab"] = _run_pool_tail_grab(wl, eff, gates)
    paradigm_pools["oversold_bounce"], p_trace["oversold_bounce"] = _run_pool_oversold(wl, eff, gates)
    paradigm_pools["sector_rotation"], p_trace["sector_rotation"] = _run_pool_sector_rotation(
        wl, code_industry, sector_strength, mpx, eff, gates
    )

    recommended, merge_meta = _merge_recommended(paradigm_pools, eff)
    rescue_used = False
    forced_used = False
    if not recommended and not any(paradigm_pools.values()):
        rescue = _build_rescue_pick(wl, gates)
        if rescue:
            recommended = [rescue]
            rescue_used = True
        else:
            forced = _build_forced_pick(wl, gates)
            if forced:
                recommended = [forced]
                forced_used = True
    p_trace["composite_top5"] = {
        "caps_note": merge_meta.get("composite_top5_caps_note"),
        "composite_top5_count": merge_meta.get("composite_top5_count"),
    }
    for r in recommended:
        sym = str(r.get("symbol") or "")
        if not r.get("sector_name"):
            for pid in PARADIGM_ORDER:
                for row in paradigm_pools.get(pid) or []:
                    if row.get("symbol") == sym and row.get("sector_name"):
                        r["sector_name"] = row["sector_name"]
                        break
                if r.get("sector_name"):
                    break

    limit_hit = _weekly_recommend_limit_hit(today, max_count=5)
    if limit_hit and recommended:
        recommended = []

    for order, r in enumerate(recommended, start=1):
        r["display_order"] = order
    northbound_trace = _attach_northbound_soft_tags(recommended)

    pools_nonempty = sum(1 for p in PARADIGM_ORDER if paradigm_pools.get(p))
    dq = "fresh" if pools_nonempty else "partial"
    if not source_diag.get("main_source_ok"):
        dq = "partial"

    no_candidate_reason = None
    if not any(paradigm_pools.values()):
        no_candidate_reason = "四范式候选池均为空（数据源或阈值）。"
    elif not recommended:
        no_candidate_reason = "推荐池为空（周频控或综合合并后无标的）。"

    stage = "recommend" if recommended else "empty"

    ct5 = int(merge_meta.get("composite_top5_count") or 0) if recommended else 0
    pfo = 0
    for x in recommended:
        st = x.get("source_tags") or []
        if any(str(t).startswith("pool_first:") for t in st) and "composite_top5" not in st:
            pfo += 1

    def _sector_cov(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        ok = sum(1 for z in rows if str(z.get("sector_name") or "").strip())
        return round(100.0 * ok / len(rows), 1)

    pool_rows_all: list[dict[str, Any]] = []
    for p in PARADIGM_ORDER:
        pool_rows_all.extend(paradigm_pools.get(p) or [])

    result: dict[str, Any] = {
        "run_id": run_id,
        "run_date": today,
        "generated_at": now_utc,
        "scoring_version": scoring_version,
        "applied_profile": applied_profile,
        "market_regime": market_regime_lbl,
        "regime_detection_notes": list(regime_meta.get("regime_detection_notes") or []),
        "stage": stage,
        "gate_snapshot": {"blocked": False, "reason": None, "weekly_recommend_limit_hit": limit_hit},
        "recommended": recommended,
        "paradigm_pools": paradigm_pools,
        "watch": [],
        "ignored": [],
        "summary": {
            "recommended_count": len(recommended),
            "watch_count": 0,
            "composite_top5_count": ct5,
            "pool_first_only_count": pfo,
            "pools_nonempty_count": pools_nonempty,
            "passed_hard_conditions": len(pool_rows_all),
            "sector_name_coverage": {
                "recommended_pct": _sector_cov(recommended),
                "paradigm_pools_pct": _sector_cov(pool_rows_all),
            },
            "data_quality": dq,
            "degraded_mode": any(
                (p_trace.get(p) or {}).get("status") == "degraded" or int((p_trace.get(p) or {}).get("degraded_history") or 0) > 0
                for p in PARADIGM_ORDER
            ),
            "degraded_counts": {
                p: int((p_trace.get(p) or {}).get("degraded_history") or 0) for p in PARADIGM_ORDER
            },
            "rescue_used": rescue_used,
            "forced_used": forced_used,
            "no_candidate_reason": no_candidate_reason,
            "applied_profile": applied_profile,
        },
        "tool_trace": {
            "notify_mode": notify_mode,
            "applied_profile": applied_profile,
            "market_regime": market_regime_lbl,
            "default_regime_requested": regime_meta.get("default_regime_requested"),
            "regime_tool_features": regime_meta.get("regime_tool_features"),
            "extra_gates_eval": extra_trace if extra_trace else [],
            "market_proxy": mpx_trace,
            "market_proxy_pct": mpx,
            "sector_rank_trace": sector_trace,
            "source_diagnostics": source_diag,
            "northbound_trace": northbound_trace,
            "paradigm_trace": p_trace,
            "config_path": str(CONFIG_PATH) if CONFIG_PATH.is_file() else None,
        },
    }
    return result


def persist_result(result: dict[str, Any]) -> dict[str, str]:
    out_dir = _tail_data_dir()
    date_key = str(result.get("run_date") or _today_shanghai())
    date_path = out_dir / f"{date_key}.json"
    latest_path = out_dir / "latest.json"
    body = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if legacy_write_allowed("intraday-tail-screening"):
        date_path.write_text(body, encoding="utf-8")
        latest_path.write_text(body, encoding="utf-8")
    _persist_new_data_layer(result)
    return {"date_path": str(date_path), "latest_path": str(latest_path)}


def _persist_new_data_layer(result: dict[str, Any]) -> None:
    trade_date = str(result.get("run_date") or _today_shanghai())
    run_id = str(result.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    degraded = bool((result.get("summary") or {}).get("degraded_mode"))
    quality_status = "degraded" if degraded else "ok"
    write_contract_json(
        ROOT / "data" / "decisions" / "recommendations" / f"tail_{trade_date}.json",
        payload=result,
        meta=MetaEnvelope(
            schema_name="tail_recommendations_v1",
            schema_version="1.0.0",
            task_id="intraday-tail-screening",
            run_id=run_id,
            data_layer="L3",
            trade_date=trade_date,
            quality_status=quality_status,
            lineage_refs=[str(ROOT / "data" / "tail_screening" / f"{trade_date}.json")],
            source_tools=["tool_fetch_a_share_fund_flow", "tool_fetch_stock_minute"],
        ),
    )
    append_contract_jsonl(
        ROOT / "data" / "semantic" / "timeline_feed" / f"{trade_date}.jsonl",
        payload={
            "event_id": f"intraday-tail-screening.{run_id}",
            "event_time": str(result.get("generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            "event_type": "tail_recommendation",
            "summary": f"recommended_count={(result.get('summary') or {}).get('recommended_count', 0)}",
            "result_ref": f"data/decisions/recommendations/tail_{trade_date}.json",
        },
        meta=MetaEnvelope(
            schema_name="timeline_event_v1",
            schema_version="1.0.0",
            task_id="intraday-tail-screening",
            run_id=run_id,
            data_layer="L4",
            trade_date=trade_date,
            quality_status=quality_status,
            lineage_refs=[str(ROOT / "data" / "decisions" / "recommendations" / f"tail_{trade_date}.json")],
            source_tools=["intraday_tail_screening_and_persist.py"],
        ),
    )


def notify(result: dict[str, Any], mode: str = "prod") -> dict[str, Any]:
    rec = result.get("recommended", [])
    if not isinstance(rec, list) or not rec:
        return {"success": True, "message": "skip notify: no recommended"}
    prof = result.get("applied_profile") or ""
    summ = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    mr = result.get("market_regime") or ""
    data_quality = str(summ.get("data_quality") or "unknown")
    quality_label = "正常" if data_quality == "fresh" else "降级"
    lines = [
        f"【尾盘选股推荐】{result.get('run_date', '')}（{quality_label}）",
        f"策略={prof} | 市场={mr} | 数据质量={data_quality}",
        f"综合前5={summ.get('composite_top5_count', '—')} 仅池第一补入={summ.get('pool_first_only_count', '—')}",
        "",
    ]
    lines.append(f"标的（{len(rec)}只）：")
    for x in rec:
        tags = ",".join(x.get("source_tags") or [])
        sec = x.get("sector_name") or "—"
        nb = x.get("northbound_align") or ""
        nb_s = f" 北向={nb}" if nb else ""
        lines.append(
            f"- {x.get('name')}({x.get('symbol')}) [{sec}] 综合{x.get('composite_score', x.get('score', ''))} | {tags}{nb_s}"
        )
        reasons = x.get("reasons") or []
        if reasons:
            lines.append(f"  逻辑：{', '.join(str(r) for r in reasons[:3])}")
    lines.append("")
    lines.append("风险提示：仅供研究参考，不构成投资建议。")
    return _run_tool(
        "tool_send_feishu_message",
        {
            "title": "尾盘选股推荐",
            "message": "\n".join(lines),
            "mode": mode,
            "cooldown_key": "cron:intraday-tail-screening:report",
            "cooldown_minutes": 5,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-candidates", type=int, default=50)
    ap.add_argument("--notify-mode", default="prod")
    ap.add_argument("--notify", action="store_true")
    args = ap.parse_args()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    abnormal: list[str] = []
    try:
        result = run_tail_screening(max_candidates=max(10, min(args.max_candidates, 100)), notify_mode=args.notify_mode)
        paths = persist_result(result)
    except Exception as e:  # noqa: BLE001
        alert = _send_feishu_abnormal(
            f"[intraday-tail-screening] 执行异常（{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} UTC）",
            [f"exception={type(e).__name__}: {e}"],
            mode=args.notify_mode,
        )
        print(json.dumps({"success": False, "error": str(e), "abnormal_notify": alert}, ensure_ascii=False, indent=2))
        return 1

    notify_resp = {"success": True, "message": "not requested"}
    if args.notify:
        try:
            notify_resp = notify(result, mode=args.notify_mode)
        except Exception as e:  # noqa: BLE001
            notify_resp = {"success": False, "error": str(e)}

    stage = str(result.get("stage") or "")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if stage == "skip":
        abnormal.append(f"stage=skip reason={result.get('skip_reason')}")
    if stage == "empty":
        abnormal.append(f"stage=empty reason={summary.get('no_candidate_reason')}")
    if args.notify and not bool(notify_resp.get("success")):
        abnormal.append(f"notify_failed={notify_resp.get('error') or notify_resp.get('message')}")

    abnormal_notify = {"success": True, "message": "skip notify: no abnormal"}
    if abnormal:
        abnormal_notify = _send_feishu_abnormal(
            f"[intraday-tail-screening] 发现异常（{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} UTC）",
            abnormal,
            mode=args.notify_mode,
        )
    print(
        json.dumps(
            {
                "success": True,
                "run_id": result.get("run_id"),
                "stage": result.get("stage"),
                "applied_profile": result.get("applied_profile"),
                "recommended_count": (result.get("summary") or {}).get("recommended_count", 0),
                "paths": paths,
                "notify": notify_resp,
                "abnormal_notify": abnormal_notify,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
