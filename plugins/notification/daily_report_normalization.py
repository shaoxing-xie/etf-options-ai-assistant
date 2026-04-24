"""
日报字段归一化、补采合并与单元测试辅助（与 workflows/daily_market_report.yaml 对齐）。

从 send_daily_report 延迟导入格式化函数，避免模块加载期循环依赖。
"""

from __future__ import annotations

import copy
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_DAILY_GLOBAL_INDEX_CODES = (
    "^N225,^HSI,^KS11,^GDAXI,^STOXX50E,^FTSE,^GSPC,^IXIC,^DJI"
)
_MARKET_FLOW_QUERY_KINDS = frozenset({"market_history", "market_proxy_ths", "market_flow_preferred"})


def _outer_extract_change_pct(row: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(row, dict):
        return None
    v = row.get("change_pct")
    if v is None:
        v = row.get("change_percent")
    try:
        return None if v is None else float(v)
    except Exception:
        return None


def _outer_hist_resp_to_index_row(code: str, resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """与盘前/开盘任务一致：index_global_hist_sina 日线最后两根推算涨跌幅。"""
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


def _merge_daily_market_global_outer_fallback(rd: Dict[str, Any]) -> None:
    """
    现货主源之后：对缺行或缺涨跌的外盘代码用「最近完整交易日」日线补齐（对齐盘前/开盘 hist 口径）。

    - 美股三大：fetch_global._fetch_akshare_us_index_sina_rows（AkShare 新浪美股指数日 K）
    - 欧/日/韩等：tool_fetch_global_index_hist_sina / index_global_hist_sina
    - 恒生：在 ^HSI 仍缺时尝试 symbol=恒生指数（name_table 名称）
    """
    if os.environ.get("DAILY_REPORT_DISABLE_GLOBAL_OUTER_FALLBACK"):
        return
    if (rd.get("report_type") or "").strip() != "daily_market":
        return

    spot = rd.get("tool_fetch_global_index_spot") or rd.get("global_index_spot")
    rows: List[Dict[str, Any]] = []
    if isinstance(spot, dict) and isinstance(spot.get("data"), list):
        rows = [dict(r) for r in spot["data"] if isinstance(r, dict)]

    by_code: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        c = r.get("code")
        if isinstance(c, str) and c:
            by_code[c] = r

    filled: List[str] = []

    # 1) 美股：日报默认用 AkShare 新浪美股指数日 K（最近两交易日收盘推算）覆盖 yfinance，
    #    避免 yfinance 5d 最后一根与「最近完整美股交易日」不一致；可用环境变量关闭覆盖仅补缺。
    try:
        from plugins.data_collection.index.fetch_global import (  # noqa: WPS433
            SYMBOL_NAME_MAP,
            _fetch_akshare_us_index_sina_rows,
        )
    except Exception:
        SYMBOL_NAME_MAP = {}
        _fetch_akshare_us_index_sina_rows = None  # type: ignore

    us_syms = ("^DJI", "^GSPC", "^IXIC")
    if _fetch_akshare_us_index_sina_rows:
        if os.environ.get("DAILY_REPORT_DISABLE_US_AK_DAILY_OVERWRITE"):
            us_need = [s for s in us_syms if s not in by_code or _outer_extract_change_pct(by_code.get(s)) is None]
            to_fetch = us_need
        else:
            to_fetch = list(us_syms)
        for ar in _fetch_akshare_us_index_sina_rows(to_fetch):
            if not isinstance(ar, dict):
                continue
            c = ar.get("code")
            if not isinstance(c, str):
                continue
            nr = dict(ar)
            prev = by_code.get(c)
            if isinstance(prev, dict) and prev.get("name"):
                nr["name"] = prev.get("name")
            elif not nr.get("name"):
                nr["name"] = SYMBOL_NAME_MAP.get(c, c)
            by_code[c] = nr
            filled.append(f"us_daily:{c}")

    # 2) 环球 hist（欧股代表 + 日韩）
    try:
        from plugins.data_collection.index.fetch_global_hist_sina import tool_fetch_global_index_hist_sina
    except Exception:
        tool_fetch_global_index_hist_sina = None  # type: ignore

    hist_syms = ("^GDAXI", "^STOXX50E", "^FTSE", "^N225", "^KS11")
    for code in hist_syms:
        if code in by_code and _outer_extract_change_pct(by_code.get(code)) is not None:
            continue
        if not tool_fetch_global_index_hist_sina:
            break
        try:
            resp = tool_fetch_global_index_hist_sina(symbol=code, limit=2)
        except Exception:
            continue
        if not isinstance(resp, dict) or not resp.get("success"):
            continue
        row = _outer_hist_resp_to_index_row(code, resp)
        if not row:
            continue
        cur = by_code.get(code)
        if isinstance(cur, dict) and cur.get("name"):
            row["name"] = cur.get("name")
        else:
            row["name"] = SYMBOL_NAME_MAP.get(code, row.get("name"))
        by_code[code] = row
        filled.append(f"hist_sina:{code}")

    # 3) 恒生：现货缺或无数值时尝试环球历史（名称入口）
    if (("^HSI" not in by_code) or _outer_extract_change_pct(by_code.get("^HSI")) is None) and tool_fetch_global_index_hist_sina:
        for sym_try in ("^HSI", "恒生指数"):
            try:
                resp = tool_fetch_global_index_hist_sina(symbol=sym_try, limit=2)
            except Exception:
                resp = None
            if not isinstance(resp, dict) or not resp.get("success"):
                continue
            row = _outer_hist_resp_to_index_row("^HSI", resp)
            if not row:
                continue
            row["code"] = "^HSI"
            row["name"] = "恒生指数"
            prev = by_code.get("^HSI")
            if isinstance(prev, dict) and prev.get("name"):
                row["name"] = prev.get("name")
            by_code["^HSI"] = row
            filled.append("hist_sina:^HSI")
            break

    if not filled:
        return

    merged_list = list(by_code.values())
    prev_src = str((spot or {}).get("source") or "").strip()
    out: Dict[str, Any] = {
        "success": bool(merged_list),
        "count": len(merged_list),
        "data": merged_list,
        "source": (prev_src + "+daily_outer_fallback") if prev_src else "daily_outer_fallback",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if isinstance(spot, dict) and spot.get("message"):
        out["message"] = spot.get("message")
    rd["global_index_spot"] = out
    rd["tool_fetch_global_index_spot"] = out
    rd["daily_market_global_outer_fallback"] = {"filled": filled}


def _normalize_global_index_display_names(rd: Dict[str, Any]) -> None:
    """将 global_index_spot 与 market_overview.indices 的 code 映射为中文名（含欧股 ^GDAXI 等）。"""
    if (rd.get("report_type") or "").strip() != "daily_market":
        return
    try:
        from plugins.data_collection.index.fetch_global import SYMBOL_NAME_MAP
    except Exception:
        return
    for key in ("tool_fetch_global_index_spot", "global_index_spot"):
        spot = rd.get(key)
        if not isinstance(spot, dict) or not isinstance(spot.get("data"), list):
            continue
        for r in spot["data"]:
            if not isinstance(r, dict):
                continue
            c = r.get("code")
            if isinstance(c, str) and c in SYMBOL_NAME_MAP:
                r["name"] = SYMBOL_NAME_MAP[c]
    mo = rd.get("market_overview")
    if isinstance(mo, dict) and isinstance(mo.get("indices"), list):
        for it in mo["indices"]:
            if not isinstance(it, dict):
                continue
            c = it.get("code")
            if isinstance(c, str) and c in SYMBOL_NAME_MAP:
                it["name"] = SYMBOL_NAME_MAP[c]


def _flatten_md_headers_in_embedded_report_text(s: str) -> str:
    """将嵌入文本中的 Markdown 标题行压成「· 标题」前缀，避免钉钉里 ## 噪声。"""

    def repl(m: re.Match[str]) -> str:
        return "· " + m.group(1).strip()

    return re.sub(r"^#{1,6}\s+(.+)$", repl, s or "", flags=re.MULTILINE)


def _looks_like_completed_tool_json(tool_name: str, val: Any) -> bool:
    """区分「完整工具 JSON」与 Agent 误传的参数字典（仅 index_codes/max_items 等）。"""
    if tool_name == "report_meta":
        return True
    if not isinstance(val, dict):
        return False
    if val.get("success") is not None:
        return True
    if any(k in val for k in ("data", "items", "sectors", "records", "formatted_output", "message")):
        return True
    stub_only = {
        "index_codes",
        "max_items",
        "underlying",
        "lookback_days",
        "symbol",
        "mode",
        "etf_code",
        "params",
        "disable_network",
        "query_kind",
        "params_echo",
    }
    if tool_name.startswith("tool_") and set(val.keys()) <= stub_only:
        return False
    return True


def _merge_extra_report_data_skipping_tool_arg_stubs(
    rd: Dict[str, Any],
    extra: Optional[Dict[str, Any]],
) -> List[str]:
    """浅合并 extra 到 rd；若某 tool_* 在 rd 中已是完整 JSON 而 extra 为参数字典，则跳过并记录。"""
    skipped: List[str] = []
    if not extra:
        return skipped
    for k, v in extra.items():
        if k.startswith("tool_") and k in rd:
            existing = rd.get(k)
            if (
                isinstance(existing, dict)
                and _looks_like_completed_tool_json(k, existing)
                and isinstance(v, dict)
                and not _looks_like_completed_tool_json(k, v)
            ):
                skipped.append(k)
                continue
        rd[k] = v
    return skipped


def _maybe_autofill_cron_daily_market_p0(rd: Dict[str, Any]) -> None:
    """Cron 日报 P0：补拉全球指数现货，并对缺行/缺涨跌用历史日线（注册工具）兜底。"""
    if os.environ.get("DAILY_REPORT_DISABLE_CRON_P0_AUTOFILL"):
        return
    if (rd.get("report_type") or "").strip() != "daily_market":
        return
    try:
        from plugins.data_collection.index.fetch_global import fetch_global_index_spot
    except Exception:
        return
    rich: Optional[Dict[str, Any]] = None
    try:
        rich = fetch_global_index_spot(_DAILY_GLOBAL_INDEX_CODES)
    except Exception:
        rich = None
    if isinstance(rich, dict):
        rd["global_index_spot"] = rich
        rd["tool_fetch_global_index_spot"] = rich
        if rich.get("success") and isinstance(rich.get("data"), list) and rich.get("data"):
            rd["cron_p0_autofill_global_index"] = True
    _merge_daily_market_global_outer_fallback(rd)
    _normalize_global_index_display_names(rd)


def _capital_flow_blocks_from(rd: Dict[str, Any]) -> Dict[str, Any]:
    """合并顶层与 analysis 内的 A 股资金流向块。"""
    out: Dict[str, Any] = {}
    for key in (
        "a_share_capital_flow_market_history",
        "a_share_capital_flow_sector_industry",
        "a_share_capital_flow_sector_concept",
    ):
        v = rd.get(key)
        if isinstance(v, dict):
            out[key] = v
    an = rd.get("analysis")
    if isinstance(an, dict):
        for key in (
            "a_share_capital_flow_market_history",
            "a_share_capital_flow_sector_industry",
            "a_share_capital_flow_sector_concept",
        ):
            v = an.get(key)
            if isinstance(v, dict) and key not in out:
                out[key] = v
    return out


def _capital_flow_topic_substantive(rd: Dict[str, Any]) -> bool:
    blocks = _capital_flow_blocks_from(rd)
    # 优先同花顺行业/概念板块资金流：这两块任一有有效 records 即视为专题可用。
    for key in ("a_share_capital_flow_sector_industry", "a_share_capital_flow_sector_concept"):
        blk = blocks.get(key)
        if not isinstance(blk, dict) or blk.get("success") is False:
            continue
        rec = blk.get("records")
        if isinstance(rec, list) and rec:
            return True
    # 兜底：若板块资金均不可用，再接受全市场历史口径。
    blk = blocks.get("a_share_capital_flow_market_history")
    if (
        isinstance(blk, dict)
        and blk.get("success") is not False
        and str(blk.get("query_kind") or "market_history") in _MARKET_FLOW_QUERY_KINDS
    ):
        rec = blk.get("records")
        if isinstance(rec, list) and rec:
            return True
    # 开盘实盘风格兜底：若有板块热度或ETF强弱快照，也视为资金状态专题可用。
    sh = rd.get("tool_sector_heat_score")
    if isinstance(sh, dict) and sh.get("success") and isinstance(sh.get("sectors"), list) and sh.get("sectors"):
        return True
    etf_rt = rd.get("tool_fetch_etf_realtime")
    if isinstance(etf_rt, dict) and etf_rt.get("success") and isinstance(etf_rt.get("data"), list):
        rows = [x for x in (etf_rt.get("data") or []) if isinstance(x, dict)]
        if rows:
            return True
    # 日报：正文「资金流向专题」若已渲染行业/概念/大盘补充/或替代口径占位，审计应与正文一致，不标缺失。
    if (rd.get("report_type") or "").strip() == "daily_market":
        try:
            topic_lines = _build_daily_capital_flow_topic_lines(rd)
        except Exception:
            topic_lines = []
        if topic_lines and any(
            marker in ln
            for ln in topic_lines
            for marker in (
                "### 一、行业板块",
                "### 二、概念板块",
                "### 全市场大盘（补充）",
                "资金与成交状态（替代口径）",
            )
        ):
            return True
    return False


def _fmt_flow_yi(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    ax = abs(x)
    if ax >= 1e6:
        yi = x / 1e8
        s2 = f"{yi:+.2f}" if yi != 0 else f"{yi:.2f}"
        return s2 + "亿"
    s = f"{x:+.2f}" if x != 0 else f"{x:.2f}"
    return s + "亿"


def _capital_flow_exec_summary_fragment(rd: Dict[str, Any]) -> Optional[str]:
    blocks = _capital_flow_blocks_from(rd)
    mh = blocks.get("a_share_capital_flow_market_history")
    if isinstance(mh, dict) and mh.get("success"):
        recs = mh.get("records")
        if isinstance(recs, list) and recs:
            last = recs[-1]
            if isinstance(last, dict):
                net = last.get("主力净流入-净额")
                if net is not None:
                    return f"全市场大盘：主力净流入约 {_fmt_flow_yi(net)}（{last.get('日期', '')}）"
    for pref, label in (
        ("a_share_capital_flow_sector_concept", "概念"),
        ("a_share_capital_flow_sector_industry", "行业"),
    ):
        blk = blocks.get(pref)
        if not isinstance(blk, dict) or not blk.get("success"):
            continue
        recs = blk.get("records")
        if not isinstance(recs, list) or not recs:
            continue
        top = recs[0]
        if isinstance(top, dict):
            nm = str(top.get("名称") or "").strip()
            if nm:
                return f"{label}资金：{nm} 等"
    return None


def _build_a_share_market_flow_lines(report_data: Dict[str, Any]) -> List[str]:
    blk = report_data.get("a_share_capital_flow_market_history")
    if not isinstance(blk, dict) or not blk.get("success"):
        blk = report_data.get("tool_fetch_a_share_fund_flow")
    if not isinstance(blk, dict) or blk.get("success") is False:
        return []
    if str(blk.get("query_kind") or "market_history") not in _MARKET_FLOW_QUERY_KINDS:
        return []
    recs = blk.get("records")
    if not isinstance(recs, list) or not recs:
        return []
    last = recs[-1]
    if not isinstance(last, dict):
        return []
    net = last.get("主力净流入-净额")
    dt = last.get("日期", "")
    src = str(blk.get("source") or "")
    if net is None:
        return []
    return [f"{dt} 主力净流入 {_fmt_flow_yi(net)}（来源 {src}）"]


def _daily_capital_flow_topic_has_registered_flow_tools(rd: Dict[str, Any]) -> bool:
    """
    是否具备 openclaw-data-china-stock 等注册工具返回的 A 股资金流（行业/概念/大盘历史），
    而非仅靠 ETF 涨跌 + 板块热度替代。
    """
    blocks = _capital_flow_blocks_from(rd)
    for key in ("a_share_capital_flow_sector_industry", "a_share_capital_flow_sector_concept"):
        blk = blocks.get(key)
        if not isinstance(blk, dict) or blk.get("success") is False:
            continue
        if isinstance(blk.get("records"), list) and blk.get("records"):
            return True
    mh = blocks.get("a_share_capital_flow_market_history")
    if isinstance(mh, dict) and mh.get("success") is not False:
        if str(mh.get("query_kind") or "market_history") in _MARKET_FLOW_QUERY_KINDS:
            if isinstance(mh.get("records"), list) and mh.get("records"):
                return True
    tff = rd.get("tool_fetch_a_share_fund_flow")
    if isinstance(tff, dict) and tff.get("success") is not False:
        if str(tff.get("query_kind") or "market_history") in _MARKET_FLOW_QUERY_KINDS:
            if isinstance(tff.get("records"), list) and tff.get("records"):
                return True
    return False


def _build_daily_capital_flow_topic_lines(report_data: Dict[str, Any]) -> List[str]:
    blocks = _capital_flow_blocks_from(report_data)
    lines: List[str] = []
    def _to_float(v: Any) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", "")
        if not s:
            return None
        mul = 1.0
        if s.endswith("亿"):
            mul = 1.0
            s = s[:-1]
        elif s.endswith("万"):
            mul = 1.0 / 10000.0
            s = s[:-1]
        try:
            return float(s) * mul
        except (TypeError, ValueError):
            return None

    def _extract_net_value(row: Dict[str, Any]) -> Optional[float]:
        direct_keys = (
            "今日主力净流入-净额",
            "主力净流入-净额",
            "净流入额",
            "净流入",
            "净额",
        )
        for k in direct_keys:
            v = row.get(k)
            try:
                if v is not None and str(v).strip() != "":
                    return float(v)
            except (TypeError, ValueError):
                continue
        for k, v in row.items():
            ks = str(k)
            if ("净流入" in ks or "净额" in ks) and "占比" not in ks and "净占比" not in ks:
                fv = _to_float(v)
                if fv is not None:
                    return fv
        return None

    def _extract_name(row: Dict[str, Any]) -> str:
        for k in ("名称", "行业", "板块", "板块名称", "概念名称", "name"):
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    ind = blocks.get("a_share_capital_flow_sector_industry")
    if isinstance(ind, dict) and ind.get("success") and ind.get("query_kind") == "sector_rank":
        recs = ind.get("records") or []
        lines.append("### 一、行业板块")
        rows: List[Tuple[str, float]] = []
        for r in recs:
            if not isinstance(r, dict):
                continue
            nm = _extract_name(r)
            if not nm:
                continue
            net = _extract_net_value(r)
            fv = float(net) if net is not None else 0.0
            rows.append((nm, fv))
        if rows:
            shown = rows[:6]
            for nm, fv in shown:
                lines.append(f"- {nm}：{_fmt_flow_yi(fv)}")
            if len(shown) >= 4:
                pos = sorted(shown, key=lambda x: x[1], reverse=True)[:3]
                neg = sorted(shown, key=lambda x: x[1])[:3]
                pj = "、".join(p[0] for p in pos)
                nj = "、".join(n[0] for n in neg)
                lines.append(f"- 净流入居前：{pj}")
                lines.append(f"- 净流入靠后：{nj}")
        else:
            lines.append("- 行业板块净流入明细暂缺（源返回字段不完整）。")

    con = blocks.get("a_share_capital_flow_sector_concept")
    if isinstance(con, dict) and con.get("success") and con.get("query_kind") == "sector_rank":
        lines.append("### 二、概念板块")
        con_rows: List[Tuple[str, float]] = []
        for r in (con.get("records") or [])[:12]:
            if not isinstance(r, dict):
                continue
            nm = _extract_name(r)
            net = _extract_net_value(r)
            fv = float(net) if net is not None else 0.0
            if nm:
                con_rows.append((nm, fv))
        if con_rows:
            for nm, fv in con_rows[:6]:
                lines.append(f"- {nm}：{_fmt_flow_yi(fv)}")
        else:
            lines.append("- 概念板块净流入明细暂缺（源返回字段不完整）。")

    # 全市场口径作为补充，不再作为专题主入口。
    mh = blocks.get("a_share_capital_flow_market_history")
    tool_blk = report_data.get("tool_fetch_a_share_fund_flow")
    if (
        isinstance(mh, dict)
        and mh.get("success")
        and str(mh.get("query_kind") or "market_history") in _MARKET_FLOW_QUERY_KINDS
    ):
        recs = mh.get("records")
        if isinstance(recs, list) and recs:
            last = recs[-1]
            if isinstance(last, dict):
                net = _extract_net_value(last)
                if net is not None:
                    lines.append(f"### 全市场大盘（补充）\n- 主力净流入：{_fmt_flow_yi(net)}")
    elif (
        isinstance(tool_blk, dict)
        and tool_blk.get("success")
        and str(tool_blk.get("query_kind") or "market_history") in _MARKET_FLOW_QUERY_KINDS
    ):
        recs = tool_blk.get("records")
        if isinstance(recs, list) and recs:
            last = recs[-1]
            if isinstance(last, dict):
                net = _extract_net_value(last)
                if net is not None:
                    lines.append(f"### 全市场大盘（补充）\n- 主力净流入：{_fmt_flow_yi(net)}")

    if (
        isinstance(mh, dict)
        and mh.get("success") is False
        and not any("### 全市场大盘（补充）" in ln for ln in lines)
    ):
        lines.insert(0, "### 全市场大盘\n- 当日全市场净流入主源暂不可用，已使用行业/概念分布做替代观察。")

    if not lines:
        # 无行业/概念/大盘资金流工具块时：用宽基 ETF 涨跌家数 + 涨跌停侧板块热度占位，避免与东财主力口径混读。
        lines.append("### 资金与成交状态（替代口径）")
        lines.append(
            "- **口径**：以下为样本宽基 ETF 的收涨/收跌只数及涨跌停侧板块热度，**不等同**于全市场或板块主力净流入；**勿与**东财/同花顺主力净额页面作一一对应。"
        )
        etf_rt = report_data.get("tool_fetch_etf_realtime")
        etf_rows = etf_rt.get("data") if isinstance(etf_rt, dict) else None
        if isinstance(etf_rows, list) and etf_rows:
            strong = 0
            weak = 0
            flat = 0
            total = 0
            for row in etf_rows[:12]:
                if not isinstance(row, dict):
                    continue
                cp = row.get("change_percent")
                try:
                    pct = float(cp)
                except (TypeError, ValueError):
                    continue
                total += 1
                if pct > 0:
                    strong += 1
                elif pct < 0:
                    weak += 1
                else:
                    flat += 1
            if total > 0:
                bias = "偏强" if strong > weak else ("偏弱" if weak > strong else "中性")
                flat_note = f"，平盘 {flat}" if flat else ""
                lines.append(
                    f"- 样本 ETF 涨跌家数：涨 {strong} / 跌 {weak} / 有效样本 {total}{flat_note}（{bias}；仅统计涨跌幅有效字段）"
                )
        sh = report_data.get("tool_sector_heat_score")
        if isinstance(sh, dict) and sh.get("success") and isinstance(sh.get("sectors"), list):
            sector_rows = [x for x in (sh.get("sectors") or []) if isinstance(x, dict)]
            top = []
            for row in sector_rows[:5]:
                name = str(row.get("name") or row.get("sector") or "").strip()
                score = row.get("score")
                if not name:
                    continue
                if score is None:
                    top.append(name)
                    continue
                try:
                    top.append(f"{name}({float(score):.0f})")
                except (TypeError, ValueError):
                    top.append(name)
            if top:
                lines.append("- 涨跌停侧板块热度靠前：" + "、".join(top))
        if len(lines) == 2:
            lines.append("- 暂未拉取有效资金流工具数据；已保留专题位，接入同花顺/东财口径工具后可展示主力净额。")
    return lines


def _build_daily_market_etf_universe_lines(
    report_data: Dict[str, Any],
    analysis: Dict[str, Any],
) -> List[str]:
    raw = report_data.get("tool_fetch_etf_realtime")
    data: List[Dict[str, Any]] = []
    if isinstance(raw, dict) and raw.get("success") and isinstance(raw.get("data"), list):
        data = [x for x in (raw.get("data") or []) if isinstance(x, dict)]

    out: List[str] = []
    for row in data[:12]:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        cp = row.get("change_percent")
        price = row.get("current_price")
        if not code:
            continue
        cp_s = ""
        if cp is not None:
            try:
                cp_s = f"涨跌 {float(cp):+.2f}%"
            except (TypeError, ValueError):
                cp_s = f"涨跌 {cp}%"
        pr_s = ""
        if price is not None:
            try:
                pr_s = f"价 {float(price):.3f}"
            except (TypeError, ValueError):
                pr_s = f"价 {price}"
        bits = [f"{code} {name}".strip(), cp_s, pr_s]
        out.append("- " + " ".join(x for x in bits if x).strip())

    # 兜底：来自 trend_analysis overlay 的第二宽基快照，避免章节全空。
    if not out and isinstance(analysis, dict):
        ov = analysis.get("daily_report_overlay")
        if isinstance(ov, dict):
            sec = ov.get("secondary_benchmark_etf")
            if isinstance(sec, dict):
                code = str(sec.get("code") or "").strip()
                name = str(sec.get("name") or "").strip()
                cp = sec.get("change_pct")
                price = sec.get("current_price")
                bits = [f"{code} {name}".strip()]
                if cp is not None:
                    try:
                        bits.append(f"涨跌 {float(cp):+.2f}%")
                    except (TypeError, ValueError):
                        bits.append(f"涨跌 {cp}%")
                if price is not None:
                    try:
                        bits.append(f"价 {float(price):.3f}")
                    except (TypeError, ValueError):
                        bits.append(f"价 {price}")
                if code:
                    out.append("- " + " ".join(x for x in bits if x).strip())
    return out


def _coverage_semantic_present(topic: str, rd: Dict[str, Any], _analysis: Dict[str, Any]) -> bool:
    t = (topic or "").strip().lower()
    if t in ("northbound", "northbound_flow"):
        # 北向数据口径已下线：不再作为日报覆盖性检查项。
        return False
    if t == "capital_flow_topic":
        return _capital_flow_topic_substantive(rd)
    return False


def _key_levels_data_present(rd: Dict[str, Any], an: Dict[str, Any]) -> bool:
    """与发送层一致：顶层 key_levels / tool_compute，或盘后 overlay 已有关键位工具结果。"""
    if any(isinstance(rd.get(k), dict) for k in ("tool_compute_index_key_levels", "key_levels")):
        for k in ("tool_compute_index_key_levels", "key_levels"):
            blk = rd.get(k)
            if isinstance(blk, dict) and blk.get("success") is not False:
                return True
    ov = an.get("daily_report_overlay") if isinstance(an, dict) else None
    if isinstance(ov, dict):
        kl = ov.get("key_levels")
        if isinstance(kl, dict) and kl.get("success"):
            return True
    return False


def _assess_daily_report_completeness(
    report_data: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """返回 (是否降级/不完整, 缺失维度说明列表)。"""
    missing: List[str] = []
    rd = report_data or {}
    an = analysis or {}
    # 1) 数据日期审计：不等同于“字段缺失”，但会显著影响结论可靠性，需进入审计缺口。
    stale = rd.get("data_stale_warning")
    if not stale and isinstance(an, dict):
        stale = an.get("data_stale_warning")
    if isinstance(stale, str) and stale.strip():
        missing.append("数据日期滞后")

    # 2) 信息面：行业要闻（常见失败为 Tavily 401/配额/网络限制）；失败应进入缺口清单。
    ind_blk = rd.get("industry_news") or rd.get("tool_fetch_industry_news_brief")
    if isinstance(ind_blk, dict) and ind_blk.get("success") is False:
        missing.append("行业要闻")

    # 3) 信息面：政策要闻同理（若显式失败则记录；空列表不算缺失）。
    pol_blk = rd.get("policy_news") or rd.get("tool_fetch_policy_news")
    if isinstance(pol_blk, dict) and pol_blk.get("success") is False:
        missing.append("政策要闻")

    if not _capital_flow_topic_substantive(rd):
        missing.append("资金流向专题")
    # 日报不再因关键位缺失阻断发送；仅用于审计行提示。
    if not _key_levels_data_present(rd, an):
        missing.append("关键位")
    degraded = bool(missing)
    return degraded, missing


def _normalize_daily_report_fields(
    report_data: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    发送前拷贝并归一化：overlay 板块热度提升、可选关键位补算等。
    返回 (normalized_report_data, merged_analysis_echo)。
    """
    out: Dict[str, Any] = copy.deepcopy(report_data) if report_data else {}
    an = analysis if isinstance(analysis, dict) else {}
    echo = copy.deepcopy(an)

    ov = an.get("daily_report_overlay")
    if isinstance(ov, dict):
        sh = ov.get("sector_heat")
        if isinstance(sh, dict) and sh.get("success") and not out.get("sector_rotation"):
            out["sector_rotation"] = sh
        # 与 trend_analysis overlay 对齐：关键位已在 overlay 时写入
        kl_ov = ov.get("key_levels")
        if (
            isinstance(kl_ov, dict)
            and kl_ov.get("success")
            and not out.get("tool_compute_index_key_levels")
            and not out.get("key_levels")
        ):
            out["tool_compute_index_key_levels"] = kl_ov

    if (out.get("report_type") or "").strip() == "daily_market":
        has_kl = isinstance(out.get("key_levels"), dict) and bool(out.get("key_levels"))
        has_tool = isinstance(out.get("tool_compute_index_key_levels"), dict) and out[
            "tool_compute_index_key_levels"
        ].get("success")
        if not has_kl and not has_tool and os.environ.get("DAILY_REPORT_DISABLE_KEY_LEVELS_AUTOFILL") != "1":
            try:
                from plugins.analysis.key_levels import tool_compute_index_key_levels

                kl = tool_compute_index_key_levels(index_code="000300")
                if isinstance(kl, dict) and kl.get("success"):
                    out["tool_compute_index_key_levels"] = kl
                    out["key_levels_fill_source"] = "send_layer_autofill"
            except Exception:
                pass

    if (out.get("report_type") or "").strip() == "daily_market":
        _normalize_global_index_display_names(out)

    return out, echo
