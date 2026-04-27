"""
进程内串接：14:40 日经225ETF（513880）尾盘监控与多角度建议。

目标：
- 生成 report_type=tail_session 的结构化 report_data
- 不输出唯一交易结论，仅输出分层建议 + 可选路径（用户最终决策）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from pathlib import Path
import re
import time
from threading import Semaphore
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

import yaml

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None  # type: ignore


logger = logging.getLogger(__name__)


def _stable_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return repr(obj)


def _memo_key(fn: Callable[..., Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    payload = {"fn": getattr(fn, "__name__", str(fn)), "args": args, "kwargs": kwargs}
    return _stable_json_dumps(payload)


class _StageBudget:
    def __init__(self, budget_s: Optional[float]):
        self.budget_s = budget_s if isinstance(budget_s, (int, float)) and float(budget_s) > 0 else None
        self.started_at = time.perf_counter()

    def remaining_s(self) -> Optional[float]:
        if self.budget_s is None:
            return None
        rem = float(self.budget_s) - (time.perf_counter() - self.started_at)
        return rem if rem > 0 else 0.0

    def expired(self) -> bool:
        rem = self.remaining_s()
        return rem is not None and rem <= 0


def _stage_budget_profile(profile: str) -> Dict[str, Optional[float]]:
    p = (profile or "").strip().lower()
    if p in ("off", "disabled", "none"):
        return {"critical": None, "slow_sources": None, "analytics": None}
    if p in ("tight", "fast"):
        return {"critical": 35.0, "slow_sources": 25.0, "analytics": 30.0}
    return {"critical": 45.0, "slow_sources": 35.0, "analytics": 40.0}


def _provider_key_for_step(step_name: str) -> str:
    n = (step_name or "").strip().lower()
    if "yf" in n or "futures" in n:
        return "yfinance"
    if "fundgz" in n:
        return "fundgz"
    if "global_spot" in n:
        return "global_spot"
    if "global_hist" in n or "index_hist" in n:
        return "akshare_sina"
    return "default"


def _semaphore_pool(max_concurrency: int) -> Dict[str, Semaphore]:
    m = max(1, int(max_concurrency or 1))
    return {
        "yfinance": Semaphore(1),
        "fundgz": Semaphore(1),
        "global_spot": Semaphore(1),
        "akshare_sina": Semaphore(1),
        "default": Semaphore(min(2, m)),
    }


def _record_stage_timing(
    stage_timing: Dict[str, Dict[str, Any]],
    stage: str,
    started_at: float,
    budget_s: Optional[float],
    status: str,
    degraded_reason: Optional[str] = None,
    skipped_tasks: Optional[List[str]] = None,
) -> None:
    stage_timing[stage] = {
        "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
        "budget_s": budget_s,
        "status": status,
        "degraded_reason": degraded_reason,
        "skipped_tasks": list(skipped_tasks or []),
    }


def _append_lineage(
    lineage_struct: List[Dict[str, Any]],
    stage: str,
    tool_key: str,
    started_at: float,
    success: Optional[bool],
    quality_status: str,
    degraded_reason: Optional[str],
    source_hint: Optional[str] = None,
) -> None:
    lineage_struct.append(
        {
            "stage": stage,
            "tool_key": tool_key,
            "success": success,
            "quality_status": quality_status,
            "degraded_reason": degraded_reason,
            "elapsed_ms": int(round((time.perf_counter() - started_at) * 1000)),
            "source_hint": source_hint or "",
        }
    )

MONITOR_WINDOWS: Dict[str, Dict[str, str]] = {
    "M1": {"label": "M1 开盘预测", "window": "09:35-10:30"},
    "M2": {"label": "M2 开盘确认", "window": "09:45-10:30"},
    "M3": {"label": "M3 早盘收官预判", "window": "10:15-10:30"},
    "M4": {"label": "M4 早盘复盘", "window": "10:45-12:30"},
    "M5": {"label": "M5 午盘确认", "window": "13:15-14:30"},
    "M6": {"label": "M6 午后跟踪", "window": "13:45-14:30"},
    "M7": {"label": "M7 收盘定调", "window": "14:30-次日开盘"},
}

MONITOR_TEMPLATE_FOCUS: Dict[str, List[str]] = {
    "M1": ["今日全天波动区间", "开盘后支撑/压力", "早盘振幅识别"],
    "M2": ["早盘剩余区间", "开盘确认偏差", "T+0首个窗口"],
    "M3": ["收官前15分钟结构", "午盘开盘区间", "收官量能特征"],
    "M4": ["早盘复盘结论", "午盘完整区间", "下午关键阈值"],
    "M5": ["下午剩余区间", "午盘确认", "T+0持仓管理"],
    "M6": ["尾盘前区间", "动量衰减/延续", "尾盘平仓窗口"],
    "M7": ["次日开盘区间", "隔夜持仓建议", "当日预测复盘"],
}


def _now_sh() -> datetime:
    if pytz is None:
        return datetime.now()
    return datetime.now(pytz.timezone("Asia/Shanghai"))


def _yyyymmdd_dash(s: str) -> Optional[str]:
    s = str(s or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _hist_start_yyyymmdd(end_yyyymmdd: str, calendar_lookback: int = 220) -> str:
    """
    historical 工具以自然日窗口拉取数据（内部会自动跳过非交易日），这里按自然日回退一段，
    确保覆盖 120 交易日前后（含周末/节假日缓冲）。
    """
    try:
        end = datetime.strptime(end_yyyymmdd, "%Y%m%d")
    except Exception:
        end = _now_sh()
        return (end - timedelta(days=calendar_lookback)).strftime("%Y%m%d")
    return (end - timedelta(days=calendar_lookback)).strftime("%Y%m%d")


def _etf_hist_last_kline(etf_hist: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(etf_hist, dict) or not etf_hist.get("success"):
        return None
    d = etf_hist.get("data")
    if not isinstance(d, dict):
        return None
    kl = d.get("klines")
    if not isinstance(kl, list) or not kl:
        return None
    last = kl[-1]
    return last if isinstance(last, dict) else None


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _parse_fundgz_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    text = str(raw_text or "").strip()
    m = re.search(r"jsonpgz\((.*)\)\s*;?\s*$", text)
    if not m:
        return None
    payload = str(m.group(1) or "").strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def _fetch_fundgz_snapshot(etf_code: str, timeout_seconds: float = 5.0) -> Dict[str, Any]:
    url = f"http://fundgz.1234567.com.cn/js/{str(etf_code).strip()}.js"
    try:
        with urlopen(url, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except (URLError, TimeoutError) as e:
        return {"status": "unavailable", "reason": f"request_failed:{type(e).__name__}"}
    except Exception as e:
        return {"status": "unavailable", "reason": f"request_error:{type(e).__name__}"}
    parsed = _parse_fundgz_payload(body)
    if not isinstance(parsed, dict):
        if "jsonpgz()" in body:
            return {"status": "unavailable", "reason": "empty_payload"}
        return {"status": "unavailable", "reason": "invalid_jsonp"}
    gsz = _safe_float(parsed.get("gsz"))
    if gsz is None or gsz <= 0:
        return {"status": "unavailable", "reason": "missing_gsz"}
    return {
        "status": "ok",
        "fundcode": str(parsed.get("fundcode") or ""),
        "name": str(parsed.get("name") or ""),
        "nav_estimate": gsz,
        "pct_change": _safe_float(parsed.get("gszzl")),
        "estimate_time": str(parsed.get("gztime") or ""),
        "nav_date": str(parsed.get("jzrq") or ""),
        "official_nav": _safe_float(parsed.get("dwjz")),
    }


def _calc_fundgz_freshness_seconds(estimate_time: str, now_sh: datetime) -> Optional[int]:
    s = str(estimate_time or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            if getattr(now_sh, "tzinfo", None) is not None:
                dt = now_sh.tzinfo.localize(dt) if hasattr(now_sh.tzinfo, "localize") else dt.replace(tzinfo=now_sh.tzinfo)
            delta = int((now_sh - dt).total_seconds())
            return max(delta, 0)
        except Exception:
            continue
    return None


def _load_recent_513300_history_days(lookback_days: int = 20) -> List[Dict[str, Any]]:
    root = Path(__file__).resolve().parents[2] / "data" / "semantic" / "nasdaq_513300_monitor_events"
    if not root.exists():
        return []
    days: List[Dict[str, Any]] = []
    for p in sorted(root.glob("*.jsonl"), reverse=True):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    days.append(obj)
        except Exception:
            continue
        if len(days) >= lookback_days * 8:
            break
    return days


def _load_recent_monitor_history_days(dataset_dir: str, lookback_days: int = 20) -> List[Dict[str, Any]]:
    """
    从语义层事件目录读取近 N 日历史（用于分位/温度计算）。

    约定：
    - `data/semantic/<dataset_dir>/YYYY-MM-DD.jsonl`：每行一条 L3 事件（append-only）
    """
    root = Path(__file__).resolve().parents[2] / "data" / "semantic" / dataset_dir
    if not root.exists():
        return []
    days: List[Dict[str, Any]] = []
    for p in sorted(root.glob("*.jsonl"), reverse=True):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    days.append(obj)
        except Exception:
            continue
        if len(days) >= lookback_days * 8:
            break
    return days


def _persist_semantic_event_jsonl(dataset_dir: str, trade_date: str, row: Dict[str, Any]) -> None:
    """
    语义层 L3 事件落盘（append-only）。
    - path: data/semantic/<dataset_dir>/<trade_date>.jsonl
    """
    td = str(trade_date or "").strip()
    if not td:
        return
    base = Path(__file__).resolve().parents[2] / "data" / "semantic" / dataset_dir
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{td}.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _persist_semantic_view_json(dataset_dir: str, trade_date: str, monitor_point: str, view: Dict[str, Any]) -> None:
    """
    语义层 L4 视图落盘（overwrite latest）。
    - path: data/semantic/<dataset_dir>/<trade_date>_<monitor_point>.json
    """
    td = str(trade_date or "").strip()
    mp = str(monitor_point or "").strip().upper()
    if not td or not mp:
        return
    base = Path(__file__).resolve().parents[2] / "data" / "semantic" / dataset_dir
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{td}_{mp}.json"
    p.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")


def _calc_nikkei_theoretical_premium(
    *,
    latest_price: Optional[float],
    yesterday_nav: Optional[float],
    index_change_pct: Optional[float],
) -> Dict[str, Any]:
    """
    日经225ETF（513880）理论NAV溢价率：
    theoretical_nav = yesterday_nav * (1 + index_change_pct/100)
    premium_rate_pct = (latest_price/theoretical_nav - 1) * 100
    """
    if latest_price is None or latest_price <= 0:
        return {"status": "unavailable", "reason": "latest_price_unavailable"}
    if yesterday_nav is None or yesterday_nav <= 0:
        return {"status": "unavailable", "reason": "yesterday_nav_unavailable"}
    if index_change_pct is None:
        return {"status": "unavailable", "reason": "index_change_pct_unavailable"}
    theoretical_nav = yesterday_nav * (1.0 + float(index_change_pct) / 100.0)
    if theoretical_nav <= 0:
        return {"status": "unavailable", "reason": "theoretical_nav_invalid"}
    premium_rate_pct = (latest_price / theoretical_nav - 1.0) * 100.0
    return {
        "status": "ok",
        "theoretical_nav": theoretical_nav,
        "premium_rate_pct": premium_rate_pct,
    }


def _nikkei_risk_gate_from_premium(
    premium_rate_pct: Optional[float],
    premium_percentile_20d: Optional[float],
    quality: str,
) -> Dict[str, Any]:
    """
    溢价门禁：绝对阈值 + 分位阈值（取更保守者）。
    - action: GO / GO_LIGHT / WAIT
    - position_ceiling: 0.25 / 0.50 / 0.75 / 1.00
    """
    reasons: List[str] = []
    action = "GO"
    cap = 1.0

    # 数据缺口：退回保守上限
    if str(quality or "").strip().lower() == "error":
        reasons.append("PREMIUM_UNAVAILABLE_FALLBACK_DEVIATION")
        return {"action": "GO_LIGHT", "position_ceiling": 0.6, "reasons": reasons}

    # 绝对溢价阈值（单位：%）
    if premium_rate_pct is not None:
        if premium_rate_pct > 3.0:
            action, cap = "WAIT", 0.25
            reasons.append("PREMIUM_GT_3PCT")
        elif premium_rate_pct > 2.0:
            action, cap = "GO_LIGHT", 0.5
            reasons.append("PREMIUM_2_TO_3PCT")
        elif premium_rate_pct > 1.0:
            action, cap = "GO", 0.75
            reasons.append("PREMIUM_1_TO_2PCT")
        else:
            action, cap = "GO", 1.0
            reasons.append("PREMIUM_LT_1PCT")

    # 分位阈值（0–100）
    if premium_percentile_20d is not None:
        pct = float(premium_percentile_20d)
        if pct > 85.0:
            cap = min(cap, 0.25)
            action = "WAIT" if action == "WAIT" else "GO_LIGHT"
            reasons.append("PREMIUM_PCTL_GT_85")
        elif pct > 60.0:
            cap = min(cap, 0.5)
            if action == "GO":
                action = "GO_LIGHT"
            reasons.append("PREMIUM_PCTL_60_TO_85")
        elif pct >= 30.0:
            cap = min(cap, 0.75)
            reasons.append("PREMIUM_PCTL_30_TO_60")
        else:
            reasons.append("PREMIUM_PCTL_LT_30")

    # 规范化
    cap = float(cap)
    if cap <= 0.26:
        cap = 0.25
    elif cap <= 0.51:
        cap = 0.5
    elif cap <= 0.76:
        cap = 0.75
    else:
        cap = 1.0
    if action not in {"GO", "GO_LIGHT", "WAIT"}:
        action = "GO_LIGHT"
    return {"action": action, "position_ceiling": cap, "reasons": reasons[:6]}


def _check_gap_protection(
    *,
    yesterday_close: Optional[float],
    today_open: Optional[float],
    nikkei_ref_change_pct: Optional[float],
    overshoot_pct: float = 1.5,
) -> Optional[Dict[str, Any]]:
    """
    缺口保护：如果开盘缺口显著大于指数参考变动，则优先 WAIT，避免“跳空追/抄”误判。

    - gap_pct = (today_open - yesterday_close)/yesterday_close*100
    - 若 gap_pct < nikkei_ref_change_pct - overshoot_pct -> WAIT
    """
    if yesterday_close in (None, 0) or today_open is None or nikkei_ref_change_pct is None:
        return None
    gap_pct = (float(today_open) - float(yesterday_close)) / float(yesterday_close) * 100.0
    if gap_pct < float(nikkei_ref_change_pct) - float(overshoot_pct):
        return {
            "action": "WAIT",
            "position_ceiling": 0.25,
            "reasons": ["GAP_RISK_OVERSHOOT"],
            "evidence": {
                "gap_pct": round(gap_pct, 3),
                "nikkei_ref_change_pct": round(float(nikkei_ref_change_pct), 3),
                "overshoot_pct": float(overshoot_pct),
            },
        }
    return None


def _safe_percentile(values: List[float], current: Optional[float]) -> Optional[float]:
    if current is None:
        return None
    arr = sorted([x for x in values if x is not None])
    if len(arr) < 5:
        return None
    le = sum(1 for x in arr if x <= current)
    return round((le / len(arr)) * 100.0, 2)


def _temperature_band(percentile: Optional[float]) -> Dict[str, Any]:
    if percentile is None:
        return {"band": "unknown", "position_ceiling": 0.6, "label": "历史样本不足"}
    if percentile < 30.0:
        return {"band": "cold", "position_ceiling": 1.0, "label": "低溢价区"}
    if percentile < 60.0:
        return {"band": "normal", "position_ceiling": 0.75, "label": "常态区"}
    if percentile < 85.0:
        return {"band": "warm", "position_ceiling": 0.5, "label": "偏热区"}
    return {"band": "hot", "position_ceiling": 0.25, "label": "高溢价区"}


def _resolve_monitor_context(monitor_point: str, monitor_bundle: Optional[str]) -> Dict[str, Any]:
    mp = str(monitor_point or "M7").strip().upper()
    if mp not in MONITOR_WINDOWS:
        mp = "M7"
    covered: List[str] = [mp]
    if isinstance(monitor_bundle, str) and monitor_bundle.strip():
        bundle = monitor_bundle.strip().upper()
        if bundle == "PROCESS":
            now = _now_sh()
            hhmm = now.strftime("%H:%M")
            # 按时间区间做粗粒度判断，不依赖精确分钟触发
            if "09:00" <= hhmm < "09:30":
                mp = "M1"
            elif "09:30" <= hhmm < "10:00":
                mp = "M2"
            elif "10:00" <= hhmm < "10:30":
                mp = "M3"
            elif "10:30" <= hhmm < "11:30":
                mp = "M4"
            elif "13:00" <= hhmm < "13:30":
                mp = "M5"
            elif "13:30" <= hhmm < "14:30":
                mp = "M6"
            covered = ["M1", "M2", "M3", "M4", "M5", "M6"]
        else:
            parts = [x.strip().upper() for x in monitor_bundle.split("_") if x.strip()]
            covered = [x for x in parts if x in MONITOR_WINDOWS] or [mp]
    return {
        "monitor_point": mp,
        "monitor_bundle": monitor_bundle,
        "covered_points": covered,
        "monitor_label": MONITOR_WINDOWS[mp]["label"],
        "target_window": MONITOR_WINDOWS[mp]["window"],
        "template_focus": MONITOR_TEMPLATE_FOCUS.get(mp, []),
    }


def _predict_intraday_bands(
    latest_price: Optional[float],
    closes: List[float],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    defaults = cfg.get("range_defaults") if isinstance(cfg.get("range_defaults"), dict) else {}
    core_mult = float(defaults.get("band_core_multiplier", 0.8))
    safe_mult = float(defaults.get("band_safe_multiplier", 1.2))
    min_band_pct = float(defaults.get("min_band_pct", 0.35))
    max_band_pct = float(defaults.get("max_band_pct", 2.2))
    if latest_price is None or latest_price <= 0:
        return {
            "core_range": None,
            "safe_range": None,
            "band_pct": None,
            "confidence": 0.0,
            "degraded_reason": "latest_price_unavailable",
        }
    vols: List[float] = []
    if len(closes) >= 10:
        for i in range(max(1, len(closes) - 20), len(closes)):
            p0 = closes[i - 1]
            p1 = closes[i]
            if p0:
                vols.append(abs((p1 - p0) / p0) * 100.0)
    vol_pct = (sum(vols) / len(vols)) if vols else 0.45
    band_pct = max(min_band_pct, min(max_band_pct, vol_pct * 1.35))
    half_core = latest_price * (band_pct / 100.0) * core_mult
    half_safe = latest_price * (band_pct / 100.0) * safe_mult
    core_low = max(0.0, latest_price - half_core)
    core_high = latest_price + half_core
    safe_low = max(0.0, latest_price - half_safe)
    safe_high = latest_price + half_safe
    confidence = 0.78 if len(vols) >= 8 else 0.62
    return {
        "core_range": [round(core_low, 4), round(core_high, 4)],
        "safe_range": [round(safe_low, 4), round(safe_high, 4)],
        "band_pct": round(band_pct, 4),
        "core_width_pct": round(((core_high - core_low) / latest_price) * 100.0, 4),
        "safe_width_pct": round(((safe_high - safe_low) / latest_price) * 100.0, 4),
        "confidence": confidence,
    }


def _classify_action_state(gate_hits: List[str], confidence: float) -> str:
    if not gate_hits and confidence >= 0.72:
        return "GO"
    if confidence >= 0.6:
        return "GO_LIGHT"
    if gate_hits:
        return "WAIT"
    return "EXIT_REDUCE"


def _build_monitor_projection(
    monitor_point: str,
    latest_price: Optional[float],
    range_pred: Dict[str, Any],
) -> Dict[str, Any]:
    core = range_pred.get("core_range") if isinstance(range_pred.get("core_range"), list) else None
    safe = range_pred.get("safe_range") if isinstance(range_pred.get("safe_range"), list) else None
    if latest_price is None or latest_price <= 0 or not core or len(core) != 2:
        return {"projection_label": "分时区间预测", "key_levels": []}

    low, high = float(core[0]), float(core[1])
    center = (low + high) / 2.0
    span = max(high - low, 0.0)
    mp = str(monitor_point or "M7").upper()

    mapping: Dict[str, Tuple[str, List[Tuple[str, float]]]] = {
        "M1": ("今日全天区间", [("day_low", low), ("day_high", high), ("day_center", center)]),
        "M2": ("早盘剩余区间", [("morning_low", low), ("morning_high", high), ("morning_close_ref", center)]),
        "M3": ("收官前结构", [("am_close_low", low), ("am_close_high", high), ("noon_open_ref", center)]),
        "M4": ("午盘完整区间", [("afternoon_low", low), ("afternoon_high", high), ("afternoon_center", center)]),
        "M5": ("下午剩余区间", [("pm_remaining_low", low), ("pm_remaining_high", high), ("t0_takeprofit_ref", center)]),
        "M6": ("尾盘前区间", [("close_window_low", low), ("close_window_high", high), ("overnight_risk_ref", center)]),
        "M7": ("次日开盘区间", [("next_open_low", center - span * 0.35), ("next_open_high", center + span * 0.35), ("next_open_ref", center)]),
    }
    label, rows = mapping.get(mp, ("分时区间预测", [("range_low", low), ("range_high", high), ("range_center", center)]))
    key_levels = [{"name": k, "value": round(v, 4)} for k, v in rows]
    out: Dict[str, Any] = {
        "projection_label": label,
        "key_levels": key_levels,
    }
    if safe and len(safe) == 2:
        out["safe_low"] = round(float(safe[0]), 4)
        out["safe_high"] = round(float(safe[1]), 4)
    return out


def _safe_step(
    name: str,
    fn: Any,
    errors: List[Dict[str, str]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        errors.append({"step": name, "error": str(e)})
        logger.warning("tail_runner step %s failed: %s", name, e, exc_info=True)
        return None


def _load_tail_cfg(market_profile: str = "nikkei_513880") -> Dict[str, Any]:
    try:
        from src.config_loader import load_system_config

        cfg = load_system_config(use_cache=True)
        seg_key = "nasdaq_tail_session_513300" if market_profile == "nasdaq_513300" else "nikkei_tail_session"
        seg = cfg.get(seg_key)
        return seg if isinstance(seg, dict) else {}
    except Exception as e:
        logger.warning("tail_runner load config failed: %s", e)
        return {}


def _load_market_data_cfg() -> Dict[str, Any]:
    try:
        path = Path(__file__).resolve().parents[2] / "config" / "domains" / "market_data.yaml"
        with path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception as e:
        logger.warning("tail_runner load market_data config failed: %s", e)
        return {}


def _yfinance_proxy_ctx():
    try:
        from plugins.utils.proxy_env import proxy_env_for_source
    except Exception:
        from contextlib import nullcontext

        return nullcontext()
    cfg = _load_market_data_cfg()
    return proxy_env_for_source(cfg, "yfinance")


def _resolve_manual_iopv(
    market_cfg: Dict[str, Any],
    etf_code: str,
    trade_date: str,
) -> Optional[Dict[str, Any]]:
    root = market_cfg.get("iopv_fallback") if isinstance(market_cfg.get("iopv_fallback"), dict) else {}
    overrides = root.get("manual_iopv_overrides") if isinstance(root.get("manual_iopv_overrides"), dict) else {}
    seg = overrides.get(str(etf_code))
    if not isinstance(seg, dict):
        return None
    updated_date = str(seg.get("updated_date") or "").strip()
    if not updated_date or updated_date != trade_date:
        return None
    iopv = _safe_float(seg.get("iopv"))
    if iopv is None or iopv <= 0:
        return None
    return {
        "iopv": iopv,
        "updated_date": updated_date,
        "source": str(seg.get("source") or "manual_config"),
    }


def _estimate_iopv(
    market_cfg: Dict[str, Any],
    etf_code: str,
    index_day_ret_pct: Optional[float],
    latest_price: Optional[float],
) -> Optional[Dict[str, Any]]:
    root = market_cfg.get("iopv_fallback") if isinstance(market_cfg.get("iopv_fallback"), dict) else {}
    est_cfg = root.get("estimation") if isinstance(root.get("estimation"), dict) else {}
    if not bool(est_cfg.get("enabled", False)):
        return None
    nav_map = est_cfg.get("etf_nav_baseline") if isinstance(est_cfg.get("etf_nav_baseline"), dict) else {}
    nav_seg = nav_map.get(str(etf_code)) if isinstance(nav_map.get(str(etf_code)), dict) else {}
    nav = _safe_float(nav_seg.get("nav"))
    if nav is None or nav <= 0 or index_day_ret_pct is None:
        return None
    iopv_est = nav * (1.0 + index_day_ret_pct / 100.0)
    if iopv_est <= 0:
        return None
    premium_est = None
    if latest_price is not None and latest_price > 0:
        premium_est = (latest_price - iopv_est) / iopv_est * 100.0
    conf_seg = est_cfg.get("confidence") if isinstance(est_cfg.get("confidence"), dict) else {}
    conf = _safe_float(conf_seg.get("with_nav_and_index"))
    if conf is None:
        conf = 0.55
    return {
        "iopv_est": iopv_est,
        "premium_est": premium_est,
        "est_confidence": conf,
        "basis": {
            "nav": nav,
            "nav_date": str(nav_seg.get("nav_date") or ""),
            "index_day_ret_pct": index_day_ret_pct,
        },
    }


def _calc_rsi14(closes: List[float]) -> Optional[float]:
    if len(closes) < 15:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(x, 0.0) for x in deltas[-14:]]
    losses = [abs(min(x, 0.0)) for x in deltas[-14:]]
    avg_gain = sum(gains) / 14.0
    avg_loss = sum(losses) / 14.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calc_streak_and_return(closes: List[float]) -> Tuple[int, float, Optional[float]]:
    if len(closes) < 2:
        return 0, 0.0, None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    last_sign = 0
    for d in reversed(deltas):
        if d > 0:
            last_sign = 1
            break
        if d < 0:
            last_sign = -1
            break
    if last_sign == 0:
        return 0, 0.0, None
    streak_abs = 0
    for d in reversed(deltas):
        sign = 1 if d > 0 else (-1 if d < 0 else 0)
        if sign != last_sign:
            break
        streak_abs += 1
    streak = last_sign * streak_abs
    base = closes[-2] if len(closes) >= 2 else 0.0
    day_ret = ((closes[-1] - base) / base * 100.0) if base else 0.0
    streak_ret: Optional[float] = None
    if streak != 0:
        start_idx = len(closes) - 1 - abs(streak)
        if 0 <= start_idx < len(closes) and closes[start_idx] != 0:
            streak_ret = (closes[-1] - closes[start_idx]) / closes[start_idx] * 100.0
    return streak, day_ret, streak_ret


def _fetch_yf_index_closes(symbol: str, lookback_days: int = 120) -> List[float]:
    """
    yfinance 后备：用于 global_hist_sina 不支持某些海外指数代码时的日线序列补齐。
    仅返回 close 序列；失败时返回空列表。
    """
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return []

    # yfinance 不可用时，尝试 AkShare 美股指数日线（.IXIC/.DJI/.INX）
    ak_symbol_map = {
        "^IXIC": ".IXIC",
        "^DJI": ".DJI",
        "^GSPC": ".INX",
    }
    ak_symbol = ak_symbol_map.get(str(symbol).strip().upper())
    if not ak_symbol:
        return []
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return []
    try:
        df = ak.index_us_stock_sina(symbol=ak_symbol)  # type: ignore[union-attr]
        if df is None or getattr(df, "empty", True):
            return []
        close_col = None
        for c in ("close", "收盘", "收盘价", "最新价"):
            if c in df.columns:
                close_col = c
                break
        if close_col is None:
            return []
        closes: List[float] = []
        for v in list(df[close_col]):
            x = _safe_float(v)
            if x is not None:
                closes.append(x)
        if len(closes) > lookback_days:
            closes = closes[-lookback_days:]
        return closes
    except Exception:
        return []
    try:
        with _yfinance_proxy_ctx():
            t = yf.Ticker(symbol)
            # 6mo 基本覆盖 120 个交易日窗口
            hist = t.history(period="6mo")
        if hist is None or getattr(hist, "empty", True):
            return []
        closes: List[float] = []
        col = hist.get("Close")
        if col is None:
            return []
        for v in list(col):
            x = _safe_float(v)
            if x is not None:
                closes.append(x)
        if len(closes) > lookback_days:
            closes = closes[-lookback_days:]
        return closes
    except Exception:
        return []


def _fetch_nikkei_futures_snapshot() -> Dict[str, Any]:
    """
    期指参考层（非强依赖）：
    - 优先 NIY=F（JPY 计价）
    - 备选 NKD=F（USD 计价）
    失败时返回 unavailable，不影响主流程。
    """
    symbols = ("NIY=F", "NKD=F")
    try:
        import yfinance as yf  # type: ignore
    except Exception as e:
        return {"status": "unavailable", "reason": f"import_error:{e}"}

    for sym in symbols:
        try:
            with _yfinance_proxy_ctx():
                t = yf.Ticker(sym)
                fi = getattr(t, "fast_info", {}) or {}
            last = _safe_float(fi.get("lastPrice"))
            prev = _safe_float(fi.get("previousClose"))
            day_high = _safe_float(fi.get("dayHigh"))
            day_low = _safe_float(fi.get("dayLow"))
            if last is None:
                with _yfinance_proxy_ctx():
                    hist = t.history(period="2d", interval="1h")
                if hist is not None and not getattr(hist, "empty", True):
                    last = _safe_float(hist["Close"].iloc[-1])
                    if len(hist) >= 2:
                        prev = _safe_float(hist["Close"].iloc[-2])
                    if day_high is None:
                        day_high = _safe_float(hist["High"].max())
                    if day_low is None:
                        day_low = _safe_float(hist["Low"].min())
            if last is None:
                continue
            change_pct = ((last - prev) / prev * 100.0) if (prev is not None and prev != 0) else None
            return {
                "status": "ok",
                "symbol": sym,
                "price": last,
                "prev_close": prev,
                "change_pct": change_pct,
                "day_high": day_high,
                "day_low": day_low,
                "exchange": str(fi.get("exchange") or ""),
                "currency": str(fi.get("currency") or ""),
            }
        except Exception:
            continue
    return {"status": "unavailable", "reason": "all_symbols_failed"}


def _fetch_nq_futures_snapshot() -> Dict[str, Any]:
    try:
        import yfinance as yf  # type: ignore
    except Exception as e:
        return {"status": "unavailable", "reason": f"import_error:{e}"}
    try:
        with _yfinance_proxy_ctx():
            ticker = yf.Ticker("NQ=F")
            fi = getattr(ticker, "fast_info", {}) or {}
        last = _safe_float(fi.get("lastPrice"))
        prev = _safe_float(fi.get("previousClose"))
        if last is None:
            with _yfinance_proxy_ctx():
                hist = ticker.history(period="2d", interval="15m")
            if hist is not None and not getattr(hist, "empty", True):
                last = _safe_float(hist["Close"].iloc[-1])
                if len(hist) >= 2:
                    prev = _safe_float(hist["Close"].iloc[-2])
        if last is None:
            return {"status": "unavailable", "reason": "no_quote"}
        change_pct = ((last - prev) / prev * 100.0) if (prev is not None and prev != 0) else None
        return {"status": "ok", "symbol": "NQ=F", "price": last, "prev_close": prev, "change_pct": change_pct}
    except Exception as e:
        return {"status": "unavailable", "reason": f"query_error:{e}"}


def _nasdaq_futures_weight(monitor_point: str) -> float:
    mapping = {
        "M1": 0.20,
        "M2": 0.35,
        "M3": 0.50,
        "M4": 0.60,
        "M5": 0.75,
        "M6": 0.90,
        "M7": 1.0,
    }
    return float(mapping.get(str(monitor_point or "M7").upper(), 1.0))


def _resolve_action_from_deviation(
    deviation_pct: Optional[float],
    nq_futures_15m_pct: Optional[float],
    tug_of_war_pct: Optional[float],
) -> Tuple[str, List[str]]:
    hits: List[str] = []
    if deviation_pct is not None:
        if deviation_pct > 2.0:
            hits.append("R1")
        elif deviation_pct > 0.5:
            hits.append("R2")
        elif deviation_pct < -2.0:
            hits.append("R3")
    if tug_of_war_pct is not None and abs(tug_of_war_pct) >= 1.0:
        hits.append("R4")
    if nq_futures_15m_pct is not None and abs(nq_futures_15m_pct) > 1.0:
        hits.append("R5")

    if "R1" in hits:
        return "WAIT", hits
    if "R5" in hits:
        return "WAIT", hits
    if "R4" in hits:
        return "WAIT", hits
    if "R2" in hits:
        return "GO_LIGHT", hits
    if "R3" in hits:
        return "GO_LIGHT", hits
    return "GO", hits


def _build_nikkei_pattern_alerts(
    monitor_point: str,
    deviation_pct: Optional[float],
    action_state: str,
    used_futures_fallback: bool,
) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    mp = str(monitor_point or "").upper()
    if deviation_pct is not None and deviation_pct > 2.0:
        alerts.append(
            {
                "rule_id": "R1",
                "severity": "high",
                "recommended_action": action_state,
                "evidence": f"deviation_pct={deviation_pct:.2f}% > 2.00%",
                "message": "ETF相对日经指数偏离过大，溢价风险升高，暂停追高。",
            }
        )
    elif deviation_pct is not None and deviation_pct > 0.5:
        alerts.append(
            {
                "rule_id": "R2",
                "severity": "medium",
                "recommended_action": action_state,
                "evidence": f"0.50% < deviation_pct={deviation_pct:.2f}% <= 2.00%",
                "message": "ETF相对指数轻度偏高，建议降仓或分批执行。",
            }
        )
    elif deviation_pct is not None and deviation_pct < -2.0:
        alerts.append(
            {
                "rule_id": "R3",
                "severity": "medium",
                "recommended_action": action_state,
                "evidence": f"deviation_pct={deviation_pct:.2f}% < -2.00%",
                "message": "ETF相对指数出现折价，关注修复机会但避免重仓。",
            }
        )
    if mp == "M2" and deviation_pct is not None and deviation_pct > 1.5 and len(alerts) < 3:
        alerts.append(
            {
                "rule_id": "JP_M2",
                "severity": "medium",
                "recommended_action": action_state,
                "evidence": f"M2 deviation_pct={deviation_pct:.2f}%",
                "message": "开盘偏离较大，警惕情绪透支导致回撤。",
            }
        )
    if mp == "M6" and deviation_pct is not None and deviation_pct > 2.0 and len(alerts) < 3:
        alerts.append(
            {
                "rule_id": "JP_M6",
                "severity": "high",
                "recommended_action": "EXIT_REDUCE",
                "evidence": f"M6 deviation_pct={deviation_pct:.2f}%",
                "message": "尾盘仍高偏离，建议减仓/不留隔夜，防范溢价回落。",
            }
        )
    if used_futures_fallback and len(alerts) < 3:
        alerts.append(
            {
                "rule_id": "JP_FALLBACK",
                "severity": "medium",
                "recommended_action": action_state,
                "evidence": "nikkei_spot_unavailable -> futures_fallback",
                "message": "日经指数实时不可用，当前基于期指代理判断，建议保守执行。",
            }
        )
    return alerts[:3]


def _build_nasdaq_pattern_alerts(
    deviation_pct: Optional[float],
    tug_of_war_pct: Optional[float],
    nq_futures_15m_pct: Optional[float],
    action_state: str,
) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []
    if deviation_pct is not None and deviation_pct > 2.0:
        alerts.append(
            {
                "rule_id": "R1",
                "severity": "high",
                "recommended_action": action_state,
                "evidence": f"deviation_pct={deviation_pct:.2f}% > 2.00%",
                "message": "显著溢价代理，暂停新增（WAIT）",
            }
        )
    elif deviation_pct is not None and deviation_pct > 0.5:
        alerts.append(
            {
                "rule_id": "R2",
                "severity": "medium",
                "recommended_action": action_state,
                "evidence": f"0.50% < deviation_pct={deviation_pct:.2f}% <= 2.00%",
                "message": "轻度溢价代理，降仓执行（GO_LIGHT）",
            }
        )
    elif deviation_pct is not None and deviation_pct < -2.0:
        alerts.append(
            {
                "rule_id": "R3",
                "severity": "medium",
                "recommended_action": action_state,
                "evidence": f"deviation_pct={deviation_pct:.2f}% < -2.00%",
                "message": "折价代理，关注分批修复（轻仓）",
            }
        )
    if tug_of_war_pct is not None and abs(tug_of_war_pct) >= 1.0 and len(alerts) < 3:
        alerts.append(
            {
                "rule_id": "R4",
                "severity": "medium",
                "recommended_action": action_state,
                "evidence": f"abs(intraday_pct-overnight_proxy_pct)={abs(tug_of_war_pct):.2f}% >= 1.00%",
                "message": "隔夜-日间拉锯，警惕修正",
            }
        )
    if nq_futures_15m_pct is not None and abs(nq_futures_15m_pct) > 1.0 and len(alerts) < 3:
        alerts.append(
            {
                "rule_id": "R5",
                "severity": "high",
                "recommended_action": action_state,
                "evidence": f"abs(nq_futures_15m_pct)={abs(nq_futures_15m_pct):.2f}% > 1.00%",
                "message": "期指波动过大，暂停新增建议（WAIT优先）",
            }
        )
    return alerts[:3]


def _layer_cycle(ma25_dev: Optional[float], rsi14: Optional[float], close: Optional[float], ma25: Optional[float]) -> Dict[str, Any]:
    regime = "震荡"
    if close is not None and ma25 is not None:
        if close > ma25 and (rsi14 is None or rsi14 < 70):
            regime = "上升"
        elif close < ma25 and (rsi14 is not None and rsi14 <= 45):
            regime = "下行"
    return {
        "layer": "cycle",
        "regime": regime,
        "signals": {"ma25_dev_pct": ma25_dev, "rsi14": rsi14},
        "options": ["hold", "buy_light"] if regime == "上升" else (["hold", "reduce"] if regime == "下行" else ["hold"]),
    }


def _layer_timing(streak: int, premium_pct: Optional[float], rsi14: Optional[float], ma25_dev: Optional[float], cfg: Dict[str, Any]) -> Dict[str, Any]:
    tech_cfg = cfg.get("technical_thresholds") if isinstance(cfg.get("technical_thresholds"), dict) else {}
    st_cfg = cfg.get("streak_thresholds") if isinstance(cfg.get("streak_thresholds"), dict) else {}
    up_days = int(st_cfg.get("up_days", 5))
    down_days = int(st_cfg.get("down_days", 3))
    overbought = float(tech_cfg.get("rsi_overbought", 70))
    ma_over = float(tech_cfg.get("ma25_dev_overheat", 5.0))

    options: List[str] = ["hold"]
    reasons: List[str] = []
    if premium_pct is not None and premium_pct < 0 and streak <= -down_days:
        options = ["buy_light", "hold"]
        reasons.append("连跌+折价")
    if streak >= up_days or ((rsi14 is not None and rsi14 >= overbought) or (ma25_dev is not None and ma25_dev >= ma_over)):
        options = ["reduce", "hold"]
        reasons.append("过热/连续上涨")
    return {
        "layer": "timing",
        "signals": {"streak": streak, "premium_pct": premium_pct, "rsi_overbought": overbought, "ma25_dev_overheat": ma_over},
        "options": options,
        "reasons": reasons,
    }


def _layer_risk(premium_pct: Optional[float], liquidity_amount: Optional[float], manager_notice: bool, cfg: Dict[str, Any]) -> Dict[str, Any]:
    g = cfg.get("gate_rules") if isinstance(cfg.get("gate_rules"), dict) else {}
    p5 = float(((g.get("premium_hard_stop") or {}).get("trigger") or {}).get("premium_pct_gte", 5.0))
    p10 = float(((g.get("premium_extreme_exit_bias") or {}).get("trigger") or {}).get("premium_pct_gte", 10.0))
    liq_cfg = g.get("liquidity_guard_gate") if isinstance(g.get("liquidity_guard_gate"), dict) else {}
    min_amt = float((((liq_cfg.get("trigger") or {}).get("min_amount_yuan_lte")) or 2e7))

    gate_hits: List[str] = []
    options = ["hold", "reduce", "exit_wait"]
    if premium_pct is not None and premium_pct >= p10:
        gate_hits.append("premium_extreme")
    elif premium_pct is not None and premium_pct >= p5:
        gate_hits.append("premium_hard_stop")
    if manager_notice and premium_pct is not None and premium_pct >= 3.0:
        gate_hits.append("fund_manager_notice")
    if liquidity_amount is not None and liquidity_amount <= min_amt:
        gate_hits.append("poor_liquidity")
    if not gate_hits:
        options = ["hold", "buy_light", "reduce"]
    return {"layer": "risk", "gate_hits": gate_hits, "options": options}


def _resolve_decision_options(layer_cycle: Dict[str, Any], layer_timing: Dict[str, Any], layer_risk: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    profiles = cfg.get("option_profiles") if isinstance(cfg.get("option_profiles"), dict) else {}
    conservative = profiles.get("conservative") if isinstance(profiles.get("conservative"), dict) else {}
    neutral = profiles.get("neutral") if isinstance(profiles.get("neutral"), dict) else {}
    aggressive = profiles.get("aggressive") if isinstance(profiles.get("aggressive"), dict) else {}

    risk_options = set(layer_risk.get("options") or [])

    def _pick(profile: Dict[str, Any], fallback: str) -> str:
        arr = profile.get("preferred_actions") if isinstance(profile.get("preferred_actions"), list) else []
        for x in arr:
            if x in risk_options:
                return str(x)
        return fallback

    return {
        "conservative": {"action": _pick(conservative, "hold"), "max_position_pct": conservative.get("max_position_pct", 20)},
        "neutral": {"action": _pick(neutral, "hold"), "max_position_pct": neutral.get("max_position_pct", 40)},
        "aggressive": {"action": _pick(aggressive, "hold"), "max_position_pct": aggressive.get("max_position_pct", 60)},
        "layer_conflicts": {
            "cycle_options": layer_cycle.get("options"),
            "timing_options": layer_timing.get("options"),
            "risk_options": layer_risk.get("options"),
        },
    }


def _build_risk_notices(payload: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    rules = cfg.get("risk_notice_rules") if isinstance(cfg.get("risk_notice_rules"), dict) else {}
    notices: List[str] = []
    premium = _safe_float(payload.get("premium_pct"))
    rsi14 = _safe_float(payload.get("rsi14"))
    ma25_dev = _safe_float(payload.get("ma25_dev_pct"))
    manager_notice = bool(payload.get("manager_premium_notice"))
    data_quality = str(payload.get("data_quality") or "fresh")

    for _, block in rules.items():
        if not isinstance(block, dict):
            continue
        when = block.get("when") if isinstance(block.get("when"), dict) else {}
        msg = str(block.get("message") or "").strip()
        if not msg:
            continue
        ok = False
        if "premium_pct_gte" in when and premium is not None and premium >= float(when["premium_pct_gte"]):
            ok = True
        if "premium_pct_lt" in when and premium is not None and premium < float(when["premium_pct_lt"]):
            ok = True
        if "rsi14_gte" in when and rsi14 is not None and rsi14 >= float(when["rsi14_gte"]):
            ok = True
        if "ma25_dev_pct_gte" in when and ma25_dev is not None and ma25_dev >= float(when["ma25_dev_pct_gte"]):
            ok = True
        if "manager_premium_notice" in when and manager_notice == bool(when["manager_premium_notice"]):
            ok = True
        if "data_quality_in" in when and data_quality in [str(x) for x in (when.get("data_quality_in") or [])]:
            ok = True
        if ok:
            notices.append(msg)
    dedup: List[str] = []
    seen = set()
    for x in notices:
        if x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup


def build_tail_session_report_data(
    fetch_mode: str = "production",
    market_profile: str = "nikkei_513880",
    monitor_point: str = "M7",
    monitor_bundle: Optional[str] = None,
    workflow_profile: str = "legacy",
    stage_budget_profile: str = "balanced",
    emit_stage_timing: bool = True,
    max_concurrency: int = 3,
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    errors: List[Dict[str, str]] = []
    profile = (workflow_profile or "").strip().lower()
    enable_optimized = profile == "cron_balanced"
    budgets = _stage_budget_profile(stage_budget_profile) if enable_optimized else _stage_budget_profile("off")
    stage_timing: Dict[str, Dict[str, Any]] = {}
    lineage_struct: List[Dict[str, Any]] = []
    degraded_stages: List[str] = []
    skipped_tasks: Dict[str, List[str]] = {"critical": [], "slow_sources": [], "analytics": []}
    memo_cache: Dict[str, Any] = {}
    sem_pool = _semaphore_pool(max_concurrency=max_concurrency)

    def _mark_stage_degraded(stage: str) -> None:
        if stage not in degraded_stages:
            degraded_stages.append(stage)

    stage_budget = {
        "critical": _StageBudget(budgets.get("critical")),
        "slow_sources": _StageBudget(budgets.get("slow_sources")),
        "analytics": _StageBudget(budgets.get("analytics")),
    }
    stage_started_at: Dict[str, float] = {}

    def _call_tool(stage: str, step_name: str, fn: Any, *args: Any, source_hint: Optional[str] = None, **kwargs: Any) -> Any:
        started_at = time.perf_counter()
        if stage not in stage_started_at:
            stage_started_at[stage] = started_at
        sb = stage_budget.get(stage)
        if enable_optimized and sb and sb.expired():
            skipped_tasks[stage].append(step_name)
            _mark_stage_degraded(stage)
            _append_lineage(
                lineage_struct,
                stage=stage,
                tool_key=step_name,
                started_at=started_at,
                success=None,
                quality_status="degraded",
                degraded_reason="timeout",
                source_hint=source_hint or _provider_key_for_step(step_name),
            )
            return None
        mk = _memo_key(fn, args, kwargs)
        if enable_optimized and mk in memo_cache:
            cached = memo_cache[mk]
            _append_lineage(
                lineage_struct,
                stage=stage,
                tool_key=f"{step_name}:memo",
                started_at=started_at,
                success=True,
                quality_status="ok",
                degraded_reason=None,
                source_hint=source_hint or _provider_key_for_step(step_name),
            )
            return cached
        provider = _provider_key_for_step(step_name)
        sem = sem_pool.get(provider) or sem_pool["default"]
        try:
            with sem:
                out = _safe_step(step_name, fn, errors, *args, **kwargs)
        except Exception as e:
            errors.append({"step": step_name, "error": str(e)})
            out = None
        success = bool(isinstance(out, dict) and out.get("success"))
        q = "ok" if success else "degraded"
        reason = None if success else "fetch_failed_or_empty"
        if not success and enable_optimized:
            _mark_stage_degraded(stage)
        _append_lineage(
            lineage_struct,
            stage=stage,
            tool_key=step_name,
            started_at=started_at,
            success=success,
            quality_status=q,
            degraded_reason=reason,
            source_hint=source_hint or provider,
        )
        if enable_optimized:
            memo_cache[mk] = out
        return out

    cfg = _load_tail_cfg(market_profile)
    market_cfg = _load_market_data_cfg()
    mode = fetch_mode if fetch_mode in ("production", "test") else "production"
    if market_profile == "nasdaq_513300":
        etf_code = "513300"
        index_symbol = "^IXIC"
    else:
        etf_code = str(cfg.get("etf_code") or "513880")
        index_symbol = str(cfg.get("index_symbol") or "^N225")

    from plugins.data_collection.utils.check_trading_status import tool_check_trading_status
    from plugins.merged.fetch_etf_data import tool_fetch_etf_data
    from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_iopv_snapshot
    from plugins.merged.fetch_index_data import tool_fetch_index_data
    from plugins.data_collection.index.fetch_global_hist_sina import tool_fetch_global_index_hist_sina
    from plugins.notification.run_opening_analysis import _safe_step as open_safe_step  # 保持统一错误记录形式

    safe = open_safe_step if callable(open_safe_step) else _safe_step

    monitor_ctx = _resolve_monitor_context(monitor_point, monitor_bundle)
    mp = str(monitor_ctx.get("monitor_point") or "M7")
    monitor_ctx["template_mode"] = "full" if mp in {"M1", "M7"} else "quick"
    rd: Dict[str, Any] = {
        "report_type": "tail_session",
        "runner_version": "tail_session_analysis_v1",
        "market_profile": market_profile,
        "monitor_context": monitor_ctx,
    }
    stage_p95_targets = {
        "nasdaq_513300": {
            "PROCESS": {"critical": 85.0, "slow_sources": 95.0, "analytics": 80.0},
            "M7": {"critical": 60.0, "slow_sources": 70.0, "analytics": 55.0},
        }
    }
    now = _now_sh()
    rd["date"] = now.strftime("%Y-%m-%d")
    rd["trade_date"] = rd["date"]
    rd["generated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

    # 非交易日：对齐到最近 A 股交易日，避免 realtime/IOPV 门禁导致整段 N/A
    # 说明：fetch_mode=test 用于单测/烟测，不应受真实日历影响（否则周末跑测试会误降级）。
    effective_trade_yyyymmdd: Optional[str] = None
    effective_trade_dash: Optional[str] = None
    non_trading_calendar_day = False
    try:
        from src.system_status import get_last_trading_day_on_or_before, is_trading_day

        if mode != "test" and not is_trading_day(now, None):
            non_trading_calendar_day = True
            effective_trade_yyyymmdd = get_last_trading_day_on_or_before(now, None)
            effective_trade_dash = _yyyymmdd_dash(effective_trade_yyyymmdd or "")
    except Exception:
        non_trading_calendar_day = False

    if non_trading_calendar_day and effective_trade_dash:
        rd["date"] = effective_trade_dash
        rd["trade_date"] = effective_trade_dash
        rd["non_trading_calendar_day"] = True
        rd["data_basis"] = "last_trading_day"
        rd["data_reference_yyyymmdd"] = effective_trade_yyyymmdd

    ts = _call_tool("critical", "check_trading_status", tool_check_trading_status, source_hint="calendar")
    if ts is not None:
        rd["trading_status"] = ts

    iopv = None
    etf_rt = None
    if not non_trading_calendar_day:
        iopv = _call_tool("critical", "fetch_etf_iopv_snapshot", tool_fetch_etf_iopv_snapshot, etf_code=etf_code, source_hint="etf")
        if iopv is not None:
            rd["tool_fetch_etf_iopv_snapshot"] = iopv

        etf_rt = _call_tool(
            "critical",
            "fetch_etf_realtime",
            tool_fetch_etf_data,
            data_type="realtime",
            etf_code=etf_code,
            mode=mode,
            source_hint="etf",
        )
        if etf_rt is not None:
            rd["tool_fetch_etf_realtime"] = etf_rt

    etf_hist = _call_tool(
        "critical",
        "fetch_etf_historical",
        tool_fetch_etf_data,
        data_type="historical",
        etf_code=etf_code,
        start_date=_hist_start_yyyymmdd(effective_trade_yyyymmdd, 220) if (non_trading_calendar_day and effective_trade_yyyymmdd) else None,
        end_date=effective_trade_yyyymmdd if (non_trading_calendar_day and effective_trade_yyyymmdd) else None,
        source_hint="etf",
    )
    if etf_hist is not None:
        rd["tool_fetch_etf_historical"] = etf_hist

    index_hist_symbol = index_symbol
    if market_profile == "nasdaq_513300":
        # 对齐 513880 方案：使用 name_table 稳定可识别的指数名称，避免 ^IXIC 在部分环境下不可解析
        index_hist_symbol = "纳斯达克"
    index_hist = _call_tool(
        "critical",
        "fetch_index_hist",
        tool_fetch_global_index_hist_sina,
        symbol=index_hist_symbol,
        limit=90,
        source_hint="akshare_sina",
    )
    if index_hist is not None:
        rd["tool_fetch_index_hist"] = index_hist

    overnight = None
    if enable_optimized and max_concurrency > 1:
        with ThreadPoolExecutor(max_workers=max(1, int(max_concurrency))) as ex:
            future_map = {
                ex.submit(
                    _call_tool,
                    "slow_sources",
                    "fetch_global_spot_for_overnight",
                    tool_fetch_index_data,
                    data_type="global_spot",
                    mode=mode,
                    index_codes="^IXIC,^DJI,^N225",
                    source_hint="global_spot",
                ): "fetch_global_spot_for_overnight"
            }
            for fut in as_completed(future_map):
                try:
                    overnight = fut.result()
                except Exception as e:
                    errors.append({"step": future_map[fut], "error": str(e)})
    else:
        overnight = _call_tool(
            "slow_sources",
            "fetch_global_spot_for_overnight",
            tool_fetch_index_data,
            data_type="global_spot",
            mode=mode,
            index_codes="^IXIC,^DJI,^N225",
            source_hint="global_spot",
        )
    if overnight is not None:
        rd["tool_fetch_global_index_spot"] = overnight

    iopv_row = (iopv or {}).get("data") if isinstance(iopv, dict) else {}
    if isinstance(iopv_row, list):
        iopv_row = iopv_row[0] if iopv_row else {}
    rt_row = (etf_rt or {}).get("data") if isinstance(etf_rt, dict) else {}
    if isinstance(rt_row, list):
        rt_row = rt_row[0] if rt_row else {}

    # 非交易日：实时价不可得时取最近交易日收盘价作为 latest_price 口径
    last_bar = _etf_hist_last_kline(etf_hist) if isinstance(etf_hist, dict) else None
    hist_close = _safe_float((last_bar or {}).get("close")) if isinstance(last_bar, dict) else None
    hist_amount = _safe_float((last_bar or {}).get("amount")) if isinstance(last_bar, dict) else None

    latest_price = (
        _safe_float((rt_row or {}).get("current_price"))
        or _safe_float((iopv_row or {}).get("latest_price"))
        or hist_close
    )
    premium_pct = _safe_float((iopv_row or {}).get("discount_pct"))
    if premium_pct is not None:
        premium_pct = -premium_pct
    iopv_val = _safe_float((iopv_row or {}).get("iopv"))
    amount = _safe_float((rt_row or {}).get("amount")) or hist_amount

    hist_rows = []
    if isinstance(index_hist, dict):
        data = index_hist.get("data")
        if isinstance(data, list):
            hist_rows = [x for x in data if isinstance(x, dict)]
    closes: List[float] = []
    for r in hist_rows:
        c = _safe_float(r.get("close"))
        if c is not None:
            closes.append(c)
    if not closes and market_profile == "nasdaq_513300":
        yf_closes = _fetch_yf_index_closes("^IXIC", lookback_days=120)
        if yf_closes:
            closes = yf_closes
            rd["tool_fetch_index_hist_yf_fallback"] = {
                "success": True,
                "source": "yfinance",
                "symbol": "^IXIC",
                "count": len(yf_closes),
            }
    # 技术指标/连涨连跌口径：
    # - 默认与 513880 一致，统一基于对应指数历史序列（index_hist）
    # - 仅在非 nasdaq_513300 场景下，才允许回退到 ETF 历史序列，避免 513300 与 ^IXIC 口径混用
    if not closes and market_profile != "nasdaq_513300" and isinstance(etf_hist, dict):
        etf_hist_data = etf_hist.get("data")
        etf_hist_rows = None
        if isinstance(etf_hist_data, dict):
            etf_hist_rows = etf_hist_data.get("klines")
        elif isinstance(etf_hist_data, list):
            etf_hist_rows = etf_hist_data
        if isinstance(etf_hist_rows, list):
            for r in etf_hist_rows:
                if not isinstance(r, dict):
                    continue
                c = _safe_float(r.get("close"))
                if c is None:
                    c = _safe_float(r.get("current_price"))
                if c is not None:
                    closes.append(c)
    ma_window = 25 if len(closes) >= 25 else (len(closes) if len(closes) >= 5 else 0)
    ma25 = (sum(closes[-ma_window:]) / float(ma_window)) if ma_window > 0 else None
    close = closes[-1] if closes else None
    ma25_dev = ((close - ma25) / ma25 * 100.0) if (close is not None and ma25 not in (None, 0.0)) else None
    rsi14 = _calc_rsi14(closes)
    streak, day_ret, streak_ret = _calc_streak_and_return(closes)
    index_close = close
    index_day_ret_pct = day_ret
    if market_profile in {"nasdaq_513300", "nikkei_513880"} and isinstance(overnight, dict):
        spot_rows = overnight.get("data")
        if isinstance(spot_rows, list):
            target_code = "^IXIC" if market_profile == "nasdaq_513300" else "^N225"
            target_row = next(
                (
                    x
                    for x in spot_rows
                    if isinstance(x, dict) and str(x.get("code") or "").strip().upper() == target_code
                ),
                None,
            )
            if isinstance(target_row, dict):
                idx_price = _safe_float(target_row.get("price"))
                if idx_price is None:
                    idx_price = _safe_float(target_row.get("latest_price"))
                idx_ret = _safe_float(target_row.get("change_pct"))
                if not hist_rows and idx_price is not None:
                    index_close = idx_price
                if idx_ret is not None:
                    index_day_ret_pct = idx_ret

    # 日经/纳指：期指快照用于偏离代理与日经指数回退
    if market_profile == "nikkei_513880":
        futures_ref = _call_tool(
            "slow_sources",
            "fetch_nikkei_futures_snapshot",
            _fetch_nikkei_futures_snapshot,
            source_hint="yfinance",
        ) or {}
    else:
        futures_ref = _call_tool(
            "slow_sources",
            "fetch_nq_futures_snapshot",
            _fetch_nq_futures_snapshot,
            source_hint="yfinance",
        ) or {}

    iopv_source = "realtime" if (iopv_val is not None and premium_pct is not None) else "unavailable"
    manual_iopv = _resolve_manual_iopv(market_cfg, etf_code=etf_code, trade_date=rd["trade_date"])
    iopv_est_pack = _estimate_iopv(market_cfg, etf_code=etf_code, index_day_ret_pct=index_day_ret_pct, latest_price=latest_price)
    if iopv_source != "realtime" and manual_iopv is not None:
        iopv_val = _safe_float(manual_iopv.get("iopv"))
        premium_pct = ((latest_price - iopv_val) / iopv_val * 100.0) if (latest_price and iopv_val) else None
        iopv_source = "manual"
    elif iopv_source != "realtime" and iopv_est_pack is not None:
        iopv_val = _safe_float(iopv_est_pack.get("iopv_est"))
        premium_pct = _safe_float(iopv_est_pack.get("premium_est"))
        iopv_source = "estimated"
    if market_profile == "nikkei_513880":
        # 日经场景：以「理论NAV」作为 IOPV 展示口径；premium_pct 为理论溢价率（%）。
        fundgz = _call_tool(
            "slow_sources",
            "fetch_fundgz_snapshot_nikkei",
            _fetch_fundgz_snapshot,
            etf_code=etf_code,
            timeout_seconds=5.0,
            source_hint="fundgz",
        ) or {}
        fundgz_official_nav = _safe_float(fundgz.get("official_nav")) if isinstance(fundgz, dict) else None
        fundgz_nav_date = str(fundgz.get("nav_date") or "").strip() if isinstance(fundgz, dict) else ""
        # 手工兜底：复用 manual_iopv_overrides.iopv 作为昨日NAV（配置命名历史原因），标记为 degraded
        manual_nav = _safe_float((manual_iopv or {}).get("iopv")) if isinstance(manual_iopv, dict) else None
        yesterday_nav = fundgz_official_nav if (fundgz_official_nav is not None and fundgz_official_nav > 0) else manual_nav
        nav_source = "fundgz_official_nav" if yesterday_nav == fundgz_official_nav else ("manual_iopv_override_as_nav" if yesterday_nav == manual_nav else "unavailable")
        idx_change_pct = _safe_float(index_day_ret_pct)
        idx_source = "nikkei_index_spot" if idx_change_pct is not None else "unavailable"
        # 若 spot 不可用，回退期指变化
        if idx_change_pct is None:
            idx_change_pct = _safe_float(futures_ref.get("change_pct"))
            if idx_change_pct is not None:
                idx_source = "nikkei_futures_fallback"
        prem_pack = _calc_nikkei_theoretical_premium(
            latest_price=latest_price,
            yesterday_nav=yesterday_nav,
            index_change_pct=idx_change_pct,
        )
        premium_quality = "ok"
        if prem_pack.get("status") != "ok":
            premium_quality = "error"
            premium_pct = None
            iopv_val = None
        else:
            iopv_val = _safe_float(prem_pack.get("theoretical_nav"))
            premium_pct = _safe_float(prem_pack.get("premium_rate_pct"))
            premium_quality = "ok"
            # 源降级规则
            if nav_source != "fundgz_official_nav" or idx_source != "nikkei_index_spot":
                premium_quality = "degraded"
            # NAV 日期不匹配也降级（fundgz 偶有延迟）
            if nav_source == "fundgz_official_nav" and fundgz_nav_date and str(rd.get("trade_date") or "") == fundgz_nav_date:
                # dwjz 通常是“昨日净值”，当天一致多为异常/盘中未更新口径，保守降级
                premium_quality = "degraded"
        rd["analysis_premium"] = {
            "quality_status": premium_quality,
            "nav_source": nav_source,
            "nav_date": fundgz_nav_date,
            "yesterday_nav": yesterday_nav,
            "index_change_pct": idx_change_pct,
            "index_source": idx_source,
            "theoretical_nav": prem_pack.get("theoretical_nav") if prem_pack.get("status") == "ok" else None,
            "premium_rate_pct": premium_pct,
            "reason": prem_pack.get("reason"),
        }
        iopv_source = "theoretical_nav"
    elif market_profile == "nasdaq_513300":
        # 纳指场景仍以偏离代理门禁为主，但保留 IOPV 展示口径（若可得）
        if iopv_source == "unavailable":
            iopv_source = "proxy_deviation"
    valuation_blend: Dict[str, Any] = {}

    manager_notice = bool((cfg.get("risk_notice_state") or {}).get("manager_premium_notice", False))
    resolved_mp = str(monitor_ctx.get("monitor_point") or "M7")
    overnight_proxy_pct = _safe_float(index_day_ret_pct)
    etf_actual_pct = _safe_float((rt_row or {}).get("change_pct"))
    if etf_actual_pct is None and latest_price is not None and hist_close not in (None, 0):
        etf_actual_pct = (latest_price - float(hist_close)) / float(hist_close) * 100.0
    if etf_actual_pct is None and latest_price is not None:
        # 最低可用口径：当实时涨跌幅缺失且无法由昨收推导时，保守回填 0.0，避免下游字段缺口。
        etf_actual_pct = 0.0
    futures_change_pct = _safe_float(futures_ref.get("change_pct"))
    futures_weight = _nasdaq_futures_weight(resolved_mp) if market_profile == "nasdaq_513300" else 0.0
    beta_track = float((cfg.get("deviation_proxy") or {}).get("beta_track", 0.95)) if isinstance(cfg.get("deviation_proxy"), dict) else 0.95
    fx_adj_pct = float((cfg.get("deviation_proxy") or {}).get("fx_adj_pct", 0.0)) if isinstance(cfg.get("deviation_proxy"), dict) else 0.0
    etf_expected_pct: Optional[float] = None
    deviation_pct: Optional[float] = None
    deviation_trend = "sideways"
    used_futures_fallback = False
    if market_profile == "nasdaq_513300" and overnight_proxy_pct is not None:
        etf_expected_pct = (overnight_proxy_pct + futures_weight * float(futures_change_pct or 0.0)) * beta_track + fx_adj_pct
        if etf_actual_pct is not None:
            deviation_pct = etf_actual_pct - etf_expected_pct
            if deviation_pct > 0.3:
                deviation_trend = "expanding"
            elif deviation_pct < -0.3:
                deviation_trend = "converging"
    elif market_profile == "nikkei_513880":
        if overnight_proxy_pct is not None:
            etf_expected_pct = overnight_proxy_pct
        elif futures_change_pct is not None:
            etf_expected_pct = futures_change_pct
            used_futures_fallback = True
        if etf_expected_pct is not None and etf_actual_pct is not None:
            deviation_pct = etf_actual_pct - etf_expected_pct
            if deviation_pct > 0.3:
                deviation_trend = "expanding"
            elif deviation_pct < -0.3:
                deviation_trend = "converging"
    if market_profile == "nasdaq_513300":
        fundgz_fresh_ok_seconds = int(cfg.get("fundgz_fresh_ok_seconds", 180))
        fundgz_fresh_degrade_seconds = int(cfg.get("fundgz_fresh_degrade_seconds", 600))
        fundgz = _call_tool(
            "slow_sources",
            "fetch_fundgz_snapshot_nasdaq",
            _fetch_fundgz_snapshot,
            etf_code=etf_code,
            timeout_seconds=5.0,
            source_hint="fundgz",
        ) or {}
        fundgz_quality = "error"
        fundgz_premium = None
        freshness_seconds = None
        if fundgz.get("status") == "ok":
            freshness_seconds = _calc_fundgz_freshness_seconds(str(fundgz.get("estimate_time") or ""), now)
            if freshness_seconds is None:
                fundgz_quality = "degraded"
            elif freshness_seconds <= fundgz_fresh_ok_seconds:
                fundgz_quality = "ok"
            elif freshness_seconds > fundgz_fresh_degrade_seconds:
                fundgz_quality = "degraded"
            else:
                fundgz_quality = "ok"
            nav_est = _safe_float(fundgz.get("nav_estimate"))
            if nav_est and latest_price:
                fundgz_premium = (latest_price - nav_est) / nav_est * 100.0
        futures_premium = deviation_pct
        agreement_gap_pct = None
        if futures_premium is not None and fundgz_premium is not None:
            agreement_gap_pct = abs(futures_premium - fundgz_premium)
        chosen_value = futures_premium
        confidence = "medium"
        blend_warn = float(cfg.get("blend_gap_warn_pct", 3.0))
        if fundgz_premium is not None and fundgz_quality == "ok" and futures_premium is not None:
            if agreement_gap_pct is not None and agreement_gap_pct <= blend_warn:
                chosen_value = (futures_premium + fundgz_premium) / 2.0
                confidence = "high"
            else:
                chosen_value = max(futures_premium, fundgz_premium)
                confidence = "low"
        elif fundgz_premium is not None and fundgz_quality == "ok":
            chosen_value = fundgz_premium
            confidence = "medium"
        valuation_blend = {
            "futures_proxy": {
                "premium_rate": futures_premium,
                "freshness_seconds": 0 if futures_change_pct is not None else None,
                "quality": "ok" if futures_change_pct is not None else "degraded",
            },
            "fundgz": {
                "premium_rate": fundgz_premium,
                "nav_estimate": fundgz.get("nav_estimate"),
                "estimate_time": fundgz.get("estimate_time"),
                "freshness_seconds": freshness_seconds,
                "quality": fundgz_quality if fundgz.get("status") == "ok" else "error",
                "reason": fundgz.get("reason"),
            },
            "chosen_value": chosen_value,
            "confidence": confidence,
            "agreement_gap_pct": agreement_gap_pct,
            "quality_status": "ok" if confidence in {"high", "medium"} else "degraded",
        }
        # fundgz 为辅助估值源：不可用时不应污染 runner_errors（避免将网络/上游波动误判为本任务失败）。
        # 其不可用原因已在 valuation_blend.fundgz.reason 中可追溯。

    layer_cycle = _layer_cycle(ma25_dev, rsi14, close, ma25)
    layer_timing = _layer_timing(streak, None, rsi14, ma25_dev, cfg)
    layer_risk = _layer_risk(None, amount, manager_notice, cfg)
    if market_profile not in {"nasdaq_513300", "nikkei_513880"} and iopv_source in ("estimated", "unavailable"):
        gate_hits = list(layer_risk.get("gate_hits") or [])
        gate_tag = "iopv_estimated_only" if iopv_source == "estimated" else "iopv_unavailable"
        if gate_tag not in gate_hits:
            gate_hits.append(gate_tag)
        layer_risk["gate_hits"] = gate_hits
        layer_risk["options"] = ["hold", "reduce", "exit_wait"]
    decision_options = _resolve_decision_options(layer_cycle, layer_timing, layer_risk, cfg)
    if market_profile == "nasdaq_513300":
        lookback_days = int(cfg.get("percentile_lookback_days", 20))
        if enable_optimized and stage_budget["analytics"].expired():
            skipped_tasks["analytics"].append("load_recent_513300_history_days")
            _mark_stage_degraded("analytics")
            history = []
        else:
            history = _load_recent_513300_history_days(lookback_days=lookback_days)
        premium_hist: List[float] = []
        deviation_hist: List[float] = []
        for row in history:
            snap0 = row.get("tail_session_snapshot") if isinstance(row.get("tail_session_snapshot"), dict) else {}
            ana0 = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
            dev0 = ana0.get("deviation_proxy") if isinstance(ana0.get("deviation_proxy"), dict) else {}
            p = _safe_float(snap0.get("premium_pct"))
            d = _safe_float(dev0.get("deviation_pct"))
            if p is not None:
                premium_hist.append(p)
            if d is not None:
                deviation_hist.append(d)
        premium_percentile = _safe_percentile(premium_hist, premium_pct)
        deviation_percentile = _safe_percentile(deviation_hist, deviation_pct)
        temperature = _temperature_band(deviation_percentile if deviation_percentile is not None else premium_percentile)
        cap_ratio = float(temperature.get("position_ceiling", 1.0))
        decision_options["premium_percentile_20d"] = premium_percentile
        decision_options["deviation_percentile_20d"] = deviation_percentile
        for profile_name in ("conservative", "neutral", "aggressive"):
            seg = decision_options.get(profile_name) if isinstance(decision_options.get(profile_name), dict) else None
            if not seg:
                continue
            base_cap = _safe_float(seg.get("max_position_pct"))
            if base_cap is not None:
                seg["base_max_position_pct"] = base_cap
                seg["max_position_pct"] = round(base_cap * cap_ratio)
        decision_options["temperature_band"] = temperature.get("band")
        decision_options["temperature_label"] = temperature.get("label")
        decision_options["temperature_position_ceiling"] = cap_ratio
    elif market_profile == "nikkei_513880":
        lookback_days = int(cfg.get("percentile_lookback_days", 20))
        if enable_optimized and stage_budget["analytics"].expired():
            skipped_tasks["analytics"].append("load_recent_nikkei_monitor_history_days")
            _mark_stage_degraded("analytics")
            history = []
        else:
            history = _load_recent_monitor_history_days("nikkei_513880_monitor_events", lookback_days=lookback_days)
        prem_hist: List[float] = []
        dev_hist: List[float] = []
        for row in history:
            ana0 = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
            snap0 = row.get("tail_session_snapshot") if isinstance(row.get("tail_session_snapshot"), dict) else {}
            dev0 = ana0.get("deviation_proxy") if isinstance(ana0.get("deviation_proxy"), dict) else {}
            # 新口径：analysis.premium_rate_pct；兼容：tail_session_snapshot.premium_pct（理论溢价率）
            p = _safe_float(ana0.get("premium_rate_pct")) or _safe_float(snap0.get("premium_pct"))
            d = _safe_float(dev0.get("deviation_pct"))
            if p is not None:
                prem_hist.append(p)
            if d is not None:
                dev_hist.append(d)
        premium_percentile = _safe_percentile(prem_hist, premium_pct)
        deviation_percentile = _safe_percentile(dev_hist, deviation_pct)
        temperature = _temperature_band(premium_percentile)
        cap_ratio = float(temperature.get("position_ceiling", 1.0))
        decision_options["premium_percentile_20d"] = premium_percentile
        decision_options["deviation_percentile_20d"] = deviation_percentile
        decision_options["temperature_band"] = temperature.get("band")
        decision_options["temperature_label"] = temperature.get("label")
        decision_options["temperature_position_ceiling"] = cap_ratio
        # 溢价门禁 cap（取更保守）
        prem_quality = str((rd.get("analysis_premium") or {}).get("quality_status") or "ok")
        gate = _nikkei_risk_gate_from_premium(premium_pct, premium_percentile, prem_quality)
        # 缺口保护：仅在 M1/M2 生效（开盘初期）
        mp0 = str(monitor_ctx.get("monitor_point") or "").strip().upper()
        if mp0 in {"M1", "M2"}:
            yesterday_close = hist_close
            today_open = _safe_float((rt_row or {}).get("open"))
            if today_open is None and isinstance(etf_hist, dict):
                # 兜底：若 open 不可得，使用 latest_price 作为开盘代理（保守）
                today_open = latest_price
            nikkei_ref = _safe_float((rd.get("analysis_premium") or {}).get("index_change_pct"))
            gap_hit = _check_gap_protection(
                yesterday_close=yesterday_close,
                today_open=today_open,
                nikkei_ref_change_pct=nikkei_ref,
                overshoot_pct=float(cfg.get("gap_overshoot_pct", 1.5)),
            )
            if gap_hit:
                # 取更保守动作与上限
                gate["action"] = "WAIT"
                gate["position_ceiling"] = min(float(gate.get("position_ceiling") or 1.0), float(gap_hit.get("position_ceiling") or 0.25))
                rs = list(gate.get("reasons") or [])
                for r in (gap_hit.get("reasons") or []):
                    if r not in rs:
                        rs.append(r)
                gate["reasons"] = rs[:6]
                decision_options["gap_protection"] = gap_hit.get("evidence")
        decision_options["nikkei_risk_gate"] = gate
        effective_cap = min(cap_ratio, float(gate.get("position_ceiling") or 1.0))
        for profile_name in ("conservative", "neutral", "aggressive"):
            seg = decision_options.get(profile_name) if isinstance(decision_options.get(profile_name), dict) else None
            if not seg:
                continue
            base_cap = _safe_float(seg.get("max_position_pct"))
            if base_cap is not None:
                seg["base_max_position_pct"] = base_cap
                seg["max_position_pct"] = round(min(base_cap, effective_cap * 100.0))

    if iopv_source == "realtime":
        data_quality = "fresh"
    elif iopv_source == "manual":
        data_quality = "manual_override"
    elif iopv_source == "estimated":
        data_quality = "estimated"
    else:
        data_quality = "partial"
    if market_profile == "nasdaq_513300" and valuation_blend:
        vqs = str(valuation_blend.get("quality_status") or "")
        if vqs == "degraded" and data_quality == "fresh":
            data_quality = "degraded"
    risk_notices = _build_risk_notices(
        {
            "premium_pct": premium_pct,
            "rsi14": rsi14,
            "ma25_dev_pct": ma25_dev,
            "manager_premium_notice": manager_notice,
            "data_quality": data_quality,
        },
        cfg,
    )
    if market_profile != "nasdaq_513300" and iopv_source == "estimated":
        risk_notices.insert(0, "IOPV/溢价率当前为估算值，仅可作风险参考，建议保守执行。")
    if market_profile != "nasdaq_513300" and iopv_source == "unavailable":
        risk_notices.insert(0, "IOPV/溢价率当前不可用，已自动进入保守门禁（仅允许持有/减仓/观望）。")
    if market_profile == "nikkei_513880" and used_futures_fallback:
        risk_notices.insert(0, "日经指数实时数据不可用，当前使用日经期指代理，建议保守执行。")
    tech_cfg = cfg.get("technical_thresholds") if isinstance(cfg.get("technical_thresholds"), dict) else {}
    ma_over = float(tech_cfg.get("ma25_dev_overheat", 5.0))
    rsi_over = float(tech_cfg.get("rsi_overbought", 70))
    if ma25_dev is not None and ma25_dev >= ma_over:
        risk_notices.insert(0, f"MA25偏离 {ma25_dev:.2f}% 已超过 {ma_over:.2f}% 警戒线，触发短线过热预警。")
    if rsi14 is not None and rsi14 >= rsi_over:
        risk_notices.insert(0, f"RSI14={rsi14:.2f} 已达到/超过 {rsi_over:.0f}，触发超买预警。")

    rd["tail_session_snapshot"] = {
        "etf_code": etf_code,
        "latest_price": latest_price,
        "change_pct": etf_actual_pct,
        "as_of": rd.get("generated_at"),
        "iopv": iopv_val,
        "premium_pct": premium_pct,
        "amount": amount,
        "data_quality": data_quality,
        "iopv_source": iopv_source,
        "manual_iopv_updated_date": (manual_iopv or {}).get("updated_date"),
        "iopv_est": (iopv_est_pack or {}).get("iopv_est"),
        "premium_est": (iopv_est_pack or {}).get("premium_est"),
        "est_confidence": (iopv_est_pack or {}).get("est_confidence"),
        "valuation_blend": valuation_blend if valuation_blend else None,
    }
    range_pred = _predict_intraday_bands(latest_price, closes, cfg)
    monitor_projection = _build_monitor_projection(str(monitor_ctx.get("monitor_point") or "M7"), latest_price, range_pred)
    tug_of_war_pct = None
    if etf_actual_pct is not None and overnight_proxy_pct is not None:
        tug_of_war_pct = etf_actual_pct - overnight_proxy_pct
    action_state = _classify_action_state(layer_risk.get("gate_hits") or [], float(range_pred.get("confidence") or 0.0))
    pattern_alerts: List[Dict[str, Any]] = []
    if market_profile == "nasdaq_513300":
        action_state, rule_hits = _resolve_action_from_deviation(deviation_pct, futures_change_pct, tug_of_war_pct)
        gate_hits = list(layer_risk.get("gate_hits") or [])
        for rid in rule_hits:
            if rid not in gate_hits:
                gate_hits.append(rid)
        layer_risk["gate_hits"] = gate_hits
        pattern_alerts = _build_nasdaq_pattern_alerts(deviation_pct, tug_of_war_pct, futures_change_pct, action_state)
    elif market_profile == "nikkei_513880":
        action_state, rule_hits = _resolve_action_from_deviation(deviation_pct, futures_change_pct, tug_of_war_pct)
        gate_hits = list(layer_risk.get("gate_hits") or [])
        for rid in rule_hits:
            if rid not in gate_hits:
                gate_hits.append(rid)
        if used_futures_fallback and "JP_FALLBACK" not in gate_hits:
            gate_hits.append("JP_FALLBACK")
        layer_risk["gate_hits"] = gate_hits
        pattern_alerts = _build_nikkei_pattern_alerts(resolved_mp, deviation_pct, action_state, used_futures_fallback)
    signal_board = {
        "direction_score": round((index_day_ret_pct or 0.0), 4),
        "strength_score": round(abs(index_day_ret_pct or 0.0) + abs(streak or 0) * 0.2, 4),
        "confidence": range_pred.get("confidence", 0.0),
        "futures_status": str(futures_ref.get("status") or "unavailable"),
        "futures_symbol": futures_ref.get("symbol"),
        "futures_change_pct": _safe_float(futures_ref.get("change_pct")),
        "overnight_ndx_pct": overnight_proxy_pct,
        "nq_futures_15m_pct": futures_change_pct if market_profile == "nasdaq_513300" else None,
        "nikkei_index_pct": overnight_proxy_pct if market_profile == "nikkei_513880" else None,
        "monitor_point": monitor_ctx.get("monitor_point"),
        "target_window": monitor_ctx.get("target_window"),
        "predicted_band": range_pred.get("core_range"),
        "predicted_band_width_pct": range_pred.get("core_width_pct"),
    }
    risk_gate = {
        "liquidity_amount": amount,
        "fx_risk_multiplier": 1.0,
        "gates_triggered": layer_risk.get("gate_hits") or [],
        "quality_status": "ok" if len(closes) >= 10 else "degraded",
        "action_state": action_state,
        "decision": action_state,
        "reason_codes": layer_risk.get("gate_hits") or [],
    }
    if market_profile == "nikkei_513880":
        gate = (decision_options.get("nikkei_risk_gate") if isinstance(decision_options.get("nikkei_risk_gate"), dict) else None) or {}
        if gate:
            risk_gate["action"] = gate.get("action")
            risk_gate["position_ceiling"] = gate.get("position_ceiling")
            risk_gate["reasons"] = gate.get("reasons") or []
            # 日经：主门禁动作以理论溢价为准，避免与 deviation_proxy 的 action_state 混淆
            risk_gate["action_state"] = gate.get("action")
    action_paths = {
        "conservative": decision_options.get("conservative"),
        "neutral": decision_options.get("neutral"),
        "aggressive": decision_options.get("aggressive"),
    }

    rd["analysis"] = {
        "index_symbol": index_symbol,
        "index_close": index_close,
        "index_day_ret_pct": index_day_ret_pct,
        "ma25": ma25,
        "ma25_dev_pct": ma25_dev,
        "rsi14": rsi14,
        "streak_days": streak,
        "streak_return_pct": streak_ret,
        "layer_outputs": [layer_cycle, layer_timing, layer_risk],
        "decision_options": decision_options,
        "gates_triggered": layer_risk.get("gate_hits") or [],
        "user_decision_note": "本系统仅提供多视角信息，不替代你的最终交易决策。",
        "risk_notices": risk_notices,
        "manager_premium_notice": manager_notice,
        "signal_board": signal_board,
        "signal_summary": {
            "direction_score": signal_board.get("direction_score"),
            "strength_score": signal_board.get("strength_score"),
            "confidence": signal_board.get("confidence"),
        },
        "risk_gate": risk_gate,
        "action_paths": action_paths,
        "range_prediction": range_pred,
        "monitor_projection": monitor_projection,
        "deviation_proxy": {
            "expected_pct": etf_expected_pct,
            "actual_pct": etf_actual_pct,
            "deviation_pct": deviation_pct,
            "deviation_trend": deviation_trend,
            "beta_track": beta_track if market_profile == "nasdaq_513300" else None,
            "futures_weight": futures_weight if market_profile == "nasdaq_513300" else None,
            "expected_source": "nikkei_index_spot" if (market_profile == "nikkei_513880" and not used_futures_fallback) else ("nikkei_futures_fallback" if market_profile == "nikkei_513880" else "overnight_plus_futures"),
        },
        "premium_percentile_20d": decision_options.get("premium_percentile_20d"),
        "deviation_percentile_20d": decision_options.get("deviation_percentile_20d"),
        "temperature_band": decision_options.get("temperature_band"),
        "temperature_position_ceiling": decision_options.get("temperature_position_ceiling"),
        "premium_theoretical_nav": (rd.get("analysis_premium") or {}).get("theoretical_nav"),
        "premium_rate_pct": premium_pct,
        "premium_quality_status": (rd.get("analysis_premium") or {}).get("quality_status"),
        "valuation_blend": valuation_blend if valuation_blend else None,
        "pattern_alerts": pattern_alerts,
        "futures_reference": futures_ref,
        "monitor_context": monitor_ctx,
    }

    # 次日开盘方向预测（失败不阻断主流程）
    if market_profile == "nasdaq_513300":
        try:
            from plugins.analysis.nasdaq_next_open_predictor import predict_next_open_direction

            pred = predict_next_open_direction(rd, persist=True)
            if isinstance(pred, dict) and pred.get("success"):
                rd["next_open_direction"] = pred.get("decision")
                rd["next_open_semantic_view"] = pred.get("semantic_view")
            else:
                rd["next_open_direction"] = {"success": False, "reason": "predictor_failed"}
        except Exception as e:
            errors.append({"step": "next_open_predictor", "error": str(e)})
            rd["next_open_direction"] = {"success": False, "reason": "predictor_exception"}
    elif market_profile == "nikkei_513880":
        try:
            from plugins.analysis.nikkei_next_open_predictor import predict_next_open_direction

            pred = predict_next_open_direction(rd)
            if isinstance(pred, dict) and pred.get("success"):
                rd["next_open_direction"] = pred.get("decision")
            else:
                rd["next_open_direction"] = {"success": False, "reason": "predictor_failed"}
        except Exception as e:
            errors.append({"step": "next_open_predictor_nikkei", "error": str(e)})
            rd["next_open_direction"] = {"success": False, "reason": "predictor_exception"}
    profile_prefix = "nasdaq" if market_profile == "nasdaq_513300" else "nikkei"
    run_id = f"{profile_prefix}-{now.strftime('%Y%m%d-%H%M%S')}-{monitor_ctx.get('monitor_point')}"
    schema_name = "nasdaq_513300_monitor_event" if market_profile == "nasdaq_513300" else "nikkei_513880_monitor_event"
    semantic_dataset = "nasdaq_513300_intraday_dashboard_view" if market_profile == "nasdaq_513300" else "nikkei_513880_intraday_dashboard_view"
    required_field_paths = [
        ("tail_session_snapshot", "latest_price"),
        ("tail_session_snapshot", "change_pct"),
        ("tail_session_snapshot", "as_of"),
        ("analysis", "range_prediction"),
        ("analysis", "signal_summary"),
        ("analysis", "monitor_projection"),
        ("analysis", "risk_gate.decision"),
        ("analysis", "risk_gate.reason_codes"),
        ("analysis", "action_paths"),
    ]
    missing_required: List[str] = []
    for p0, p1 in required_field_paths:
        block = rd.get(p0) if isinstance(rd.get(p0), dict) else {}
        path_keys = str(p1).split(".")
        node: Any = block
        for k in path_keys:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(k)
        if node is None:
            missing_required.append(f"{p0}.{p1}")
    if missing_required:
        errors.append({"step": "required_fields", "error": f"missing:{','.join(missing_required)}"})
        _mark_stage_degraded("analytics")

    run_quality = "ok_full"
    if errors and missing_required:
        run_quality = "error"
    elif degraded_stages:
        run_quality = "ok_degraded"

    rd["run_quality"] = run_quality
    rd["degraded_stages"] = degraded_stages
    rd["skipped_tasks"] = skipped_tasks
    rd["termination_reason"] = "completed"
    if run_quality == "ok_degraded":
        reason_codes = sorted(
            {
                str(x.get("degraded_reason") or "partial_data")
                for x in lineage_struct
                if isinstance(x, dict) and str(x.get("quality_status") or "") == "degraded"
            }
        )
        rd["degrade"] = {"reason_codes": reason_codes}
        rd["degraded_notice"] = "本次结果为降级可用（ok_degraded），已标注降级原因与影响字段。"
    elif run_quality == "error":
        rd["degrade"] = {"reason_codes": ["critical_output_unavailable"]}
    else:
        rd["degrade"] = {"reason_codes": []}

    rd["_meta"] = {
        "schema_name": schema_name,
        "schema_version": "1.0.0",
        "task_id": f"etf-{profile_prefix}-{monitor_ctx.get('monitor_point', 'M7').lower()}-{'513300' if market_profile == 'nasdaq_513300' else '513880'}",
        "run_id": run_id,
        "data_layer": "L3",
        "generated_at": rd["generated_at"],
        "trade_date": rd["trade_date"],
        "source_tools": [
            "tool_fetch_etf_data",
            "tool_fetch_global_index_hist_sina",
            "tool_fetch_index_data",
        ],
        "lineage_refs": [f"monitor_point:{monitor_ctx.get('monitor_point')}"],
        "quality_status": "error" if run_quality == "error" else ("degraded" if run_quality == "ok_degraded" else risk_gate.get("quality_status", "ok")),
    }
    rd["semantic_view"] = {
        "dataset": semantic_dataset,
        "monitor_point": monitor_ctx.get("monitor_point"),
        "target_window": monitor_ctx.get("target_window"),
        "core_range": range_pred.get("core_range"),
        "safe_range": range_pred.get("safe_range"),
        "projection_label": monitor_projection.get("projection_label"),
        "action_paths": action_paths,
        "deviation_proxy": rd.get("analysis", {}).get("deviation_proxy") if isinstance(rd.get("analysis"), dict) else None,
        "valuation_blend": valuation_blend if valuation_blend else None,
        "premium_rate_pct": rd.get("analysis", {}).get("premium_rate_pct") if isinstance(rd.get("analysis"), dict) else None,
        "premium_percentile_20d": rd.get("analysis", {}).get("premium_percentile_20d") if isinstance(rd.get("analysis"), dict) else None,
        "deviation_percentile_20d": rd.get("analysis", {}).get("deviation_percentile_20d") if isinstance(rd.get("analysis"), dict) else None,
        "temperature_band": rd.get("analysis", {}).get("temperature_band") if isinstance(rd.get("analysis"), dict) else None,
        "temperature_position_ceiling": rd.get("analysis", {}).get("temperature_position_ceiling") if isinstance(rd.get("analysis"), dict) else None,
        "risk_gate": rd.get("analysis", {}).get("risk_gate") if isinstance(rd.get("analysis"), dict) else None,
        "run_quality": run_quality,
        "degrade_reason_codes": (rd.get("degrade") or {}).get("reason_codes"),
    }
    td_reasons = layer_timing.get("reasons") if isinstance(layer_timing.get("reasons"), list) else []
    if "过热/连续上涨" in td_reasons:
        rd["analysis"]["indicator_opinion"] = "短线过热，当前以持有/减仓为主，不建议追高加仓。"
        # 过热状态下风险层强制禁买，避免与节奏层结论冲突
        layer_risk["options"] = ["hold", "reduce", "exit_wait"]
        rd["analysis"]["decision_options"] = _resolve_decision_options(layer_cycle, layer_timing, layer_risk, cfg)
    rd["risk_notice_rules"] = {"messages": risk_notices}
    rd["tail_decision_mode"] = str(cfg.get("decision_mode") or "user_final_decision")

    for stage in ("critical", "slow_sources", "analytics"):
        sb = stage_budget.get(stage)
        stage_status = "ok"
        stage_reason = None
        if stage in degraded_stages:
            stage_status = "degraded"
            stage_reason = "timeout_or_partial"
        _record_stage_timing(
            stage_timing,
            stage=stage,
            started_at=stage_started_at.get(stage, sb.started_at if sb else time.perf_counter()),
            budget_s=sb.budget_s if sb else None,
            status=stage_status,
            degraded_reason=stage_reason,
            skipped_tasks=skipped_tasks.get(stage) or [],
        )
    if emit_stage_timing:
        rd["stage_timing"] = stage_timing
        rd["lineage_struct"] = lineage_struct
        bundle = str(monitor_ctx.get("monitor_bundle") or "").upper()
        monitor_key = "PROCESS" if bundle == "PROCESS" else str(monitor_ctx.get("monitor_point") or "M7").upper()
        if market_profile == "nasdaq_513300":
            rd["stage_p95_targets"] = (stage_p95_targets.get("nasdaq_513300") or {}).get(monitor_key)

    if errors:
        rd["runner_errors"] = errors

    # L3/L4 语义落盘（用于回放与分位计算；写入失败不阻断主流程）
    try:
        dataset_dir = "nasdaq_513300_monitor_events" if market_profile == "nasdaq_513300" else "nikkei_513880_monitor_events"
        view_dir = "nasdaq_513300_intraday_dashboard_view" if market_profile == "nasdaq_513300" else "nikkei_513880_intraday_dashboard_view"
        _persist_semantic_event_jsonl(dataset_dir, rd.get("trade_date") or "", rd)
        mp = str(monitor_ctx.get("monitor_point") or "").strip().upper()
        sem = rd.get("semantic_view") if isinstance(rd.get("semantic_view"), dict) else {}
        sem_obj = {
            "_meta": {
                "schema_name": "nasdaq_513300_intraday_semantic" if market_profile == "nasdaq_513300" else "nikkei_513880_intraday_semantic",
                "schema_version": "1.0.0",
                "generated_at": rd.get("generated_at"),
                "trade_date": rd.get("trade_date"),
            },
            "data": sem,
        }
        _persist_semantic_view_json(view_dir, rd.get("trade_date") or "", mp, sem_obj)
    except Exception as e:
        errors.append({"step": "persist_semantic_view", "error": str(e)})
    return rd, errors


def tool_run_tail_session_analysis_and_send(
    mode: str = "prod",
    fetch_mode: str = "production",
    market_profile: str = "nikkei_513880",
    monitor_point: str = "M7",
    monitor_bundle: Optional[str] = None,
    workflow_profile: str = "legacy",
    stage_budget_profile: str = "balanced",
    emit_stage_timing: bool = True,
    max_concurrency: int = 3,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    split_markdown_sections: bool = True,
    max_chars_per_message: Optional[int] = None,
) -> Dict[str, Any]:
    from plugins.notification.send_analysis_report import tool_send_analysis_report

    report_data, _ = build_tail_session_report_data(
        fetch_mode=fetch_mode,
        market_profile=market_profile,
        monitor_point=monitor_point,
        monitor_bundle=monitor_bundle,
        workflow_profile=workflow_profile,
        stage_budget_profile=stage_budget_profile,
        emit_stage_timing=emit_stage_timing,
        max_concurrency=max_concurrency,
    )
    out = tool_send_analysis_report(
        report_data=report_data,
        mode=mode,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
        split_markdown_sections=split_markdown_sections,
        max_chars_per_message=max_chars_per_message,
    )
    if isinstance(out, dict):
        data = dict(out.get("data") or {})
        delivery = out.get("delivery") if isinstance(out.get("delivery"), dict) else {}
        delivery_ok = bool(delivery.get("ok"))
        delivery_status = str(delivery.get("status") or ("ok" if delivery_ok else "not-delivered"))
        channel_code = delivery.get("errcode")
        if channel_code is None and isinstance(out.get("response"), dict):
            channel_code = out.get("response", {}).get("errcode")
        channel_msg = delivery.get("errmsg")
        if channel_msg is None and isinstance(out.get("response"), dict):
            channel_msg = out.get("response", {}).get("errmsg")
        data["report_type"] = "tail_session"
        data["runner_errors"] = report_data.get("runner_errors") or []
        data["run_quality"] = report_data.get("run_quality")
        data["degraded_stages"] = report_data.get("degraded_stages") or []
        data["stage_timing"] = report_data.get("stage_timing") or {}
        data["lineage_struct"] = report_data.get("lineage_struct") or []
        data["termination_reason"] = report_data.get("termination_reason") or "completed"
        data["stage_p95_targets"] = report_data.get("stage_p95_targets") or {}
        data["degrade"] = report_data.get("degrade") or {"reason_codes": []}
        if report_data.get("run_quality") == "ok_degraded":
            data["degraded_notice"] = report_data.get("degraded_notice") or "本次结果为降级可用（ok_degraded），已标注降级原因与影响字段。"
        data["delivery"] = {
            "attempted": True,
            "success": delivery_ok,
            "channel_code": channel_code,
            "channel_message": channel_msg,
            "status": delivery_status,
        }
        # 兼容 cron 侧旧口径字段，确保不再出现成功却 not-delivered。
        out["delivered"] = delivery_ok
        out["deliveryStatus"] = "ok" if delivery_ok else "not-delivered"
        out["data"] = data
    return out

