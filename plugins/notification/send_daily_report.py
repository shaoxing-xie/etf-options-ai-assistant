"""
发送市场日报（飞书通知）

说明：
- 工作流脚本期望存在 `notification.send_daily_report.tool_send_daily_report`
- 实际发送能力复用合并工具 `merged.send_feishu_notification.tool_send_feishu_notification`
- 默认 mode="prod"：真实发送到飞书 webhook
- mode="test"：仅做格式化/校验，不发出网络请求（用于 step_by_step 工作流测试，避免刷屏）
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple, Mapping
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _daily_report_timing_enabled() -> bool:
    """环境变量 DAILY_REPORT_TIMING=1 时启用分段耗时（供压测/排障，默认关闭）。"""
    return os.environ.get("DAILY_REPORT_TIMING", "").strip().lower() in ("1", "true", "yes")


def _to_pretty_text(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(data)


def _fmt_pct(v: Any) -> Optional[str]:
    try:
        if v is None:
            return None
        x = float(v)
        if x != x or x in (float("inf"), float("-inf")):  # NaN / inf
            return None
        return f"{x:.2f}%"
    except Exception:
        return None


def _fmt_num(v: Any, nd: int = 4) -> Optional[str]:
    try:
        if v is None:
            return None
        return f"{float(v):.{nd}f}"
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _detect_report_type(report_data: Dict[str, Any]) -> str:
    rt = report_data.get("report_type")
    if isinstance(rt, str) and rt.strip():
        rts = rt.strip()
        if rts == "limitup_after_close_enhanced":
            return "limitup_after_close_enhanced"
        return rts
    # 兼容：如果没有 report_type，但存在某些字段，可粗略判断
    if "signals" in report_data:
        return "after_close"
    return "daily_report"


def _extract_llm_summary(report_data: Dict[str, Any]) -> str:
    # 1) 顶层
    for k in ("llm_summary", "analysis_summary", "summary"):
        v = report_data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 1.5) 兼容嵌套：可能是 { report_data: {...} } 或 { data: { report_data: {...} } }
    for outer_k in ("report_data", "data"):
        outer = report_data.get(outer_k)
        if not isinstance(outer, dict):
            continue
        for k in ("llm_summary", "analysis_summary", "summary"):
            v = outer.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        inner = outer.get("report_data")
        if isinstance(inner, dict):
            for k in ("llm_summary", "analysis_summary", "summary"):
                v = inner.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    # 2) analysis / analysis_data
    for key in ("analysis", "analysis_data"):
        v = report_data.get(key)
        if isinstance(v, dict):
            s = v.get("llm_summary") or v.get("analysis_summary") or v.get("summary")
            if isinstance(s, str) and s.strip():
                return s.strip()
    return ""


def _build_market_overview_lines(report_data: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    gmd = report_data.get("global_market_digest")
    if isinstance(gmd, dict) and gmd.get("replaces_index_overview"):
        summ = str(gmd.get("summary") or "").strip()
        if summ:
            lines.append(summ + "（检索摘要归纳；个别指数逐点涨跌未展示）")
            return lines

    mo = report_data.get("market_overview")
    if not isinstance(mo, dict):
        mo = {}
    indices = mo.get("indices")
    if isinstance(indices, list) and indices:
        parts: List[str] = []
        for it in indices[:8]:
            if not isinstance(it, dict):
                continue
            name = it.get("name") or it.get("code") or ""
            chg = it.get("change_pct")
            if chg is None:
                chg = it.get("change")
            chg_s = _fmt_pct(chg) or str(chg) if chg is not None else "N/A"
            if name:
                parts.append(f"{name}: {chg_s}")
        if parts:
            lines.append("外盘/指数概览： " + " | ".join(parts))

    macro = mo.get("macro_commodities") or mo.get("commodities")
    if isinstance(macro, list) and macro:
        parts2: List[str] = []
        for it in macro[:6]:
            if not isinstance(it, dict):
                continue
            nm = it.get("name") or it.get("code") or ""
            chg = it.get("change_pct")
            chg_s = _fmt_pct(chg) if chg is not None else "N/A"
            if nm:
                parts2.append(f"{nm}: {chg_s}")
        if parts2:
            lines.append("大宗商品： " + " | ".join(parts2))

    # before_open 常见还有 A50/HXC（在 analysis_data 中）
    ad = report_data.get("analysis_data")
    if not isinstance(ad, dict):
        ad = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
    if isinstance(ad, dict):
        a50 = ad.get("a50_change")
        hxc = ad.get("hxc_change")
        extra: List[str] = []
        a50_s = _fmt_pct(a50)
        if a50_s is not None:
            extra.append(f"A50: {a50_s}")
        hxc_s = _fmt_pct(hxc)
        if hxc_s is not None:
            extra.append(f"金龙: {hxc_s}")
        if extra:
            lines.append("外盘补充： " + " | ".join(extra))

    ms = _as_tool_data_payload(report_data.get("macro_snapshot"))
    if isinstance(ms, dict):
        items = ms.get("items")
        if isinstance(items, list) and items:
            parts3: List[str] = []
            for it in items[:6]:
                if not isinstance(it, dict):
                    continue
                nm = it.get("name") or it.get("code") or ""
                chg = it.get("change_pct")
                dg = it.get("digest")
                if chg is not None:
                    chg_s = _fmt_pct(chg) or "N/A"
                    if nm:
                        parts3.append(f"{nm}: {chg_s}")
                elif dg and nm:
                    parts3.append(f"{nm}: {str(dg)[:120]}…(检索)")
            if parts3:
                lines.append("大宗商品： " + " | ".join(parts3))

    return lines


def _daily_market_outer_overview_is_research_digest(report_data: Dict[str, Any], mo_lines: List[str]) -> bool:
    """外盘概览是否由 Tavily/综述替代逐指数数值（与 tool_fetch_global_index_spot 数值行区分）。"""
    gmd = report_data.get("global_market_digest")
    if isinstance(gmd, dict) and gmd.get("replaces_index_overview"):
        return True
    if mo_lines and len(mo_lines) == 1 and "检索摘要归纳" in (mo_lines[0] or ""):
        return True
    return False


def _build_a_share_volume_lines(report_data: Dict[str, Any]) -> List[str]:
    snap = report_data.get("tool_fetch_index_realtime")
    if not isinstance(snap, dict):
        return []
    data = snap.get("data")
    rows: List[Dict[str, Any]] = []
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        rows = [r for r in data.values() if isinstance(r, dict)]
    if not rows:
        # 兜底：使用 trend_analysis overlay 的量能摘要，避免章节空白。
        an = report_data.get("analysis")
        ov = an.get("daily_report_overlay") if isinstance(an, dict) else None
        mvd = ov.get("market_volume_digest") if isinstance(ov, dict) else None
        if isinstance(mvd, dict):
            latest = mvd.get("latest")
            prev = mvd.get("previous")
            dod = mvd.get("dod_pct")
            benchmark = str(mvd.get("benchmark") or "上证指数").strip()
            out: List[str] = []
            try:
                if latest is not None:
                    out.append(f"{benchmark}成交额（最新）约 {float(latest)/1e8:.2f} 亿元")
                if prev is not None:
                    out.append(f"{benchmark}成交额（前值）约 {float(prev)/1e8:.2f} 亿元")
                if dod is not None:
                    out.append(f"{benchmark}成交额环比 {float(dod):+.2f}%")
            except Exception:
                pass
            if out:
                return out
        return []
    amount_sum = 0.0
    amount_cnt = 0
    vol_sum = 0.0
    vol_cnt = 0
    breadth_up = 0
    breadth_dn = 0
    for r in rows:
        a = r.get("amount")
        v = r.get("volume")
        cp = r.get("change_percent")
        try:
            if a is not None:
                amount_sum += float(a)
                amount_cnt += 1
        except Exception:
            pass
        try:
            if v is not None:
                vol_sum += float(v)
                vol_cnt += 1
        except Exception:
            pass
        try:
            if cp is not None and float(cp) > 0:
                breadth_up += 1
            elif cp is not None and float(cp) < 0:
                breadth_dn += 1
        except Exception:
            pass
    out: List[str] = []
    if amount_cnt > 0:
        out.append(f"A股主要指数成交额合计约 {amount_sum/1e8:.2f} 亿元（样本{amount_cnt}）")
    if vol_cnt > 0:
        out.append(f"A股主要指数成交量合计约 {vol_sum/1e4:.2f} 万手（样本{vol_cnt}）")
    if breadth_up or breadth_dn:
        bias = "偏多" if breadth_up > breadth_dn else "偏空" if breadth_dn > breadth_up else "均衡"
        out.append(f"指数涨跌家数：上涨 {breadth_up} / 下跌 {breadth_dn}，结构 {bias}")
    return out


def _collect_before_open_reference_urls(report_data: Dict[str, Any], *, max_urls: int = 5) -> List[str]:
    """隔夜检索证据链接 + 政策条目链接，去重，供盘前报告置顶「参考链接」行。"""
    seen: set[str] = set()
    out: List[str] = []

    def _push(u: Any) -> None:
        if not isinstance(u, str):
            return
        s = u.strip()
        if not s or s in seen:
            return
        if not (s.startswith("http://") or s.startswith("https://")):
            return
        seen.add(s)
        out.append(s)

    od = _as_tool_data_payload(report_data.get("overnight_digest"))
    if isinstance(od, dict):
        for u in od.get("evidence_urls") or []:
            _push(u)
            if len(out) >= max_urls:
                return out
    pn = _as_tool_data_payload(
        report_data.get("policy_news")
        or report_data.get("fetch_policy_news")
        or report_data.get("tool_fetch_policy_news")
    )
    if isinstance(pn, dict):
        items = pn.get("items")
        if isinstance(items, list):
            for it in items:
                if len(out) >= max_urls:
                    break
                if isinstance(it, dict):
                    _push(it.get("url"))
    return out


def _build_overnight_digest_lines(report_data: Dict[str, Any], analysis: Dict[str, Any]) -> List[str]:
    od = _as_tool_data_payload(report_data.get("overnight_digest"))
    if not isinstance(od, dict):
        return []
    lines: List[str] = []
    if od.get("a50_digest"):
        lines.append(f"A50（检索摘要，未核验数值）： {od['a50_digest']}")
    if od.get("hxc_digest"):
        lines.append(f"金龙（检索摘要，未核验数值）： {od['hxc_digest']}")
    urls = od.get("evidence_urls")
    if isinstance(urls, list) and urls:
        lines.append("参考链接： " + " | ".join(str(u) for u in urls[:5]))
    if not lines and analysis.get("overnight_overlay_degraded"):
        lines.append("隔夜 A50/金龙主源不可用；请依赖上方全球指数或工作流检索摘要。")
    return lines


def _as_tool_data_payload(d: Any) -> Dict[str, Any]:
    """兼容直接把工具返回 { success, data: {...} } 塞进 report_data 的情况。"""
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        return d["data"]
    return d if isinstance(d, dict) else {}


def _build_industry_news_lines(report_data: Dict[str, Any]) -> List[str]:
    ind = _as_tool_data_payload(
        report_data.get("industry_news")
        or report_data.get("tool_fetch_industry_news_brief")
    )
    if not isinstance(ind, dict):
        return []
    items = ind.get("items")
    if not isinstance(items, list) or not items:
        return []
    lines: List[str] = []
    if ind.get("brief_answer"):
        lines.append(f"行业提要：{str(ind['brief_answer'])[:400]}")
    for i, it in enumerate(items[:8], 1):
        if not isinstance(it, dict):
            continue
        t = it.get("title") or ""
        u = it.get("url") or ""
        lines.append(f"{i}. {t[:120]} {u[:120]}".strip())
    return lines


def _build_global_spot_lines(report_data: Dict[str, Any]) -> List[str]:
    raw = report_data.get("global_index_spot")
    if raw is None:
        raw = report_data.get("global_spot")
    block: Dict[str, Any] = {}
    if isinstance(raw, dict):
        if isinstance(raw.get("data"), list):
            block = raw
        elif raw.get("success") and isinstance(raw.get("data"), list):
            block = raw
    rows = block.get("data") if isinstance(block.get("data"), list) else []
    if not rows:
        return []
    parts: List[str] = []
    for it in rows[:14]:
        if not isinstance(it, dict):
            continue
        name = it.get("name") or it.get("code") or ""
        chg = it.get("change_pct")
        chg_s = _fmt_pct(chg) if chg is not None else "N/A"
        if name:
            parts.append(f"{name}: {chg_s}")
    return [f"全球指数： {' | '.join(parts)}"] if parts else []


def _build_overnight_calibration_lines(report_data: Dict[str, Any]) -> List[str]:
    cal = report_data.get("overnight_calibration")
    if isinstance(cal, dict) and cal.get("success") is False and cal.get("message"):
        return [f"隔夜校准：{cal.get('message')}"]
    d = _as_tool_data_payload(cal)
    if not isinstance(d, dict):
        return []
    gap = d.get("a50_vs_hs300_gap_pct")
    impact = d.get("impact_score")
    a50 = d.get("a50_change_pct")
    hs = d.get("hs300_daily_change_pct")
    lines: List[str] = []
    if a50 is not None or hs is not None:
        lines.append(
            f"A50涨跌%: {_fmt_pct(a50) or str(a50)} ；沪深300日涨跌%: {_fmt_pct(hs) or str(hs)}"
        )
    if gap is not None:
        lines.append(f"A50与沪深300日涨跌幅差（百分点）: {gap}")
    if impact is not None:
        lines.append(f"impact_score（说明见工具）: {impact}")
    if d.get("note"):
        lines.append(str(d["note"])[:300])
    return lines


def _build_scenario_lines(report_data: Dict[str, Any]) -> List[str]:
    sc = report_data.get("scenarios")
    d = _as_tool_data_payload(sc)
    if not isinstance(d, dict):
        return []
    lines: List[str] = []
    for key in ("optimistic", "neutral", "pessimistic"):
        blob = d.get(key)
        if not isinstance(blob, dict):
            continue
        title = blob.get("title") or key
        lines.append(f"**{title}**")
        for c in blob.get("conditions") or []:
            if c:
                lines.append(f"- {c}")
        hint = blob.get("position_hint")
        if hint:
            lines.append(f"- 仓位提示：{hint}")
    if d.get("disclaimer"):
        lines.append(str(d["disclaimer"])[:500])
    return lines


def _build_limitup_record_lines(report_data: Dict[str, Any]) -> List[str]:
    lr = report_data.get("limitup_record")
    if isinstance(lr, str) and lr.strip():
        return [lr.strip()[:800]]
    if not isinstance(lr, dict):
        return []
    lines: List[str] = []
    if lr.get("path"):
        lines.append(f"已落盘：{lr.get('path')}")
    for k in ("watchlist_summary", "hypothesis", "sector_notes"):
        v = lr.get(k)
        if isinstance(v, str) and v.strip():
            lines.append(f"{k}: {v.strip()[:400]}")
    leaders = lr.get("leaders")
    if isinstance(leaders, list) and leaders:
        lines.append("龙头观察：" + ", ".join(str(x) for x in leaders[:12]))
    return lines


def _policy_brief_looks_mostly_english_latin(text: str) -> bool:
    s = str(text or "")
    if not s.strip():
        return False
    letters = sum(1 for c in s if "a" <= c.lower() <= "z")
    cjk = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    return letters > 40 and cjk < 8


def _build_policy_news_lines(
    report_data: Dict[str, Any],
    *,
    brief_max: int = 400,
    opening_prefer_cn_brief: bool = False,
) -> List[str]:
    pn = _as_tool_data_payload(
        report_data.get("policy_news")
        or report_data.get("fetch_policy_news")
        or report_data.get("tool_fetch_policy_news")
    )
    if not isinstance(pn, dict):
        return []
    items = pn.get("items")
    if not isinstance(items, list) or not items:
        return []
    lines: List[str] = []
    if opening_prefer_cn_brief and pn.get("brief_answer"):
        ba = str(pn["brief_answer"])
        titles = [
            str(it.get("title") or "").strip()
            for it in items[:10]
            if isinstance(it, dict) and str(it.get("title") or "").strip()
        ]
        has_cn_title = any(any("\u4e00" <= c <= "\u9fff" for c in t) for t in titles)
        if _policy_brief_looks_mostly_english_latin(ba) and has_cn_title:
            body = "；".join(titles[:6])[: max(80, brief_max)]
            lines.append(f"提要：综合要点（据下列中文来源标题）{body}")
            return lines
    if pn.get("brief_answer"):
        lines.append(f"提要：{str(pn['brief_answer'])[:brief_max]}")
    for i, it in enumerate(items[:8], 1):
        if not isinstance(it, dict):
            continue
        t = it.get("title") or ""
        u = it.get("url") or ""
        lines.append(f"{i}. {t[:120]} {u[:120]}".strip())
    return lines


def _build_info_fallback_lines_from_context_cache(max_lines: int = 2) -> List[str]:
    """信息面兜底：读取已有分析缓存摘要（由上游分析流程产出），避免章节完全空白。"""
    try:
        p = Path(__file__).resolve().parents[2] / "data" / "cache" / "llm_context_today.json"
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8"))
        summaries = raw.get("summaries") if isinstance(raw, dict) else None
        if not isinstance(summaries, list) or not summaries:
            return []
        out: List[str] = []
        for s in summaries[:max_lines]:
            if not isinstance(s, str):
                continue
            txt = s.strip()
            if not txt:
                continue
            # 常见格式 "11:02 after_close: xxx"
            if ":" in txt:
                txt = txt.split(":", 1)[1].strip()
            out.append(txt[:220])
        return out
    except Exception:
        return []


def _strip_prose_markdown_noise(text: str) -> str:
    """去掉 LLM 偶发的 # 标题行，压成机构晨报式一段。"""
    out: List[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r"^#{1,6}\s*", "", s)
        out.append(s)
    return " ".join(out).strip()


def _cjk_char_ratio(text: str) -> float:
    s = text or ""
    if not s:
        return 0.0
    n = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    return n / max(len(s), 1)


_TAVILY_JUNK_LINE = re.compile(
    r"(?i)^(advertisement|subscribe|sign up|newsletter|continue to article|read more|"
    r"markets am newsletter|image\s*\d+|plus:\s*a flashback)\b|"
    r"^\s*\[\]\(\s*\)\s*$|^\s*#\s*#+\s*"
)


def _strip_tavily_digest_noise(text: str) -> str:
    """去掉 Tavily 拼接结果里常见的英文报刊版式噪声（广告、图片占位、空链等）。"""
    out: List[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if len(s) < 4:
            continue
        if _TAVILY_JUNK_LINE.search(s):
            continue
        if re.match(r"(?i)^image\s+\d+", s):
            continue
        if s.lower().startswith("http://") or s.lower().startswith("https://"):
            continue
        if re.match(r"^\d+\.\s*$", s):
            continue
        s = re.sub(r"\s*\|\s*###\s*", " — ", s)
        out.append(s)
    merged = " ".join(out)
    merged = re.sub(r"\s{2,}", " ", merged).strip()
    return merged


def _opening_digest_temporal_anchor_block(report_data: Optional[Dict[str, Any]]) -> str:
    """
    开盘 Cron 默认约 9:28：美欧 vs 日韩的时段锚定（定性口径）。
    周一：美欧 = 上一完整常规交易日（一般为上周五）收市后；日韩 = 「今早」早盘。
    周二至周五：美欧 = 昨夜（上一美东交易日）收市后；日韩 = 「今早」早盘。
    """
    if not report_data:
        return ""
    td = str(report_data.get("trade_date") or report_data.get("date") or "").strip()[:10]
    if not td or len(td) < 10:
        return ""
    try:
        d = datetime.strptime(td, "%Y-%m-%d")
        wd = d.weekday()
    except ValueError:
        return ""
    if wd == 0:
        us_eu = (
            "美欧股指时段锚定：上一完整常规交易日（一般为上周五）收市后的隔夜信息；"
            "本段仅定性，不含未经 yfinance/交易所主源核验的涨跌幅数字。"
        )
        jp_kr = (
            "日韩股指时段锚定：「今早」早盘（截至报告生成时）的市况；"
            "本段仅定性，不含未经主源核验的涨跌幅数字。"
        )
    else:
        us_eu = (
            "美欧股指时段锚定：昨夜（上一美东交易日）收市后的隔夜信息；"
            "本段仅定性，不含未经 yfinance/交易所主源核验的涨跌幅数字。"
        )
        jp_kr = (
            "日韩股指时段锚定：「今早」早盘；"
            "本段仅定性，不含未经主源核验的涨跌幅数字。"
        )
    return f"【报告日 {td}·开盘前例行】\n{us_eu}\n{jp_kr}\n"


def _enforce_no_numeric_percentages(text: str) -> str:
    """
    无 yfinance 数值主源时最后防线：删除阿拉伯数字百分比及常见「百分点」写法，避免误导读数。
    """
    t = text or ""
    t = re.sub(r"[（(]?±?\s*\d+(?:\.\d+)?\s*%[)）]?", "", t)
    t = re.sub(r"\d+(?:\.\d+)?\s*%", "", t)
    t = re.sub(r"(?:约|大约|上下|左右)\s*\d+(?:\.\d+)?\s*个百分点", "有限幅度", t)
    t = re.sub(r"\d+(?:\.\d+)?\s*个百分点", "有限幅度", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"\s+([，。；])", r"\1", t)
    return t


def _refine_opening_global_digest_for_dingtalk(
    raw: str,
    *,
    max_chars: int = 720,
    report_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    外盘 Tavily 摘要（无 yfinance 有效数值行时）：去噪 → LLM 压成中文定性 + 时段锚定。
    产品口径 B：全文不得出现任何阿拉伯数字百分比（含约 x%）；不写精确涨跌数值。
    """
    base = _strip_tavily_digest_noise(raw)
    if not base:
        return ""
    anchor = _opening_digest_temporal_anchor_block(report_data)
    # 已是中文且不含「数字%」时可直接截断，仍做一次百分点清理以防漏网
    if _cjk_char_ratio(base) >= 0.08 and not re.search(r"\d+(?:\.\d+)?\s*%", base):
        out = (anchor + "\n" + base).strip() if anchor else base
        cleaned = _enforce_no_numeric_percentages(out)
        return cleaned[:max_chars] + ("…" if len(cleaned) > max_chars else "")
    try:
        from src.config_loader import load_system_config
        from plugins.utils.llm_structured_extract import llm_prose_from_unstructured

        cfg = load_system_config(use_cache=True)
        material = (anchor + "\n\n---\n\n" + base) if anchor else base
        instructions = (
            "下列为外盘检索摘要素材（可能含英文与杂质）。请用简体中文写一段「隔夜外盘要点」（4～8 句），"
            "与上方【时段锚定】自然衔接，不得与之矛盾。\n"
            "硬约束（无 yfinance 等主源数值时）：全文禁止出现任何阿拉伯数字的百分比符号 %，"
            "禁止「约1.1%」「±0.3%」「1.84%」等一切具体涨跌幅数字；禁止用阿拉伯数字写涨跌幅度或点数；"
            "仅用「上涨/下跌/震荡/分化/承压/偏强/偏弱/幅度有限」等定性表述。\n"
            "不要使用 markdown 标题或 #；不要广告、订阅、Image、链结说明；勿编造素材中未出现的指数名称。"
        )
        r = llm_prose_from_unstructured(
            material[:4200],
            instructions,
            config=cfg,
            profile="default",
            max_output_chars=min(max_chars + 400, 1400),
        )
        if r.get("success"):
            prose = _strip_prose_markdown_noise(str(r.get("text") or "").strip())
            if prose:
                prose = _enforce_no_numeric_percentages(prose)
                if prose:
                    return prose[:max_chars] + ("…" if len(prose) > max_chars else "")
    except Exception as e:
        logger.warning("refine_opening_global_digest_for_dingtalk: %s", e)
    # LLM 失败：仅输出时段锚定 + 极短定性，避免贴回含 % 的英文素材
    fallback = anchor or "外盘：主源数值暂缺，以下为检索语境下的定性说明（不含具体涨跌幅）。"
    return fallback[:max_chars]


def _fallback_us_tavily_strip_other_markets(text: str, max_chars: int) -> str:
    """LLM 不可用时：去掉明显复述欧股/日韩的句子，减轻与同行重复。"""
    t = _enforce_no_numeric_percentages(_strip_tavily_digest_noise(text))
    if not t:
        return ""
    bad = re.compile(
        r"(欧洲|欧股|斯托克|富时|德国\s*DAX|DAX|英国|法国|CAC|"
        r"日经|韩国|KOSPI|恒生|A50)"
    )
    parts: List[str] = []
    for seg in re.split(r"(?<=[。；\n])", t):
        s = seg.strip()
        if not s:
            continue
        if bad.search(s):
            continue
        parts.append(s)
    out = "".join(parts).strip()
    if not out:
        out = t[:max_chars]
    return out[:max_chars] + ("…" if len(out) > max_chars else "")


def _refine_opening_us_tavily_for_dingtalk(
    raw: str,
    *,
    max_chars: int = 480,
    report_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    美股类 Tavily 兜底：只谈道琼斯/标普500/纳斯达克，不复述欧股日韩（第三节其他行已覆盖）。
    仍遵守无阿拉伯数字 % 的口径。
    """
    base = _strip_tavily_digest_noise(raw)
    if not base:
        return ""
    anchor = _opening_digest_temporal_anchor_block(report_data)
    material = (anchor + "\n\n---\n\n" + base) if anchor else base
    try:
        from src.config_loader import load_system_config
        from plugins.utils.llm_structured_extract import llm_prose_from_unstructured

        cfg = load_system_config(use_cache=True)
        instructions = (
            "下列为检索素材。请用简体中文写一段「美股三大指数隔夜要点」（约 4～8 句）。\n"
            "结构要求：必须分别点到「道琼斯」「标普500」「纳斯达克」（可用「标普五百」「纳指」），"
            "各用至少一句描述其定性走势（涨/跌/震荡/分化/偏强/偏弱等）。\n"
            "硬约束：\n"
            "1）全文禁止阿拉伯数字与 % 符号；禁止「约1.2%」类写法；不写点数。\n"
            "2）严禁写欧洲股市、英国富时、德国DAX、欧洲斯托克、法国CAC、亚太泛述；"
            "严禁写日经、韩国、恒生、A50——本报告上一行已写欧股/日韩/A50，本段只写美国三大股指。\n"
            "3）素材若缺少某一指数的信息，用一句说明「公开报道对该指数着墨较少」即可，勿编造。\n"
            "4）不要 markdown、不要链接说明、不要广告。"
        )
        r = llm_prose_from_unstructured(
            material[:4200],
            instructions,
            config=cfg,
            profile="default",
            max_output_chars=min(max_chars + 400, 1200),
        )
        if r.get("success"):
            prose = _strip_prose_markdown_noise(str(r.get("text") or "").strip())
            if prose:
                prose = _enforce_no_numeric_percentages(prose)
                if prose:
                    return prose[:max_chars] + ("…" if len(prose) > max_chars else "")
    except Exception as e:
        logger.warning("refine_opening_us_tavily_for_dingtalk: %s", e)
    return _fallback_us_tavily_strip_other_markets(base, max_chars)


def _opening_policy_placeholder_line(report_data: Dict[str, Any]) -> str:
    """政策要闻无可用条目时的占位行；若 tool_fetch_policy_news 已失败，附带简短原因（如 Tavily HTTP 432）。"""
    pn = report_data.get("tool_fetch_policy_news")
    if isinstance(pn, dict) and pn.get("success") is False:
        msg = str(pn.get("message") or "").strip()
        if msg:
            tail = "…" if len(msg) > 240 else ""
            return f"- 暂无可用政策要闻摘要。（上游：{msg[:240]}{tail}）"
    return "- 暂无可用政策要闻摘要。"


def _build_opening_policy_news_institutional_lines(report_data: Dict[str, Any]) -> List[str]:
    """
    开盘专用：检索结果经 LLM 压成「综合要点」正文，不附链接（机构晨报口径）。
    依赖合并后配置 `llm_structured_extract.enabled`（来源：`config/domains/outbound.yaml`）；关闭时退回标题拼接。
    """
    pn = _as_tool_data_payload(
        report_data.get("policy_news")
        or report_data.get("fetch_policy_news")
        or report_data.get("tool_fetch_policy_news")
    )
    if not isinstance(pn, dict):
        return []
    items = pn.get("items")
    if not isinstance(items, list) or not items:
        return []
    titles: List[str] = []
    for it in items[:14]:
        if not isinstance(it, dict):
            continue
        t = str(it.get("title") or "").strip()
        if t:
            titles.append(t)
    if not titles:
        return []
    ba = str(pn.get("brief_answer") or "").strip()
    material = "中文标题：\n" + "\n".join(f"- {t}" for t in titles)
    if ba:
        material += "\n\n检索摘要（可能有噪）：\n" + ba[:3500]
    try:
        from src.config_loader import load_system_config
        from plugins.utils.llm_structured_extract import llm_prose_from_unstructured

        cfg = load_system_config(use_cache=True)
        instructions = (
            "请根据下列政策与宏观要闻素材，用简体中文写一段「机构晨报」综合要点（3～6 句）。"
            "要求：客观、信息密、不逐条复述标题；不要任何链接或网址；不要使用 markdown 标题（不要 #）；"
            "不要用编号列表；勿编造素材中未出现的数字与结论。"
        )
        r = llm_prose_from_unstructured(
            material,
            instructions,
            config=cfg,
            profile="default",
            max_output_chars=900,
        )
        if r.get("success") and str(r.get("text") or "").strip():
            prose = _strip_prose_markdown_noise(str(r["text"]).strip())
            if prose:
                return [f"综合要点：{prose}"]
    except Exception as e:
        logger.warning("opening policy institutional digest: %s", e)
    body = "；".join(titles[:5])
    if len(body) > 500:
        body = body[:499] + "…"
    return [f"综合要点：{body}（LLM 未启用或失败，暂由标题压缩代替）"]


_OPENING_US_CODES: Tuple[str, ...] = ("^DJI", "^GSPC", "^IXIC")
_OPENING_JK_CODES: Tuple[str, ...] = ("^N225", "^KS11")
_OPENING_EU_CODES: Tuple[str, ...] = ("^FTSE", "^GDAXI", "^STOXX50E")
_OPENING_DISPLAY_NAME_MAP: Mapping[str, str] = {
    "^DJI": "道琼斯",
    "^GSPC": "标普500",
    "^IXIC": "纳斯达克",
    "^N225": "日经225",
    "^KS11": "韩国综合",
    "^FTSE": "英国富时100",
    "^GDAXI": "德国DAX",
    "^STOXX50E": "欧洲斯托克50",
}

# 新浪 hq 返回的 code（如 int_dji）与 yfinance 符号（^DJI）对齐，供开盘隔夜分组匹配
_OPENING_SINA_CODE_TO_YF: Mapping[str, str] = {
    "INT_DJI": "DJI",
    "INT_NASDAQ": "IXIC",
    "INT_SP500": "GSPC",
    "INT_NIKKEI": "N225",
    "RT_HKHSI": "HSI",
    "RT_HK": "HSI",
    "INT_HS": "HSI",
}


def _opening_normalized_row_code(row_code: Any) -> str:
    s = str(row_code or "").strip().upper().replace("^", "")
    if not s:
        return ""
    if s in _OPENING_SINA_CODE_TO_YF:
        return _OPENING_SINA_CODE_TO_YF[s]
    return s


def _opening_index_code_match(row_code: Any, wanted_yf: str) -> bool:
    a = _opening_normalized_row_code(row_code)
    b = str(wanted_yf or "").strip().upper().replace("^", "")
    return bool(a) and a == b


def _opening_pick_row(rows: List[Dict[str, Any]], wanted_yf: str) -> Optional[Dict[str, Any]]:
    for it in rows:
        if not isinstance(it, dict):
            continue
        if _opening_index_code_match(it.get("code"), wanted_yf):
            return it
    return None


def _opening_global_index_row_key(row_code: Any) -> str:
    """合并去重用：int_dji 与 ^DJI 等同为 DJI，避免 pick 命中带 NaN 的旧别名行。"""
    k = _opening_normalized_row_code(row_code)
    if k:
        return k
    s = str(row_code or "").strip()
    return s.upper().replace("^", "") if s else ""


def _opening_global_index_rows(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    合并 global_spot 各别名键与 market_overview.indices（按 code 去重后并列）。
    注意：若仅因 tool 返回 data=[] 就提前 return，会丢掉 market_overview 中的 A 股开盘行，
    且无法与新浪/yfinance 行合并；故必须合并后再返回。

    现货与补全行可能并存 ``int_dji`` 与 ``^DJI``：按归一化键去重，且 **market_overview 后写入覆盖现货**，
    以便 hist 补全后的有效涨跌幅参与隔夜节渲染。
    """
    by_code: Dict[str, Dict[str, Any]] = {}
    for key in ("global_index_spot", "tool_fetch_global_index_spot", "fetch_global_index_spot"):
        raw = report_data.get(key)
        if not isinstance(raw, dict):
            continue
        data = raw.get("data")
        if not isinstance(data, list):
            continue
        for x in data:
            if not isinstance(x, dict):
                continue
            c = x.get("code") or x.get("name")
            if not c:
                continue
            rk = _opening_global_index_row_key(c)
            if not rk:
                continue
            by_code[rk] = x
    mo = report_data.get("market_overview")
    if isinstance(mo, dict):
        idx = mo.get("indices")
        if isinstance(idx, list):
            for x in idx:
                if not isinstance(x, dict):
                    continue
                c = x.get("code") or x.get("name")
                if not c:
                    continue
                rk = _opening_global_index_row_key(c)
                if not rk:
                    continue
                by_code[rk] = x
    return list(by_code.values())


def _fmt_opening_index_group(label: str, codes: Tuple[str, ...], rows: List[Dict[str, Any]]) -> Optional[str]:
    parts: List[str] = []
    for c in codes:
        it = _opening_pick_row(rows, c)
        if it is None:
            continue
        # 已知代码统一用中文简称，避免 FMP/yfinance 返回英文全称（如 Dow Jones Industrial Average）
        name = _OPENING_DISPLAY_NAME_MAP.get(c) or it.get("name") or c
        chg = it.get("change_pct")
        if chg is None:
            chg = it.get("change_percent")
        chg_s = _fmt_pct(chg) if chg is not None else "N/A"
        parts.append(f"{name}: {chg_s}")
    if not parts:
        return None
    return f"**{label}** " + " | ".join(parts)


def _resolve_opening_analysis_dict(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """合并 analysis / tool_analyze_market.data 等，供 A50 等字段读取。"""
    a: Dict[str, Any] = {}
    if isinstance(report_data.get("analysis"), dict):
        a.update(report_data["analysis"])
    elif isinstance(report_data.get("analysis_data"), dict):
        a.update(report_data["analysis_data"])
    for k in ("tool_analyze_market", "analyze_opening_market"):
        t = report_data.get(k)
        if isinstance(t, dict) and isinstance(t.get("data"), dict):
            for kk, vv in t["data"].items():
                if kk not in a or a.get(kk) is None:
                    if vv is not None:
                        a[kk] = vv
    return a


def _opening_a50_numeric_line(report_data: Dict[str, Any]) -> Optional[str]:
    """A50：主源（期货/趋势模块）数值行；无有效涨跌幅则返回 None（触发 Tavily 类兜底）。"""
    an = _resolve_opening_analysis_dict(report_data)
    chg = an.get("a50_change")
    s = _fmt_pct(chg)
    if s is not None:
        return f"**A50期指（主源）：** {s}"
    return None


def _opening_index_group_available(codes: Tuple[str, ...], rows: List[Dict[str, Any]]) -> bool:
    return _fmt_opening_index_group("_", codes, rows) is not None


def _tavily_opening_category_digest(cat: str) -> Optional[str]:
    """
    按类检索（与主源链路独立）：a50 / jk / eu / us。
    受 overlay.tavily_fallback_enabled 控制。
    """
    overlay: Dict[str, Any] = {}
    try:
        from src.config_loader import load_system_config
        from plugins.analysis.trend_analysis import _merge_trend_plugin_config

        cfg = load_system_config(use_cache=True)
        overlay = (_merge_trend_plugin_config(cfg).get("overlay") or {})
    except Exception:
        pass
    if not overlay.get("tavily_fallback_enabled", True):
        return None
    try:
        from plugins.utils.tavily_client import (
            DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
            parse_include_domains,
            tavily_effective_answer_text,
            tavily_search_with_include_domain_fallback,
        )

        domains = parse_include_domains(
            overlay.get("tavily_global_include_domains"),
            default=DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
        )
        deep = bool(overlay.get("tavily_global_deep", True))
        days = int(overlay.get("tavily_global_days", 2) or 2)
        mx = max(3, min(int(overlay.get("tavily_global_max_results", 6) or 6), 12))
    except Exception as e:
        logger.warning("tavily_opening_category_digest import: %s", e)
        return None

    # 美股：双路 query，减少泛全球综述里夹带欧股（与上一行重复）
    if cat == "us":
        chunks: List[str] = []
        for q in (
            "Dow Jones Industrial Average S&P 500 Nasdaq Composite previous US trading day close",
            "道琼斯 标普500 纳斯达克 美股 上一交易日 收盘 涨跌 概况",
        ):
            try:
                t = tavily_search_with_include_domain_fallback(
                    q, max_results=mx, days=days, deep=deep, include_domains=domains
                )
                if t.get("success"):
                    tx = tavily_effective_answer_text(t).strip()
                    if tx:
                        chunks.append(tx)
            except Exception as ex:
                logger.warning("tavily_opening_category_digest us subquery: %s", ex)
        merged = "\n\n".join(chunks).strip()
        return merged[:900] if merged else None

    queries = {
        "a50": "富时中国A50 期货 新加坡交易所 隔夜 涨跌",
        "jk": "日经225指数 韩国综合指数 KOSPI 最新 涨跌",
        "eu": "英国富时100 德国DAX 欧洲斯托克50 上一交易日 收市 涨跌",
    }
    q = queries.get(cat)
    if not q:
        return None
    try:
        t = tavily_search_with_include_domain_fallback(
            q, max_results=mx, days=days, deep=deep, include_domains=domains
        )
        if not t.get("success"):
            return None
        text = tavily_effective_answer_text(t).strip()
        return text[:650] if text else None
    except Exception as e:
        logger.warning("tavily_opening_category_digest %s: %s", cat, e)
        return None


def attach_opening_overnight_category_tavily(report_data: Dict[str, Any]) -> None:
    """
    开盘隔夜四类（A50 / 日韩 / 欧股 / 美股）主源缺有效行时，按类写入 Tavily 摘要至
    ``opening_overnight_category_tavily``（键 a50/jk/eu/us）。
    """
    rows = _opening_global_index_rows(report_data)
    need = {
        "a50": _opening_a50_numeric_line(report_data) is None,
        "jk": not _opening_index_group_available(_OPENING_JK_CODES, rows),
        "eu": not _opening_index_group_available(_OPENING_EU_CODES, rows),
        "us": not _opening_index_group_available(_OPENING_US_CODES, rows),
    }
    out: Dict[str, str] = {}
    for k, miss in need.items():
        if not miss:
            continue
        txt = _tavily_opening_category_digest(k)
        if txt:
            out[k] = txt
    if out:
        report_data["opening_overnight_category_tavily"] = out


def _build_opening_overnight_four_lines_section(report_data: Dict[str, Any]) -> List[str]:
    """
    隔夜指示正文：四类顺序 A50 → 日韩 → 欧洲 → 美股。
    主源失败时用 ``opening_overnight_category_tavily`` 中对应类检索摘要。
    """
    rows = _opening_global_index_rows(report_data)
    tv = report_data.get("opening_overnight_category_tavily")
    if not isinstance(tv, dict):
        tv = {}

    a50_n = _opening_a50_numeric_line(report_data)
    jk_n = _fmt_opening_index_group("日/韩（当日已开盘）", _OPENING_JK_CODES, rows)
    eu_n = _fmt_opening_index_group("欧股（上一交易日收市）", _OPENING_EU_CODES, rows)
    us_n = _fmt_opening_index_group("美股（北京时间当日凌晨时段）", _OPENING_US_CODES, rows)

    def _line(cat: str, numeric: Optional[str], digest_title: str) -> str:
        if numeric:
            return numeric
        raw = tv.get(cat)
        if isinstance(raw, str) and raw.strip():
            if cat == "us":
                refined = _refine_opening_us_tavily_for_dingtalk(
                    raw.strip(), max_chars=480, report_data=report_data
                )
            else:
                refined = _refine_opening_global_digest_for_dingtalk(
                    raw.strip(), max_chars=480, report_data=report_data
                )
            if refined:
                return f"**{digest_title}（检索摘要，非交易所逐点数值）：** {refined}"
        return f"**{digest_title}：** 主源暂不可用（检索未返回有效摘要）"

    return [
        _line("a50", a50_n, "A50期指"),
        _line("jk", jk_n, "日韩"),
        _line("eu", eu_n, "欧洲股市"),
        _line("us", us_n, "美股指数"),
    ]


def _build_opening_overnight_index_lines(report_data: Dict[str, Any]) -> List[str]:
    """四类一行一条：A50 → 日韩 → 欧洲 → 美股（主源失败则该类用 Tavily 或降级文案）。"""
    return _build_opening_overnight_four_lines_section(report_data)


def _build_opening_overnight_outer_lines(report_data: Dict[str, Any]) -> List[str]:
    """
    兼容旧版外盘隔夜展示；四类与 `_build_opening_overnight_index_lines` 同源。
    若四类主源均无有效数值且仅有 ``global_market_digest``，保留「单段摘要 + 脚注」回退。
    """
    rows = _opening_global_index_rows(report_data)
    any_numeric = (
        _opening_a50_numeric_line(report_data) is not None
        or _opening_index_group_available(_OPENING_JK_CODES, rows)
        or _opening_index_group_available(_OPENING_EU_CODES, rows)
        or _opening_index_group_available(_OPENING_US_CODES, rows)
    )
    if not any_numeric:
        gmd = report_data.get("global_market_digest")
        raw_spot = report_data.get("tool_fetch_global_index_spot")
        if not isinstance(gmd, dict) and isinstance(raw_spot, dict):
            gmd = raw_spot.get("global_market_digest")
        overlay = report_data.get("daily_report_overlay")
        if not isinstance(gmd, dict) and isinstance(overlay, dict):
            gmd = overlay.get("global_market_digest")
        if isinstance(gmd, dict):
            summ = str(gmd.get("summary") or "").strip()
            if summ:
                refined = _refine_opening_global_digest_for_dingtalk(
                    summ, max_chars=720, report_data=report_data
                )
                if refined:
                    return [refined, "（摘要替代完整指数表；见每日市场分析报告）"]

    tv = report_data.get("opening_overnight_category_tavily")
    if not isinstance(tv, dict):
        tv = {}
    a50_n = _opening_a50_numeric_line(report_data)
    jk_n = _fmt_opening_index_group("日/韩（当日开盘）", _OPENING_JK_CODES, rows)
    eu_n = _fmt_opening_index_group("欧股（上一交易日收市）", _OPENING_EU_CODES, rows)
    us_n = _fmt_opening_index_group("美股（隔夜）", _OPENING_US_CODES, rows)

    def _ol(cat: str, numeric: Optional[str], digest_title: str) -> str:
        if numeric:
            return numeric
        raw = tv.get(cat)
        if isinstance(raw, str) and raw.strip():
            if cat == "us":
                refined = _refine_opening_us_tavily_for_dingtalk(
                    raw.strip(), max_chars=480, report_data=report_data
                )
            else:
                refined = _refine_opening_global_digest_for_dingtalk(
                    raw.strip(), max_chars=480, report_data=report_data
                )
            if refined:
                return f"**{digest_title}（检索摘要，非交易所逐点数值）：** {refined}"
        return f"**{digest_title}：** 主源暂不可用（检索未返回有效摘要）"

    return [
        _ol("a50", a50_n, "A50期指"),
        _ol("jk", jk_n, "日韩"),
        _ol("eu", eu_n, "欧洲股市"),
        _ol("us", us_n, "美股指数"),
    ]


def _opening_should_emit_hxc_overnight_line(display: str) -> bool:
    """金龙隔夜展示：「获取失败*」类硬失败文案不输出，避免刷屏。"""
    s = str(display or "").strip()
    if not s:
        return False
    if s.startswith("获取失败"):
        return False
    return True


def _build_opening_hot_sector_bullets(report_data: Dict[str, Any]) -> List[str]:
    """开盘/日报：由 tool_sector_heat_score 生成板块热度 bullet（与单元测试约定一致）。"""
    raw = report_data.get("tool_sector_heat_score")
    if not isinstance(raw, dict):
        return []
    d = _as_tool_data_payload(raw)
    if not isinstance(d, dict) or not d.get("sectors"):
        d = raw
    sectors = d.get("sectors")
    if not isinstance(sectors, list) or not sectors:
        return []
    ref = str(report_data.get("sector_heat_ref_trade_date") or "").strip()
    lines: List[str] = []
    if ref and len(ref) == 8 and ref.isdigit():
        lines.append(
            f"- *热度样本日期：{ref[:4]}-{ref[4:6]}-{ref[6:8]}（上一交易日）*"
        )
    lines.append("- **板块热度（涨跌停侧）**")
    for s in sectors[:12]:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        score = s.get("score")
        luc = s.get("limit_up_count")
        phase = str(s.get("phase") or "").strip()
        bits = [name]
        if score is not None:
            try:
                bits.append(f"热度{float(score):.0f}")
            except (TypeError, ValueError):
                bits.append(f"热度{score}")
        if luc is not None:
            try:
                bits.append(f"涨停{int(luc)}")
            except (TypeError, ValueError):
                bits.append(f"涨停{luc}")
        if phase:
            bits.append(phase)
        lines.append("- " + " ".join(bits))
    return lines if len(lines) > 1 else []


def _build_key_levels_lines(report_data: Dict[str, Any]) -> List[str]:
    kl = report_data.get("key_levels")
    if not isinstance(kl, dict):
        raw = report_data.get("tool_compute_index_key_levels")
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            kl = raw
    if not isinstance(kl, dict):
        return []
    data = kl.get("data") if isinstance(kl.get("data"), dict) else kl
    sup = data.get("support")
    res = data.get("resistance")
    lines: List[str] = []
    if isinstance(sup, list) and sup:
        lines.append("支撑：" + " / ".join(str(x) for x in sup[:3]))
    if isinstance(res, list) and res:
        lines.append("压力：" + " / ".join(str(x) for x in res[:3]))
    if data.get("last_close") is not None:
        lines.append(f"昨收参考：{data.get('last_close')}")
    return lines


def _build_announcement_lines(report_data: Dict[str, Any]) -> List[str]:
    ad = _as_tool_data_payload(
        report_data.get("announcement_digest")
        or report_data.get("tool_fetch_announcement_digest")
    )
    if not isinstance(ad, dict):
        return []
    items = ad.get("items")
    if not isinstance(items, list) or not items:
        return []
    lines: List[str] = []
    brief = ad.get("brief_answer") or ad.get("summary")
    if isinstance(brief, str) and brief.strip():
        lines.append(f"公告提要：{brief.strip()[:220]}")
    for i, it in enumerate(items[:6], 1):
        if not isinstance(it, dict):
            continue
        lines.append(f"{i}. {(it.get('title') or '')[:100]} {(it.get('url') or '')[:80]}".strip())
    return lines


def _build_broad_index_impact_hint(report_data: Dict[str, Any]) -> List[str]:
    text_parts: List[str] = []
    ind = _as_tool_data_payload(report_data.get("industry_news") or report_data.get("tool_fetch_industry_news_brief"))
    ann = _as_tool_data_payload(report_data.get("announcement_digest") or report_data.get("tool_fetch_announcement_digest"))
    if isinstance(ind, dict):
        ba = ind.get("brief_answer")
        if isinstance(ba, str) and ba.strip():
            text_parts.append(ba.strip())
        for it in (ind.get("items") or [])[:8]:
            if isinstance(it, dict):
                t = it.get("title")
                if isinstance(t, str) and t.strip():
                    text_parts.append(t.strip())
    if isinstance(ann, dict):
        ba2 = ann.get("brief_answer") or ann.get("summary")
        if isinstance(ba2, str) and ba2.strip():
            text_parts.append(ba2.strip())
        for it in (ann.get("items") or [])[:8]:
            if isinstance(it, dict):
                t2 = it.get("title")
                if isinstance(t2, str) and t2.strip():
                    text_parts.append(t2.strip())
    blob = " ".join(text_parts)
    if not blob:
        return []
    hints: List[str] = []
    if any(k in blob for k in ("芯片", "半导体", "AI", "软件", "光模块", "CPO")):
        hints.append("成长风格线索偏强（创业板/中证500弹性更高）")
    if any(k in blob for k in ("银行", "券商", "保险", "地产", "基建", "煤炭", "石油", "电力")):
        hints.append("价值权重线索偏强（上证50/沪深300承接更直接）")
    if any(k in blob for k in ("消费", "医药", "白酒", "出行", "零售")):
        hints.append("内需消费链有催化，关注沪深300成分中的消费权重股传导")
    if not hints:
        hints.append("行业与公告催化未形成单一主线，维持均衡配置观察。")
    return hints[:2]


def _load_hot_sectors_fallback() -> List[str]:
    try:
        root = Path(__file__).resolve().parents[2]
        p = root / "config" / "hot_sectors.json"
        if not p.exists():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
        sectors = data.get("sectors") if isinstance(data, dict) else None
        if not isinstance(sectors, list):
            return []
        parts: List[str] = []
        for s in sectors[:5]:
            if not isinstance(s, dict):
                continue
            nm = s.get("name") or ""
            etfs = s.get("etf_examples") or []
            if nm:
                tail = f"（ETF: {','.join(str(x) for x in etfs[:2])}）" if etfs else ""
                parts.append(f"{nm}{tail}")
        return parts
    except Exception:
        return []


def _build_sector_rotation_lines(
    report_data: Dict[str, Any],
    *,
    skip_hot_sectors_fallback: bool = False,
) -> List[str]:
    sr = report_data.get("sector_rotation")
    if isinstance(sr, str) and sr.strip():
        return [sr.strip()[:500]]
    if isinstance(sr, dict):
        hint = sr.get("summary") or sr.get("text")
        if isinstance(hint, str) and hint.strip():
            out = [hint.strip()[:500]]
            heat = sr.get("heat") or sr.get("data")
            if heat:
                out.append(_to_pretty_text(heat)[:400])
            return out
        seclist = sr.get("sectors")
        if isinstance(seclist, list) and seclist:
            parts: List[str] = []
            for s in seclist[:10]:
                if not isinstance(s, dict):
                    continue
                nm = str(s.get("name") or "").strip()
                if nm:
                    parts.append(nm)
            if parts:
                return [f"板块轮动（热度）：{'、'.join(parts)}"]
    if skip_hot_sectors_fallback:
        return ["板块与轮动：请结合正文主要 ETF 与指数章节；此处不重复列举配置中的关注板块池。"]
    fb = _load_hot_sectors_fallback()
    if fb:
        return ["关注板块池（config/hot_sectors）："] + [f"- {x}" for x in fb]
    return []


def _build_prediction_review_lines(report_data: Dict[str, Any]) -> List[str]:
    pr_raw = report_data.get("prediction_review")
    pr = _as_tool_data_payload(pr_raw)
    if not isinstance(pr, dict) and isinstance(pr_raw, dict):
        pr = pr_raw
    if not isinstance(pr, dict):
        return []
    rev = pr.get("review")
    if rev is None and isinstance(pr.get("data"), dict):
        rev = pr["data"].get("review")
    if not isinstance(rev, dict):
        return []
    lines = ["昨日预测回顾（粗检）："]
    if rev.get("in_range") is not None:
        lines.append(f"昨预测日内区间是否覆盖现价：{'是' if rev['in_range'] else '否'}")
    if rev.get("record_date"):
        lines.append(f"记录日：{rev['record_date']}")
    return lines


def _format_limitup_after_close_enhanced(
    report_data: Dict[str, Any],
    analysis: Dict[str, Any],
    date_str: Optional[str],
    now: str,
    llm_text: str,
) -> Tuple[str, str]:
    """机构化涨停回马枪盘后：二级标题便于钉钉分段。"""
    title_date = date_str or now[:10]
    title = f"涨停回马枪盘后（增强） - {title_date}"
    if isinstance(llm_text, str) and llm_text.strip():
        body = f"{title}\n\n{llm_text.strip()}"
        body += "\n\n---\n*以上内容仅供研究参考，不构成投资建议。*"
        return title, body.strip()

    lines: List[str] = [title, ""]
    lines.append("## 外盘与大宗")
    gsl = _build_global_spot_lines(report_data)
    mo = _build_market_overview_lines(report_data)
    if gsl:
        for x in gsl:
            lines.append(f"- {x}")
    if mo:
        for x in mo:
            lines.append(f"- {x}")
    ms = _as_tool_data_payload(report_data.get("macro_snapshot"))
    if not ms and report_data.get("macro_commodities"):
        ms = _as_tool_data_payload(report_data.get("macro_commodities"))
    if isinstance(ms, dict) and ms.get("items"):
        fake_rd = dict(report_data)
        fake_rd["macro_snapshot"] = ms
        for x in _build_market_overview_lines(fake_rd):
            if "大宗" in x or "商品" in x or "原油" in x:
                lines.append(f"- {x}")
    lines.append("")
    lines.append("## 要闻与公告")
    pol = _build_policy_news_lines(report_data)
    ind = _build_industry_news_lines(report_data)
    ann = _build_announcement_lines(report_data)
    if pol:
        lines.append("### 政策")
        for x in pol:
            lines.append(f"- {x}")
    else:
        lines.append("- （政策要闻未合并）")
    if ind:
        lines.append("### 行业")
        for x in ind:
            lines.append(f"- {x}")
    else:
        lines.append("- （行业要闻未合并）")
    if ann:
        lines.append("### 公告")
        for x in ann:
            lines.append(f"- {x}")
    lines.append("")
    lines.append("## 资金与关键位")
    kl = _build_key_levels_lines(report_data)
    if kl:
        for x in kl:
            lines.append(f"- {x}")
    lines.append("")
    lines.append("## 隔夜校准与情景")
    for x in _build_overnight_calibration_lines(report_data):
        lines.append(f"- {x}")
    scen_lines = _build_scenario_lines(report_data)
    if scen_lines:
        lines.extend(scen_lines)
    lines.append("")
    lines.append("## 昨日预判回顾")
    prv = _build_prediction_review_lines(report_data)
    if prv:
        lines.extend(prv)
    else:
        lines.append("- （无昨日 prediction_records 或未调用 review）")
    lr = _build_limitup_record_lines(report_data)
    if lr:
        lines.append("")
        lines.append("### 当日观察落盘摘要")
        for x in lr:
            lines.append(f"- {x}")
    lines.append("")
    lines.append("## 涨停回马枪专题")
    lu = report_data.get("limit_up_summary") or report_data.get("limit_up_flow_text")
    if isinstance(lu, str) and lu.strip():
        lines.append(lu.strip()[:4000])
    else:
        for key in ("dragon_tiger", "limit_up_flow", "capital_flow_digest"):
            v = report_data.get(key)
            if isinstance(v, str) and v.strip():
                lines.append(v.strip()[:2000])
                break
        else:
            lines.append("- （请合并龙虎榜/涨停流向正文或 llm_summary）")
    lines.append("")
    lines.append("---")
    lines.append("*以上内容仅供研究参考，不构成投资建议。*")
    return title, "\n".join(lines).strip()


def _build_institutional_extras_lines(*, intraday_allowed: bool = True) -> List[str]:
    lines = [
        "### 情景推演（参考沪深主指 ±0.5% / ±0.2% 粗分档）",
        "- 高开(>0.5%)：关注 5 分钟量能验证，策略偏多但设止损",
        "- 平开(±0.2%)：结构性轮动，结合板块热度与量能",
        "- 低开(<-0.5%)：偏防守，反弹注意减仓节奏",
        "",
    ]
    if intraday_allowed:
        lines.extend(
            [
        "### 盘中时间锚点",
        "- 09:35：开盘 5 分钟量能与方向验证",
        "- 10:30：首小时换手与板块轮动",
        "- 13:30：午后资金回流与再定价",
    ]
        )
    else:
        lines.extend(
            [
                "### 次日时间锚点（非连续竞价时段）",
                "- 09:35：观察开盘 5 分钟量能与方向是否与隔夜信号一致",
                "- 10:30：复核首小时换手与板块轮动是否扩散",
                "- 13:30：评估午后资金回流与再定价强弱",
            ]
        )
    return lines


def _dingtalk_trim(text: str, max_len: int = 20000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 40] + "\n\n…（正文已截断，详见 data/ 落盘）"


def _append_failure_log(event: Dict[str, Any]) -> Optional[str]:
    """将失败诊断写入本地 jsonl，便于 cron 排障。"""
    try:
        root = Path(__file__).resolve().parents[2]
        log_dir = root / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        p = log_dir / "daily_report_failures.jsonl"
        rec = dict(event)
        rec["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return str(p)
    except Exception:
        return None


def _send_failure_alert_to_dingtalk(
    *,
    title: str,
    reason: str,
    detail_lines: List[str],
    mode: str,
    webhook_url: Optional[str],
    secret: Optional[str],
    keyword: Optional[str],
) -> Dict[str, Any]:
    """在同一钉钉渠道发送失败告警，方便第一时间排障。"""
    try:
        from .send_dingtalk_message import tool_send_dingtalk_message

        lines = [f"【失败告警】{title}", "", f"- 原因：{reason}"]
        for ln in detail_lines[:12]:
            lines.append(f"- {ln}")
        msg = "\n".join(lines)
        return tool_send_dingtalk_message(
            message=msg,
            title=f"{title}（失败告警）",
            webhook_url=webhook_url,
            secret=secret,
            keyword=keyword,
            mode=mode,
            split_markdown_sections=False,
        )
    except Exception as e:
        return {"success": False, "message": f"failure alert send exception: {e}"}


def _build_trend_lines(report_data: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    # 兼容不同字段命名
    trend = report_data.get("overall_trend") or report_data.get("market_trend")
    strength = report_data.get("trend_strength")

    ad = report_data.get("analysis_data")
    if not isinstance(ad, dict):
        ad = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
    if isinstance(ad, dict):
        trend = trend or ad.get("final_trend") or ad.get("overall_trend") or ad.get("after_close_trend")
        if strength is None:
            strength = ad.get("final_strength") or ad.get("trend_strength")

    if trend is not None or strength is not None:
        strength_s = None
        try:
            if strength is not None:
                strength_s = f"{float(strength):.3f}"
        except Exception:
            strength_s = str(strength)
        if strength_s:
            lines.append(f"趋势：{trend or 'N/A'}（强度 {strength_s}）")
        else:
            lines.append(f"趋势：{trend or 'N/A'}")

    # 盘前策略（opening_strategy）
    if isinstance(ad, dict):
        opening = ad.get("opening_strategy")
        if isinstance(opening, dict):
            direction = opening.get("direction")
            position_size = opening.get("position_size")
            suggest_call = opening.get("suggest_call")
            suggest_put = opening.get("suggest_put")
            hint: List[str] = []
            if direction:
                hint.append(f"方向 {direction}")
            if position_size:
                hint.append(f"仓位 {position_size}")
            if suggest_call is not None or suggest_put is not None:
                hint.append(f"Call {'✅' if suggest_call else '❌'} / Put {'✅' if suggest_put else '❌'}")
            if hint:
                lines.append("开盘策略： " + "，".join(hint))
    return lines


def _build_volatility_lines(report_data: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    vol = report_data.get("volatility")
    # 有些工作流会直接把格式化文本塞到 volatility_prediction
    vol_txt = report_data.get("volatility_prediction")
    if isinstance(vol_txt, str) and vol_txt.strip() and not isinstance(vol, dict):
        # 取前几行，避免过长刷屏
        flat = _flatten_md_headers_in_embedded_report_text(vol_txt.strip())
        cleaned: List[str] = []
        for ln in flat.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("|") or s.startswith("------"):
                continue
            cleaned.append(s)
            if len(cleaned) >= 10:
                break
        lines.append("日频全日区间（摘要）：")
        lines.extend(cleaned)
        return lines

    if isinstance(vol, dict):
        cp = vol.get("current_price")
        upper = vol.get("upper")
        lower = vol.get("lower")
        rng = vol.get("range_pct")
        conf = vol.get("confidence")
        parts: List[str] = []
        cp_s = _fmt_num(cp, 4)
        if cp_s:
            parts.append(f"当前 {cp_s}")
        up_s = _fmt_num(upper, 4)
        lo_s = _fmt_num(lower, 4)
        if up_s and lo_s:
            parts.append(f"区间 {lo_s} ~ {up_s}")
        rng_s = _fmt_pct(rng)
        if rng_s:
            parts.append(f"范围 {rng_s}")
        try:
            if conf is not None:
                parts.append(f"置信度 {float(conf):.2f}")
        except Exception:
            pass
        if parts:
            lines.append("波动区间： " + "，".join(parts))
    else:
        # 兜底：顶层 predicted_volatility / predicted_range
        pv = report_data.get("predicted_volatility")
        pr = report_data.get("predicted_range")
        parts2: List[str] = []
        if pv is not None:
            parts2.append(f"predicted_volatility={pv}")
        if pr is not None:
            parts2.append(f"predicted_range={pr}")
        if parts2:
            lines.append("波动预测： " + "，".join(parts2))

    return lines


def _row_price(row: Dict[str, Any]) -> Optional[float]:
    for k in ("price", "current_price", "last_price", "latest_price", "close", "last_close"):
        v = row.get(k)
        try:
            if v is not None:
                return float(v)
        except Exception:
            continue
    return None


def _build_signals_lines(report_data: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    sig = report_data.get("signals")
    if not (isinstance(sig, list) and sig):
        sig_tool = report_data.get("tool_generate_option_trading_signals")
        if isinstance(sig_tool, dict):
            td = sig_tool.get("data")
            if isinstance(td, dict):
                if isinstance(td.get("signals"), list) and td.get("signals"):
                    sig = td.get("signals")
                else:
                    # 无交易信号时也给结构化状态，避免固定占位句
                    st = td.get("signal_type")
                    conf = td.get("signal_confidence")
                    strength = td.get("signal_strength")
                    sym = td.get("symbol") or "510300"
                    parts: List[str] = []
                    if st:
                        parts.append(f"信号类型 {st}")
                    if strength is not None:
                        parts.append(f"强度 {strength}")
                    if conf is not None:
                        parts.append(f"置信度 {conf}")
                    if parts:
                        lines.append(f"- {sym}：{'，'.join(parts)}")
                    msg = sig_tool.get("message")
                    if isinstance(msg, str) and msg.strip():
                        lines.append(f"- 状态：{msg.strip()[:120]}")
    if isinstance(sig, list) and sig:
        lines.append("信号：")
        for it in sig[:6]:
            if isinstance(it, dict):
                st = it.get("signal_type") or it.get("type") or it.get("action") or "signal"
                sym = it.get("symbol") or it.get("etf_symbol") or it.get("underlying") or ""
                strength = it.get("signal_strength") or it.get("strength")
                extra = []
                if strength is not None:
                    extra.append(f"强度={strength}")
                reason = it.get("reason") or it.get("desc")
                if isinstance(reason, str) and reason.strip():
                    extra.append(reason.strip()[:80])
                tail = ("，" + "，".join(extra)) if extra else ""
                lines.append(f"- {st} {sym}{tail}".strip())
            else:
                lines.append(f"- {str(it)[:120]}")
    return lines


def _resolve_trend_fields(
    report_data: Dict[str, Any], analysis: Dict[str, Any]
) -> Tuple[Optional[Any], Optional[Any]]:
    """
    统一解析「整体趋势 / 趋势强度」：兼容原系统字段与简化开盘 summary（market_sentiment、sentiment_score、强弱计数）。
    """
    overall_trend = (
        report_data.get("overall_trend")
        or analysis.get("final_trend")
        or analysis.get("overall_trend")
        or analysis.get("after_close_trend")
        or report_data.get("market_trend")
    )
    strength = report_data.get("trend_strength")
    if strength is None:
        strength = analysis.get("final_strength") or analysis.get("trend_strength")

    summ = analysis.get("summary") if isinstance(analysis.get("summary"), dict) else {}
    if overall_trend is None:
        overall_trend = summ.get("market_sentiment")
    if overall_trend is None:
        sc = int(summ.get("strong_count") or 0)
        wc = int(summ.get("weak_count") or 0)
        edge = sc + wc
        if edge > 0:
            if sc > wc:
                overall_trend = "偏强"
            elif wc > sc:
                overall_trend = "偏弱"
            else:
                overall_trend = "中性"
    if strength is None:
        strength = summ.get("sentiment_score")
    if strength is None:
        sc = int(summ.get("strong_count") or 0)
        wc = int(summ.get("weak_count") or 0)
        edge = sc + wc
        if edge > 0:
            strength = (sc - wc) / edge
    if strength is None:
        rm = analysis.get("report_meta") if isinstance(analysis.get("report_meta"), dict) else {}
        mss = rm.get("market_sentiment_score")
        if isinstance(mss, (int, float)):
            strength = mss
    return overall_trend, strength


def _allows_intraday_wording(report_data: Dict[str, Any]) -> bool:
    ts = report_data.get("trading_status")
    if isinstance(ts, dict):
        d = ts.get("data")
        if isinstance(d, dict) and d.get("allows_intraday_continuous_wording") is False:
            return False
    regime = str(report_data.get("a_share_regime_note") or "").strip()
    if "收盘后" in regime or "连续竞价已结束" in regime or "禁止将收盘数据叙述为" in regime:
        return False
    return True


def _tail_option_line(name: str, blob: Any) -> Optional[str]:
    if not isinstance(blob, dict):
        return None
    action = str(blob.get("action") or "").strip()
    cap = blob.get("max_position_pct")
    if not action:
        return None
    try:
        cap_txt = f"{float(cap):.0f}%"
    except Exception:
        cap_txt = str(cap) if cap is not None else "N/A"
    return f"- **{name}：** {_tail_action_label(action)}（仓位上限 {cap_txt}）"


def _tail_action_label(action: str) -> str:
    m = {
        "hold": "持有",
        "buy_light": "轻仓买入",
        "buy_split": "分批买入",
        "reduce": "减仓",
        "exit_wait": "退出观望",
    }
    return m.get(str(action).strip(), str(action))


def _tail_layer_label(layer_name: str) -> str:
    m = {
        "cycle": "趋势判断（大势）",
        "timing": "择时信号（节奏）",
        "risk": "风控约束（门槛）",
    }
    return m.get(str(layer_name).strip(), str(layer_name))


def _format_tail_session_report(
    report_data: Dict[str, Any],
    title: str,
    now: str,
) -> Tuple[str, str]:
    analysis = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
    snap = report_data.get("tail_session_snapshot") if isinstance(report_data.get("tail_session_snapshot"), dict) else {}
    etf_code = str(snap.get("etf_code") or "").strip()
    index_symbol = str(analysis.get("index_symbol") or "").strip().upper()
    if index_symbol == "^IXIC":
        index_label = "纳斯达克指数"
    elif index_symbol == "^N225":
        index_label = "日经225指数"
    else:
        index_label = index_symbol or "指数"
    non_trading = bool(report_data.get("non_trading_calendar_day"))
    trade_date = str(report_data.get("trade_date") or report_data.get("date") or "").strip()
    monitor_ctx = report_data.get("monitor_context") if isinstance(report_data.get("monitor_context"), dict) else {}
    monitor_label = str(monitor_ctx.get("monitor_label") or "").strip()
    subtitle = "## 📊 交易时段多角度建议报告" if not non_trading else "## 📊 多角度建议（非交易日复盘口径）"
    if monitor_label:
        subtitle = f"{subtitle}（{monitor_label}）"
    lines: List[str] = [title, "", subtitle, f"**分析时间：** {now}"]
    if non_trading and trade_date:
        lines.append(f"**数据日期：** {trade_date}（最近交易日）")
    lines.append("")

    monitor_ctx = report_data.get("monitor_context") if isinstance(report_data.get("monitor_context"), dict) else {}
    signal_board = analysis.get("signal_board") if isinstance(analysis.get("signal_board"), dict) else {}
    risk_gate = analysis.get("risk_gate") if isinstance(analysis.get("risk_gate"), dict) else {}
    range_prediction = analysis.get("range_prediction") if isinstance(analysis.get("range_prediction"), dict) else {}
    monitor_projection = analysis.get("monitor_projection") if isinstance(analysis.get("monitor_projection"), dict) else {}

    lines.append("### 一、时点快照")
    if monitor_ctx:
        lines.append(
            f"- 监控点：{monitor_ctx.get('monitor_point') or 'N/A'}（{monitor_ctx.get('monitor_label') or 'N/A'}） / 覆盖窗口：{monitor_ctx.get('target_window') or 'N/A'}"
        )
    lines.append(
        f"- {etf_code or 'N/A'} 现价 {_fmt_num(snap.get('latest_price'), 3) or 'N/A'} / IOPV {_fmt_num(snap.get('iopv'), 3) or 'N/A'} / 溢价率 {_fmt_pct(snap.get('premium_pct')) or 'N/A'}"
    )
    lines.append(f"- 数据质量：{snap.get('data_quality') or 'N/A'}")
    if snap.get("iopv_source"):
        lines.append(f"- IOPV来源：{snap.get('iopv_source')}")
    if snap.get("iopv_source") == "estimated":
        lines.append(
            f"- 估算通道：IOPV估算 {_fmt_num(snap.get('iopv_est'), 3) or 'N/A'} / 溢价估算 {_fmt_pct(snap.get('premium_est')) or 'N/A'} / 置信度 {_fmt_num(snap.get('est_confidence'), 2) or 'N/A'}"
        )
    if snap.get("iopv_source") == "manual":
        lines.append(f"- 人工IOPV日期：{snap.get('manual_iopv_updated_date') or 'N/A'}")
    amt = _safe_float(snap.get("amount"))
    if amt is not None:
        lines.append(f"- 成交额（代理流动性）：{amt/1e8:.2f} 亿元")
    lines.append("")

    lines.append("### 二、本时点模板焦点")
    focus = monitor_ctx.get("template_focus") if isinstance(monitor_ctx.get("template_focus"), list) else []
    if focus:
        for item in focus[:4]:
            lines.append(f"- {item}")
    else:
        lines.append("- 区间预测与风险门槛联动")
    lines.append("")

    lines.append("### 三、区间预测（操作参考主轴）")
    core = range_prediction.get("core_range") if isinstance(range_prediction.get("core_range"), list) else None
    safe = range_prediction.get("safe_range") if isinstance(range_prediction.get("safe_range"), list) else None
    if core and len(core) == 2:
        lines.append(f"- 核心参考区间：[{_fmt_num(core[0], 4)}, {_fmt_num(core[1], 4)}]（宽度 {range_prediction.get('core_width_pct', 'N/A')}%）")
    if safe and len(safe) == 2:
        lines.append(f"- 安全缓冲区间：[{_fmt_num(safe[0], 4)}, {_fmt_num(safe[1], 4)}]（宽度 {range_prediction.get('safe_width_pct', 'N/A')}%）")
    lines.append(f"- 区间置信度：{_fmt_num(signal_board.get('confidence'), 2) or 'N/A'}")
    lines.append("")

    lines.append("### 四、时点专项预测")
    proj_label = str(monitor_projection.get("projection_label") or "分时区间预测")
    lines.append(f"- 预测对象：{proj_label}")
    key_levels = monitor_projection.get("key_levels") if isinstance(monitor_projection.get("key_levels"), list) else []
    if key_levels:
        for kv in key_levels[:4]:
            if isinstance(kv, dict):
                lines.append(f"- {kv.get('name')}: {_fmt_num(kv.get('value'), 4) or 'N/A'}")
    if monitor_projection.get("safe_low") is not None and monitor_projection.get("safe_high") is not None:
        lines.append(
            f"- 缓冲边界：[{_fmt_num(monitor_projection.get('safe_low'), 4)}, {_fmt_num(monitor_projection.get('safe_high'), 4)}]"
        )
    lines.append("")

    lines.append("### 五、周期与技术状态")
    lines.append(
        f"- 指数（参考）：{index_label} 收盘 {(_fmt_num(analysis.get('index_close'), 2) or 'N/A')}，日涨跌 {_fmt_pct(analysis.get('index_day_ret_pct')) or 'N/A'}"
    )
    streak_days = analysis.get("streak_days")
    streak_ret_raw = _safe_float(analysis.get("streak_return_pct"))
    streak_ret = _fmt_pct(streak_ret_raw)
    streak_txt = "连平天数 N/A"
    try:
        sd = int(streak_days)
        if sd > 0:
            streak_txt = f"连涨天数 {sd}"
            if streak_ret:
                streak_txt += f"，累计涨 {streak_ret}"
        elif sd < 0:
            streak_txt = f"连跌天数 {abs(sd)}"
            if streak_ret_raw is not None:
                streak_txt += f"，累计跌 {_fmt_pct(abs(streak_ret_raw)) or 'N/A'}"
        else:
            streak_txt = "连平天数 0"
    except Exception:
        streak_txt = f"连涨跌天数 {streak_days}"
    lines.append(
        f"- 指数技术状态（{index_label}）：MA25 偏离 {_fmt_pct(analysis.get('ma25_dev_pct')) or 'N/A'}，RSI14 {_fmt_num(analysis.get('rsi14'), 2) or 'N/A'}，{streak_txt}"
    )
    lines.append("")

    lines.append("### 六、SignalBoard / RiskGate")
    lines.append(
        f"- SignalBoard：方向分 {_fmt_num(signal_board.get('direction_score'), 2) or 'N/A'}，强度分 {_fmt_num(signal_board.get('strength_score'), 2) or 'N/A'}，期货状态 {signal_board.get('futures_status') or 'N/A'}"
    )
    lines.append(
        f"- RiskGate：流动性(成交额) {(_fmt_num((_safe_float(risk_gate.get('liquidity_amount')) or 0.0)/1e8, 2) + '亿') if risk_gate.get('liquidity_amount') is not None else 'N/A'}，汇率风险倍率 {_fmt_num(risk_gate.get('fx_risk_multiplier'), 2) or 'N/A'}，质量 {risk_gate.get('quality_status') or 'N/A'}"
    )
    if risk_gate.get("action_state"):
        lines.append(f"- 动作矩阵状态：{risk_gate.get('action_state')}")
    hits = risk_gate.get("gates_triggered") if isinstance(risk_gate.get("gates_triggered"), list) else []
    if hits:
        lines.append(f"- 门槛触发：{', '.join(str(x) for x in hits)}")
    lines.append("")

    lines.append("### 七、分层建议（不合成单一结论）")
    layer_outputs = analysis.get("layer_outputs") if isinstance(analysis.get("layer_outputs"), list) else []
    for it in layer_outputs:
        if not isinstance(it, dict):
            continue
        layer_name = str(it.get("layer") or "layer")
        opts = it.get("options") if isinstance(it.get("options"), list) else []
        rs = it.get("reasons") if isinstance(it.get("reasons"), list) else []
        hit = it.get("gate_hits") if isinstance(it.get("gate_hits"), list) else []
        opts_txt = ", ".join(_tail_action_label(str(x)) for x in opts) if opts else "N/A"
        lines.append(f"- **{_tail_layer_label(layer_name)}：** 选项 {opts_txt}")
        if rs:
            lines.append(f"  - 原因：{'; '.join(str(x) for x in rs[:3])}")
        if hit:
            lines.append(f"  - 闸门触发：{', '.join(str(x) for x in hit)}")
    if isinstance(analysis.get("indicator_opinion"), str) and analysis.get("indicator_opinion").strip():
        lines.append(f"- **指标结论：** {analysis.get('indicator_opinion').strip()}")
    lines.append("")

    lines.append("### 八、用户可选路径")
    options = analysis.get("decision_options") if isinstance(analysis.get("decision_options"), dict) else {}
    l1 = _tail_option_line("保守", options.get("conservative"))
    l2 = _tail_option_line("中性", options.get("neutral"))
    l3 = _tail_option_line("积极", options.get("aggressive"))
    if l1:
        lines.append(l1)
    if l2:
        lines.append(l2)
    if l3:
        lines.append(l3)
    conflicts = options.get("layer_conflicts") if isinstance(options.get("layer_conflicts"), dict) else {}
    if conflicts:
        c_opts = conflicts.get("cycle_options") if isinstance(conflicts.get("cycle_options"), list) else []
        t_opts = conflicts.get("timing_options") if isinstance(conflicts.get("timing_options"), list) else []
        r_opts = conflicts.get("risk_options") if isinstance(conflicts.get("risk_options"), list) else []
        lines.append("- 层间分歧：")
        c_txt = ", ".join(_tail_action_label(str(x)) for x in c_opts) if c_opts else "N/A"
        t_txt = ", ".join(_tail_action_label(str(x)) for x in t_opts) if t_opts else "N/A"
        r_txt = ", ".join(_tail_action_label(str(x)) for x in r_opts) if r_opts else "N/A"
        lines.append(f"  - 趋势判断（大势）: {c_txt}")
        lines.append(f"  - 择时信号（节奏）: {t_txt}")
        lines.append(f"  - 风控约束（门槛）: {r_txt}")
    lines.append("")

    lines.append("### 九、风险提示与执行摩擦")
    notices = analysis.get("risk_notices") if isinstance(analysis.get("risk_notices"), list) else []
    if notices:
        for n in notices[:8]:
            lines.append(f"- {n}")
    else:
        lines.append("- 暂无触发的额外风险提示。")
    if amt is not None and amt <= 2e7:
        lines.append("- 尾盘成交额偏低，存在滑点与成交冲击，建议被动挂单或缩小单次交易量。")
    lines.append("")

    lines.append("### 十、用户决策声明")
    lines.append(f"- {analysis.get('user_decision_note') or '本系统仅提供多视角信息，不替代你的最终交易决策。'}")
    lines.append("---")
    lines.append(f"*分析完成时间：{now}*")
    return title, _dingtalk_trim("\n".join(lines).strip())


def _format_daily_report(
    report_data: Dict[str, Any],
    report_date: Optional[str],
    _timing_out: Optional[Dict[str, float]] = None,
) -> Tuple[str, str]:
    rt = _detect_report_type(report_data)

    analysis: Dict[str, Any] = {}
    if isinstance(report_data.get("analysis"), dict):
        analysis = report_data.get("analysis", {})  # type: ignore[assignment]
    elif isinstance(report_data.get("analysis_data"), dict):
        analysis = report_data.get("analysis_data", {})  # type: ignore[assignment]

    # 日期/时间
    date_str = None
    for k in ("date", "trade_date"):
        v = report_data.get(k)
        if isinstance(v, str) and v.strip():
            date_str = v.strip()
            break
    if not date_str:
        v = analysis.get("date")
        if isinstance(v, str) and v.strip():
            date_str = v.strip()
    if report_date:
        date_str = report_date

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generated_at = report_data.get("generated_at")
    if isinstance(generated_at, str) and generated_at.strip():
        now = generated_at.strip()[:19]

    # 标题（尽量贴近原系统/示例文案）
    if rt == "before_open":
        title = "开盘前市场趋势分析报告"
        subtitle = "## 📊 开盘前市场趋势分析报告"
    elif rt in ("opening", "opening_market"):
        variant = str(report_data.get("opening_report_variant") or "legacy").strip().lower()
        if variant == "realtime":
            title = "开盘实盘行情报告"
            subtitle = "## 📊 开盘实盘行情报告"
        else:
            title = "盘前行情分析报告"
            subtitle = "## 📊 盘前行情分析报告"
    elif rt == "after_close":
        title = "盘后市场复盘报告"
        subtitle = "## 📊 盘后市场复盘报告"
    elif rt == "tail_session":
        snap = report_data.get("tail_session_snapshot") if isinstance(report_data.get("tail_session_snapshot"), dict) else {}
        etf_code = str(snap.get("etf_code") or "").strip()
        if etf_code == "513300":
            title = "纳斯达克ETF华夏监控报告"
            subtitle = "## 📊 纳斯达克ETF华夏监控报告"
        else:
            title = "日经225ETF监控报告"
            subtitle = "## 📊 日经225ETF监控报告"
    elif rt == "etf_rotation_research":
        title = "ETF 轮动研究报告"
        subtitle = "## 📊 ETF 轮动研究报告"
    else:
        title = "市场日报"
        subtitle = "## 📊 市场日报"

    if date_str and rt not in ("before_open",):
        title = f"{title} - {date_str}"

    # LLM摘要（优先使用已有 llm_summary；缺失时再尝试调用一次 LLM）
    llm_text = _extract_llm_summary(report_data)
    if not llm_text:
        # 复用 Prompt_config.yaml：用相同 analysis_type 生成摘要
        _t_llm0 = time.perf_counter() if _timing_out is not None else None
        try:
            from src.config_loader import load_system_config
            from src.llm_enhancer import enhance_with_llm

            cfg = load_system_config(use_cache=True)
            analysis_type = "default"
            if rt == "before_open":
                analysis_type = "before_open"
            elif rt in ("opening", "opening_market"):
                analysis_type = "opening_market"
            elif rt == "after_close":
                analysis_type = "after_close"

            # 将日报上下文一起喂给 LLM（更接近“通知”生成，而不只是单一模块摘要）
            payload = {
                "report_type": rt,
                "analysis": analysis,
                "market_overview": report_data.get("market_overview"),
                "volatility": report_data.get("volatility"),
                "intraday_range": report_data.get("intraday_range"),
                "policy_news": report_data.get("policy_news"),
                "capital_flow": report_data.get("capital_flow"),
                "macro_snapshot": report_data.get("macro_snapshot"),
                "overnight_digest": report_data.get("overnight_digest"),
                "announcement_digest": report_data.get("announcement_digest"),
                "key_levels": report_data.get("key_levels"),
                "sector_rotation": report_data.get("sector_rotation"),
                "prediction_review": report_data.get("prediction_review"),
            }
            llm_text, _ = enhance_with_llm(payload, analysis_type=analysis_type, config=cfg)
        except Exception:
            llm_text = ""
        finally:
            if _timing_out is not None and _t_llm0 is not None:
                _timing_out["format_llm_enhance_s"] = time.perf_counter() - _t_llm0
    elif _timing_out is not None:
        _timing_out["format_llm_enhance_s"] = 0.0

    if rt == "limitup_after_close_enhanced":
        return _format_limitup_after_close_enhanced(
            report_data, analysis, date_str, now, llm_text or ""
        )

    # ETF轮动研究：优先直接使用已生成的研究摘要，避免误落入“市场日报/N-A趋势”通用模板。
    if rt == "etf_rotation_research" and llm_text:
        lines = [title, "", subtitle]
        if date_str:
            lines.append(f"**日期：** {date_str}")
        lines.append(f"**分析时间：** {now}")
        lines.append("")
        lines.append(llm_text.strip())
        lines.append("")
        lines.append(f"*分析完成时间：{now}*")
        return title, _dingtalk_trim("\n".join(lines).strip())

    # 关键指标（尽量结构化展示，不输出原始 dict）
    overall_trend, strength = _resolve_trend_fields(report_data, analysis)

    opening_strategy = analysis.get("opening_strategy") if isinstance(analysis.get("opening_strategy"), dict) else {}
    a50_change = analysis.get("a50_change")
    hxc_change = analysis.get("hxc_change")
    a50_status = analysis.get("a50_status")
    hxc_status = analysis.get("hxc_status")
    a50_reason = analysis.get("a50_reason")
    hxc_reason = analysis.get("hxc_reason")

    lines: List[str] = []
    lines.append(title)
    lines.append("")
    lines.append(subtitle)
    if date_str and rt not in ("opening", "opening_market", "before_open"):
        lines.append(f"**日期：** {date_str}")
    lines.append(f"**分析时间：** {now}")
    lines.append("")

    # 每日市场分析（daily_market/daily_report）：固定长版收评体，避免回退到通用短模板
    if rt in ("daily_market", "daily_report"):
        title = f"每日市场分析报告（A股·宽基ETF） - {date_str or now[:10].replace('-', '')}"
        lines = [title, ""]
        lines.append(f"**数据日期：** {date_str or now[:10].replace('-', '')}")
        lines.append(f"**分析时间：** {now}")
        lines.append("")
        lines.append("*收评体 · 研究参考非投资建议*")
        lines.append("")

        lines.append("## 执行摘要")
        if isinstance(strength, (int, float)):
            lines.append(f"- 整体趋势 **{overall_trend if overall_trend is not None else 'N/A'}**（强度 {float(strength):.2f}）")
        else:
            lines.append(f"- 整体趋势 **{overall_trend if overall_trend is not None else 'N/A'}**（强度 {strength if strength is not None else 'N/A'}）")
        flow_frag = _capital_flow_exec_summary_fragment(report_data)
        if flow_frag:
            lines.append(f"- 资金流向：{flow_frag}")
        lines.append("")

        lines.append("## 大盘与量能")
        mo_lines = _build_market_overview_lines(report_data)
        volm_lines = _build_a_share_volume_lines(report_data)
        if mo_lines:
            for ln in mo_lines:
                lines.append(f"- {ln}")
            if _daily_market_outer_overview_is_research_digest(report_data, mo_lines):
                # 综述单行已在括号内标注「检索摘要归纳」时不重复脚注
                if not (mo_lines and "检索摘要归纳" in (mo_lines[0] or "")):
                    lines.append("- （检索摘要归纳，非交易所逐指数实时行情）")
            else:
                lines.append("- （外盘：注册工具拉取；非连续竞价时段为最近可用收盘/日线口径）")
        else:
            lines.append("- 外盘/指数概览暂缺。")
        if volm_lines:
            for ln in volm_lines:
                lines.append(f"- {ln}")
        else:
            lines.append("- A股量能快照暂缺（建议补采 tool_fetch_index_data(data_type='realtime')）。")
        lines.append("")

        lines.append("## 主要 ETF 及预警股票池")
        etf_lines = _build_daily_market_etf_universe_lines(report_data, analysis)
        if etf_lines:
            for ln in etf_lines[:12]:
                lines.append(ln)
        else:
            lines.append("- 宽基ETF实时快照暂缺。")
        lines.append("")

        lines.append("## 结构与主线")
        if overall_trend is not None:
            try:
                lines.append(f"- 趋势：{overall_trend}（强度 {float(strength):.3f}）")
            except Exception:
                lines.append(f"- 趋势：{overall_trend}（强度 {strength}）")
        else:
            lines.append("- 趋势：N/A")
        lines.append("")

        lines.append("## 板块与题材")
        hot_lines = _build_opening_hot_sector_bullets(report_data)
        if hot_lines:
            lines.extend(hot_lines[:14])
        else:
            sec_lines = _build_sector_rotation_lines(report_data, skip_hot_sectors_fallback=True)
            if sec_lines:
                for ln in sec_lines[:10]:
                    lines.append(f"- {ln}")
            else:
                lines.append("- 板块热度暂缺。")
        lines.append("")

        lines.append("## 资金流向专题")
        cf_lines = _build_daily_capital_flow_topic_lines(report_data)
        if cf_lines:
            lines.extend(cf_lines)
            if _daily_capital_flow_topic_has_registered_flow_tools(report_data):
                lines.append(
                    "- 扩展查阅（与上方工具口径同属东财/行业主力维度，供交叉核对）："
                    "https://data.eastmoney.com/zjlx/dpzjlx.html · "
                    "https://data.eastmoney.com/bkzj/jlr.html · "
                    "https://data.eastmoney.com/bkzj/hy.html"
                )
        else:
            lines.append("- 资金流向专题暂缺。")
        lines.append("")

        lines.append("## 信息面")
        pol = _build_policy_news_lines(report_data, opening_prefer_cn_brief=True)
        ann = _build_announcement_lines(report_data)
        if pol:
            lines.append("- **政策**")
            for ln in pol[:8]:
                lines.append(f"  - {ln}")
        ind = _build_industry_news_lines(report_data)
        if ind:
            lines.append("- **行业**")
            for ln in ind[:6]:
                lines.append(f"  - {ln}")
        elif pol or ann:
            lines.append("- **行业**")
            tib = report_data.get("industry_news") or report_data.get("tool_fetch_industry_news_brief")
            if isinstance(tib, dict) and tib.get("success") is False:
                msg = str(tib.get("message") or tib.get("error") or "未知")[:160]
                lines.append(f"  - 行业要闻暂不可用：{msg}")
            else:
                lines.append(
                    "  - 当日未检索到有效行业要闻条目（检索结果为空或过滤后为空；宽基映射仍可能来自政策/公告文本）。"
                )
        if ann:
            lines.append("- **公告**")
            for ln in ann[:6]:
                lines.append(f"  - {ln}")
        hints = _build_broad_index_impact_hint(report_data)
        if hints:
            lines.append("- **宽基影响映射**")
            for ln in hints[:2]:
                lines.append(f"  - {ln}")
        if not (pol or ind or ann):
            fb = _build_info_fallback_lines_from_context_cache(max_lines=2)
            if fb:
                lines.append("- 信息面主源暂缺，以下为最近分析缓存摘要：")
                for ln in fb:
                    lines.append(f"  - {ln}")
            else:
                lines.append("- 信息面数据暂缺。")
            lines.append("")

        lines.append("## 外围与大宗")
        g_lines = _build_global_spot_lines(report_data)
        if g_lines:
            for ln in g_lines:
                lines.append(f"- {ln}")
        if mo_lines:
            g0 = g_lines[0] if g_lines else ""
            m0 = mo_lines[0]
            if isinstance(g0, str) and isinstance(m0, str):
                g_norm = g0.split("：", 1)[-1].strip()
                m_norm = m0.split("：", 1)[-1].strip()
                if m_norm and g_norm and m_norm != g_norm and m_norm not in g_norm and g_norm not in m_norm:
                    lines.append(f"- 检索总览：{m0}")
            else:
                lines.append(f"- 检索总览：{m0}")
        lines.append("")

        lines.append("## 波动与关键位")
        v_lines = _build_volatility_lines(report_data)
        if v_lines:
            for ln in v_lines[:20]:
                lines.append(f"- {ln}")
        kl_lines = _build_key_levels_lines(report_data)
        if kl_lines:
            for ln in kl_lines:
                lines.append(f"- {ln}")
        lines.append("")

        lines.append("## 信号与纪律")
        sig_lines = _build_signals_lines(report_data)
        if sig_lines:
            lines.extend(sig_lines[:12])
        else:
            sig_tool = report_data.get("tool_generate_option_trading_signals")
            msg = ""
            if isinstance(sig_tool, dict):
                raw_msg = sig_tool.get("message")
                if isinstance(raw_msg, str):
                    msg = raw_msg.strip()
            if msg:
                lines.append(f"- 当前未触发可执行信号（{msg[:100]}）。")
            else:
                lines.append("- 当前未触发可执行信号；维持规则化观察与仓位纪律。")
        lines.append("")

        lines.append("## 展望与风险")
        next_bias = analysis.get("next_day_outlook") if isinstance(analysis, dict) else None
        if isinstance(next_bias, str) and next_bias.strip():
            lines.append(f"- **次日观察：** {next_bias.strip()}")
        else:
            lines.append("- **次日观察：** 暂无明确方向，关注量价与外盘共振。")
        lines.append("")

        lines.append("## 数据可信度与审计")
        stale = report_data.get("data_stale_warning")
        if not stale and isinstance(analysis, dict):
            stale = analysis.get("data_stale_warning")
        if isinstance(stale, str) and stale.strip():
            lines.append(stale.strip())
        gate = report_data.get("daily_report_gate")
        if isinstance(gate, dict):
            miss = gate.get("missing_fields")
            if isinstance(miss, list) and miss:
                lines.append("- 采集缺口：" + ",".join(str(x) for x in miss))
        errs = report_data.get("runner_errors")
        if isinstance(errs, list) and errs:
            brief: List[str] = []
            for e in errs[:3]:
                if isinstance(e, dict):
                    step = str(e.get("step") or "unknown")
                    msg = str(e.get("error") or e.get("message") or "error")
                    brief.append(f"{step}: {msg}")
            if brief:
                lines.append("- 采集告警：" + " | ".join(brief))
        degraded, missing = _assess_daily_report_completeness(report_data, analysis)
        status = "DEGRADED" if degraded else "OK"
        miss = ",".join(missing) if missing else "NONE"
        lines.append("")
        lines.append(f"`DAILY_REPORT_STATUS={status}; MISSING_FIELDS={miss}`")
        lines.append("")
        lines.append("---")
        lines.append(f"*分析完成时间：{now}*")
        return title, _dingtalk_trim("\n".join(lines).strip())

    if rt == "tail_session":
        return _format_tail_session_report(report_data, title, now)

    # 开盘行情分析（opening）：legacy=盘前版式，realtime=实盘版式
    if rt in ("opening", "opening_market"):
        variant = str(report_data.get("opening_report_variant") or "legacy").strip().lower()
        if variant != "realtime":
            lines.append("### 一、晨间结论")
            lines.append(f"- **整体趋势：** {overall_trend if overall_trend is not None else 'N/A'}")
            try:
                lines.append(
                    f"- **趋势强度：** {float(strength):.2f}"
                    if strength is not None
                    else "- **趋势强度：** N/A"
                )
            except Exception:
                lines.append(f"- **趋势强度：** {strength}")
            lines.append("")

            lines.append("### 二、政策要闻（研究摘要）")
            pol = _build_opening_policy_news_institutional_lines(report_data)
            if not pol:
                pol = _build_policy_news_lines(report_data, opening_prefer_cn_brief=True)
            if pol:
                for ln in pol[:6]:
                    lines.append(f"- {ln}")
            else:
                lines.append(_opening_policy_placeholder_line(report_data))
            lines.append("")

            lines.append("### 三、隔夜指示（A50｜日韩｜欧股｜美股）")
            for ln in _build_opening_overnight_index_lines(report_data):
                lines.append(f"- {ln}")
            lines.append("")

            lines.append("### 四、关键位（技术近似）")
            kl_lines = _build_key_levels_lines(report_data)
            if kl_lines:
                for ln in kl_lines:
                    lines.append(f"- {ln}")
            else:
                lines.append("- 关键位数据暂缺。")
            lines.append("")

            lines.append("### ✅ 五、执行清单（开盘前/开盘后）")
            lines.append("- **开盘前：** 先核对外盘与政策要闻是否同向。")
            lines.append("- **开盘后 30 分钟：** 观察量价共振与主线扩散，避免情绪追单。")
            lines.append("- **午前复核：** 若趋势强度回落或信号冲突，主动降仓并等待二次确认。")
            lines.append("")

            lines.extend(
                _build_institutional_extras_lines(
                    intraday_allowed=_allows_intraday_wording(report_data)
                )
            )
            lines.append("")
            lines.append("### 热点与板块")
            hot_bo = _build_opening_hot_sector_bullets(report_data)
            if hot_bo:
                lines.extend(hot_bo)
            else:
                lines.append("- （板块热度暂缺）")
            lines.append("")
            lines.append("---")
            lines.append(f"*分析完成时间：{now}*")
            return title, _dingtalk_trim("\n".join(lines).strip())

        rc = report_data.get("runtime_context") if isinstance(report_data.get("runtime_context"), dict) else {}
        snap_time = str((rc or {}).get("snapshot_time") or now)[:19]
        mode_text = "开盘实时" if bool((rc or {}).get("is_opening_window", True)) else "非开盘复盘"
        lines.append(f"**快照时点：** {snap_time}")
        lines.append(f"**模式：** {mode_text}")
        lines.append("")

        lines.append("### 一、开盘快照（竞价/开盘）")
        oms = report_data.get("opening_market_snapshot") if isinstance(report_data.get("opening_market_snapshot"), dict) else {}
        idx_rt = oms.get("indices_realtime") if isinstance(oms.get("indices_realtime"), list) else []
        etf_rt = oms.get("etf_realtime") if isinstance(oms.get("etf_realtime"), list) else []
        lines.append("- **指数类：**")
        for row in idx_rt[:4]:
            if not isinstance(row, dict):
                continue
            nm = row.get("name") or row.get("code") or "指数"
            p = _row_price(row)
            cp = row.get("change_pct") if row.get("change_pct") is not None else row.get("change_percent")
            p_txt = f"{p:.2f}" if p is not None else "N/A"
            lines.append(f"  - **{nm}** 指数 {p_txt}，涨跌幅 {_fmt_pct(cp) or 'N/A'}")
        lines.append("- **ETF类：**")
        for row in etf_rt[:3]:
            if not isinstance(row, dict):
                continue
            nm = row.get("name") or row.get("code") or "ETF"
            p = _row_price(row)
            cp = row.get("change_pct") if row.get("change_pct") is not None else row.get("change_percent")
            p_txt = f"{p:.3f}" if p is not None else "N/A"
            lines.append(f"  - **{nm}** 现价 {p_txt}，涨跌幅 {_fmt_pct(cp) or 'N/A'}")
        lines.append("")

        lines.append("### 二、板块温度（开盘前15分钟）")
        hot_b = _build_opening_hot_sector_bullets(report_data)
        if hot_b:
            lines.extend(hot_b[:8])
        else:
            lines.append("- 板块温度数据暂缺。")
        lines.append("")

        lines.append("### 三、资金与成交状态")
        ofs = report_data.get("opening_flow_signals") if isinstance(report_data.get("opening_flow_signals"), dict) else {}
        mb = ofs.get("market_breadth") if isinstance(ofs.get("market_breadth"), dict) else {}
        sc = int(mb.get("tracked_etf_strong_count") or 0)
        wc = int(mb.get("tracked_etf_weak_count") or 0)
        tc = int(mb.get("tracked_etf_total") or 0)
        breadth = (sc / tc * 100.0) if tc > 0 else 0.0
        lines.append(f"- 市场广度：强势ETF {sc} / 弱势ETF {wc} / 样本 {tc}（强势占比 {breadth:.0f}%）")
        lines.append(f"- 资金风格：{ofs.get('flow_bias') or '中性'}（基于ETF强弱 + 板块热度的开盘近似）")
        note = ofs.get("note")
        if isinstance(note, str) and note.strip():
            lines.append(f"- {note.strip()[:120]}")
        lines.append("")

        lines.append("### 四、跟踪标的（ETF/股票）")
        tas = report_data.get("tracked_assets_snapshot") if isinstance(report_data.get("tracked_assets_snapshot"), dict) else {}
        te = tas.get("etf") if isinstance(tas.get("etf"), list) else []
        if te:
            for row in te[:8]:
                if not isinstance(row, dict):
                    continue
                nm = row.get("name") or row.get("code") or "ETF"
                lines.append(
                    f"- ETF {nm}：{row.get('strength') or '中'}（涨跌幅 {_fmt_pct(row.get('change_pct')) or 'N/A'}）"
                )
        else:
            lines.append("- ETF 跟踪快照暂缺。")
        lines.append("- 股票：默认未配置，按策略白名单扩展。")
        lines.append("")

        lines.append("### 五、当日预判与执行")
        lines.append(f"- **整体趋势：** {overall_trend if overall_trend is not None else 'N/A'}")
        try:
            lines.append(
                f"- **趋势强度：** {float(strength):.2f}"
                if strength is not None
                else "- **趋势强度：** N/A"
            )
        except Exception:
            lines.append(f"- **趋势强度：** {strength}")
        lines.append("- **执行建议：** 先验证量价一致性，再决定是否追随主线；若分化加剧优先降仓。")
        lines.append("")

        lines.append("### 六、交易阈值与风控（机构口径）")
        lines.append("- 适用标的：基准指数 **沪深300(000300)**；执行锚 **510300/510050/510500**。")
        kl_lines = _build_key_levels_lines(report_data)
        if kl_lines:
            for ln in kl_lines:
                lines.append(f"- {ln}")
        else:
            lines.append("- 关键位数据暂缺。")
        intraday = report_data.get("intraday_range") if isinstance(report_data.get("intraday_range"), dict) else {}
        up = _fmt_num(intraday.get("upper"), 3)
        lo = _fmt_num(intraday.get("lower"), 3)
        if up and lo:
            lines.append(f"- 基准区间（510300）：{lo} ~ {up}（超区间需下调风险偏好）。")
        lines.append("- 执行纪律：首30分钟不追单；放量背离、信号冲突或跌破关键位时先降仓后复核。")
        lines.append("")

        lines.append("### 背景（隔夜）")
        for ln in _build_opening_overnight_index_lines(report_data)[:4]:
            lines.append(f"- {ln}")
        lines.append("")

        if llm_text:
            lines.append("### 摘要（LLM）")
            lines.append(llm_text.strip()[:900])
            lines.append("")

        lines.append("---")
        lines.append(f"*分析完成时间：{now}*")
        return title, _dingtalk_trim("\n".join(lines).strip())

    # 盘前 before_open：完整晨报章节（opening / opening_market 已在上文单独 return）
    _full_morning_brief = rt == "before_open"

    if _full_morning_brief:
        # 版式对齐「机构盘前晨报」：参考链接 → 政策 → 趋势 → 关键位 → 波动 → 策略 → 情景 → 热点 → LLM；
        # 隔夜外盘/A50 检索摘要等细节优先由 LLM 摘要展开，避免顶栏重复冗长。
        regime = report_data.get("a_share_regime_note")
        if isinstance(regime, str) and regime.strip():
            rtxt = regime.strip()[:400]
            if rtxt.startswith("- "):
                rtxt = rtxt[2:].strip()
            lines.append("### ⏰ 时段与口径")
            lines.append(f"- {rtxt}")
            lines.append("")
        ref_urls = _collect_before_open_reference_urls(report_data)
        if ref_urls:
            lines.append("### 🔗 参考链接")
            for i, u in enumerate(ref_urls[:5], 1):
                lines.append(f"- {i}. {u}")
            lines.append("")

        pol = _build_opening_policy_news_institutional_lines(report_data)
        if not pol:
            pol = _build_policy_news_lines(report_data, opening_prefer_cn_brief=True)
        lines.append("### 📰 政策要闻（检索摘要，请以原文链接为准）")
        if pol:
            for ln in pol:
                lines.append(f"- {ln}")
        else:
            lines.append(_opening_policy_placeholder_line(report_data))
        lines.append("")

        lines.append("### 🔍 趋势判定")
        lines.append(f"- **整体趋势：** {overall_trend if overall_trend is not None else 'N/A'}")
        try:
            if strength is not None:
                lines.append(f"- **趋势强度：** {float(strength):.2f}")
            else:
                lines.append("- **趋势强度：** N/A")
        except Exception:
            lines.append(f"- **趋势强度：** {strength}")

        a50_s = _fmt_pct(a50_change)
        if a50_s is None:
            if a50_status == "insufficient_data":
                a50_display = "样本不足"
            elif a50_status == "error":
                a50_display = "接口异常"
            else:
                a50_display = "获取失败"
            if isinstance(a50_reason, str) and a50_reason.strip():
                a50_display = f"{a50_display}（{a50_reason.strip()}）"
        else:
            a50_display = a50_s
        lines.append(f"- **A50期指（主源）：** {a50_display}")

        hxc_s = _fmt_pct(hxc_change)
        if hxc_s is None:
            if hxc_status == "insufficient_data":
                hxc_display = "样本不足"
            elif hxc_status == "error":
                hxc_display = "接口异常"
            else:
                hxc_display = "获取失败"
            _ = hxc_reason  # 失败具体原因不在晨报正文展开，避免噪声
        else:
            hxc_display = hxc_s
        lines.append(f"- **纳斯达克中国金龙：** {hxc_display}")
        if analysis.get("overnight_overlay_degraded"):
            lines.append("- **说明：** 隔夜主源数值缺失，趋势更重前日收盘；可合并 tavily 定性摘要。")
        lines.append("")

        kl_lines = _build_key_levels_lines(report_data)
        lines.append("### 📐 关键位（技术近似）")
        if kl_lines:
            for ln in kl_lines:
                lines.append(f"- {ln}")
        else:
            lines.append("- （未合并；可调用 tool_compute_index_key_levels）")
        lines.append("")

        vol_lines = _build_volatility_lines(report_data)
        if vol_lines:
            lines.append("### 📈 波动/区间（摘要）")
            for ln in vol_lines[:24]:
                lines.append(ln)
        lines.append("")

        if opening_strategy:
            lines.append("### 🎯 开盘策略建议")
            direction = opening_strategy.get("direction")
            position_size = opening_strategy.get("position_size")
            signal_threshold = opening_strategy.get("signal_threshold")
            suggest_call = opening_strategy.get("suggest_call")
            suggest_put = opening_strategy.get("suggest_put")
            if direction is not None:
                lines.append(f"- **方向：** {direction}")
            if suggest_call is not None or suggest_put is not None:
                lines.append(
                    f"- **建议关注：** "
                    f"{'认购(Call)' if suggest_call else '认购(Call)不优先'} / "
                    f"{'认沽(Put)' if suggest_put else '认沽(Put)不优先'}"
                )
            if position_size is not None:
                lines.append(f"- **仓位建议：** {position_size}")
            if signal_threshold is not None:
                lines.append(f"- **信号阈值：** {signal_threshold}")
            lines.append("")

        if rt in ("opening", "opening_market"):
            sig_lines = _build_signals_lines(report_data)
            if sig_lines:
                lines.append("### 📌 信号（开盘）")
                lines.extend(sig_lines)
                lines.append("")

        lines.extend(_build_institutional_extras_lines(intraday_allowed=_allows_intraday_wording(report_data)))
        lines.append("")

        lines.append("### 🔥 热点与板块")
        hot_bo = _build_opening_hot_sector_bullets(report_data)
        if hot_bo:
            for ln in hot_bo:
                lines.append(ln)
        else:
            sec_lines = _build_sector_rotation_lines(report_data)
        if sec_lines:
            for ln in sec_lines:
                lines.append(f"- {ln}")
        else:
            lines.append("- （可合并 tool_sector_heat_score + config/hot_sectors.json）")
        lines.append("")

        ann = _build_announcement_lines(report_data)
        if ann:
            lines.append("### 📋 公告速览（检索）")
            for ln in ann:
                lines.append(f"- {ln}")
            lines.append("")

        prv = _build_prediction_review_lines(report_data)
        if prv:
            for ln in prv:
                lines.append(ln)
            lines.append("")

        stale = report_data.get("data_stale_warning")
        if not stale and isinstance(analysis, dict):
            stale = analysis.get("data_stale_warning")
        if isinstance(stale, str) and stale.strip():
            lines.append("### ⚠️ 数据提示")
            lines.append(stale.strip())
            lines.append("")

        if llm_text:
            lines.append("### 📝 摘要（LLM）")
            lines.append(llm_text.strip()[:2800])
            lines.append("")

        lines.append("---")
        lines.append(f"*分析完成时间：{now}*")
        body = _dingtalk_trim("\n".join(lines).strip())
        return title, body

    lines.append("### 🔍 趋势分析结果")
    lines.append(f"- **整体趋势：** {overall_trend if overall_trend is not None else 'N/A'}")
    try:
        lines.append(
            f"- **趋势强度：** {float(strength):.2f}"
            if strength is not None
            else "- **趋势强度：** N/A"
        )
    except Exception:
        lines.append(f"- **趋势强度：** {strength}")
    lines.append("")

    mo_lines = _build_market_overview_lines(report_data)
    if mo_lines:
        lines.append("### 🌏 外盘/指数概览")
        for ln in mo_lines:
            lines.append(f"- {ln}")
        lines.append("")

    if opening_strategy:
        lines.append("### 🎯 开盘策略建议")
        direction = opening_strategy.get("direction")
        position_size = opening_strategy.get("position_size")
        signal_threshold = opening_strategy.get("signal_threshold")
        suggest_call = opening_strategy.get("suggest_call")
        suggest_put = opening_strategy.get("suggest_put")
        if direction is not None:
            lines.append(f"- **方向：** {direction}")
        if suggest_call is not None or suggest_put is not None:
            lines.append(
                f"- **建议关注：** "
                f"{'认购(Call)' if suggest_call else '认购(Call)不优先'} / "
                f"{'认沽(Put)' if suggest_put else '认沽(Put)不优先'}"
            )
        if position_size is not None:
            lines.append(f"- **仓位建议：** {position_size}")
        if signal_threshold is not None:
            lines.append(f"- **信号阈值：** {signal_threshold}")
        lines.append("")

    vol_lines = _build_volatility_lines(report_data)
    if vol_lines:
        lines.append("### 📈 波动/区间（摘要）")
        for ln in vol_lines[:30]:
            lines.append(f"- {ln}")
        lines.append("")

    sig_lines = _build_signals_lines(report_data)
    if sig_lines:
        lines.append("### 📌 信号")
        lines.extend(sig_lines)
        lines.append("")

    stale = report_data.get("data_stale_warning")
    if not stale and isinstance(analysis, dict):
        stale = analysis.get("data_stale_warning")
    if isinstance(stale, str) and stale.strip():
        lines.append("### ⚠️ 数据提示")
        lines.append(stale.strip())
        lines.append("")

    lines.append("---")
    lines.append(f"*分析完成时间：{now}*")
    return title, _dingtalk_trim("\n".join(lines).strip())


def tool_send_daily_report(
    report_data: Dict[str, Any],
    report_date: Optional[str] = None,
    webhook_url: Optional[str] = None,
    mode: str = "prod",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    工具：发送盘前/盘后“市场日报”到钉钉自定义机器人（支持 SEC 加签）。

    Args:
        report_data: 报告数据（建议包含 report_type: before_open/after_close/daily 等）
        report_date: 报告日期（可选）
        webhook_url: 覆盖配置中的钉钉 webhook（可选；包含 access_token）
        mode: "prod" 真实发送；"test" 不发送（dry-run）
        kwargs: 可含 secret、keyword、split_markdown_sections、max_chars_per_message。
            分析类长文默认 ``split_markdown_sections=True``（与每日市场分析报告一致，按 ##/### 节合并分条）；
            仅当显式传入 ``split_markdown_sections=False`` 时关闭。
    """
    timing_sink = kwargs.pop("_timing_sink", None)
    if not isinstance(timing_sink, dict):
        timing_sink = None
    elif not _daily_report_timing_enabled():
        timing_sink = None

    payload = report_data
    _t_norm0 = time.perf_counter() if timing_sink is not None else None
    try:
        rt = _detect_report_type(report_data)
        if rt == "daily_market":
            analysis = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
            payload, _ = _normalize_daily_report_fields(report_data, analysis)
            analysis_p = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
            gate = payload.get("daily_report_gate")
            if isinstance(gate, dict):
                degraded, missing = _assess_daily_report_completeness(payload, analysis_p)
                payload["daily_report_gate"] = {**gate, "missing_fields": missing, "degraded": degraded}
    except Exception:
        payload = report_data
    if timing_sink is not None and _t_norm0 is not None:
        timing_sink["send_normalize_s"] = time.perf_counter() - _t_norm0

    fmt_timing: Optional[Dict[str, float]] = {} if timing_sink is not None else None
    _t_fmt0 = time.perf_counter() if timing_sink is not None else None
    title, structured_message = _format_daily_report(
        report_data=payload, report_date=report_date, _timing_out=fmt_timing
    )
    if timing_sink is not None and _t_fmt0 is not None:
        timing_sink["send_format_total_s"] = time.perf_counter() - _t_fmt0
        if fmt_timing:
            timing_sink.update(fmt_timing)

    if str(mode).lower() != "prod":
        report_type = _detect_report_type(report_data)
        out = {
            "success": True,
            "skipped": True,
            "message": f"dry-run: {title}",
            "data": {
                "report_type": report_type,
                "report_date": report_date,
                "title": title,
                "preview": structured_message[:2000],
            },
        }
        if timing_sink:
            out["data"]["timing_phases_s"] = dict(timing_sink)
        return out

    # 发送：复用钉钉自定义机器人发送工具（它会根据 secret 进行 SEC 加签）
    from .send_dingtalk_message import tool_send_dingtalk_message

    mc_raw = kwargs.get("max_chars_per_message")
    mc_opt: Optional[int] = None
    if mc_raw is not None:
        try:
            mc_opt = int(mc_raw)
        except (TypeError, ValueError):
            mc_opt = None

    if "split_markdown_sections" in kwargs:
        split_flag = bool(kwargs["split_markdown_sections"])
    else:
        split_flag = True

    _t_dt0 = time.perf_counter() if timing_sink is not None else None
    dt_ret = tool_send_dingtalk_message(
        message=structured_message,
        title=title,
        webhook_url=webhook_url,
        secret=kwargs.get("secret"),
        keyword=kwargs.get("keyword"),
        mode=mode,
        split_markdown_sections=split_flag,
        max_chars_per_message=mc_opt,
    )
    if timing_sink is not None and _t_dt0 is not None:
        timing_sink["send_dingtalk_s"] = time.perf_counter() - _t_dt0
    if timing_sink and isinstance(dt_ret, dict):
        data = dt_ret.get("data")
        if isinstance(data, dict):
            data = {**data, "timing_phases_s": dict(timing_sink)}
            return {**dt_ret, "data": data}
        return {**dt_ret, "data": {"timing_phases_s": dict(timing_sink)}}
    return dt_ret


def tool_analyze_after_close_and_send_daily_report(
    report_date: Optional[str] = None,
    webhook_url: Optional[str] = None,
    mode: str = "prod",
    extra_report_data: Optional[Dict[str, Any]] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    split_markdown_sections: bool = True,
    max_chars_per_message: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    进程内串接：盘后分析 → 组装 report_data → tool_send_daily_report。

    与 workflows/daily_market_report.yaml 的 cron 单次调用约定一致；可选 ``extra_report_data``
    浅合并到 ``report_data`` 顶层（参数字典不会覆盖已有完整 ``tool_*`` JSON）。
    """
    from plugins.analysis.trend_analysis import tool_analyze_after_close
    from plugins.notification import daily_report_normalization as _drn

    def _safe_call(name: str, fn: Any, *a: Any, **kw: Any) -> Any:
        try:
            return fn(*a, **kw)
        except Exception as e:
            return {"success": False, "message": f"{name} failed: {e}"}

    timing_sink: Optional[Dict[str, float]] = {} if _daily_report_timing_enabled() else None

    _tp0 = time.perf_counter() if timing_sink is not None else None
    ac = tool_analyze_after_close()
    if timing_sink is not None and _tp0 is not None:
        timing_sink["pipeline_1_analyze_after_close_s"] = time.perf_counter() - _tp0

    _tp1 = time.perf_counter() if timing_sink is not None else None
    rd: Dict[str, Any] = {
        "report_type": "daily_market",
        "tool_analyze_after_close": ac,
    }
    data = ac.get("data") if isinstance(ac, dict) else None
    if isinstance(data, dict):
        rd["analysis"] = data
    elif data is not None:
        rd["analysis"] = {"_non_dict_payload": data}
    if extra_report_data:
        _drn._merge_extra_report_data_skipping_tool_arg_stubs(rd, extra_report_data)
    _drn._maybe_autofill_cron_daily_market_p0(rd)

    # P0 自动补齐：避免日报退化为“有模板无内容”
    try:
        from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score
        # NOTE: `plugins.data_collection` is a symlink to the OpenClaw runtime plugin directory (read-only).
        # Use assistant-side policy news fetcher to ensure TAVILY_API_KEYS multi-key rotation (incl. HTTP 432).
        from plugins.data_access.policy_news import tool_fetch_policy_news
        from plugins.data_collection.morning_brief_fetchers import (
            tool_fetch_industry_news_brief,
            tool_fetch_announcement_digest,
        )
        from plugins.merged.fetch_etf_data import tool_fetch_etf_data
        from plugins.merged.fetch_index_data import tool_fetch_index_data
        from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range
        from src.signal_generation import tool_generate_option_trading_signals

        # 资金流工具在当前仓库可能由外部扩展提供；不可用时不能影响其它补采链路。
        tool_fetch_a_share_fund_flow = None
        try:
            from plugins.data_collection.a_share_fund_flow import tool_fetch_a_share_fund_flow as _ff  # type: ignore

            tool_fetch_a_share_fund_flow = _ff
        except Exception:
            tool_fetch_a_share_fund_flow = None

        if "tool_sector_heat_score" not in rd:
            rd["tool_sector_heat_score"] = _safe_call("tool_sector_heat_score", tool_sector_heat_score)
        if "tool_fetch_policy_news" not in rd:
            rd["tool_fetch_policy_news"] = _safe_call(
                "tool_fetch_policy_news", tool_fetch_policy_news, max_items=6
            )
        if "policy_news" not in rd and isinstance(rd.get("tool_fetch_policy_news"), dict):
            rd["policy_news"] = rd.get("tool_fetch_policy_news")
        if "tool_fetch_industry_news_brief" not in rd:
            rd["tool_fetch_industry_news_brief"] = _safe_call(
                "tool_fetch_industry_news_brief", tool_fetch_industry_news_brief, max_items=10
            )
        if "industry_news" not in rd and isinstance(rd.get("tool_fetch_industry_news_brief"), dict):
            rd["industry_news"] = rd.get("tool_fetch_industry_news_brief")
        if "tool_fetch_announcement_digest" not in rd:
            rd["tool_fetch_announcement_digest"] = _safe_call(
                "tool_fetch_announcement_digest", tool_fetch_announcement_digest, max_items=10
            )
        if "announcement_digest" not in rd and isinstance(rd.get("tool_fetch_announcement_digest"), dict):
            rd["announcement_digest"] = rd.get("tool_fetch_announcement_digest")
        # 资金流专题优先口径：同花顺行业/概念板块资金流；全市场大盘口径作为补充。
        if callable(tool_fetch_a_share_fund_flow):
            if "a_share_capital_flow_sector_industry" not in rd:
                rd["a_share_capital_flow_sector_industry"] = _safe_call(
                    "tool_fetch_a_share_fund_flow.sector_industry",
                    tool_fetch_a_share_fund_flow,
                    query_kind="sector_rank",
                    sector_type="industry",
                    rank_window="immediate",
                    limit=12,
                )
            if "a_share_capital_flow_sector_concept" not in rd:
                rd["a_share_capital_flow_sector_concept"] = _safe_call(
                    "tool_fetch_a_share_fund_flow.sector_concept",
                    tool_fetch_a_share_fund_flow,
                    query_kind="sector_rank",
                    sector_type="concept",
                    rank_window="immediate",
                    limit=12,
                )
            if "a_share_capital_flow_market_history" not in rd:
                rd["a_share_capital_flow_market_history"] = _safe_call(
                    "tool_fetch_a_share_fund_flow.market_flow_preferred",
                    tool_fetch_a_share_fund_flow,
                    query_kind="market_flow_preferred",
                    provider_preference="auto",
                    rank_window="immediate",
                    limit=120,
                    max_days=20,
                )
            mh_blk = rd.get("a_share_capital_flow_market_history")
            if (
                not (isinstance(mh_blk, dict) and mh_blk.get("success"))
                and "a_share_capital_flow_stock_rank_proxy" not in rd
            ):
                rd["a_share_capital_flow_stock_rank_proxy"] = _safe_call(
                    "tool_fetch_a_share_fund_flow.stock_rank",
                    tool_fetch_a_share_fund_flow,
                    query_kind="stock_rank",
                    rank_window="immediate",
                    limit=100,
                )
            proxy_blk = rd.get("a_share_capital_flow_stock_rank_proxy")
        else:
            mh_blk = rd.get("a_share_capital_flow_market_history")
            proxy_blk = rd.get("a_share_capital_flow_stock_rank_proxy")

        # 不对资金流做本地估算拼装；仅消费真实工具返回数据。
        if "tool_fetch_etf_realtime" not in rd:
            rd["tool_fetch_etf_realtime"] = _safe_call(
                "tool_fetch_etf_realtime",
                tool_fetch_etf_data,
                data_type="realtime",
                etf_code="510300,510500,510050,159919,159915",
                mode="production",
            )
        if "tool_fetch_index_realtime" not in rd:
            rd["tool_fetch_index_realtime"] = _safe_call(
                "tool_fetch_index_realtime",
                tool_fetch_index_data,
                data_type="realtime",
                index_code="000001,000300,399001,399006",
                mode="production",
            )
        if "tool_predict_daily_volatility_range" not in rd:
            rd["tool_predict_daily_volatility_range"] = _safe_call(
                "tool_predict_daily_volatility_range",
                tool_predict_daily_volatility_range,
                underlying="510300",
            )
        dvr = rd.get("tool_predict_daily_volatility_range")
        if isinstance(dvr, dict):
            if isinstance(dvr.get("formatted_output"), str) and dvr.get("formatted_output", "").strip():
                rd["volatility_prediction"] = dvr.get("formatted_output")
            dvr_data = dvr.get("data")
            if isinstance(dvr_data, dict):
                rd["volatility"] = {
                    "current_price": dvr_data.get("current_price"),
                    "upper": dvr_data.get("upper"),
                    "lower": dvr_data.get("lower"),
                    "range_pct": dvr_data.get("range_pct"),
                    "confidence": dvr_data.get("confidence"),
                }
        if "tool_generate_option_trading_signals" not in rd:
            rd["tool_generate_option_trading_signals"] = _safe_call(
                "tool_generate_option_trading_signals",
                tool_generate_option_trading_signals,
                underlying="510300",
                mode="production",
            )
    except Exception:
        # 补齐失败不阻断主流程；由发送层审计行标识降级
        pass

    if timing_sink is not None and _tp1 is not None:
        timing_sink["pipeline_2_p0_autofill_network_s"] = time.perf_counter() - _tp1

    _tp2 = time.perf_counter() if timing_sink is not None else None
    # 传递层兜底重试：逐项补采，避免单点 import/调用失败导致整段缺失。
    def _historical_to_realtime_like(his: Any, code_key: str) -> List[Dict[str, Any]]:
        payload = his.get("data") if isinstance(his, dict) else None
        items = payload if isinstance(payload, list) else ([payload] if isinstance(payload, dict) else [])
        out_rows: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get(code_key) or item.get("code") or "").strip()
            name = str(item.get("index_name") or item.get("etf_name") or item.get("name") or code).strip()
            kl = item.get("klines")
            if not isinstance(kl, list) or not kl:
                continue
            last = kl[-1]
            if not isinstance(last, dict):
                continue
            out_rows.append(
                {
                    "code": code,
                    "name": name,
                    "current_price": last.get("close"),
                    "change_percent": last.get("change_percent"),
                    "volume": last.get("volume"),
                    "amount": last.get("amount"),
                }
            )
        return out_rows

    def _ensure_index_etf_info_blocks() -> None:
        # 指数实时
        idx_rt = rd.get("tool_fetch_index_realtime")
        idx_ok = isinstance(idx_rt, dict) and idx_rt.get("success") and isinstance(idx_rt.get("data"), list) and bool(
            idx_rt.get("data")
        )
        if not idx_ok:
            try:
                from plugins.merged.fetch_index_data import tool_fetch_index_data

                idx_rt2 = _safe_call(
                    "tool_fetch_index_realtime",
                    tool_fetch_index_data,
                    data_type="realtime",
                    index_code="000001,000300,399001,399006",
                    mode="production",
                )
                if isinstance(idx_rt2, dict):
                    rd["tool_fetch_index_realtime"] = idx_rt2
                    idx_ok = bool(idx_rt2.get("success") and isinstance(idx_rt2.get("data"), list) and idx_rt2.get("data"))
                if not idx_ok:
                    idx_his = _safe_call(
                        "tool_fetch_index_historical.daily",
                        tool_fetch_index_data,
                        data_type="historical",
                        index_code="000001,000300,399001,399006",
                        period="daily",
                        mode="production",
                    )
                    his_rows = _historical_to_realtime_like(idx_his, "index_code")
                    if his_rows:
                        rd["tool_fetch_index_realtime"] = {
                            "success": True,
                            "source": "historical_fallback",
                            "data": his_rows,
                        }
            except Exception:
                pass

        # ETF实时
        etf_rt = rd.get("tool_fetch_etf_realtime")
        etf_ok = isinstance(etf_rt, dict) and etf_rt.get("success") and isinstance(etf_rt.get("data"), list) and bool(
            etf_rt.get("data")
        )
        if not etf_ok:
            try:
                from plugins.merged.fetch_etf_data import tool_fetch_etf_data

                etf_rt2 = _safe_call(
                    "tool_fetch_etf_realtime",
                    tool_fetch_etf_data,
                    data_type="realtime",
                    etf_code="510300,510500,510050,159919,159915",
                    mode="production",
                )
                if isinstance(etf_rt2, dict):
                    rd["tool_fetch_etf_realtime"] = etf_rt2
                    etf_ok = bool(etf_rt2.get("success") and isinstance(etf_rt2.get("data"), list) and etf_rt2.get("data"))
                if not etf_ok:
                    etf_his = _safe_call(
                        "tool_fetch_etf_historical.daily",
                        tool_fetch_etf_data,
                        data_type="historical",
                        etf_code="510300,510500,510050,159919,159915",
                        period="daily",
                        mode="production",
                    )
                    his_rows = _historical_to_realtime_like(etf_his, "etf_code")
                    if his_rows:
                        rd["tool_fetch_etf_realtime"] = {
                            "success": True,
                            "source": "historical_fallback",
                            "data": his_rows,
                        }
            except Exception:
                pass

        # 信息面（逐项补齐）
        try:
            # NOTE: `plugins.data_collection` is a symlink to the OpenClaw runtime plugin directory (read-only).
            # Use assistant-side policy news fetcher to ensure TAVILY_API_KEYS multi-key rotation (incl. HTTP 432).
            from plugins.data_access.policy_news import tool_fetch_policy_news
            from plugins.data_collection.morning_brief_fetchers import (
                tool_fetch_industry_news_brief,
                tool_fetch_announcement_digest,
            )

            if "tool_fetch_policy_news" not in rd:
                rd["tool_fetch_policy_news"] = _safe_call("tool_fetch_policy_news", tool_fetch_policy_news, max_items=6)
            if "policy_news" not in rd and isinstance(rd.get("tool_fetch_policy_news"), dict):
                rd["policy_news"] = rd.get("tool_fetch_policy_news")

            if "tool_fetch_industry_news_brief" not in rd:
                rd["tool_fetch_industry_news_brief"] = _safe_call(
                    "tool_fetch_industry_news_brief", tool_fetch_industry_news_brief, max_items=10
                )
            if "industry_news" not in rd and isinstance(rd.get("tool_fetch_industry_news_brief"), dict):
                rd["industry_news"] = rd.get("tool_fetch_industry_news_brief")

            if "tool_fetch_announcement_digest" not in rd:
                rd["tool_fetch_announcement_digest"] = _safe_call(
                    "tool_fetch_announcement_digest", tool_fetch_announcement_digest, max_items=10
                )
            if "announcement_digest" not in rd and isinstance(rd.get("tool_fetch_announcement_digest"), dict):
                rd["announcement_digest"] = rd.get("tool_fetch_announcement_digest")
        except Exception:
            pass

    _ensure_index_etf_info_blocks()

    # 派生字段：修复日报模板字段对齐
    gis = rd.get("global_index_spot")
    if isinstance(gis, dict) and isinstance(gis.get("data"), list):
        rows = gis.get("data") or []
        if rows and not isinstance(rd.get("market_overview"), dict):
            rd["market_overview"] = {
                "indices": [
                    {
                        "name": r.get("name") or r.get("code"),
                        "code": r.get("code"),
                        "change_pct": r.get("change_pct"),
                    }
                    for r in rows
                    if isinstance(r, dict)
                ]
            }
    if not rd.get("global_market_digest"):
        mo = rd.get("market_overview") if isinstance(rd.get("market_overview"), dict) else {}
        idx = mo.get("indices") if isinstance(mo.get("indices"), list) else []
        parts: List[str] = []
        for it in idx[:8]:
            if not isinstance(it, dict):
                continue
            nm = it.get("name") or it.get("code") or ""
            cp = _fmt_pct(it.get("change_pct"))
            if nm and cp:
                parts.append(f"{nm}{cp}")
        if parts:
            rd["global_market_digest"] = {"summary": "；".join(parts), "replaces_index_overview": False}

    analysis_obj = rd.get("analysis") if isinstance(rd.get("analysis"), dict) else {}
    if not analysis_obj.get("next_day_outlook"):
        trend = str(
            analysis_obj.get("final_trend")
            or analysis_obj.get("overall_trend")
            or rd.get("overall_trend")
            or ""
        ).strip()
        if trend:
            if any(k in trend for k in ("强", "偏多", "多")):
                analysis_obj["next_day_outlook"] = "偏多，关注高开后的量能持续性与主线扩散。"
            elif any(k in trend for k in ("弱", "偏空", "空")):
                analysis_obj["next_day_outlook"] = "偏空，优先控制回撤并等待量价共振后再加仓。"
        if analysis_obj:
            rd["analysis"] = analysis_obj

    # 发送层归一化（overlay 关键位、关键位补算等）后再做软门禁，避免 missing_fields 与正文不一致
    analysis_obj = rd.get("analysis") if isinstance(rd.get("analysis"), dict) else {}
    rd, _ = _drn._normalize_daily_report_fields(rd, analysis_obj)

    # 软门禁：仅记录缺失并在审计行体现，不再阻断正式发送（对齐开盘实盘报告口径）
    analysis_obj = rd.get("analysis") if isinstance(rd.get("analysis"), dict) else {}
    degraded, missing = _drn._assess_daily_report_completeness(rd, analysis_obj)
    ac_success = bool(isinstance(ac, dict) and ac.get("success"))
    if degraded or (not ac_success):
        reasons: List[str] = []
        if not ac_success:
            reasons.append(
                f"core analyze failed: {str((ac or {}).get('message') or (ac or {}).get('error') or 'unknown')}"
            )
        if degraded:
            reasons.append("missing sections: " + ",".join(missing))
        log_path = _append_failure_log(
            {
                "task": "daily_market_report",
                "reason": " | ".join(reasons) if reasons else "degraded_without_reason",
                "missing": missing,
                "analyze_success": ac_success,
                "report_date": report_date,
                "send_mode": "soft_gate_continue_send",
            }
        )
        rd["daily_report_gate"] = {
            "mode": "soft",
            "degraded": bool(degraded),
            "missing_fields": missing,
            "analyze_success": ac_success,
            "failure_log_path": log_path,
        }

    if timing_sink is not None and _tp2 is not None:
        timing_sink["pipeline_3_ensure_derive_normalize_gate_s"] = time.perf_counter() - _tp2

    send_kw: Dict[str, Any] = dict(kwargs)
    if secret is not None:
        send_kw["secret"] = secret
    if keyword is not None:
        send_kw["keyword"] = keyword
    send_kw["split_markdown_sections"] = split_markdown_sections
    if max_chars_per_message is not None:
        send_kw["max_chars_per_message"] = max_chars_per_message

    if timing_sink is not None:
        send_kw["_timing_sink"] = timing_sink

    _tp3 = time.perf_counter() if timing_sink is not None else None
    out = tool_send_daily_report(
        report_data=rd,
        report_date=report_date,
        webhook_url=webhook_url,
        mode=mode,
        **send_kw,
    )
    if timing_sink is not None and _tp3 is not None:
        timing_sink["pipeline_4_send_daily_report_total_s"] = time.perf_counter() - _tp3
        if isinstance(out, dict):
            d = out.get("data")
            if isinstance(d, dict):
                d["timing_phases_s"] = dict(timing_sink)
            else:
                out["data"] = {"timing_phases_s": dict(timing_sink)}
    return out


from plugins.notification import daily_report_normalization as _daily_norm

_flatten_md_headers_in_embedded_report_text = _daily_norm._flatten_md_headers_in_embedded_report_text
_normalize_daily_report_fields = _daily_norm._normalize_daily_report_fields
_build_daily_market_etf_universe_lines = _daily_norm._build_daily_market_etf_universe_lines
_build_a_share_market_flow_lines = _daily_norm._build_a_share_market_flow_lines
_build_daily_capital_flow_topic_lines = _daily_norm._build_daily_capital_flow_topic_lines
_daily_capital_flow_topic_has_registered_flow_tools = (
    _daily_norm._daily_capital_flow_topic_has_registered_flow_tools
)
_capital_flow_topic_substantive = _daily_norm._capital_flow_topic_substantive
_capital_flow_exec_summary_fragment = _daily_norm._capital_flow_exec_summary_fragment
_coverage_semantic_present = _daily_norm._coverage_semantic_present
_looks_like_completed_tool_json = _daily_norm._looks_like_completed_tool_json
_merge_extra_report_data_skipping_tool_arg_stubs = _daily_norm._merge_extra_report_data_skipping_tool_arg_stubs
_maybe_autofill_cron_daily_market_p0 = _daily_norm._maybe_autofill_cron_daily_market_p0
_merge_daily_market_global_outer_fallback = _daily_norm._merge_daily_market_global_outer_fallback
_assess_daily_report_completeness = _daily_norm._assess_daily_report_completeness

