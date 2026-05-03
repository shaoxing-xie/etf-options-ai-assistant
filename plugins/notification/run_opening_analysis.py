"""
进程内串接：9:20 开盘行情分析（预开盘执行版，对齐 workflows/opening_analysis.yaml）。

供 Cron 单次 tool_call，避免 Gateway 多轮合并 report_data 与 idle 超时。

若钉钉正文出现缺段、N/A 或 degraded：先对照本模块合并逻辑与 send_daily_report 的字段路径逐项排查，
勿默认归因数据采集或网络；运维说明见 docs/ops/cron_opening_analysis_triage.md。
"""

from __future__ import annotations

import logging
import math
import json
import time
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timedelta
from threading import Semaphore
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None  # type: ignore

logger = logging.getLogger(__name__)
_OPENING_GLOBAL_SPOT_TIMEOUT_S = 8.0

# 与日报外盘推荐集合对齐：美股三大 + 日韩现货开盘参考 + 港股 + 欧股收市口径（开盘前展示更稳定）
_OPENING_GLOBAL_INDEX_CODES = "^DJI,^GSPC,^IXIC,^N225,^KS11,^HSI,^GDAXI,^STOXX50E,^FTSE"

# 历史日线口径补齐（上一完整交易日收盘）：当 yfinance/新浪 spot 缺行或缺 change_pct 时补全。
# 需覆盖隔夜指示三组：美股三大、日/韩、欧股；否则会出现「仅有欧股行、美股空白」等半屏问题。
_OPENING_GLOBAL_HIST_CODES = (
    "^DJI",
    "^GSPC",
    "^IXIC",
    "^N225",
    "^KS11",
    "^GDAXI",
    "^STOXX50E",
    "^FTSE",
)


def _now_sh() -> datetime:
    if pytz is None:
        return datetime.now()
    return datetime.now(pytz.timezone("Asia/Shanghai"))


def _previous_trading_day_yyyymmdd_for_opening_sector() -> str:
    """
    盘前任务用：相对「今日」的上一完整 A 股交易日（YYYYMMDD）。
    用于板块热度/涨停聚合，避免 09:20 当日涨停列表尚未落全导致全空。
    """
    try:
        from src.config_loader import load_system_config
        from src.system_status import get_last_trading_day_on_or_before

        now_sh = _now_sh()
        anchor = (now_sh - timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        try:
            cfg = load_system_config(use_cache=True)
        except Exception:
            cfg = None
        return get_last_trading_day_on_or_before(
            anchor, cfg if isinstance(cfg, dict) else None
        )
    except Exception as e:
        logger.warning("opening sector heat trade date fallback: %s", e)
        return _now_sh().strftime("%Y%m%d")


def _safe_step(
    name: str,
    fn: Callable[..., Any],
    errors: List[Dict[str, str]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning("opening_runner step %s failed: %s", name, e, exc_info=True)
        errors.append({"step": name, "error": str(e)})
        return None


def _stable_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return repr(obj)


def _attach_global_spot_report_fields(rd: Dict[str, Any], gspot: Any) -> None:
    """Normalize global spot diagnostics onto report_data (opening + daily sender)."""
    if not isinstance(gspot, dict):
        return
    attempts = gspot.get("attempts")
    if isinstance(attempts, list):
        fail_codes = [str((x or {}).get("failure_code") or "") for x in attempts if isinstance(x, dict)]
        rd["global_spot_failure_codes"] = [x for x in fail_codes if x]
        rd["global_spot_attempts"] = len(attempts)
    src = str(gspot.get("source") or "").strip()
    if src:
        rd["global_spot_source_used"] = src
    em = gspot.get("elapsed_ms")
    if em is not None:
        rd["global_spot_elapsed_ms"] = em


def _maybe_attach_global_spot_catalog_debug(rd: Dict[str, Any], gspot: Any) -> None:
    try:
        from src.plugin_catalog_observability import debug_plugin_catalog_enabled, extract_global_index_spot_catalog_debug
    except Exception:
        return
    if not debug_plugin_catalog_enabled():
        return
    frag = extract_global_index_spot_catalog_debug(gspot)
    if not frag:
        return
    rd.setdefault("_debug", {}).setdefault("plugin_catalog", {})["global_index_spot"] = frag


def _memo_key(fn: Callable[..., Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    payload = {
        "fn": getattr(fn, "__name__", str(fn)),
        "args": args,
        "kwargs": kwargs,
    }
    return _stable_json_dumps(payload)


class _StageBudget:
    def __init__(self, budget_s: Optional[float]):
        self.budget_s = budget_s if (isinstance(budget_s, (int, float)) and budget_s > 0) else None
        self.started_at = time.perf_counter()

    def remaining_s(self) -> Optional[float]:
        if self.budget_s is None:
            return None
        spent = time.perf_counter() - self.started_at
        rem = self.budget_s - spent
        return rem if rem > 0 else 0.0

    def expired(self) -> bool:
        rem = self.remaining_s()
        return rem is not None and rem <= 0


def _stage_budget_profile(profile: str) -> Dict[str, Optional[float]]:
    """
    Stage budgets (seconds). Keep conservative defaults; allow 'off' to disable.
    balanced targets p50<=75s p95<=150s with degraded-but-usable output.
    """
    p = (profile or "").strip().lower()
    if p in ("off", "disabled", "none"):
        return {
            "critical": None,
            "slow_sources": None,
            "analytics": None,
        }
    if p in ("tight", "fast"):
        return {
            "critical": 35.0,
            "slow_sources": 20.0,
            "analytics": 30.0,
        }
    # balanced
    return {
        "critical": 45.0,
        "slow_sources": 30.0,
        "analytics": 40.0,
    }


def _provider_key_for_step(step_name: str) -> str:
    # Heuristic mapping; we only need stable buckets for semaphores.
    n = (step_name or "").strip().lower()
    if "policy_news" in n or "tavily" in n:
        return "tavily"
    if "global_index_hist_sina" in n:
        return "akshare_sina"
    if "global_index_spot" in n:
        return "global_spot"
    if "macro_commodities" in n:
        return "macro"
    if "announcement_digest" in n:
        return "announcement"
    if "overnight_futures_digest" in n:
        return "overnight"
    return "default"


def _semaphore_pool(max_concurrency: int) -> Dict[str, Semaphore]:
    # Default allows limited parallelism; tavily is stricter to reduce 432/rotation pressure.
    m = max(1, int(max_concurrency or 1))
    return {
        "tavily": Semaphore(1),
        "akshare_sina": Semaphore(1),
        "global_spot": Semaphore(1),
        "default": Semaphore(min(2, m)),
        "macro": Semaphore(min(2, m)),
        "announcement": Semaphore(1),
        "overnight": Semaphore(1),
    }


def _record_stage_timing(
    stage_timing: Dict[str, Dict[str, Any]],
    stage: str,
    started_at: float,
    budget_s: Optional[float],
    status: str,
    degraded_reason: Optional[str] = None,
) -> None:
    elapsed_ms = int(round((time.perf_counter() - started_at) * 1000))
    stage_timing[stage] = {
        "elapsed_ms": elapsed_ms,
        "budget_s": budget_s,
        "status": status,
        "degraded_reason": degraded_reason,
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


def _indices_from_response(resp: Any) -> List[Dict[str, Any]]:
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _rows_from_tool_data(resp: Any) -> List[Dict[str, Any]]:
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _to_float(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except Exception:
        return None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_trade_date(value: Any) -> Optional[datetime]:
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _normalize_trade_date_ymd(value: Any) -> str:
    dt = _parse_trade_date(value)
    if dt is None:
        return str(value or "").strip()
    return dt.strftime("%Y-%m-%d")


def _previous_trading_day_ymd(trade_date: str) -> str:
    """
    返回给定报告日对应的上一交易日（YYYY-MM-DD）。
    非交易日也返回最近可用上一交易日，供轮动前日基准读取。
    """
    try:
        from src.config_loader import load_system_config
        from src.system_status import get_last_trading_day_on_or_before

        td = _parse_trade_date(trade_date) or _now_sh()
        anchor = (td - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        try:
            cfg = load_system_config(use_cache=True)
        except Exception:
            cfg = None
        prev = get_last_trading_day_on_or_before(anchor, cfg if isinstance(cfg, dict) else None)
        return _normalize_trade_date_ymd(prev)
    except Exception:
        td = _parse_trade_date(trade_date)
        if td is None:
            return _now_sh().strftime("%Y-%m-%d")
        return (td - timedelta(days=1)).strftime("%Y-%m-%d")


def _load_rotation_validation_config() -> Dict[str, Any]:
    default = {
        "open_change_strong_threshold": 0.5,
        "open_change_weak_threshold": -1.0,
        "volume_ratio_strong_threshold": 1.2,
        "volume_ratio_weak_threshold": 0.7,
        "observe_band_pct": 0.3,
        "max_rotation_etf_in_report": 8,
        "signal_position_multiplier": {
            "STRONG": 1.0,
            "CAUTIOUS": 0.5,
            "OBSERVE": 0.0,
            "WEAK": 0.0,
            "NEUTRAL": 0.0,
        },
    }
    try:
        from src.config_loader import load_system_config

        cfg = load_system_config(use_cache=True)
        if not isinstance(cfg, dict):
            return default
        notification = cfg.get("notification") if isinstance(cfg.get("notification"), dict) else {}
        opening_cfg = notification.get("opening_rotation_validation") if isinstance(notification, dict) else {}
        if not isinstance(opening_cfg, dict):
            return default
        merged = dict(default)
        for k in (
            "open_change_strong_threshold",
            "open_change_weak_threshold",
            "volume_ratio_strong_threshold",
            "volume_ratio_weak_threshold",
            "observe_band_pct",
            "max_rotation_etf_in_report",
        ):
            if opening_cfg.get(k) is not None:
                merged[k] = opening_cfg.get(k)
        spm = opening_cfg.get("signal_position_multiplier")
        if isinstance(spm, dict):
            merged_spm = dict(default["signal_position_multiplier"])
            for kk, vv in spm.items():
                merged_spm[str(kk).upper()] = vv
            merged["signal_position_multiplier"] = merged_spm
        return merged
    except Exception:
        return default


def _load_rotation_latest_for_opening(opening_trade_date: str) -> Dict[str, Any]:
    root = _project_root()
    base = root / "data" / "semantic" / "rotation_latest"
    prev_td = _previous_trading_day_ymd(opening_trade_date)
    out: Dict[str, Any] = {
        "quality_status": "degraded",
        "degraded_reason": "rotation_latest_missing",
        "rotation_trade_date": prev_td,
        "opening_trade_date": _normalize_trade_date_ymd(opening_trade_date),
        "data": {},
        "path": str(base / f"{prev_td}.json"),
    }
    if not base.exists():
        return out

    primary = base / f"{prev_td}.json"
    candidates: List[Path] = [primary]
    if not primary.exists():
        try:
            all_paths = sorted([p for p in base.glob("*.json") if p.is_file()], reverse=True)
            candidates.extend(all_paths[:5])
        except Exception:
            pass
    chosen: Optional[Path] = None
    payload: Dict[str, Any] = {}
    for p in candidates:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        data = obj.get("data") if isinstance(obj, dict) and isinstance(obj.get("data"), dict) else {}
        if data:
            payload = data
            chosen = p
            break
    if chosen is None:
        out["degraded_reason"] = "rotation_latest_invalid"
        return out

    chosen_td = chosen.stem
    out.update(
        {
            "quality_status": "ok",
            "degraded_reason": "",
            "rotation_trade_date": _normalize_trade_date_ymd(chosen_td),
            "path": str(chosen),
            "data": payload,
        }
    )
    return out


def _build_rotation_candidate_union(rotation_payload: Dict[str, Any], max_candidates: int = 10) -> List[Dict[str, Any]]:
    unified = rotation_payload.get("unified_next_day")
    unified = [x for x in unified if isinstance(x, dict)] if isinstance(unified, list) else []
    legacy = rotation_payload.get("legacy_views") if isinstance(rotation_payload.get("legacy_views"), dict) else {}
    rps_rows = legacy.get("rps_recommendations")
    rps_rows = [x for x in rps_rows if isinstance(x, dict)] if isinstance(rps_rows, list) else []
    tf_rows = legacy.get("three_factor_top5")
    tf_rows = [x for x in tf_rows if isinstance(x, dict)] if isinstance(tf_rows, list) else []

    by_code: Dict[str, Dict[str, Any]] = {}

    for row in unified:
        code = str(row.get("etf_code") or "").strip()
        if not code:
            continue
        by_code[code] = {
            "etf_code": code,
            "etf_name": str(row.get("etf_name") or row.get("name") or ""),
            "rotation_score": _to_float(row.get("unified_score")),
            "rotation_rank": row.get("rank"),
            "from_rps": False,
            "from_three_factor": False,
            "from_unified": True,
            "source_tags": ["unified"],
        }

    for row in rps_rows:
        code = str(row.get("etf_code") or "").strip()
        if not code:
            continue
        rec = by_code.setdefault(
            code,
            {
                "etf_code": code,
                "etf_name": str(row.get("etf_name") or ""),
                "rotation_score": _to_float(row.get("composite_score")),
                "rotation_rank": row.get("rank"),
                "from_rps": False,
                "from_three_factor": False,
                "from_unified": False,
                "source_tags": [],
            },
        )
        rec["from_rps"] = True
        if "rps" not in rec["source_tags"]:
            rec["source_tags"].append("rps")
        if not rec.get("etf_name"):
            rec["etf_name"] = str(row.get("etf_name") or "")
        if rec.get("rotation_score") is None:
            rec["rotation_score"] = _to_float(row.get("composite_score"))

    for row in tf_rows:
        code = str(row.get("symbol") or row.get("etf_code") or "").strip()
        if not code:
            continue
        rec = by_code.setdefault(
            code,
            {
                "etf_code": code,
                "etf_name": str(row.get("name") or row.get("etf_name") or ""),
                "rotation_score": _to_float(row.get("score") if row.get("score") is not None else row.get("composite_score")),
                "rotation_rank": row.get("rank"),
                "from_rps": False,
                "from_three_factor": False,
                "from_unified": False,
                "source_tags": [],
            },
        )
        rec["from_three_factor"] = True
        if "three_factor" not in rec["source_tags"]:
            rec["source_tags"].append("three_factor")
        if not rec.get("etf_name"):
            rec["etf_name"] = str(row.get("name") or row.get("etf_name") or "")
        if rec.get("rotation_score") is None:
            rec["rotation_score"] = _to_float(row.get("score") if row.get("score") is not None else row.get("composite_score"))

    rows = list(by_code.values())
    rows.sort(
        key=lambda x: (
            -9999.0 if _to_float(x.get("rotation_score")) is None else -float(_to_float(x.get("rotation_score")) or 0.0),
            9999 if _to_float(x.get("rotation_rank")) is None else int(_to_float(x.get("rotation_rank")) or 0),
            str(x.get("etf_code") or ""),
        )
    )
    return rows[: max(1, int(max_candidates or 10))]


def _extract_volume_ratio(row: Dict[str, Any]) -> Optional[float]:
    for key in ("volume_ratio", "vol_ratio", "turnover_ratio", "amount_ratio", "ratio"):
        v = _to_float(row.get(key))
        if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return v
    return None


def _extract_realtime_rows(resp: Any) -> List[Dict[str, Any]]:
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _derive_rotation_market_gate(rotation_payload: Dict[str, Any]) -> str:
    sec_env_eff = rotation_payload.get("sector_environment_effective")
    if isinstance(sec_env_eff, dict):
        gate = str(sec_env_eff.get("effective_gate") or "").strip().upper()
        if gate:
            return gate
    sec_env = rotation_payload.get("sector_environment")
    if isinstance(sec_env, dict):
        gate = str(sec_env.get("gate") or "").strip().upper()
        if gate:
            return gate
    env = rotation_payload.get("environment")
    if isinstance(env, dict):
        gate = str(env.get("gate") or env.get("stage") or "").strip().upper()
        if gate:
            return gate
    return "UNKNOWN"


def _validate_rotation_opening(
    candidates: List[Dict[str, Any]],
    realtime_rows: List[Dict[str, Any]],
    cfg: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    by_code = {}
    for row in realtime_rows:
        code = str(row.get("code") or row.get("symbol") or "").strip()
        if code:
            by_code[code] = row

    st = _to_float(cfg.get("open_change_strong_threshold")) or 0.5
    wt = _to_float(cfg.get("open_change_weak_threshold")) or -1.0
    vt = _to_float(cfg.get("volume_ratio_strong_threshold")) or 1.2
    vwt = _to_float(cfg.get("volume_ratio_weak_threshold")) or 0.7
    obs = abs(_to_float(cfg.get("observe_band_pct")) or 0.3)

    out: List[Dict[str, Any]] = []
    missing: List[str] = []
    for rec in candidates:
        code = str(rec.get("etf_code") or "").strip()
        row = by_code.get(code)
        if row is None:
            missing.append(code)
            out.append(
                {
                    **rec,
                    "signal": "OBSERVE",
                    "signal_reason": "实时行情缺失，降级观察",
                    "confidence": "low",
                    "open_change_pct": None,
                    "volume_ratio": None,
                    "validation_status": "missing_realtime",
                }
            )
            continue
        open_change = _to_float(row.get("change_pct") if row.get("change_pct") is not None else row.get("change_percent"))
        volume_ratio = _extract_volume_ratio(row)
        if volume_ratio is None:
            volume_ratio = 1.0

        signal = "NEUTRAL"
        reason = "常规波动，维持观察"
        confidence = "medium"
        if open_change is not None and open_change > st and volume_ratio >= vt:
            signal = "STRONG"
            reason = "高开放量，动量延续"
            confidence = "high"
        elif open_change is not None and open_change > 0 and volume_ratio >= 1.0:
            signal = "CAUTIOUS"
            reason = "小幅高开，量能温和"
        elif open_change is not None and open_change <= wt and volume_ratio >= max(vt, 1.5):
            signal = "WEAK"
            reason = "低开放量，抛压加重"
            confidence = "high"
        elif open_change is not None and abs(open_change) <= obs:
            signal = "OBSERVE"
            reason = "平开震荡，等待方向"
        elif volume_ratio <= vwt and open_change is not None and open_change <= 0:
            signal = "OBSERVE"
            reason = "缩量偏弱，等待确认"

        out.append(
            {
                **rec,
                "open_change_pct": open_change,
                "volume_ratio": volume_ratio,
                "signal": signal,
                "signal_reason": reason,
                "confidence": confidence,
                "validation_status": "confirmed" if signal in ("STRONG", "CAUTIOUS") else "observed",
            }
        )
    return out, missing


def _build_rotation_suggestions(
    validations: List[Dict[str, Any]],
    market_gate: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    mp = cfg.get("signal_position_multiplier") if isinstance(cfg.get("signal_position_multiplier"), dict) else {}
    gate_u = str(market_gate or "UNKNOWN").upper()
    gate_multiplier = 1.0
    if gate_u == "CAUTION":
        gate_multiplier = 0.5
    elif gate_u == "STOP":
        gate_multiplier = 0.0

    main_actions: List[Dict[str, Any]] = []
    observe_list: List[Dict[str, Any]] = []
    for row in validations:
        signal = str(row.get("signal") or "OBSERVE").upper()
        base = _to_float(mp.get(signal) if isinstance(mp, dict) else None)
        base = 0.0 if base is None else max(0.0, min(1.0, base))
        effective = round(base * gate_multiplier, 2)
        item = {
            "etf_code": row.get("etf_code"),
            "etf_name": row.get("etf_name"),
            "signal": signal,
            "position_multiplier": effective,
            "signal_reason": row.get("signal_reason"),
            "open_change_pct": row.get("open_change_pct"),
            "volume_ratio": row.get("volume_ratio"),
        }
        if gate_u != "STOP" and signal in ("STRONG", "CAUTIOUS") and effective > 0:
            main_actions.append(item)
        else:
            observe_list.append(item)

    risk_controls = [
        f"市场门闸：{gate_u}；门闸系数 {gate_multiplier:.1f}",
        "单只ETF仓位不超过20%，总仓位遵循当日总策略上限。",
        "若开盘30分钟内涨幅回吐超过一半，降低预期并回归观察。",
        "溢价提示仅可使用实时IOPV同点比较，禁止跨时点净值比价。",
    ]
    if gate_u == "STOP":
        risk_controls.insert(0, "环境门闸为 STOP，本栏目仅保留观察，不输出主建议。")

    return {
        "market_gate": gate_u,
        "gate_multiplier": gate_multiplier,
        "main_actions": main_actions[:5],
        "observe_list": observe_list[:10],
        "risk_controls": risk_controls,
    }


def _attach_rotation_opening_block(
    rd: Dict[str, Any],
    errors: List[Dict[str, str]],
    *,
    fetch_etf_fn: Callable[..., Any],
    fetch_mode: str,
    allow_realtime_validation: bool,
) -> None:
    cfg = _load_rotation_validation_config()
    opening_td = _normalize_trade_date_ymd(rd.get("trade_date") or rd.get("date") or _now_sh().strftime("%Y-%m-%d"))
    rot_loaded = _load_rotation_latest_for_opening(opening_td)
    rot_payload = rot_loaded.get("data") if isinstance(rot_loaded.get("data"), dict) else {}
    candidates = _build_rotation_candidate_union(rot_payload, max_candidates=10)
    market_gate = _derive_rotation_market_gate(rot_payload)
    codes = [str(x.get("etf_code") or "").strip() for x in candidates if str(x.get("etf_code") or "").strip()]
    rt_rows: List[Dict[str, Any]] = []
    if codes and allow_realtime_validation:
        rt_resp = _safe_step(
            "fetch_rotation_etf_realtime",
            fetch_etf_fn,
            errors,
            data_type="realtime",
            etf_code=",".join(codes),
            mode=fetch_mode,
        )
        rt_rows = _extract_realtime_rows(rt_resp)
        rd["tool_fetch_rotation_etf_realtime"] = rt_resp
    if allow_realtime_validation:
        validations, missing_fields = _validate_rotation_opening(candidates, rt_rows, cfg)
    else:
        validations = [
            {
                **rec,
                "signal": "OBSERVE",
                "signal_reason": "非开盘复盘：跳过开盘验证（仅展示轮动清单）",
                "confidence": "low",
                "open_change_pct": None,
                "volume_ratio": None,
                "validation_status": "skipped_non_opening_window",
            }
            for rec in candidates
        ]
        missing_fields = []
    suggestions = _build_rotation_suggestions(validations, market_gate=market_gate, cfg=cfg)

    prev_td = _previous_trading_day_ymd(opening_td)
    rot_td = _normalize_trade_date_ymd(rot_loaded.get("rotation_trade_date") or "")
    freshness = {
        "rotation_trade_date": rot_td,
        "opening_trade_date": opening_td,
        "is_prev_trading_day": bool(rot_td and rot_td == prev_td),
        "note": f"轮动数据基准：{rot_td or 'N/A'}；开盘验证基于当日实时行情。",
    }
    quality_status = "ok"
    degraded_reason = ""
    if not allow_realtime_validation:
        quality_status = "degraded"
        degraded_reason = "not_opening_window_skip_validation"
    elif str(rot_loaded.get("quality_status") or "") != "ok":
        quality_status = "degraded"
        degraded_reason = str(rot_loaded.get("degraded_reason") or "rotation_latest_missing")
    elif not candidates:
        quality_status = "degraded"
        degraded_reason = "rotation_candidates_empty"
    elif len(missing_fields) >= max(1, len(candidates) // 2):
        quality_status = "degraded"
        degraded_reason = "rotation_realtime_partially_missing"

    rd["rotation_opening_candidates"] = candidates
    rd["rotation_opening_validation"] = validations
    rd["rotation_trading_suggestions"] = suggestions
    rd["rotation_validation_quality"] = {
        "quality_status": quality_status,
        "degraded_reason": degraded_reason,
        "missing_fields": missing_fields,
        "rotation_source_path": rot_loaded.get("path"),
    }
    rd["rotation_data_freshness"] = freshness


def _extract_pct(row: Dict[str, Any]) -> Optional[float]:
    return _to_float(row.get("change_pct") if row.get("change_pct") is not None else row.get("change_percent"))


def _asset_strength_from_pct(pct: Optional[float]) -> str:
    if pct is None:
        return "中"
    # 开盘短窗口用更敏感阈值，避免几乎全部落在“中”导致资金判读失真
    if pct >= 0.15:
        return "强"
    if pct <= -0.15:
        return "弱"
    return "中"


def _parse_snapshot_ts(v: Any) -> Optional[datetime]:
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except Exception:
            continue
    return None


def _sign(x: Optional[float], eps: float = 1e-9) -> int:
    if x is None:
        return 0
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def _cross_check_index_etf_consistency(
    *,
    idx_rows: List[Dict[str, Any]],
    etf_rows: List[Dict[str, Any]],
    snapshot_time: str,
) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    idx = next((x for x in idx_rows if str(x.get("code") or "").strip() == "000300"), None)
    etf = next((x for x in etf_rows if str(x.get("code") or "").strip() == "510300"), None)
    idx_pct = _extract_pct(idx or {}) if isinstance(idx, dict) else None
    etf_pct = _extract_pct(etf or {}) if isinstance(etf, dict) else None

    if _sign(idx_pct) != 0 and _sign(etf_pct) != 0 and _sign(idx_pct) != _sign(etf_pct):
        flags.append(
            {
                "code": "direction_conflict",
                "severity": "medium",
                "index_code": "000300",
                "etf_code": "510300",
                "index_pct": idx_pct,
                "etf_pct": etf_pct,
            }
        )

    if idx_pct is not None and etf_pct is not None and abs(float(etf_pct) - float(idx_pct)) > 0.8:
        flags.append(
            {
                "code": "large_basis_gap",
                "severity": "low",
                "index_code": "000300",
                "etf_code": "510300",
                "index_pct": idx_pct,
                "etf_pct": etf_pct,
                "gap_pct": round(abs(float(etf_pct) - float(idx_pct)), 4),
                "threshold_pct": 0.8,
            }
        )

    snap_dt = _parse_snapshot_ts(snapshot_time)
    stale_candidates = []
    for label, row in (("000300", idx), ("510300", etf)):
        if not isinstance(row, dict):
            continue
        row_ts = _parse_snapshot_ts(row.get("timestamp") or row.get("as_of"))
        if row_ts is None or snap_dt is None:
            continue
        drift_s = abs((snap_dt - row_ts).total_seconds())
        if drift_s > 300:
            stale_candidates.append({"symbol": label, "drift_s": int(drift_s)})
    if stale_candidates:
        flags.append(
            {
                "code": "stale_data",
                "severity": "low",
                "threshold_s": 300,
                "items": stale_candidates,
            }
        )
    return flags


def _mark_analysis_health(
    rd: Dict[str, Any],
    *,
    analysis_tool_key: str,
) -> None:
    """
    分析契约健康检查：避免分析缺失时静默渲染 N/A。
    不抛错，统一写入 rd.analysis_health / rd.degraded.analysis_health。
    """
    analysis = rd.get("analysis")
    tool_blob = rd.get(analysis_tool_key)
    reason = ""
    if not isinstance(tool_blob, dict):
        reason = "analysis_tool_missing"
    elif tool_blob.get("success") is False:
        reason = f"analysis_tool_failed:{tool_blob.get('message') or 'unknown'}"
    elif not isinstance(analysis, dict) or not analysis:
        reason = "analysis_payload_missing"
    else:
        has_trend = any(
            analysis.get(k) is not None
            for k in ("overall_trend", "final_trend", "trend_strength", "final_strength")
        )
        summ = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
        report_meta = analysis.get("report_meta") if isinstance(analysis.get("report_meta"), dict) else {}
        if not has_trend and not isinstance(summ.get("market_sentiment"), str):
            if not isinstance(report_meta.get("market_sentiment_score"), (int, float)):
                reason = "analysis_missing_trend_fields"

    if reason:
        rd["analysis_health"] = {
            "status": "degraded",
            "reason": reason,
            "analysis_tool_key": analysis_tool_key,
        }
        rd.setdefault("degraded", {})
        rd["degraded"]["analysis_health"] = reason
    else:
        rd["analysis_health"] = {
            "status": "ok",
            "reason": "",
            "analysis_tool_key": analysis_tool_key,
        }


def _merge_market_overview(gspot: Any, opening: Any) -> Optional[Dict[str, Any]]:
    by_code: Dict[str, Dict[str, Any]] = {}
    for row in _indices_from_response(gspot):
        c = row.get("code") or row.get("name")
        if c:
            by_code[str(c)] = row
    for row in _indices_from_response(opening):
        c = row.get("code") or row.get("name")
        if c:
            by_code[str(c)] = row
    if not by_code:
        return None
    return {"indices": list(by_code.values())}


def _extract_change_pct(row: Dict[str, Any]) -> Optional[float]:
    v = row.get("change_pct")
    if v is None:
        v = row.get("change_percent")
    try:
        return None if v is None else float(v)
    except Exception:
        return None


_OVERNIGHT_CODE_ALIASES: Dict[str, Tuple[str, ...]] = {
    "^N225": ("^N225", "N225", "NKY", "NI225", "日经225", "日经"),
    "^DJI": ("^DJI", "DJI", "DOW", "INT_DJI", "US30", "道琼斯", "道指"),
    "^GSPC": ("^GSPC", "GSPC", "SPX", "SP500", "标普500", "标普"),
    "^IXIC": ("^IXIC", "IXIC", "NDX", "NASDAQ", "纳斯达克", "纳指"),
    "A50": ("A50", "CN00Y", "XIN9", "富时A50", "A50期指"),
}

_OVERNIGHT_DEFAULT_WEIGHTS: Dict[str, float] = {
    "A50": 0.25,
    "^N225": 0.15,
    "^DJI": 0.20,
    "^GSPC": 0.20,
    "^IXIC": 0.20,
}


def _normalize_code(v: Any) -> str:
    s = str(v or "").strip().upper()
    if not s:
        return ""
    return s.replace("-", "").replace("_", "")


def _find_index_row(rows: List[Dict[str, Any]], canonical: str) -> Optional[Dict[str, Any]]:
    aliases = _OVERNIGHT_CODE_ALIASES.get(canonical, (canonical,))
    alias_norm = {_normalize_code(x) for x in aliases}
    for row in rows:
        code_norm = _normalize_code(row.get("code") or row.get("name"))
        if code_norm in alias_norm:
            return row
    return None


def _overnight_strength_factor(change_pct: Optional[float]) -> float:
    if change_pct is None:
        return 0.0
    if change_pct > 1.0:
        return 1.0
    if change_pct > 0.3:
        return 0.6
    if change_pct >= -0.3:
        return 0.0
    if change_pct >= -1.0:
        return -0.6
    return -1.0


def _overnight_label(score: float) -> str:
    if score > 0.25:
        return "偏强"
    if score < -0.25:
        return "谨慎偏弱"
    return "分化"


def _extract_local_trend_score(rd: Dict[str, Any]) -> float:
    analysis = rd.get("analysis") if isinstance(rd.get("analysis"), dict) else {}
    vals: List[float] = []
    for v in (
        rd.get("trend_strength"),
        analysis.get("trend_strength"),
        analysis.get("final_strength"),
        (analysis.get("summary") or {}).get("sentiment_score") if isinstance(analysis.get("summary"), dict) else None,
        (analysis.get("report_meta") or {}).get("market_sentiment_score") if isinstance(analysis.get("report_meta"), dict) else None,
    ):
        if isinstance(v, (int, float)):
            vals.append(float(v))
    if vals:
        return float(max(-1.0, min(1.0, vals[0])))
    return 0.0


def _build_overnight_bias(rd: Dict[str, Any]) -> Dict[str, Any]:
    mo = rd.get("market_overview") if isinstance(rd.get("market_overview"), dict) else {}
    rows = [x for x in (mo.get("indices") or []) if isinstance(x, dict)]
    votes: List[Dict[str, Any]] = []
    weighted_sum = 0.0
    available_weight = 0.0
    up_count = down_count = flat_count = 0
    matched_count = 0
    missing_codes: List[str] = []
    for code, weight in _OVERNIGHT_DEFAULT_WEIGHTS.items():
        row = _find_index_row(rows, code)
        pct = _extract_change_pct(row or {})
        sf = _overnight_strength_factor(pct)
        contrib = round(weight * sf, 4)
        has_data = row is not None and pct is not None
        if has_data:
            matched_count += 1
            if sf > 0:
                up_count += 1
            elif sf < 0:
                down_count += 1
            else:
                flat_count += 1
            available_weight += weight
        else:
            missing_codes.append(code)
        weighted_sum += contrib
        votes.append(
            {
                "index_code": code,
                "weight": weight,
                "change_pct": pct,
                "strength_factor": sf,
                "weighted_contribution": contrib,
                "has_data": has_data,
            }
        )
    score = round(weighted_sum, 4)
    return {
        "votes": votes,
        "score": score,
        "label": _overnight_label(score),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "matched_count": matched_count,
        "target_count": len(_OVERNIGHT_DEFAULT_WEIGHTS),
        "missing_codes": missing_codes,
        "available_weight": round(available_weight, 4),
        "scope": "A50,^N225,^DJI,^GSPC,^IXIC",
    }


def _apply_opening_trend_resolution(rd: Dict[str, Any]) -> None:
    overnight = _build_overnight_bias(rd)
    rd["overnight_bias_vote"] = overnight.get("votes")
    rd["overnight_bias_score"] = overnight.get("score")
    rd["overnight_bias_label"] = overnight.get("label")
    rd["up_count"] = overnight.get("up_count")
    rd["down_count"] = overnight.get("down_count")
    rd["flat_count"] = overnight.get("flat_count")
    rd["matched_count"] = overnight.get("matched_count")
    rd["target_count"] = overnight.get("target_count")
    rd["scope"] = overnight.get("scope")
    local_score = _extract_local_trend_score(rd)
    overnight_score = float(overnight.get("score") or 0.0)
    conflict = (
        (local_score * overnight_score) < 0
        and abs(local_score - overnight_score) > 0.3
    )
    resolved_trend = str(overnight.get("label") or "分化")
    if conflict:
        if overnight_score <= -0.2:
            resolved_trend = "分化/谨慎偏弱"
        elif overnight_score >= 0.2:
            resolved_trend = "分化/谨慎偏强"
    # 无论是否冲突，都必须写入结论字段；否则会在“同向”场景落入 N/A。
    rd["overall_trend"] = resolved_trend
    rd["trend_strength"] = round(overnight_score, 4)
    rd["trend_resolution"] = {
        "local_score": round(local_score, 4),
        "overnight_score": round(overnight_score, 4),
        "conflict": conflict,
        "conflict_threshold": 0.3,
        "resolved_overall_trend": resolved_trend,
        "matched_count": overnight.get("matched_count"),
        "target_count": overnight.get("target_count"),
        "scope": overnight.get("scope"),
    }


def _build_policy_event_signals(rd: Dict[str, Any]) -> None:
    pn = rd.get("tool_fetch_policy_news")
    payload = pn.get("data") if isinstance(pn, dict) else None
    if not isinstance(payload, dict):
        rd["policy_event_signals"] = []
        rd["policy_event_quality"] = {
            "quality_status": "degraded",
            "degraded_reason": "policy_news_payload_missing",
        }
        return
    items = [x for x in (payload.get("items") or []) if isinstance(x, dict)]
    brief = str(payload.get("brief_answer") or "")
    full_text = "\n".join([brief] + [str(x.get("title") or "") + " " + str(x.get("summary") or "") for x in items])
    events: List[Dict[str, Any]] = []

    def _extract_vote_split(text: str) -> str:
        m = re.search(r"(\d+)\s*[-比:]\s*(\d+)", text)
        if not m:
            return ""
        return f"{m.group(1)}-{m.group(2)}"

    def _extract_rate_decision(text: str) -> str:
        if re.search(r"维持|不变|hold|unchanged", text, re.I):
            return "hold"
        if re.search(r"加息|上调|hike|raise", text, re.I):
            return "hike"
        if re.search(r"降息|下调|cut", text, re.I):
            return "cut"
        return "unknown"

    if re.search(r"美联储|FOMC|Federal Reserve", full_text, re.I):
        vote_split = _extract_vote_split(full_text)
        has_rate = bool(re.search(r"利率|bps|基点|维持|加息|降息|hold|cut|hike", full_text, re.I))
        stance = "neutral"
        if re.search(r"加息|hawk|偏鹰|higher for longer", full_text, re.I):
            stance = "hawkish"
        elif re.search(r"降息|dovish|偏鸽", full_text, re.I):
            stance = "dovish"
        rate_decision = _extract_rate_decision(full_text)
        events.append(
            {
                "event_type": "FOMC",
                "policy_stance": stance,
                "rate_decision": rate_decision,
                "vote_split": vote_split,
                "market_impact_chain": "利率路径预期 -> 全球风险偏好 -> A股开盘风险偏好",
                "confidence": 0.85 if vote_split and has_rate and rate_decision != "unknown" else 0.6,
            }
        )

    if re.search(r"油价|原油|布油|WTI|伊朗|封锁|港口", full_text, re.I):
        events.append(
            {
                "event_type": "OilShock",
                "policy_stance": "inflationary_risk",
                "vote_split": "",
                "market_impact_chain": "能源价格上行 -> 通胀预期抬升 -> 利率预期偏紧 -> 权益风险偏好回落",
                "confidence": 0.75,
            }
        )

    if re.search(r"Meta|并购|收购|AI|监管|国家安全", full_text, re.I):
        events.append(
            {
                "event_type": "CrossBorderAIMnA",
                "policy_stance": "regulatory_tightening",
                "vote_split": "",
                "market_impact_chain": "跨境并购监管趋严 -> 科技估值风险溢价上升 -> 情绪影响中长期大于短期",
                "confidence": 0.65,
            }
        )

    fed_expected = bool(re.search(r"美联储|FOMC|Federal Reserve", full_text, re.I))
    fed_event = next((e for e in events if e.get("event_type") == "FOMC"), None)
    reason_codes: List[str] = []
    if fed_expected and fed_event is None:
        reason_codes.append("missing_fomc_core_event")
    if fed_event is not None:
        if not str(fed_event.get("vote_split") or "").strip():
            reason_codes.append("missing_fomc_vote_split")
        if not re.match(r"^\d+-\d+$", str(fed_event.get("vote_split") or "").strip()):
            reason_codes.append("invalid_vote_split_format")
        if str(fed_event.get("rate_decision") or "unknown") == "unknown":
            reason_codes.append("missing_fomc_rate_decision")
        stance = str(fed_event.get("policy_stance") or "")
        rate_decision = str(fed_event.get("rate_decision") or "")
        if rate_decision == "cut" and stance == "hawkish":
            reason_codes.append("fomc_stance_conflict")
        if rate_decision == "hike" and stance == "dovish":
            reason_codes.append("fomc_stance_conflict")

    if reason_codes:
        severity = "error" if any(x.startswith("missing_fomc") or x in ("invalid_vote_split_format", "fomc_stance_conflict") for x in reason_codes) else "degraded"
        q = {
            "quality_status": severity,
            "degraded_reason": reason_codes[0],
            "reason_codes": reason_codes,
            "required_fields": ["event_type", "rate_decision", "vote_split", "policy_stance"],
        }
    elif not events:
        q = {
            "quality_status": "degraded",
            "degraded_reason": "policy_events_not_structured",
            "reason_codes": ["policy_events_not_structured"],
            "required_fields": ["event_type", "rate_decision", "vote_split", "policy_stance"],
        }
    else:
        q = {
            "quality_status": "ok",
            "degraded_reason": "",
            "reason_codes": [],
            "required_fields": ["event_type", "rate_decision", "vote_split", "policy_stance"],
        }
    rd["policy_event_signals"] = events
    rd["policy_event_quality"] = q
    if q.get("quality_status") != "ok":
        rd.setdefault("degraded", {})
        rd["degraded"]["policy_event_quality"] = q.get("degraded_reason")


def _compute_holiday_position_hint(rd: Dict[str, Any]) -> None:
    try:
        from src.config_loader import load_system_config
        from src.system_status import is_trading_day
        cfg = load_system_config(use_cache=True)
    except Exception:
        cfg = None
        is_trading_day = None  # type: ignore
    td_raw = str(rd.get("trade_date") or "").strip()
    hint: Dict[str, Any] = {"enabled": False, "non_trading_days_ahead": 0}
    try:
        dt = datetime.strptime(td_raw, "%Y-%m-%d")
    except Exception:
        rd["holiday_position_hint"] = hint
        return
    cnt = 0
    if is_trading_day is not None:
        for i in range(1, 8):
            d = dt + timedelta(days=i)
            if is_trading_day(d, cfg):
                break
            cnt += 1
    hint["non_trading_days_ahead"] = cnt
    hint["enabled"] = cnt >= 3
    if hint["enabled"]:
        hint["title"] = "节前持仓提示"
        hint["bias_label"] = rd.get("overnight_bias_label") or "分化"
    rd["holiday_position_hint"] = hint


def _change_pct_is_usable(row: Optional[Dict[str, Any]]) -> bool:
    """与报告层一致：None/NaN/inf 视为缺数，需 hist 补全。"""
    if not isinstance(row, dict):
        return False
    p = _extract_change_pct(row)
    if p is None:
        return False
    try:
        if isinstance(p, float) and (math.isnan(p) or math.isinf(p)):
            return False
    except Exception:
        return False
    return True


def _hist_resp_to_index_row(code: str, resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    将 tool_fetch_global_index_hist_sina 的返回（data 为日线 rows）转为 global_spot 风格的一行。
    """
    data = resp.get("data")
    if not isinstance(data, list) or len(data) < 2:
        return None
    r2 = data[-2] if isinstance(data[-2], dict) else None
    r1 = data[-1] if isinstance(data[-1], dict) else None
    if not isinstance(r1, dict) or not isinstance(r2, dict):
        return None
    try:
        close1 = float(r1.get("close"))
        close2 = float(r2.get("close"))
    except Exception:
        return None
    if close2 == 0:
        return None
    change = close1 - close2
    change_pct = change / close2 * 100.0
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bar_date = str(r1.get("date") or "").strip()
    return {
        "code": code,
        "name": code,
        "price": close1,
        "change": change,
        "change_pct": round(change_pct, 4),
        "timestamp": ts,
        "as_of": ts,
        "data_semantics": "daily_close",
        "source_detail": f"global_hist_sina;bar_date={bar_date}",
    }


def _maybe_fill_opening_global_from_hist(rd: Dict[str, Any], errors: List[Dict[str, str]]) -> None:
    """
    开盘：spot 缺行或缺 change_pct 时，用 akshare 新浪全球指数日线补齐上一完整交易日收盘涨跌幅。
    覆盖美股/日韩/欧股，避免仅欧股被 hist 补全而美股组缺失（global_spot 主源偶发不全时）。
    结果写入 market_overview.indices，供 send_daily_report 统一渲染。

    注意：新浪现货行可能用 ``int_dji`` 等 code，不能用 ``by_code.get('^DJI')`` 判断；
    缺数须与 ``send_daily_report._opening_pick_row`` 同一套归一化匹配。
    """
    try:
        from plugins.data_collection.index.fetch_global_hist_sina import tool_fetch_global_index_hist_sina
        from plugins.notification.send_daily_report import (
            _opening_global_index_rows,
            _opening_index_code_match,
            _opening_pick_row,
        )
    except Exception as e:
        logger.warning("opening_runner: import global_hist_sina failed: %s", e)
        return

    mo = rd.get("market_overview")
    if not isinstance(mo, dict):
        mo = {}
    indices = mo.get("indices")
    idx_list: List[Dict[str, Any]] = [x for x in indices if isinstance(x, dict)] if isinstance(indices, list) else []
    by_code = {str(x.get("code") or x.get("name") or ""): x for x in idx_list if (x.get("code") or x.get("name"))}

    def _merged_preview_rows() -> List[Dict[str, Any]]:
        """与发送层一致：gspot + 当前正在编辑的 indices。"""
        tmp = {**rd, "market_overview": {"indices": list(by_code.values())}}
        return _opening_global_index_rows(tmp)

    filled_rows: List[Dict[str, Any]] = []
    for code in _OPENING_GLOBAL_HIST_CODES:
        rows_preview = _merged_preview_rows()
        existing = _opening_pick_row(rows_preview, code)
        if _change_pct_is_usable(existing):
            continue
        resp = _safe_step(f"fetch_global_index_hist_sina:{code}", tool_fetch_global_index_hist_sina, errors, symbol=code, limit=2)
        if not isinstance(resp, dict) or not resp.get("success"):
            continue
        row = _hist_resp_to_index_row(code, resp)
        if not row:
            continue
        # 用更友好的中文名（如果 spot 已有 name 则保留）
        if isinstance(existing, dict) and existing.get("name"):
            row["name"] = existing.get("name")
        # 去掉同指数的旧别名行（如 int_dji），避免隔夜节重复或匹配歧义
        for k in list(by_code.keys()):
            o = by_code[k]
            if isinstance(o, dict) and _opening_index_code_match(o.get("code"), code):
                del by_code[k]
        by_code[str(row.get("code") or code)] = row
        filled_rows.append(row)

    if filled_rows:
        rd["tool_fetch_global_index_hist_sina"] = {
            "success": True,
            "count": len(filled_rows),
            "data": filled_rows,
            "source": "akshare.index_global_hist_sina",
        }
        mo["indices"] = list(by_code.values())
        rd["market_overview"] = mo


def _opening_us_jk_lines_would_be_empty(rd: Dict[str, Any]) -> bool:
    """
    与 send_daily_report 开盘「隔夜指示」一致：若美股与日/韩两组都拼不出一行，则需 Tavily 等兜底。
    注意：yfinance/新浪可能返回非空 data，但只有恒生或 A 股指数，仍会导致两组均为空。
    """
    try:
        from plugins.notification.send_daily_report import (
            _OPENING_JK_CODES,
            _OPENING_US_CODES,
            _fmt_opening_index_group,
            _opening_global_index_rows,
        )
    except Exception:
        return True
    rows = _opening_global_index_rows(rd)
    us = _fmt_opening_index_group("美股（北京时间当日凌晨时段）", _OPENING_US_CODES, rows)
    jk = _fmt_opening_index_group("日/韩（当日已开盘）", _OPENING_JK_CODES, rows)
    return not us and not jk


def _maybe_attach_global_market_tavily_digest(rd: Dict[str, Any], gspot: Any) -> None:
    """
    fetch_global 在 data 完全为空时会内嵌 Tavily；若仅有部分指数或缺少 ^DJI 等，仍可能两组标题都为空，
    此时只要合并后的 report_data 仍拼不出美股/日韩行，就补拉 Tavily（与盘后 overlay 同源）。
    """
    if isinstance(rd.get("global_market_digest"), dict) and str(rd["global_market_digest"].get("summary") or "").strip():
        return
    if not _opening_us_jk_lines_would_be_empty(rd):
        return
    try:
        from src.config_loader import load_system_config
        from plugins.analysis.trend_analysis import _merge_trend_plugin_config, _tavily_fallback_global_digest

        cfg = load_system_config(use_cache=True)
        ov = (_merge_trend_plugin_config(cfg).get("overlay") or {})
        fb = _tavily_fallback_global_digest(ov)
        if isinstance(fb, dict) and str(fb.get("summary") or "").strip():
            rd["global_market_digest"] = fb
    except Exception as e:
        logger.warning("opening_runner global_market_digest (tavily): %s", e)


def build_opening_report_data(fetch_mode: str = "production") -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """
    按 opening_analysis.yaml 顺序采集并组装 report_data（含 report_type=opening）。
    返回 (report_data, runner_errors)。
    """
    errors: List[Dict[str, str]] = []
    mode = fetch_mode if fetch_mode in ("production", "test") else "production"

    from plugins.data_collection.utils.check_trading_status import tool_check_trading_status
    from plugins.merged.fetch_index_data import tool_fetch_index_data
    # NOTE: `plugins.data_collection` is a symlink to the OpenClaw runtime plugin directory (read-only).
    # We use an assistant-side policy news fetcher to ensure TAVILY_API_KEYS multi-key rotation (incl. HTTP 432).
    from plugins.data_access.policy_news import tool_fetch_policy_news
    from plugins.data_collection.morning_brief_fetchers import (
        tool_fetch_macro_commodities,
        tool_fetch_overnight_futures_digest,
        tool_fetch_announcement_digest,
    )
    from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score
    from plugins.analysis.key_levels import tool_compute_index_key_levels
    from plugins.merged.fetch_etf_data import tool_fetch_etf_data
    from src.services.indicator_runtime import calculate_indicators_via_tool, resolve_indicator_runtime
    from plugins.merged.analyze_market import tool_analyze_market
    from plugins.merged.volatility import tool_volatility
    from plugins.analysis.intraday_range import tool_predict_intraday_range
    from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range
    from plugins.analysis.accuracy_tracker import tool_get_yesterday_prediction_review
    from src.signal_generation import tool_generate_option_trading_signals

    rd: Dict[str, Any] = {
        "report_type": "opening",
        "runner_version": "opening_analysis_composite_v1",
    }

    now = _now_sh()
    rd["date"] = now.strftime("%Y-%m-%d")
    rd["trade_date"] = rd["date"]
    rd["generated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

    ts = _safe_step("check_trading_status", tool_check_trading_status, errors)
    if ts is not None:
        rd["trading_status"] = ts
        ts_data = ts.get("data") if isinstance(ts, dict) else None
        if isinstance(ts_data, dict):
            rule = ts_data.get("quote_narration_rule_cn")
            if isinstance(rule, str) and rule.strip():
                txt = rule.strip()
                rd["a_share_regime_note"] = txt if txt.startswith("- ") else f"- {txt}"

    gspot = _safe_step(
        "fetch_global_index_spot",
        tool_fetch_index_data,
        errors,
        data_type="global_spot",
        mode=mode,
        index_codes=_OPENING_GLOBAL_INDEX_CODES,
    )
    if gspot is not None:
        rd["tool_fetch_global_index_spot"] = gspot
        emb = gspot.get("global_market_digest")
        if isinstance(emb, dict) and str(emb.get("summary") or "").strip():
            rd["global_market_digest"] = emb
        _attach_global_spot_report_fields(rd, gspot)
        _maybe_attach_global_spot_catalog_debug(rd, gspot)

    idx_opening = _safe_step(
        "fetch_index_opening",
        tool_fetch_index_data,
        errors,
        data_type="opening",
        mode=mode,
    )
    if idx_opening is not None:
        rd["tool_fetch_index_opening"] = idx_opening

    mo = _merge_market_overview(gspot, idx_opening)
    if mo:
        rd["market_overview"] = mo

    # 与盘后 daily_report_overlay 同源：yfinance+新浪均无有效行时，用 Tavily 拼一段外盘定性摘要（非逐点涨跌幅）
    _maybe_attach_global_market_tavily_digest(rd, gspot)

    # 全球主要指数：用历史日线补齐 spot 缺口（美/日/韩/欧），避免隔夜指示只出半屏
    _maybe_fill_opening_global_from_hist(rd, errors)

    pn = _safe_step(
        "fetch_policy_news",
        tool_fetch_policy_news,
        errors,
        max_items=5,
    )
    if pn is not None:
        rd["tool_fetch_policy_news"] = pn
    _build_policy_event_signals(rd)

    macro = _safe_step("fetch_macro_commodities", tool_fetch_macro_commodities, errors)
    if macro is not None:
        rd["tool_fetch_macro_commodities"] = macro

    od = _safe_step(
        "fetch_overnight_futures_digest",
        tool_fetch_overnight_futures_digest,
        errors,
        disable_network=False,
    )
    if od is not None:
        rd["tool_fetch_overnight_futures_digest"] = od
        od_inner = od.get("data") if isinstance(od, dict) else None
        if isinstance(od_inner, dict) and (od_inner.get("a50_digest") or od_inner.get("hxc_digest")):
            rd["overnight_digest"] = od_inner

    ann = _safe_step(
        "fetch_announcement_digest",
        tool_fetch_announcement_digest,
        errors,
        max_items=5,
        disable_network=False,
    )
    if ann is not None:
        rd["tool_fetch_announcement_digest"] = ann

    sector_td = _previous_trading_day_yyyymmdd_for_opening_sector()
    sector = _safe_step(
        "sector_heat_score",
        tool_sector_heat_score,
        errors,
        date=sector_td,
    )
    if sector is not None:
        rd["tool_sector_heat_score"] = sector
        rd["sector_heat_ref_trade_date"] = sector_td
        rd["sector_heat_ref_note"] = (
            "盘前任务采用上一交易日涨停与板块样本；当日开盘初刻数据可能尚未完整。"
        )

    kl = _safe_step(
        "compute_index_key_levels",
        tool_compute_index_key_levels,
        errors,
        index_code="000300",
    )
    if kl is not None:
        rd["tool_compute_index_key_levels"] = kl

    rt_idx = _safe_step(
        "fetch_index_realtime",
        tool_fetch_index_data,
        errors,
        data_type="realtime",
        index_code="000300,000016,000001,399006",
        mode=mode,
    )
    if rt_idx is not None:
        rd["tool_fetch_index_realtime"] = rt_idx

    rt_etf = _safe_step(
        "fetch_etf_realtime",
        tool_fetch_etf_data,
        errors,
        data_type="realtime",
        etf_code="510300,510050,510500",
        mode=mode,
    )
    if rt_etf is not None:
        rd["tool_fetch_etf_realtime"] = rt_etf

    _ind_rt = resolve_indicator_runtime("opening_analysis")
    tech = _safe_step(
        "technical_indicators",
        calculate_indicators_via_tool,
        errors,
        symbol="510300",
        data_type="etf_daily",
        indicators=["ma", "macd", "rsi", "bollinger", "atr"],
    )
    if tech is not None:
        rd["tool_calculate_technical_indicators"] = tech
        rd["indicator_runtime"] = {
            "task": "opening_analysis",
            "route": _ind_rt.route,
            "notes": _ind_rt.notes,
        }

    opening_analysis = _safe_step(
        "analyze_opening_market",
        tool_analyze_market,
        errors,
        moment="opening",
    )
    if opening_analysis is not None:
        rd["tool_analyze_market"] = opening_analysis
        rd["analyze_opening_market"] = opening_analysis
        if isinstance(opening_analysis, dict) and opening_analysis.get("success"):
            data = opening_analysis.get("data")
            if isinstance(data, dict) and data:
                rd["analysis"] = data
    _mark_analysis_health(rd, analysis_tool_key="tool_analyze_market")
    _apply_opening_trend_resolution(rd)

    vol = _safe_step(
        "predict_volatility",
        tool_volatility,
        errors,
        mode="predict",
        underlying="510300",
    )
    if vol is not None:
        rd["tool_predict_volatility"] = vol
        if isinstance(vol, dict):
            data_obj = vol.get("data")
            use_struct = False
            if isinstance(data_obj, dict) and data_obj.get("success") is not False:
                if any(
                    data_obj.get(k) is not None for k in ("upper", "lower", "current_price", "range_pct")
                ):
                    use_struct = True
            if use_struct:
                rd["volatility"] = data_obj
            else:
                fo = vol.get("formatted_output")
                if isinstance(fo, str) and fo.strip():
                    rd["volatility_prediction"] = fo.strip()
                elif vol.get("success") and isinstance(vol.get("message"), str):
                    rd["volatility_prediction"] = str(vol.get("message"))

    intr = _safe_step(
        "predict_intraday_range",
        tool_predict_intraday_range,
        errors,
        symbol="510300",
    )
    if intr is not None:
        rd["tool_predict_intraday_range"] = intr
        if isinstance(intr, dict) and intr.get("success"):
            inner = intr.get("data")
            if isinstance(inner, dict):
                rd["intraday_range"] = inner

    dvol = _safe_step(
        "predict_daily_volatility_range",
        tool_predict_daily_volatility_range,
        errors,
        underlying="510300",
    )
    if dvol is not None:
        rd["tool_predict_daily_volatility_range"] = dvol
        if isinstance(dvol, dict) and dvol.get("success") is not False:
            rd["daily_volatility_range"] = dvol

    prev = _safe_step(
        "prediction_review",
        tool_get_yesterday_prediction_review,
        errors,
    )
    if prev is not None:
        rd["tool_get_yesterday_prediction_review"] = prev
        if isinstance(prev, dict) and prev.get("success"):
            pdata = prev.get("data")
            if pdata is not None:
                rd["prediction_review"] = pdata

    sig_mode = "production" if mode == "production" else "test"
    sig = _safe_step(
        "generate_option_trading_signals",
        tool_generate_option_trading_signals,
        errors,
        underlying="510300",
        mode=sig_mode,
    )
    if sig is not None:
        rd["tool_generate_option_trading_signals"] = sig

    # 开盘数据契约：供发送层按“开盘快照/资金与成交状态/跟踪标的”渲染
    idx_rows = _rows_from_tool_data(rt_idx)
    etf_rows = _rows_from_tool_data(rt_etf)
    tracked_etf = []
    for r in etf_rows[:12]:
        code = str(r.get("code") or r.get("symbol") or "").strip()
        if not code:
            continue
        pct = _extract_pct(r)
        tracked_etf.append(
            {
                "code": code,
                "name": r.get("name") or code,
                "price": _to_float(r.get("price") or r.get("current_price")),
                "change_pct": pct,
                "strength": _asset_strength_from_pct(pct),
            }
        )

    opening_idx = _rows_from_tool_data(idx_opening)
    rd["opening_market_snapshot"] = {
        "snapshot_time": rd.get("generated_at"),
        "indices_opening": opening_idx[:12],
        "indices_realtime": idx_rows[:12],
        "etf_realtime": etf_rows[:12],
    }
    rd["tracked_assets_snapshot"] = {
        "etf": tracked_etf,
        "stocks": [],
    }
    strong_cnt = len([x for x in tracked_etf if x.get("strength") == "强"])
    weak_cnt = len([x for x in tracked_etf if x.get("strength") == "弱"])
    heat_rows = []
    if isinstance(sector, dict):
        heat_rows = [x for x in (sector.get("sectors") or []) if isinstance(x, dict)]
    rd["opening_flow_signals"] = {
        "market_breadth": {
            "tracked_etf_strong_count": strong_cnt,
            "tracked_etf_weak_count": weak_cnt,
            "tracked_etf_total": len(tracked_etf),
        },
        "sector_heat_top": heat_rows[:5],
        "flow_bias": "偏强" if strong_cnt > weak_cnt else ("偏弱" if weak_cnt > strong_cnt else "中性"),
        "note": "基于ETF强弱与板块热度的开盘资金状态近似，不含北向资金口径。",
    }
    intraday_allowed = True
    tsd = ts.get("data") if isinstance(ts, dict) else None
    if isinstance(tsd, dict) and tsd.get("allows_intraday_continuous_wording") is False:
        intraday_allowed = False
    _attach_rotation_opening_block(
        rd,
        errors,
        fetch_etf_fn=tool_fetch_etf_data,
        fetch_mode=mode,
        allow_realtime_validation=bool(intraday_allowed),
    )
    rd["runtime_context"] = {
        "is_opening_window": bool(intraday_allowed),
        "snapshot_time": rd.get("generated_at"),
        "fallback_mode": "replay" if not intraday_allowed else "realtime",
    }
    _compute_holiday_position_hint(rd)

    if errors:
        rd["runner_errors"] = errors

    # 隔夜指示四类：主源仍缺时按类 Tavily（需在 analysis/A50 与 hist 合并之后）
    try:
        from plugins.notification.send_daily_report import attach_opening_overnight_category_tavily

        attach_opening_overnight_category_tavily(rd)
    except Exception as e:
        logger.warning("opening_runner attach_opening_overnight_category_tavily: %s", e)

    return rd, errors


def tool_run_opening_analysis_and_send(
    mode: str = "prod",
    fetch_mode: str = "production",
    report_variant: str = "legacy",
    workflow_profile: str = "legacy",
    stage_budget_profile: str = "balanced",
    emit_stage_timing: bool = True,
    max_concurrency: int = 4,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    split_markdown_sections: bool = True,
    max_chars_per_message: Optional[int] = None,
) -> Dict[str, Any]:
    """
    进程内执行开盘行情分析全链路并发送钉钉（report_type=opening）。

    Args:
        mode: prod|test（钉钉；test 不发网络请求）
        fetch_mode: production|test（透传指数/ETF 等采集）
        report_variant: legacy|realtime，控制 opening 报告模板分支
        workflow_profile: legacy|cron_balanced，控制是否启用阶段预算/并发/去重等优化策略
        stage_budget_profile: balanced|tight|off，阶段预算档位
        emit_stage_timing: 是否输出 stage_timing/lineage_struct 等观测字段
        max_concurrency: 慢源并发上限（仅 workflow_profile=cron_balanced 生效）
        webhook_url/secret/keyword: 可选，透传发送层
        split_markdown_sections: 默认 True，与每日市场分析报告一致按章节分条；单条推送时显式 False。
        max_chars_per_message: 可选；省略则读 config notification.dingtalk_max_chars_per_message。
    """
    from plugins.notification.send_analysis_report import tool_send_analysis_report
    profile = (workflow_profile or "").strip().lower()
    budgets = _stage_budget_profile(stage_budget_profile)

    # observability containers (schema-fixed)
    stage_timing: Dict[str, Dict[str, Any]] = {}
    lineage_struct: List[Dict[str, Any]] = []
    memo: Dict[str, Any] = {}
    sem_pool = _semaphore_pool(max_concurrency=max_concurrency)

    def _call_tool(
        stage: str,
        tool_key: str,
        step_name: str,
        fn: Callable[..., Any],
        errors: List[Dict[str, str]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        started = time.perf_counter()
        provider = _provider_key_for_step(step_name)
        sem = sem_pool.get(provider) or sem_pool["default"]
        try:
            k = _memo_key(fn, args, kwargs)
        except Exception:
            k = None
        if k and k in memo:
            _append_lineage(
                lineage_struct,
                stage=stage,
                tool_key=tool_key,
                started_at=started,
                success=True if isinstance(memo[k], dict) else None,
                quality_status="ok",
                degraded_reason=None,
                source_hint=f"memo;provider={provider}",
            )
            return memo[k]
        try:
            sem.acquire()
            out = fn(*args, **kwargs)
            if k:
                memo[k] = out
            succ = out.get("success") if isinstance(out, dict) else None
            _append_lineage(
                lineage_struct,
                stage=stage,
                tool_key=tool_key,
                started_at=started,
                success=succ if isinstance(succ, bool) else None,
                quality_status="ok",
                degraded_reason=None,
                source_hint=f"provider={provider}",
            )
            return out
        except Exception as e:
            errors.append({"step": step_name, "error": str(e)})
            _append_lineage(
                lineage_struct,
                stage=stage,
                tool_key=tool_key,
                started_at=started,
                success=False,
                quality_status="error",
                degraded_reason="provider_error",
                source_hint=f"provider={provider}",
            )
            return None
        finally:
            try:
                sem.release()
            except Exception:
                pass

    def _build_opening_report_data_optimized(fetch_mode: str) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
        errors: List[Dict[str, str]] = []
        mode_inner = fetch_mode if fetch_mode in ("production", "test") else "production"

        from plugins.data_collection.utils.check_trading_status import tool_check_trading_status
        from plugins.merged.fetch_index_data import tool_fetch_index_data
        from plugins.data_access.policy_news import tool_fetch_policy_news
        from plugins.data_collection.morning_brief_fetchers import (
            tool_fetch_macro_commodities,
            tool_fetch_overnight_futures_digest,
            tool_fetch_announcement_digest,
        )
        from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score
        from plugins.analysis.key_levels import tool_compute_index_key_levels
        from plugins.merged.fetch_etf_data import tool_fetch_etf_data
        from src.services.indicator_runtime import calculate_indicators_via_tool, resolve_indicator_runtime
        from plugins.merged.analyze_market import tool_analyze_market
        from plugins.merged.volatility import tool_volatility
        from plugins.analysis.intraday_range import tool_predict_intraday_range
        from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range
        from plugins.analysis.accuracy_tracker import tool_get_yesterday_prediction_review
        from src.signal_generation import tool_generate_option_trading_signals

        rd: Dict[str, Any] = {
            "report_type": "opening",
            "runner_version": "opening_analysis_composite_v2_stage_budget",
        }
        now = _now_sh()
        rd["date"] = now.strftime("%Y-%m-%d")
        rd["trade_date"] = rd["date"]
        rd["generated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

        # Stage: critical (sequential, budgeted)
        stage = "critical"
        stage_start = time.perf_counter()
        budget = budgets.get(stage)
        sb = _StageBudget(budget)

        def _guard_budget_or_skip(tool_key: str) -> bool:
            if sb.expired():
                _append_lineage(
                    lineage_struct,
                    stage=stage,
                    tool_key=tool_key,
                    started_at=time.perf_counter(),
                    success=None,
                    quality_status="degraded",
                    degraded_reason="timeout",
                    source_hint="skipped_by_budget",
                )
                return True
            return False

        ts = None
        if not _guard_budget_or_skip("tool_check_trading_status"):
            ts = _safe_step(
                "check_trading_status",
                lambda: _call_tool(stage, "tool_check_trading_status", "check_trading_status", tool_check_trading_status, errors),
                errors,
            )
        if ts is not None:
            rd["trading_status"] = ts
            ts_data = ts.get("data") if isinstance(ts, dict) else None
            if isinstance(ts_data, dict):
                rule = ts_data.get("quote_narration_rule_cn")
                if isinstance(rule, str) and rule.strip():
                    txt = rule.strip()
                    rd["a_share_regime_note"] = txt if txt.startswith("- ") else f"- {txt}"

        idx_opening = None
        if not _guard_budget_or_skip("tool_fetch_index_opening"):
            idx_opening = _call_tool(
                stage,
                "tool_fetch_index_opening",
                "fetch_index_opening",
                tool_fetch_index_data,
                errors,
                data_type="opening",
                mode=mode_inner,
            )
        if idx_opening is not None:
            rd["tool_fetch_index_opening"] = idx_opening

        # critical realtime snapshots
        rt_idx = None
        if not _guard_budget_or_skip("tool_fetch_index_realtime"):
            rt_idx = _call_tool(
                stage,
                "tool_fetch_index_realtime",
                "fetch_index_realtime",
                tool_fetch_index_data,
                errors,
                data_type="realtime",
                index_code="000300,000016,000001,399006",
                mode=mode_inner,
            )
        if rt_idx is not None:
            rd["tool_fetch_index_realtime"] = rt_idx

        rt_etf = None
        if not _guard_budget_or_skip("tool_fetch_etf_realtime"):
            rt_etf = _call_tool(
                stage,
                "tool_fetch_etf_realtime",
                "fetch_etf_realtime",
                tool_fetch_etf_data,
                errors,
                data_type="realtime",
                etf_code="510300,510050,510500",
                mode=mode_inner,
            )
        if rt_etf is not None:
            rd["tool_fetch_etf_realtime"] = rt_etf

        kl = None
        if not _guard_budget_or_skip("tool_compute_index_key_levels"):
            kl = _call_tool(
                stage,
                "tool_compute_index_key_levels",
                "compute_index_key_levels",
                tool_compute_index_key_levels,
                errors,
                index_code="000300",
            )
        if kl is not None:
            rd["tool_compute_index_key_levels"] = kl

        mo = _merge_market_overview(None, idx_opening)
        if mo:
            rd["market_overview"] = mo

        _record_stage_timing(
            stage_timing,
            stage=stage,
            started_at=stage_start,
            budget_s=budget,
            status="degraded" if sb.expired() else "ok",
            degraded_reason="timeout" if sb.expired() else None,
        )

        # Stage: slow_sources (concurrent, budgeted, cancel/skip)
        stage = "slow_sources"
        stage_start = time.perf_counter()
        budget = budgets.get(stage)
        sb = _StageBudget(budget)

        slow_results: Dict[str, Any] = {}
        slow_tasks: List[Tuple[str, str, Callable[..., Any], Tuple[Any, ...], Dict[str, Any]]] = [
            (
                "tool_fetch_global_index_spot",
                "fetch_global_index_spot",
                tool_fetch_index_data,
                tuple(),
                {"data_type": "global_spot", "mode": mode_inner, "index_codes": _OPENING_GLOBAL_INDEX_CODES},
            ),
            ("tool_fetch_policy_news", "fetch_policy_news", tool_fetch_policy_news, tuple(), {"max_items": 5}),
            ("tool_fetch_macro_commodities", "fetch_macro_commodities", tool_fetch_macro_commodities, tuple(), {}),
            ("tool_fetch_overnight_futures_digest", "fetch_overnight_futures_digest", tool_fetch_overnight_futures_digest, tuple(), {"disable_network": False}),
            ("tool_fetch_announcement_digest", "fetch_announcement_digest", tool_fetch_announcement_digest, tuple(), {"max_items": 5, "disable_network": False}),
            ("tool_sector_heat_score", "sector_heat_score", tool_sector_heat_score, tuple(), {"date": _previous_trading_day_yyyymmdd_for_opening_sector()}),
        ]

        skipped_tasks: List[str] = []
        if max_concurrency <= 1:
            # sequential fallback (still budget-guarded)
            for tool_key, step_name, fn, args, kwargs in slow_tasks:
                if sb.expired():
                    skipped_tasks.append(tool_key)
                    continue
                if tool_key == "tool_fetch_global_index_spot":
                    started = time.perf_counter()
                    provider = _provider_key_for_step(step_name)
                    sem = sem_pool.get(provider) or sem_pool["default"]
                    def _provider_run() -> Any:
                        sem.acquire()
                        try:
                            return fn(*args, **kwargs)
                        finally:
                            sem.release()

                    with ThreadPoolExecutor(max_workers=1) as ex:
                        fut = ex.submit(_provider_run)
                        timeout_s = min(_OPENING_GLOBAL_SPOT_TIMEOUT_S, sb.remaining_s() or _OPENING_GLOBAL_SPOT_TIMEOUT_S)
                        try:
                            res = fut.result(timeout=max(0.1, timeout_s))
                            _append_lineage(
                                lineage_struct,
                                stage=stage,
                                tool_key=tool_key,
                                started_at=started,
                                success=bool(isinstance(res, dict) and res.get("success")),
                                quality_status="ok" if isinstance(res, dict) and res.get("success") else "degraded",
                                degraded_reason=None if isinstance(res, dict) and res.get("success") else "fetch_failed_or_empty",
                                source_hint=f"provider={provider}",
                            )
                        except FuturesTimeoutError:
                            res = None
                            skipped_tasks.append(tool_key)
                            rd.setdefault("degraded", {})
                            rd["degraded"]["slow_source_timeout"] = "slow_source_timeout"
                            rd["degraded"]["slow_source_timeout_tool"] = tool_key
                            rd["degraded"]["slow_source_timeout_s"] = _OPENING_GLOBAL_SPOT_TIMEOUT_S
                            _append_lineage(
                                lineage_struct,
                                stage=stage,
                                tool_key=tool_key,
                                started_at=started,
                                success=None,
                                quality_status="degraded",
                                degraded_reason="slow_source_timeout",
                                source_hint="skipped_by_timeout",
                            )
                else:
                    res = _call_tool(stage, tool_key, step_name, fn, errors, *args, **kwargs)
                slow_results[tool_key] = res
        else:
            with ThreadPoolExecutor(max_workers=max(1, int(max_concurrency))) as ex:
                futures = {}
                for tool_key, step_name, fn, args, kwargs in slow_tasks:
                    if sb.expired():
                        skipped_tasks.append(tool_key)
                        continue
                    if tool_key == "tool_fetch_global_index_spot":
                        def _run_global_with_timeout(
                            _fn: Callable[..., Any],
                            _args: Tuple[Any, ...],
                            _kwargs: Dict[str, Any],
                            _stage: str,
                            _tool_key: str,
                            _step_name: str,
                        ) -> Any:
                            started = time.perf_counter()
                            provider = _provider_key_for_step(_step_name)
                            sem = sem_pool.get(provider) or sem_pool["default"]
                            def _provider_run() -> Any:
                                sem.acquire()
                                try:
                                    return _fn(*_args, **_kwargs)
                                finally:
                                    sem.release()

                            with ThreadPoolExecutor(max_workers=1) as local_ex:
                                local_fut = local_ex.submit(_provider_run)
                                try:
                                    out = local_fut.result(timeout=_OPENING_GLOBAL_SPOT_TIMEOUT_S)
                                    _append_lineage(
                                        lineage_struct,
                                        stage=_stage,
                                        tool_key=_tool_key,
                                        started_at=started,
                                        success=bool(isinstance(out, dict) and out.get("success")),
                                        quality_status="ok" if isinstance(out, dict) and out.get("success") else "degraded",
                                        degraded_reason=None if isinstance(out, dict) and out.get("success") else "fetch_failed_or_empty",
                                        source_hint=f"provider={provider}",
                                    )
                                    return out
                                except FuturesTimeoutError:
                                    rd.setdefault("degraded", {})
                                    rd["degraded"]["slow_source_timeout"] = "slow_source_timeout"
                                    rd["degraded"]["slow_source_timeout_tool"] = _tool_key
                                    rd["degraded"]["slow_source_timeout_s"] = _OPENING_GLOBAL_SPOT_TIMEOUT_S
                                    _append_lineage(
                                        lineage_struct,
                                        stage=_stage,
                                        tool_key=_tool_key,
                                        started_at=started,
                                        success=None,
                                        quality_status="degraded",
                                        degraded_reason="slow_source_timeout",
                                        source_hint="skipped_by_timeout",
                                    )
                                    return None

                        fut = ex.submit(_run_global_with_timeout, fn, args, kwargs, stage, tool_key, step_name)
                    else:
                        fut = ex.submit(_call_tool, stage, tool_key, step_name, fn, errors, *args, **kwargs)
                    futures[fut] = tool_key

                # Budgeted collection; on expiry, cancel not-yet-run futures and skip.
                while futures:
                    rem = sb.remaining_s()
                    if rem is not None and rem <= 0:
                        for fut, tool_key in list(futures.items()):
                            if fut.cancel():
                                skipped_tasks.append(tool_key)
                            else:
                                # already running; we mark as timed out and ignore its result
                                skipped_tasks.append(tool_key)
                        futures.clear()
                        break
                    try:
                        done_iter = as_completed(list(futures.keys()), timeout=rem if rem is not None else None)
                        for fut in done_iter:
                            tool_key = futures.pop(fut, "")
                            try:
                                slow_results[tool_key] = fut.result()
                            except Exception:
                                slow_results[tool_key] = None
                    except FuturesTimeoutError:
                        # budget hit
                        for fut, tool_key in list(futures.items()):
                            if fut.cancel():
                                skipped_tasks.append(tool_key)
                            else:
                                skipped_tasks.append(tool_key)
                        futures.clear()
                        break

        gspot = slow_results.get("tool_fetch_global_index_spot")
        if gspot is not None:
            rd["tool_fetch_global_index_spot"] = gspot
            emb = gspot.get("global_market_digest") if isinstance(gspot, dict) else None
            if isinstance(emb, dict) and str(emb.get("summary") or "").strip():
                rd["global_market_digest"] = emb
        _attach_global_spot_report_fields(rd, gspot)
        _maybe_attach_global_spot_catalog_debug(rd, gspot)

        pn = slow_results.get("tool_fetch_policy_news")
        if pn is not None:
            rd["tool_fetch_policy_news"] = pn
        _build_policy_event_signals(rd)
        macro = slow_results.get("tool_fetch_macro_commodities")
        if macro is not None:
            rd["tool_fetch_macro_commodities"] = macro
        od = slow_results.get("tool_fetch_overnight_futures_digest")
        if od is not None:
            rd["tool_fetch_overnight_futures_digest"] = od
            od_inner = od.get("data") if isinstance(od, dict) else None
            if isinstance(od_inner, dict) and (od_inner.get("a50_digest") or od_inner.get("hxc_digest")):
                rd["overnight_digest"] = od_inner
        ann = slow_results.get("tool_fetch_announcement_digest")
        if ann is not None:
            rd["tool_fetch_announcement_digest"] = ann
        sector = slow_results.get("tool_sector_heat_score")
        if sector is not None:
            sector_td = rd.get("sector_heat_ref_trade_date") or _previous_trading_day_yyyymmdd_for_opening_sector()
            rd["tool_sector_heat_score"] = sector
            rd["sector_heat_ref_trade_date"] = sector_td
            rd["sector_heat_ref_note"] = "盘前任务采用上一交易日涨停与板块样本；当日开盘初刻数据可能尚未完整。"

        # global hist fill (budgeted best-effort; keep sequential inside helper)
        if not sb.expired():
            _maybe_fill_opening_global_from_hist(rd, errors)
        else:
            if skipped_tasks is not None:
                skipped_tasks.append("tool_fetch_global_index_hist_sina(fill)")

        mo2 = _merge_market_overview(rd.get("tool_fetch_global_index_spot"), rd.get("tool_fetch_index_opening"))
        if mo2:
            rd["market_overview"] = mo2
        if not sb.expired():
            _maybe_attach_global_market_tavily_digest(rd, rd.get("tool_fetch_global_index_spot"))

        if skipped_tasks:
            rd.setdefault("degraded", {})
            rd["degraded"]["slow_sources_skipped"] = skipped_tasks

        _record_stage_timing(
            stage_timing,
            stage=stage,
            started_at=stage_start,
            budget_s=budget,
            status="degraded" if sb.expired() else "ok",
            degraded_reason="timeout" if sb.expired() else None,
        )

        # Stage: analytics (sequential, budgeted)
        stage = "analytics"
        stage_start = time.perf_counter()
        budget = budgets.get(stage)
        sb = _StageBudget(budget)

        vol = intr = dvol = prev = sig = None
        # Prefer core market analysis in analytics stage (separate budget) to avoid
        # being skipped when critical stage is consumed by slow network sources.
        if not sb.expired():
            opening_analysis = _call_tool(
                stage,
                "tool_analyze_market",
                "analyze_opening_market",
                tool_analyze_market,
                errors,
                moment="opening",
            )
            if opening_analysis is not None:
                rd["tool_analyze_market"] = opening_analysis
                rd["analyze_opening_market"] = opening_analysis
                if isinstance(opening_analysis, dict) and opening_analysis.get("success"):
                    data = opening_analysis.get("data")
                    if isinstance(data, dict) and data:
                        rd["analysis"] = data
        _mark_analysis_health(rd, analysis_tool_key="tool_analyze_market")

        _ind_rt = resolve_indicator_runtime("opening_analysis")
        if not sb.expired():
            tech = _call_tool(
                stage,
                "tool_calculate_technical_indicators",
                "technical_indicators",
                calculate_indicators_via_tool,
                errors,
                symbol="510300",
                data_type="etf_daily",
                indicators=["ma", "macd", "rsi", "bollinger", "atr"],
            )
            if tech is not None:
                rd["tool_calculate_technical_indicators"] = tech
                rd["indicator_runtime"] = {
                    "task": "opening_analysis",
                    "route": _ind_rt.route,
                    "notes": _ind_rt.notes,
                }

        # Trend resolution depends on market_overview + (optional) local analysis;
        # run after analysis tool has had a chance to populate rd["analysis"].
        _apply_opening_trend_resolution(rd)

        if not sb.expired():
            vol = _call_tool(
                stage,
                "tool_predict_volatility",
                "predict_volatility",
                tool_volatility,
                errors,
                mode="predict",
                underlying="510300",
            )
        if vol is not None:
            rd["tool_predict_volatility"] = vol
            if isinstance(vol, dict):
                data_obj = vol.get("data")
                use_struct = False
                if isinstance(data_obj, dict) and data_obj.get("success") is not False:
                    if any(data_obj.get(k) is not None for k in ("upper", "lower", "current_price", "range_pct")):
                        use_struct = True
                if use_struct:
                    rd["volatility"] = data_obj
                else:
                    fo = vol.get("formatted_output")
                    if isinstance(fo, str) and fo.strip():
                        rd["volatility_prediction"] = fo.strip()
                    elif vol.get("success") and isinstance(vol.get("message"), str):
                        rd["volatility_prediction"] = str(vol.get("message"))

        if not sb.expired():
            intr = _call_tool(
                stage,
                "tool_predict_intraday_range",
                "predict_intraday_range",
                tool_predict_intraday_range,
                errors,
                symbol="510300",
            )
        if intr is not None:
            rd["tool_predict_intraday_range"] = intr
            if isinstance(intr, dict) and intr.get("success"):
                inner = intr.get("data")
                if isinstance(inner, dict):
                    rd["intraday_range"] = inner

        if not sb.expired():
            dvol = _call_tool(
                stage,
                "tool_predict_daily_volatility_range",
                "predict_daily_volatility_range",
                tool_predict_daily_volatility_range,
                errors,
                underlying="510300",
            )
        if dvol is not None:
            rd["tool_predict_daily_volatility_range"] = dvol
            if isinstance(dvol, dict) and dvol.get("success") is not False:
                rd["daily_volatility_range"] = dvol

        if not sb.expired():
            prev = _call_tool(
                stage,
                "tool_get_yesterday_prediction_review",
                "prediction_review",
                tool_get_yesterday_prediction_review,
                errors,
            )
        if prev is not None:
            rd["tool_get_yesterday_prediction_review"] = prev
            if isinstance(prev, dict) and prev.get("success"):
                pdata = prev.get("data")
                if pdata is not None:
                    rd["prediction_review"] = pdata

        if not sb.expired():
            sig_mode = "production" if mode_inner == "production" else "test"
            sig = _call_tool(
                stage,
                "tool_generate_option_trading_signals",
                "generate_option_trading_signals",
                tool_generate_option_trading_signals,
                errors,
                underlying="510300",
                mode=sig_mode,
            )
        if sig is not None:
            rd["tool_generate_option_trading_signals"] = sig

        # snapshots and runtime context (do not budget-gate; cheap)
        idx_rows = _rows_from_tool_data(rd.get("tool_fetch_index_realtime"))
        etf_rows = _rows_from_tool_data(rd.get("tool_fetch_etf_realtime"))
        tracked_etf = []
        for r in etf_rows[:12]:
            code = str(r.get("code") or r.get("symbol") or "").strip()
            if not code:
                continue
            pct = _extract_pct(r)
            tracked_etf.append(
                {
                    "code": code,
                    "name": r.get("name") or code,
                    "price": _to_float(r.get("price") or r.get("current_price")),
                    "change_pct": pct,
                    "strength": _asset_strength_from_pct(pct),
                }
            )

        opening_idx = _rows_from_tool_data(rd.get("tool_fetch_index_opening"))
        rd["opening_market_snapshot"] = {
            "snapshot_time": rd.get("generated_at"),
            "indices_opening": opening_idx[:12],
            "indices_realtime": idx_rows[:12],
            "etf_realtime": etf_rows[:12],
        }
        flags = _cross_check_index_etf_consistency(
            idx_rows=idx_rows,
            etf_rows=etf_rows,
            snapshot_time=str(rd.get("generated_at") or ""),
        )
        rd["data_quality_flags"] = flags
        rd["data_quality_status"] = "degraded" if flags else "ok"
        ah = rd.get("analysis_health") if isinstance(rd.get("analysis_health"), dict) else {}
        if flags:
            # 仅写入质量提示，不覆盖分析主状态/主 reason（避免“慢源/一致性提示”误判为分析失败）。
            ah["data_quality_flags"] = flags
            rd["analysis_health"] = ah
            rd.setdefault("degraded", {})
            rd["degraded"]["core_snapshot_incomplete"] = [str(x.get("code") or "") for x in flags]
        rd["tracked_assets_snapshot"] = {"etf": tracked_etf, "stocks": []}
        strong_cnt = len([x for x in tracked_etf if x.get("strength") == "强"])
        weak_cnt = len([x for x in tracked_etf if x.get("strength") == "弱"])
        heat_rows = []
        sector_obj = rd.get("tool_sector_heat_score")
        if isinstance(sector_obj, dict):
            heat_rows = [x for x in (sector_obj.get("sectors") or []) if isinstance(x, dict)]
        rd["opening_flow_signals"] = {
            "market_breadth": {
                "tracked_etf_strong_count": strong_cnt,
                "tracked_etf_weak_count": weak_cnt,
                "tracked_etf_total": len(tracked_etf),
            },
            "sector_heat_top": heat_rows[:5],
            "flow_bias": "偏强" if strong_cnt > weak_cnt else ("偏弱" if weak_cnt > strong_cnt else "中性"),
            "note": "基于ETF强弱与板块热度的开盘资金状态近似，不含北向资金口径。",
        }
        intraday_allowed = True
        tsd = (rd.get("trading_status") or {}).get("data") if isinstance(rd.get("trading_status"), dict) else None
        if isinstance(tsd, dict) and tsd.get("allows_intraday_continuous_wording") is False:
            intraday_allowed = False
        _attach_rotation_opening_block(
            rd,
            errors,
            fetch_etf_fn=tool_fetch_etf_data,
            fetch_mode=mode_inner,
            allow_realtime_validation=bool(intraday_allowed),
        )
        rd["runtime_context"] = {
            "is_opening_window": bool(intraday_allowed),
            "snapshot_time": rd.get("generated_at"),
            "fallback_mode": "replay" if not intraday_allowed else "realtime",
        }
        _compute_holiday_position_hint(rd)

        if errors:
            rd["runner_errors"] = errors

        try:
            from plugins.notification.send_daily_report import attach_opening_overnight_category_tavily

            attach_opening_overnight_category_tavily(rd)
        except Exception as e:
            logger.warning("opening_runner attach_opening_overnight_category_tavily: %s", e)

        _record_stage_timing(
            stage_timing,
            stage=stage,
            started_at=stage_start,
            budget_s=budget,
            status="degraded" if sb.expired() else "ok",
            degraded_reason="timeout" if sb.expired() else None,
        )

        if emit_stage_timing:
            rd["stage_timing"] = stage_timing
            rd["lineage_struct"] = lineage_struct
        return rd, errors

    # dispatch build path
    if profile in ("cron_balanced", "balanced", "fast"):
        report_data, _errors = _build_opening_report_data_optimized(fetch_mode=fetch_mode)
    else:
        report_data, _errors = build_opening_report_data(fetch_mode=fetch_mode)
        if emit_stage_timing:
            # legacy path: still emit empty containers for schema stability
            report_data.setdefault("stage_timing", {})
            report_data.setdefault("lineage_struct", [])

    rv = str(report_variant or "").strip().lower()
    report_data["opening_report_variant"] = "realtime" if rv == "realtime" else "legacy"
    ah = report_data.get("analysis_health") if isinstance(report_data.get("analysis_health"), dict) else {}
    analysis_degraded = bool(ah.get("status") == "degraded")
    policy_quality = report_data.get("policy_event_quality") if isinstance(report_data.get("policy_event_quality"), dict) else {}
    policy_is_error = str(policy_quality.get("quality_status") or "").strip().lower() == "error"
    policy_is_degraded = str(policy_quality.get("quality_status") or "").strip().lower() == "degraded"
    runner_errs = report_data.get("runner_errors") if isinstance(report_data.get("runner_errors"), list) else []
    has_stage_degraded = any(
        isinstance(v, dict) and v.get("status") == "degraded"
        for v in (report_data.get("stage_timing") or {}).values()
    )
    report_data["run_quality"] = (
        "error"
        if (runner_errs or policy_is_error)
        else ("ok_degraded" if (analysis_degraded or has_stage_degraded or policy_is_degraded) else "ok_full")
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
        out_delivery = out.get("delivery") if isinstance(out.get("delivery"), dict) else {}
        delivery_ok = bool(out_delivery.get("ok"))
        delivery_status = str(out_delivery.get("status") or "").strip() or (
            "ok" if delivery_ok else "failed"
        )
        if not delivery_ok:
            report_data["run_quality"] = "error"
        data = dict(out.get("data") or {})
        data["runner_errors"] = report_data.get("runner_errors") or []
        data["report_type"] = "opening"
        data["run_quality"] = report_data.get("run_quality") or "ok_full"
        data["analysis_health"] = report_data.get("analysis_health") or {"status": "unknown", "reason": ""}
        data["overnight_bias_vote"] = report_data.get("overnight_bias_vote") or []
        data["overnight_bias_score"] = report_data.get("overnight_bias_score")
        data["overnight_bias_label"] = report_data.get("overnight_bias_label")
        data["trend_resolution"] = report_data.get("trend_resolution") or {}
        data["policy_event_quality"] = report_data.get("policy_event_quality") or {}
        data["holiday_position_hint"] = report_data.get("holiday_position_hint") or {}
        data["data_quality_flags"] = report_data.get("data_quality_flags") or []
        data["slow_sources_skipped"] = (report_data.get("degraded") or {}).get("slow_sources_skipped") or []
        data["global_spot_source_used"] = report_data.get("global_spot_source_used")
        data["global_spot_attempts"] = report_data.get("global_spot_attempts")
        data["global_spot_failure_code"] = (report_data.get("global_spot_failure_codes") or [None])[0]
        st = report_data.get("stage_timing") if isinstance(report_data.get("stage_timing"), dict) else {}
        critical = st.get("critical") if isinstance(st.get("critical"), dict) else {}
        data["critical_elapsed_ms"] = critical.get("elapsed_ms")
        lineage_rows = report_data.get("lineage_struct") if isinstance(report_data.get("lineage_struct"), list) else []
        g_rows = [
            x for x in lineage_rows
            if isinstance(x, dict) and str(x.get("tool_key") or "") == "tool_fetch_global_index_spot"
        ]
        data["global_spot_elapsed_ms"] = (g_rows[-1].get("elapsed_ms") if g_rows else None)
        # explicit delivery semantics for cron ACK verification
        data["delivery"] = {
            "attempted": bool((mode or "").strip().lower() == "prod"),
            "mode": "prod_send" if (mode or "").strip().lower() == "prod" else "skip_test",
            "ok": delivery_ok,
            "status": delivery_status,
            "channel": out_delivery.get("channel"),
            "attempts": out_delivery.get("attempts"),
        }
        if emit_stage_timing:
            data["stage_timing"] = report_data.get("stage_timing") or {}
            data["lineage_struct"] = report_data.get("lineage_struct") or []
        out["data"] = data
    return out
