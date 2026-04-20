"""
进程内串接：9:20 盘前机构晨报（对齐 workflows/before_open_analysis.yaml）。

供 Cron 单次 tool_call，避免 Gateway 多轮合并 report_data 与 idle 超时。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from datetime import datetime

from plugins.notification.run_opening_analysis import (
    _OPENING_GLOBAL_HIST_CODES,
    _OPENING_GLOBAL_INDEX_CODES,
    _maybe_attach_global_market_tavily_digest,
    _merge_market_overview,
    _now_sh,
    _safe_step,
)

logger = logging.getLogger(__name__)

def _extract_change_pct(row: Dict[str, Any]) -> Optional[float]:
    v = row.get("change_pct")
    if v is None:
        v = row.get("change_percent")
    try:
        return None if v is None else float(v)
    except Exception:
        return None


def _hist_resp_to_index_row(code: str, resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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


def _maybe_fill_before_open_from_hist(rd: Dict[str, Any], errors: List[Dict[str, str]]) -> None:
    """
    盘前 9:20：若 spot 对欧股代表等缺 change_pct/缺行，且需要“昨收/上周五收市”口径，
    则用 tool_fetch_global_index_hist_sina 补齐上一完整交易日收盘涨跌幅。
    """
    try:
        from plugins.data_collection.index.fetch_global_hist_sina import tool_fetch_global_index_hist_sina
    except Exception as e:
        logger.warning("before_open_runner: import global_hist_sina failed: %s", e)
        return

    mo = rd.get("market_overview")
    if not isinstance(mo, dict):
        mo = {}
    indices = mo.get("indices")
    idx_list: List[Dict[str, Any]] = [x for x in indices if isinstance(x, dict)] if isinstance(indices, list) else []
    by_code = {str(x.get("code") or x.get("name") or ""): x for x in idx_list if (x.get("code") or x.get("name"))}

    filled_rows: List[Dict[str, Any]] = []
    for code in _OPENING_GLOBAL_HIST_CODES:
        cur = by_code.get(code)
        if isinstance(cur, dict) and _extract_change_pct(cur) is not None:
            continue
        resp = _safe_step(
            f"fetch_global_index_hist_sina:{code}",
            tool_fetch_global_index_hist_sina,
            errors,
            symbol=code,
            limit=2,
        )
        if not isinstance(resp, dict) or not resp.get("success"):
            continue
        row = _hist_resp_to_index_row(code, resp)
        if not row:
            continue
        if isinstance(cur, dict) and cur.get("name"):
            row["name"] = cur.get("name")
        filled_rows.append(row)
        by_code[code] = row

    if filled_rows:
        rd["tool_fetch_global_index_hist_sina"] = {
            "success": True,
            "count": len(filled_rows),
            "data": filled_rows,
            "source": "akshare.index_global_hist_sina",
        }
        mo["indices"] = list(by_code.values())
        rd["market_overview"] = mo


def build_before_open_report_data(fetch_mode: str = "production") -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """
    按 before_open_analysis.yaml 顺序采集并组装 report_data（含 report_type=before_open）。
    返回 (report_data, runner_errors)。
    """
    errors: List[Dict[str, str]] = []
    mode = fetch_mode if fetch_mode in ("production", "test") else "production"

    from plugins.analysis.accuracy_tracker import tool_get_yesterday_prediction_review
    from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range
    from plugins.analysis.intraday_range import tool_predict_intraday_range
    from plugins.analysis.key_levels import tool_compute_index_key_levels
    from plugins.analysis.trend_analysis import tool_analyze_before_open
    from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score
    # NOTE: `plugins.data_collection` is a symlink to the OpenClaw runtime plugin directory (read-only).
    # We use an assistant-side policy news fetcher to ensure TAVILY_API_KEYS multi-key rotation (incl. HTTP 432).
    from plugins.data_access.policy_news import tool_fetch_policy_news
    from plugins.data_collection.morning_brief_fetchers import (
        tool_fetch_announcement_digest,
        tool_fetch_macro_commodities,
        tool_fetch_overnight_futures_digest,
    )
    from plugins.data_collection.utils.check_trading_status import tool_check_trading_status
    from plugins.merged.fetch_index_data import tool_fetch_index_data
    from plugins.merged.volatility import tool_volatility

    rd: Dict[str, Any] = {
        "report_type": "before_open",
        "runner_version": "before_open_analysis_composite_v1",
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

    _maybe_attach_global_market_tavily_digest(rd, gspot)
    _maybe_fill_before_open_from_hist(rd, errors)

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

    sector = _safe_step("sector_heat_score", tool_sector_heat_score, errors)
    if sector is not None:
        rd["tool_sector_heat_score"] = sector

    kl = _safe_step(
        "compute_index_key_levels",
        tool_compute_index_key_levels,
        errors,
        index_code="000300",
    )
    if kl is not None:
        rd["tool_compute_index_key_levels"] = kl

    before_open_analysis = _safe_step(
        "analyze_before_open",
        tool_analyze_before_open,
        errors,
    )
    if before_open_analysis is not None:
        rd["tool_analyze_before_open"] = before_open_analysis
        if isinstance(before_open_analysis, dict) and before_open_analysis.get("success"):
            data = before_open_analysis.get("data")
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

    if errors:
        rd["runner_errors"] = errors

    return rd, errors


def tool_run_before_open_analysis_and_send(
    mode: str = "prod",
    fetch_mode: str = "production",
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    split_markdown_sections: bool = True,
    max_chars_per_message: Optional[int] = None,
) -> Dict[str, Any]:
    """
    进程内执行盘前机构晨报全链路并发送钉钉（report_type=before_open）。

    Args:
        mode: prod|test（钉钉；test 不发网络请求）
        fetch_mode: production|test（透传指数等采集）
        webhook_url/secret/keyword: 可选，透传发送层
        split_markdown_sections: 默认 True，与每日市场分析报告一致按章节分条。
        max_chars_per_message: 可选；省略则读 config notification.dingtalk_max_chars_per_message。
    """
    from plugins.notification.send_analysis_report import tool_send_analysis_report

    report_data, _errors = build_before_open_report_data(fetch_mode=fetch_mode)
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
        data["report_type"] = "before_open"
        out["data"] = data
    return out
