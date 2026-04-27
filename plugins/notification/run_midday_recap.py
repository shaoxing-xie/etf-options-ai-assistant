"""
进程内串接：午间行情盘点与下午操作指引（report_type=midday_recap）。

注意：Cron 任务推荐单次调用 `tool_run_midday_recap_and_send`，避免多轮工具调用与 idle 超时。
本 runner 以“可用即发”为原则：尽量采集关键字段，缺失则在 report_data 中标注。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
import json
from pathlib import Path
import time

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None  # type: ignore


def _now_sh() -> datetime:
    if pytz is None:
        return datetime.now()
    return datetime.now(pytz.timezone("Asia/Shanghai"))


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _fmt_pct(v: Any) -> str:
    x = _safe_float(v)
    if x is None:
        return "N/A"
    return f"{x:+.2f}%"


def _fmt_num(v: Any, nd: int = 3) -> str:
    x = _safe_float(v)
    if x is None:
        return "N/A"
    return f"{x:.{nd}f}"


def _fmt_amount_yi(amount: Any) -> str:
    x = _safe_float(amount)
    if x is None:
        return "N/A"
    # 常见：amount 可能是 元 / 万元 / 亿元（不可靠），这里只做保守展示
    if x > 1e8:
        return f"{x/1e8:.2f} 亿元"
    if x > 1e4:
        return f"{x/1e4:.2f} 万元"
    return f"{x:.0f}"


def _fmt_yi(v: Any) -> str:
    x = _safe_float(v)
    if x is None:
        return "N/A"
    # 智能口径：
    # - 若绝对值很大（>=1e6），通常是“元” -> 转亿元
    # - 否则通常已是“亿”口径 -> 直接展示
    if abs(x) >= 1e6:
        return f"{x/1e8:+.2f} 亿"
    return f"{x:+.2f} 亿"


_FUND_FLOW_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "midday_fund_flow_latest.json"


def _load_fund_flow_cache() -> Optional[Dict[str, Any]]:
    try:
        if not _FUND_FLOW_CACHE_PATH.exists():
            return None
        with _FUND_FLOW_CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_fund_flow_cache(payload: Dict[str, Any]) -> None:
    try:
        _FUND_FLOW_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _FUND_FLOW_CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        # 缓存失败不应影响主流程
        pass


def _try_fetch_fund_flow(now: datetime) -> Dict[str, Any]:
    """
    可选资金流向：依赖 openclaw-data-china-stock（已被 OpenClaw 加载到 plugins.* 时可 import）。
    返回结构稳定：{ok, market? , note?}
    """
    out: Dict[str, Any] = {"ok": False}
    # 1) 同花顺优先：直接调用 AkShare stock_board_industry_summary_ths（包含净流入）
    try:
        import pandas as pd  # type: ignore
        import akshare as ak  # type: ignore

        raw = ak.stock_board_industry_summary_ths()
        if raw is not None and not getattr(raw, "empty", True) and "板块" in raw.columns and "涨跌幅" in raw.columns:
            # 兼容：净流入列名可能不存在/不同
            net_col = None
            for c in raw.columns:
                if "净流入" in str(c):
                    net_col = c
                    break
            df = pd.DataFrame(
                {
                    "sector_name": raw["板块"].astype(str).str.strip(),
                    "change_percent": pd.to_numeric(raw["涨跌幅"], errors="coerce"),
                    "net_inflow": pd.to_numeric(raw[net_col], errors="coerce").fillna(0.0) if net_col else None,
                }
            )
            df = df[(df["sector_name"].str.len() > 0) & (df["change_percent"].notna())]
            out["industry_ths"] = {
                "status": "success",
                "date": now.strftime("%Y-%m-%d"),
                "source": "akshare.stock_board_industry_summary_ths",
                "data": df.to_dict("records"),
            }
            out["ok"] = True
        else:
            out["industry_ths_error"] = "THS行业一览返回空/缺字段"
    except Exception as e:
        out["industry_ths_error"] = str(e)

    # 2) 兜底：东财直连大盘资金流（日K）
    try:
        from plugins.data_collection.utils.eastmoney_fund_flow_direct import (  # type: ignore
            stock_market_fund_flow_direct,
            em_http_available,
        )

        if callable(em_http_available) and not em_http_available():
            out["market_error"] = "eastmoney_fund_flow_direct 不可用（request_with_retry 缺失）"
        else:
            df = stock_market_fund_flow_direct()
            if getattr(df, "empty", True):
                out["market_error"] = "大盘资金流返回空"
            else:
                last = df.tail(1).iloc[0].to_dict()
                out["market"] = last
                out["ok"] = True
    except Exception as e:
        out["market_error"] = str(e)

    # 3) 写缓存/读缓存：避免上游偶发抖动导致整段退化
    if out.get("ok"):
        cache_payload = {
            "cached_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "industry_ths": out.get("industry_ths"),
            "market": out.get("market"),
        }
        _save_fund_flow_cache(cache_payload)
        return out

    cached = _load_fund_flow_cache()
    if isinstance(cached, dict):
        ind = cached.get("industry_ths")
        mkt = cached.get("market")
        if isinstance(ind, dict):
            out["industry_ths"] = dict(ind)
            out["industry_ths"]["source"] = f"{ind.get('source') or 'unknown'} (cache)"
            out["ok"] = True
        if isinstance(mkt, dict):
            out["market"] = mkt
            out["ok"] = True
        if out.get("ok"):
            out["cache_used"] = True
            out["cache_time"] = cached.get("cached_at")
    return out


def _index_hist_last_kline(hist_resp: Any) -> Optional[Dict[str, Any]]:
    """取指数日线 historical 返回中最后一根 K 线（dict）。"""
    if not isinstance(hist_resp, dict) or not hist_resp.get("success"):
        return None
    d = hist_resp.get("data")
    if not isinstance(d, dict):
        return None
    klines = d.get("klines")
    if not isinstance(klines, list) or not klines:
        return None
    last = klines[-1]
    return last if isinstance(last, dict) else None


def _etf_hist_last_kline(hist_resp: Any) -> Optional[Dict[str, Any]]:
    """取 ETF 日线 historical 返回中最后一根 K 线（dict）。"""
    return _index_hist_last_kline(hist_resp)


def _hist_start_yyyymmdd(end_yyyymmdd: str, calendar_lookback: int = 45) -> str:
    try:
        end = datetime.strptime(end_yyyymmdd, "%Y%m%d")
    except Exception:
        end = _now_sh()
        return (end - timedelta(days=calendar_lookback)).strftime("%Y%m%d")
    return (end - timedelta(days=calendar_lookback)).strftime("%Y%m%d")


def _synthetic_index_realtime_row(code: str, hist_resp: Dict[str, Any]) -> Dict[str, Any]:
    """把最近一根日线包装成与指数 realtime 接近的 dict，供 _extract_index_rows / 展示用。"""
    last = _index_hist_last_kline(hist_resp)
    dmeta = hist_resp.get("data") if isinstance(hist_resp.get("data"), dict) else {}
    name = str(dmeta.get("index_name") or "").strip() or code
    if not last:
        return {"code": code, "name": name, "change_percent": None, "current_price": None}
    close = last.get("close")
    pct = last.get("change_percent")
    trade_d = str(last.get("date") or "").strip()
    return {
        "code": code,
        "name": name,
        "current_price": close,
        "close": close,
        "change_percent": pct,
        "timestamp": trade_d,
        "data_basis": "historical_daily_last",
    }


def _synthetic_etf_realtime_from_hist(hist_resp: Dict[str, Any], etf_code: str = "510300") -> Dict[str, Any]:
    last = _etf_hist_last_kline(hist_resp)
    if not last:
        return {"success": False, "message": "historical ETF empty", "data": None}
    dmeta = hist_resp.get("data") if isinstance(hist_resp.get("data"), dict) else {}
    row = {
        "code": etf_code,
        "name": str(dmeta.get("name") or etf_code),
        "current_price": last.get("close"),
        "price": last.get("close"),
        "close": last.get("close"),
        "amount": last.get("amount"),
        "change_percent": last.get("change_percent"),
        "timestamp": str(last.get("date") or "").strip(),
        "data_basis": "historical_daily_last",
    }
    return {
        "success": True,
        "message": "synthetic from historical last bar (non-trading day)",
        "data": row,
        "source": "historical_last_trading_day",
    }


def _extract_index_rows(idx_resp: Any) -> List[Dict[str, Any]]:
    if not isinstance(idx_resp, dict):
        return []
    data = idx_resp.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        # 单条 dict（例如新浪 spot 返回）
        if any(k in data for k in ("code", "index_code", "symbol", "change_percent", "change_pct")):
            return [data]
        rec = data.get("records")
        if isinstance(rec, list):
            return [x for x in rec if isinstance(x, dict)]
    return []


def _pick_change(row: Dict[str, Any]) -> Any:
    for k in ("change_pct", "change_percent", "pct_chg", "pct_change", "涨跌幅"):
        if k in row:
            return row.get(k)
    return None


def _extract_etf_row(resp: Any) -> Dict[str, Any]:
    if not isinstance(resp, dict):
        return {}
    data = resp.get("data")
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict):
        return data
    return {}


def _extract_sector_top(heat_resp: Any, limit: int = 8) -> List[str]:
    if not isinstance(heat_resp, dict):
        return []
    rows: List[Dict[str, Any]] = []
    # 常见：tool_sector_heat_score 直接返回顶层 sectors
    if isinstance(heat_resp.get("sectors"), list):
        rows = [x for x in (heat_resp.get("sectors") or []) if isinstance(x, dict)]
    else:
        data = heat_resp.get("data")
        if isinstance(data, list):
            rows = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            for k in ("sectors", "records", "data"):
                v = data.get(k)
                if isinstance(v, list):
                    rows = [x for x in v if isinstance(x, dict)]
                    break
    if not rows:
        return []
    out: List[str] = []
    for r in rows[:limit]:
        name = str(r.get("name") or r.get("sector") or r.get("板块") or "").strip()
        score = r.get("score") or r.get("heat") or r.get("热度") or r.get("value")
        if name:
            out.append(f"- {name}（热度 { _fmt_num(score, 2) }）")
    return out


def _extract_risk_summary(risk_resp: Any) -> Dict[str, Any]:
    if not isinstance(risk_resp, dict):
        return {}
    data = risk_resp.get("data")
    if not isinstance(data, dict):
        return {}
    return {
        "risk_level": data.get("risk_level") or data.get("level") or data.get("position_risk_flag") or "N/A",
        "var_pct": data.get("var_historical_pct") or data.get("var") or data.get("VaR"),
        "max_dd_pct": data.get("max_drawdown_pct") or data.get("max_drawdown") or data.get("max_dd"),
        "cur_dd_pct": data.get("current_drawdown_pct") or data.get("current_drawdown") or data.get("current_dd"),
        "pos_pct": data.get("current_position_pct"),
        "cash_pct": data.get("cash_pct"),
    }


def _risk_level_label(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if not s or s == "n/a":
        return "N/A"
    mapping = {
        "ok": "低风险",
        "low": "低风险",
        "safe": "低风险",
        "neutral": "中性",
        "medium": "中风险",
        "warn": "中风险",
        "warning": "中风险",
        "high": "高风险",
        "alert": "高风险",
        "extreme": "极高风险",
    }
    return mapping.get(s, str(raw))


def _derive_afternoon_bias(flat: Dict[str, Any]) -> Tuple[str, str]:
    """
    用最小可得数据做一个可解释的“下午倾向”。
    """
    hs300 = _safe_float(flat.get("hs300_change"))
    gem = _safe_float(flat.get("gem_change"))
    zz500 = _safe_float(flat.get("zz500_change"))
    vals = [x for x in (hs300, gem, zz500) if x is not None]
    if not vals:
        return "N/A", "指数半日涨跌数据缺失"
    avg = sum(vals) / len(vals)
    if avg >= 0.6:
        return "偏强", "主要指数整体偏强（均值较高），但需防冲高回落"
    if avg <= -0.6:
        return "偏弱", "主要指数整体偏弱（均值较低），优先风控"
    return "震荡", "主要指数涨跌幅处于中性区间，更偏结构性机会"


def _mark_midday_analysis_health(rd: Dict[str, Any]) -> None:
    """
    午间链路健康检查：确保关键指数快照缺失时显式标记 degraded，
    避免正文静默 N/A 且难以排障。
    """
    rows = _extract_index_rows(rd.get("tool_fetch_index_realtime"))
    by_code: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        code = str(r.get("code") or r.get("index_code") or r.get("symbol") or "").strip()
        if code:
            by_code[code] = r

    missing: List[str] = []
    for code in ("000300", "399006", "000905"):
        row = by_code.get(code)
        if not isinstance(row, dict):
            missing.append(f"{code}:row_missing")
            continue
        if _pick_change(row) is None:
            missing.append(f"{code}:change_missing")

    if missing:
        reason = "midday_index_snapshot_incomplete:" + ",".join(missing)
        rd["analysis_health"] = {"status": "degraded", "reason": reason}
        rd.setdefault("degraded", {})
        rd["degraded"]["analysis_health"] = reason
    else:
        rd["analysis_health"] = {"status": "ok", "reason": ""}


def _build_paths(bias: str, risk_level: str) -> Dict[str, Any]:
    # 简化但可执行的三路径（不输出唯一结论）
    risk = (risk_level or "").strip().lower()
    if bias == "偏强":
        cons = {"action": "持有", "cap": "20%"}
        neu = {"action": "持有/回撤加仓", "cap": "40%"}
        aggr = {"action": "轻仓买入", "cap": "60%"}
    elif bias == "偏弱":
        cons = {"action": "观望/减仓", "cap": "20%"}
        neu = {"action": "持有+防守", "cap": "35%"}
        aggr = {"action": "仅做试错", "cap": "50%"}
    else:
        cons = {"action": "持有", "cap": "20%"}
        neu = {"action": "区间内高抛低吸", "cap": "40%"}
        aggr = {"action": "小仓位轮动", "cap": "55%"}

    if risk in ("high", "高", "extreme"):
        # 风险高时统一收敛
        cons = {"action": "减仓/观望", "cap": "15%"}
        neu = {"action": "减仓/观望", "cap": "25%"}
        aggr = {"action": "减仓/观望", "cap": "35%"}

    return {
        "conservative": cons,
        "neutral": neu,
        "aggressive": aggr,
        "default_path": "中性",
    }


def _safe_step(name: str, fn: Any, errors: List[Dict[str, str]], /, **kwargs: Any) -> Any:
    try:
        return fn(**kwargs)
    except Exception as e:
        errors.append({"step": name, "error": f"{e}"})
        return {"success": False, "message": f"{name} failed: {e}"}


_WORKFLOW_PROFILES = {"legacy", "cron_balanced"}
_STAGE_BUDGET_PRESETS: Dict[str, Dict[str, int]] = {
    "balanced": {"critical": 45, "slow_sources": 60, "compose_send": 30},
    "tight": {"critical": 35, "slow_sources": 45, "compose_send": 25},
}


def _resolve_stage_budgets(profile: str) -> Optional[Dict[str, int]]:
    if profile == "off":
        return None
    return dict(_STAGE_BUDGET_PRESETS.get(profile, _STAGE_BUDGET_PRESETS["balanced"]))


def _mark_stage(
    stage_timing: Dict[str, Any],
    stage_name: str,
    start_ts: float,
    budget_s: Optional[int],
    degraded_reason: Optional[str] = None,
) -> Dict[str, Any]:
    elapsed_ms = int(round((time.perf_counter() - start_ts) * 1000))
    status = "degraded" if degraded_reason else "ok"
    stage_timing[stage_name] = {
        "elapsed_ms": elapsed_ms,
        "budget_s": budget_s,
        "status": status,
        "degraded_reason": degraded_reason,
    }
    return stage_timing[stage_name]


def _lineage_entry(
    stage: str,
    tool_key: str,
    payload: Any,
    *,
    source_hint: str = "",
    degraded_reason: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
) -> Dict[str, Any]:
    success = bool(isinstance(payload, dict) and payload.get("success", True))
    quality = "ok"
    if degraded_reason:
        quality = "degraded"
    elif not success:
        quality = "error"
    return {
        "stage": stage,
        "tool_key": tool_key,
        "success": success,
        "quality_status": quality,
        "degraded_reason": degraded_reason,
        "elapsed_ms": elapsed_ms,
        "source_hint": source_hint or "internal",
    }


def build_midday_recap_report_data(
    fetch_mode: str = "production",
    workflow_profile: str = "legacy",
    stage_budget_profile: str = "balanced",
    emit_stage_timing: bool = True,
    max_concurrency: int = 3,
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """
    采集并组装 report_data（含 report_type=midday_recap）。
    返回 (report_data, runner_errors)。
    """
    errors: List[Dict[str, str]] = []
    mode = fetch_mode if fetch_mode in ("production", "test") else "production"
    wf_profile = workflow_profile if workflow_profile in _WORKFLOW_PROFILES else "legacy"
    budget_profile = stage_budget_profile if stage_budget_profile in ("balanced", "tight", "off") else "balanced"
    budgets = _resolve_stage_budgets(budget_profile) if wf_profile == "cron_balanced" else None
    use_observability = bool(emit_stage_timing) or wf_profile == "cron_balanced"
    concurrency = max(1, min(int(max_concurrency or 1), 6))
    now = _now_sh()

    from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score
    from plugins.merged.fetch_etf_data import tool_fetch_etf_data
    from plugins.merged.fetch_index_data import tool_fetch_index_data
    from plugins.risk.portfolio_risk_snapshot import tool_portfolio_risk_snapshot

    rd: Dict[str, Any] = {
        "report_type": "midday_recap",
        "runner_version": "midday_recap_composite_v2",
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    stage_timing: Dict[str, Any] = {}
    lineage_struct: List[Dict[str, Any]] = []
    skipped_tasks: List[str] = []

    # 非交易日：production 下 realtime 会被交易日门禁拦截；对齐到最近 A 股交易日的日线最后一根
    ref_yyyymmdd: Optional[str] = None
    use_hist_last_td = False
    try:
        from src.system_status import get_last_trading_day_on_or_before, is_trading_day

        if not is_trading_day(now, None):
            ref_yyyymmdd = get_last_trading_day_on_or_before(now, None)
            use_hist_last_td = bool(ref_yyyymmdd)
    except Exception:
        ref_yyyymmdd = None
        use_hist_last_td = False

    idx: Any = None
    idx_399006: Any = None
    idx_000905: Any = None
    etf510: Any = None
    risk: Any = {}
    heat: Any = {}
    fund_flow: Any = {}
    skip_slow_sources = False

    critical_start = time.perf_counter()
    if use_hist_last_td and ref_yyyymmdd:
        start_d = _hist_start_yyyymmdd(ref_yyyymmdd)
        critical_calls: Dict[str, Tuple[Callable[..., Any], Dict[str, Any], str]] = {
            "idx_000300": (
                tool_fetch_index_data,
                {
                    "data_type": "historical",
                    "index_code": "000300",
                    "start_date": start_d,
                    "end_date": ref_yyyymmdd,
                },
                "fetch_index_historical_000300_last_td",
            ),
            "idx_399006": (
                tool_fetch_index_data,
                {
                    "data_type": "historical",
                    "index_code": "399006",
                    "start_date": start_d,
                    "end_date": ref_yyyymmdd,
                },
                "fetch_index_historical_399006_last_td",
            ),
            "idx_000905": (
                tool_fetch_index_data,
                {
                    "data_type": "historical",
                    "index_code": "000905",
                    "start_date": start_d,
                    "end_date": ref_yyyymmdd,
                },
                "fetch_index_historical_000905_last_td",
            ),
            "etf_510300": (
                tool_fetch_etf_data,
                {
                    "data_type": "historical",
                    "etf_code": "510300",
                    "start_date": start_d,
                    "end_date": ref_yyyymmdd,
                },
                "fetch_etf_historical_510300_last_td",
            ),
            "risk": (tool_portfolio_risk_snapshot, {}, "portfolio_risk_snapshot"),
        }
        with ThreadPoolExecutor(max_workers=min(5, concurrency + 1)) as pool:
            future_map = {
                pool.submit(_safe_step, step_name, fn, errors, **kwargs): key
                for key, (fn, kwargs, step_name) in critical_calls.items()
            }
            for fut in as_completed(future_map):
                key = future_map[fut]
                payload = fut.result()
                if key == "idx_000300":
                    idx = payload
                elif key == "idx_399006":
                    idx_399006 = payload
                elif key == "idx_000905":
                    idx_000905 = payload
                elif key == "etf_510300":
                    etf510 = payload
                elif key == "risk":
                    risk = payload
                lineage_struct.append(_lineage_entry("critical", key, payload, source_hint="fetch"))
        r300 = _synthetic_index_realtime_row("000300", idx if isinstance(idx, dict) else {})
        r006 = _synthetic_index_realtime_row("399006", idx_399006 if isinstance(idx_399006, dict) else {})
        r905 = _synthetic_index_realtime_row("000905", idx_000905 if isinstance(idx_000905, dict) else {})
        rd["tool_fetch_index_realtime"] = {
            "success": True,
            "data": [r300, r006, r905],
            "source": "historical_last_trading_day",
            "data_reference_yyyymmdd": ref_yyyymmdd,
        }
        rd["tool_fetch_etf_realtime_510300"] = (
            _synthetic_etf_realtime_from_hist(etf510, "510300")
            if isinstance(etf510, dict)
            else {"success": False, "data": None}
        )
    else:
        critical_calls = {
            "idx_000300": (
                tool_fetch_index_data,
                {"data_type": "realtime", "mode": mode, "index_code": "000300"},
                "fetch_index_realtime",
            ),
            "idx_399006": (
                tool_fetch_index_data,
                {"data_type": "realtime", "mode": mode, "index_code": "399006"},
                "fetch_index_realtime_399006",
            ),
            "idx_000905": (
                tool_fetch_index_data,
                {"data_type": "realtime", "mode": mode, "index_code": "000905"},
                "fetch_index_realtime_000905",
            ),
            "etf_510300": (
                tool_fetch_etf_data,
                {"data_type": "realtime", "etf_code": "510300", "mode": mode},
                "fetch_etf_realtime_510300",
            ),
            "risk": (tool_portfolio_risk_snapshot, {}, "portfolio_risk_snapshot"),
        }
        with ThreadPoolExecutor(max_workers=min(5, concurrency + 1)) as pool:
            future_map = {
                pool.submit(_safe_step, step_name, fn, errors, **kwargs): key
                for key, (fn, kwargs, step_name) in critical_calls.items()
            }
            for fut in as_completed(future_map):
                key = future_map[fut]
                payload = fut.result()
                if key == "idx_000300":
                    idx = payload
                elif key == "idx_399006":
                    idx_399006 = payload
                elif key == "idx_000905":
                    idx_000905 = payload
                elif key == "etf_510300":
                    etf510 = payload
                elif key == "risk":
                    risk = payload
                lineage_struct.append(_lineage_entry("critical", key, payload, source_hint="fetch"))

        rd["tool_fetch_index_realtime"] = {
            "success": True,
            "data": [
                idx.get("data") if isinstance(idx, dict) else idx,
                idx_399006.get("data") if isinstance(idx_399006, dict) else idx_399006,
                idx_000905.get("data") if isinstance(idx_000905, dict) else idx_000905,
            ],
        }
        rd["tool_fetch_etf_realtime_510300"] = etf510

    critical_budget = (budgets or {}).get("critical")
    critical_degraded = None
    if critical_budget is not None and (time.perf_counter() - critical_start) > critical_budget:
        critical_degraded = "timeout"
        skip_slow_sources = True
    _mark_stage(stage_timing, "critical", critical_start, critical_budget, critical_degraded)

    slow_start = time.perf_counter()
    if skip_slow_sources:
        skipped_tasks.extend(["sector_heat_score", "fund_flow_optional"])
        heat = {"success": False, "message": "skipped due to critical timeout", "quality_status": "degraded"}
        fund_flow = {"ok": False, "message": "skipped due to critical timeout", "quality_status": "degraded"}
        lineage_struct.append(
            _lineage_entry(
                "slow_sources",
                "sector_heat_score",
                heat,
                source_hint="skipped",
                degraded_reason="critical_timeout",
            )
        )
        lineage_struct.append(
            _lineage_entry(
                "slow_sources",
                "fund_flow_optional",
                fund_flow,
                source_hint="skipped",
                degraded_reason="critical_timeout",
            )
        )
    else:
        slow_calls = {
            "sector_heat_score": (tool_sector_heat_score, {}, "sector_heat_score"),
            "fund_flow_optional": (_try_fetch_fund_flow, {"now": now}, "fund_flow_optional"),
        }
        with ThreadPoolExecutor(max_workers=min(2, concurrency)) as pool:
            future_map = {
                pool.submit(_safe_step, step_name, fn, errors, **kwargs): key
                for key, (fn, kwargs, step_name) in slow_calls.items()
            }
            for fut in as_completed(future_map):
                key = future_map[fut]
                payload = fut.result()
                if key == "sector_heat_score":
                    heat = payload
                else:
                    fund_flow = payload
                lineage_struct.append(_lineage_entry("slow_sources", key, payload, source_hint="fetch"))
    rd["tool_sector_heat_score"] = heat
    rd["tool_portfolio_risk_snapshot"] = risk
    rd["tool_fund_flow_optional"] = fund_flow

    slow_budget = (budgets or {}).get("slow_sources")
    slow_degraded = None
    if slow_budget is not None and (time.perf_counter() - slow_start) > slow_budget:
        slow_degraded = "timeout"
    _mark_stage(stage_timing, "slow_sources", slow_start, slow_budget, slow_degraded)

    analytics_start = time.perf_counter()

    ref_dash: Optional[str] = None
    if ref_yyyymmdd and len(str(ref_yyyymmdd)) == 8 and str(ref_yyyymmdd).isdigit():
        ys = str(ref_yyyymmdd)
        ref_dash = f"{ys[:4]}-{ys[4:6]}-{ys[6:8]}"

    # 将 formatter 需要的字段塞进 midday_recap
    mr: Dict[str, Any] = {
        "date": (ref_dash if use_hist_last_td and ref_dash else now.strftime("%Y-%m-%d")),
        "non_trading": bool(use_hist_last_td),
        "market_state_label": ("非交易日（日线对齐最近交易日）" if use_hist_last_td else "N/A"),
        "session_note": (
            f"指数与 510300 取截至 {ref_dash} 收市的日线：涨跌幅为全日相对前一交易日收盘；非交易日无实时半日涨跌。"
            if (use_hist_last_td and ref_dash)
            else ""
        ),
        "fund_flow_data_note": "",
        "fund_flow_summary_lines": [],
        "sector_rank_lines": [],
        "sector_heat_tool": heat,
        "opening_expectation": {"available": False},
        "afternoon_bias": "N/A",
        "afternoon_bias_rationale": "N/A",
        "afternoon_advice": {
            "session_basis": "本报告仅提供多视角参考；缺字段时按 N/A 展示。",
            "trend": {"action": "N/A", "reason": ""},
            "timing": {"action": "N/A", "reason": ""},
            "risk": {"action": "N/A", "reason": ""},
            "paths": {
                "conservative": {"action": "hold", "cap": "N/A"},
                "neutral": {"action": "hold", "cap": "N/A"},
                "aggressive": {"action": "hold", "cap": "N/A"},
                "default_path": "中性",
            },
        },
        "cross_border_lines": [],
        "time_reminders": ["13:00 关注回补缺口/承接强度变化", "14:30 关注券商/权重异动与指数脉冲"],
        "user_decision_note": "本系统仅提供多视角信息，不替代你的最终交易决策。",
    }

    # 半日成交额代理（尽可能从 ETF realtime 中取）
    amt = None
    if isinstance(etf510, dict) and isinstance(etf510.get("data"), dict):
        d = etf510["data"]
        for k in ("amount", "turnover", "成交额", "成交额(元)", "成交额(万元)"):
            if k in d:
                amt = d.get(k)
                break
    mr["morning_amount_510300"] = amt

    # 简单扁平化：若 index realtime 返回可解析涨跌，写入 inspection_flat
    flat: Dict[str, Any] = {}
    idx_rows = _extract_index_rows(rd.get("tool_fetch_index_realtime"))
    if idx_rows:
        by = {}
        for r in idx_rows:
            code = str(r.get("code") or r.get("index_code") or r.get("symbol") or "").strip()
            if code:
                by[code] = r
        flat["hs300_change"] = _pick_change(by.get("000300", {}))
        flat["gem_change"] = _pick_change(by.get("399006", {}))
        flat["zz500_change"] = _pick_change(by.get("000905", {}))
    # 风控摘要（尽量短）
    if isinstance(risk, dict) and isinstance(risk.get("data"), dict):
        rdata = risk["data"]
        flat["risk_level"] = rdata.get("risk_level") or rdata.get("level")
        flat["var_snapshot"] = rdata.get("var") or rdata.get("VaR")
        flat["max_dd_snapshot"] = rdata.get("max_drawdown") or rdata.get("max_dd")
        flat["current_dd_snapshot"] = rdata.get("current_drawdown") or rdata.get("current_dd")
        flat["position_risk_snapshot"] = rdata.get("position_note") or rdata.get("position")
    mr["inspection_flat"] = flat

    # 资金流向摘要 lines（若可用）
    ff_lines: List[str] = []
    if isinstance(fund_flow, dict):
        ind = fund_flow.get("industry_ths")
        if isinstance(ind, dict) and ind.get("status") == "success":
            rows = ind.get("data")
            if isinstance(rows, list):
                # 取净流入 Top（若无净流入则跳过）
                rich = [r for r in rows if isinstance(r, dict) and _safe_float(r.get("net_inflow")) is not None]
                rich.sort(key=lambda r: float(_safe_float(r.get("net_inflow")) or 0.0), reverse=True)
                top = rich[:5]
                if top:
                    src = str(ind.get("source") or "同花顺")
                    ff_lines.append(f"- 行业资金净流入 Top（数据源：{src}）")
                    for r in top:
                        name = str(r.get("sector_name") or r.get("name") or "").strip()
                        net = r.get("net_inflow")
                        if name:
                            ff_lines.append(f"  - {name}：{_fmt_yi(net)}")
        m = fund_flow.get("market")
        if isinstance(m, dict):
            ff_lines.append("- 大盘资金流（数据源：东财直连回退）")
            ff_lines.append(
                f"- 大盘主力净流入：{_fmt_yi(m.get('主力净流入-净额'))}｜超大单：{_fmt_yi(m.get('超大单净流入-净额'))}｜大单：{_fmt_yi(m.get('大单净流入-净额'))}"
            )
        if fund_flow.get("cache_used"):
            ff_lines.append(f"- 说明：当前使用最近成功缓存（时间：{fund_flow.get('cache_time') or 'N/A'}）")
    mr["fund_flow_summary_lines"] = ff_lines
    if not ff_lines:
        mr["fund_flow_data_note"] = "资金流向工具不可用或返回空（需要 openclaw-data-china-stock 扩展及可用数据源）。"

    analytics_budget = (budgets or {}).get("compose_send")
    analytics_degraded = None
    if analytics_budget is not None and (time.perf_counter() - analytics_start) > analytics_budget:
        analytics_degraded = "timeout"
    _mark_stage(stage_timing, "compose_send", analytics_start, analytics_budget, analytics_degraded)

    rd["midday_recap"] = mr
    if errors:
        rd["runner_errors"] = errors
    _mark_midday_analysis_health(rd)
    degraded = any((v or {}).get("status") == "degraded" for v in stage_timing.values()) or bool(skipped_tasks)
    if isinstance(rd.get("analysis_health"), dict) and rd["analysis_health"].get("status") == "degraded":
        degraded = True
    rd["run_quality"] = "error" if errors else ("ok_degraded" if degraded else "ok_full")
    if skipped_tasks:
        rd["skipped_tasks"] = skipped_tasks
    if use_observability:
        rd["stage_timing"] = stage_timing
        rd["lineage_struct"] = lineage_struct
    rd["_meta"] = {
        "schema_name": "midday_recap_report",
        "schema_version": "2.0.0",
        "task_id": "etf-midday-recap-1200",
        "data_layer": "L3",
        "generated_at": rd.get("generated_at"),
        "trade_date": mr.get("date"),
        "source_tools": [x.get("tool_key") for x in lineage_struct if isinstance(x, dict)],
        "lineage_refs": [{"stage": x.get("stage"), "tool_key": x.get("tool_key")} for x in lineage_struct if isinstance(x, dict)],
        "quality_status": "error" if errors else ("degraded" if degraded else "ok"),
    }
    return rd, errors


def tool_run_midday_recap_and_send(
    mode: str = "prod",
    fetch_mode: str = "production",
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
    """
    进程内执行午间盘点采集并发送钉钉（report_type=midday_recap）。
    """
    report_data, _errors = build_midday_recap_report_data(
        fetch_mode=fetch_mode,
        workflow_profile=workflow_profile,
        stage_budget_profile=stage_budget_profile,
        emit_stage_timing=emit_stage_timing,
        max_concurrency=max_concurrency,
    )
    mr = report_data.get("midday_recap") if isinstance(report_data.get("midday_recap"), dict) else {}
    title = f"午间行情盘点与下午操作指引 - {mr.get('date') or datetime.now().strftime('%Y-%m-%d')}"

    flat = mr.get("inspection_flat") if isinstance(mr.get("inspection_flat"), dict) else {}
    idx_rows = _extract_index_rows(report_data.get("tool_fetch_index_realtime"))
    by_code = {}
    for r in idx_rows:
        code = str(r.get("code") or r.get("index_code") or r.get("symbol") or "").strip()
        if code:
            by_code[code] = r

    etf_row = _extract_etf_row(report_data.get("tool_fetch_etf_realtime_510300"))
    etf_price = etf_row.get("current_price") or etf_row.get("price") or etf_row.get("close")
    etf_amount = etf_row.get("amount") or etf_row.get("turnover")
    risk_summary = _extract_risk_summary(report_data.get("tool_portfolio_risk_snapshot"))
    risk_level_raw = str(risk_summary.get("risk_level") or flat.get("risk_level") or "N/A")
    risk_level = _risk_level_label(risk_level_raw)
    var_s = risk_summary.get("var_pct") or flat.get("var_snapshot")
    max_dd = risk_summary.get("max_dd_pct")
    cur_dd = risk_summary.get("cur_dd_pct")
    pos_pct = risk_summary.get("pos_pct")
    cash_pct = risk_summary.get("cash_pct")

    bias, bias_reason = _derive_afternoon_bias(flat)
    paths = _build_paths(bias, risk_level_raw)
    sector_lines = _extract_sector_top(report_data.get("tool_sector_heat_score"))

    hs300 = _fmt_pct(_pick_change(by_code.get("000300", {})) or flat.get("hs300_change"))
    gem = _fmt_pct(_pick_change(by_code.get("399006", {})) or flat.get("gem_change"))
    zz500 = _fmt_pct(_pick_change(by_code.get("000905", {})) or flat.get("zz500_change"))

    lines: List[str] = [
        title,
        "",
        "## 📊 午间盘点（完整版）",
        f"- **生成时间**：{report_data.get('generated_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "### 一、核心指数与宽基ETF",
        f"- 沪深300：{hs300}｜创业板指：{gem}｜中证500：{zz500}",
        f"- 510300 现价：{_fmt_num(etf_price, 3)}｜成交额：{_fmt_amount_yi(etf_amount)}",
    ]
    sn = (mr.get("session_note") or "").strip()
    if sn:
        lines.append(f"- **数据口径**：{sn}")
    lines.extend(
        [
            "",
            "### 二、风险与约束（摘要）",
            f"- 风险等级：{risk_level}",
            f"- VaR（历史{_fmt_num(0.95,2)}置信）：{_fmt_num(var_s, 4) if var_s is not None else 'N/A'}%",
            f"- 最大回撤：{_fmt_num(max_dd, 2) if max_dd is not None else 'N/A'}%｜当前回撤：{_fmt_num(cur_dd, 2) if cur_dd is not None else 'N/A'}%",
            f"- 仓位/现金：{_fmt_num(pos_pct, 1) if pos_pct is not None else 'N/A'}% / {_fmt_num(cash_pct, 1) if cash_pct is not None else 'N/A'}%",
            "",
            "### 三、板块热度（涨停侧 Top）",
        ],
    )
    if sector_lines:
        lines.extend(sector_lines)
    else:
        lines.append("- N/A（上游未返回可解析的板块列表）")
    lines.extend(
        [
            "",
            "### 四、资金流向（说明）",
        *(
            (mr.get("fund_flow_summary_lines") or [])
            if isinstance(mr.get("fund_flow_summary_lines"), list) and (mr.get("fund_flow_summary_lines") or [])
            else [f"- {mr.get('fund_flow_data_note') or 'N/A'}"]
        ),
            "",
            "### 五、下午操作指引（不合成单一结论）",
            f"- **下午倾向：** {bias}（{bias_reason}）",
            "",
            "#### 用户可选三路径",
            f"- **保守：** {paths['conservative']['action']}（仓位上限 {paths['conservative']['cap']}）",
            f"- **中性：** {paths['neutral']['action']}（仓位上限 {paths['neutral']['cap']}）",
            f"- **积极：** {paths['aggressive']['action']}（仓位上限 {paths['aggressive']['cap']}）",
            "",
            "### 六、时间提醒",
        ]
    )
    for t in mr.get("time_reminders") or []:
        if isinstance(t, str) and t.strip():
            lines.append(f"- {t.strip()}")
    lines.extend(
        [
            "",
            "### 七、用户决策声明",
            f"- {mr.get('user_decision_note') or '本系统仅提供多视角信息，不替代你的最终交易决策。'}",
        ]
    )
    errs = report_data.get("runner_errors")
    if isinstance(errs, list) and errs:
        lines.append("")
        lines.append("### ⚠️ 采集告警（摘要）")
        for e in errs[:6]:
            if isinstance(e, dict):
                lines.append(f"- {e.get('step')}: {e.get('error')}")
    message = "\n".join(lines).strip()

    from .send_dingtalk_message import tool_send_dingtalk_message

    out = tool_send_dingtalk_message(
        message=message,
        title=title,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
        mode=mode,
        split_markdown_sections=bool(split_markdown_sections),
        max_chars_per_message=max_chars_per_message,
    )
    if isinstance(out, dict):
        data = dict(out.get("data") or {})
        data["runner_errors"] = report_data.get("runner_errors") or []
        data["report_type"] = "midday_recap"
        data["run_quality"] = report_data.get("run_quality") or "ok_full"
        data["analysis_health"] = report_data.get("analysis_health") or {"status": "unknown", "reason": ""}
        data["stage_timing"] = report_data.get("stage_timing") or {}
        data["lineage_struct"] = report_data.get("lineage_struct") or []
        data["skipped_tasks"] = report_data.get("skipped_tasks") or []
        data["_meta"] = report_data.get("_meta") or {}
        out["data"] = data
    return out

