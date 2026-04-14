"""
日报字段归一化、补采合并与单元测试辅助（与 workflows/daily_market_report.yaml 对齐）。

从 send_daily_report 延迟导入格式化函数，避免模块加载期循环依赖。
"""

from __future__ import annotations

import copy
import os
import re
from typing import Any, Dict, List, Optional, Tuple

_DAILY_GLOBAL_INDEX_CODES = (
    "^N225,^HSI,^KS11,^GDAXI,^STOXX50E,^FTSE,^GSPC,^IXIC,^DJI"
)


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
    """Cron 日报 P0：在允许时补拉全球指数现货，写回 global_index_spot / tool_fetch_global_index_spot。"""
    if os.environ.get("DAILY_REPORT_DISABLE_CRON_P0_AUTOFILL"):
        return
    if (rd.get("report_type") or "").strip() != "daily_market":
        return
    try:
        from plugins.data_collection.index.fetch_global import fetch_global_index_spot
    except Exception:
        return
    try:
        rich = fetch_global_index_spot(_DAILY_GLOBAL_INDEX_CODES)
    except Exception:
        return
    if isinstance(rich, dict) and rich.get("success"):
        rd["global_index_spot"] = rich
        rd["tool_fetch_global_index_spot"] = rich
        rd["cron_p0_autofill_global_index"] = True


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
    for blk in blocks.values():
        if not isinstance(blk, dict) or blk.get("success") is False:
            continue
        rec = blk.get("records")
        if isinstance(rec, list) and rec:
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
    if blk.get("query_kind") != "market_history":
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

    mh = blocks.get("a_share_capital_flow_market_history")
    tool_blk = report_data.get("tool_fetch_a_share_fund_flow")
    if isinstance(mh, dict) and mh.get("success") and mh.get("query_kind") == "market_history":
        recs = mh.get("records")
        if isinstance(recs, list) and recs:
            last = recs[-1]
            if isinstance(last, dict):
                net = _extract_net_value(last)
                if net is not None:
                    lines.append(f"### 全市场大盘\n- 主力净流入：{_fmt_flow_yi(net)}")
    elif isinstance(tool_blk, dict) and tool_blk.get("success"):
        if tool_blk.get("query_kind") == "market_history":
            recs = tool_blk.get("records")
            if isinstance(recs, list) and recs:
                last = recs[-1]
                if isinstance(last, dict):
                    net = _extract_net_value(last)
                    if net is not None:
                        lines.append(f"### 全市场大盘\n- 主力净流入：{_fmt_flow_yi(net)}")
        else:
            lines.append(
                "### 资金流向专题\n- 暂未拉取两市全市场在交易层面的净流入历史（见 openclaw-data-china-stock / 工具 query_kind）"
            )

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

    if (
        isinstance(mh, dict)
        and mh.get("success") is False
        and not any("### 全市场大盘" in ln for ln in lines)
    ):
        lines.insert(0, "### 全市场大盘\n- 当日全市场净流入主源暂不可用，已使用行业/概念分布做替代观察。")

    if not lines:
        lines.append("### 资金流向专题\n- 暂未拉取有效数据块（见 openclaw-data-china-stock）")
    return lines


def _build_daily_market_etf_universe_lines(
    report_data: Dict[str, Any],
    _analysis: Dict[str, Any],
) -> List[str]:
    raw = report_data.get("tool_fetch_etf_realtime")
    if not isinstance(raw, dict) or not raw.get("success"):
        return []
    data = raw.get("data")
    if not isinstance(data, list):
        return []
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
    return out


def _coverage_semantic_present(topic: str, rd: Dict[str, Any], _analysis: Dict[str, Any]) -> bool:
    t = (topic or "").strip().lower()
    if t in ("northbound", "northbound_flow"):
        if isinstance(rd.get("northbound"), dict):
            return True
        if isinstance(rd.get("tool_fetch_northbound_flow"), dict):
            return True
        if _capital_flow_topic_substantive(rd):
            return True
        return False
    if t == "capital_flow_topic":
        return _capital_flow_topic_substantive(rd)
    return False


def _assess_daily_report_completeness(
    report_data: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """返回 (是否降级/不完整, 缺失维度说明列表)。"""
    missing: List[str] = []
    rd = report_data or {}
    an = analysis or {}
    if not _capital_flow_topic_substantive(rd):
        missing.append("资金流向专题")
    if not isinstance(rd.get("northbound"), dict) and not isinstance(
        rd.get("tool_fetch_northbound_flow"), dict
    ):
        if not any(
            isinstance(rd.get(k), dict) for k in ("tool_compute_index_key_levels", "key_levels")
        ):
            missing.append("北向/关键位等（示例门禁）")
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

    return out, echo
