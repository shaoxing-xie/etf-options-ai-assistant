"""
进程内串接：9:20 开盘行情分析（预开盘执行版，对齐 workflows/opening_analysis.yaml）。

供 Cron 单次 tool_call，避免 Gateway 多轮合并 report_data 与 idle 超时。

若钉钉正文出现缺段、N/A 或 degraded：先对照本模块合并逻辑与 send_daily_report 的字段路径逐项排查，
勿默认归因数据采集或网络；运维说明见 docs/ops/cron_opening_analysis_triage.md。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import pytz
except ImportError:  # pragma: no cover
    pytz = None  # type: ignore

logger = logging.getLogger(__name__)

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
    rd["runtime_context"] = {
        "is_opening_window": bool(intraday_allowed),
        "snapshot_time": rd.get("generated_at"),
        "fallback_mode": "replay" if not intraday_allowed else "realtime",
    }

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
        webhook_url/secret/keyword: 可选，透传发送层
        split_markdown_sections: 默认 True，与每日市场分析报告一致按章节分条；单条推送时显式 False。
        max_chars_per_message: 可选；省略则读 config notification.dingtalk_max_chars_per_message。
    """
    from plugins.notification.send_analysis_report import tool_send_analysis_report

    report_data, _errors = build_opening_report_data(fetch_mode=fetch_mode)
    rv = str(report_variant or "").strip().lower()
    report_data["opening_report_variant"] = "realtime" if rv == "realtime" else "legacy"
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
        data["runner_errors"] = report_data.get("runner_errors") or []
        data["report_type"] = "opening"
        out["data"] = data
    return out
