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
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


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
        return f"{float(v):.2f}%"
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


def _opening_global_index_rows(report_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    合并 global_spot 各别名键与 market_overview.indices（按 code 去重后并列）。
    注意：若仅因 tool 返回 data=[] 就提前 return，会丢掉 market_overview 中的 A 股开盘行，
    且无法与新浪/yfinance 行合并；故必须合并后再返回。
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
            if c:
                by_code[str(c)] = x
    mo = report_data.get("market_overview")
    if isinstance(mo, dict):
        idx = mo.get("indices")
        if isinstance(idx, list):
            for x in idx:
                if not isinstance(x, dict):
                    continue
                c = x.get("code") or x.get("name")
                if c:
                    by_code[str(c)] = x
    return list(by_code.values())


def _fmt_opening_index_group(label: str, codes: Tuple[str, ...], rows: List[Dict[str, Any]]) -> Optional[str]:
    parts: List[str] = []
    for c in codes:
        it = _opening_pick_row(rows, c)
        if it is None:
            continue
        name = it.get("name") or _OPENING_DISPLAY_NAME_MAP.get(c) or c
        if str(name).strip() == c and c in _OPENING_DISPLAY_NAME_MAP:
            name = _OPENING_DISPLAY_NAME_MAP[c]
        chg = it.get("change_pct")
        if chg is None:
            chg = it.get("change_percent")
        chg_s = _fmt_pct(chg) if chg is not None else "N/A"
        parts.append(f"{name}: {chg_s}")
    if not parts:
        return None
    return f"**{label}** " + " | ".join(parts)


def _build_opening_overnight_index_lines(report_data: Dict[str, Any]) -> List[str]:
    rows = _opening_global_index_rows(report_data)
    out: List[str] = []
    us = _fmt_opening_index_group("美股（北京时间当日凌晨时段）", _OPENING_US_CODES, rows)
    if us:
        out.append(us)
    eu = _fmt_opening_index_group("欧股（上一交易日收市）", _OPENING_EU_CODES, rows)
    if eu:
        out.append(eu)
    jk = _fmt_opening_index_group("日/韩（当日已开盘）", _OPENING_JK_CODES, rows)
    if jk:
        out.append(jk)
    if not out:
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
                    out.append("**外盘（检索摘要，非交易所逐点数值）：** " + refined)
        if not out and isinstance(raw_spot, dict):
            msg = str(raw_spot.get("message") or "").strip()
            if msg and len(msg) > 10:
                out.append("**外盘指数：** 数值接口未返回有效行（" + msg[:320] + ("…" if len(msg) > 320 else "") + "）")
        if not out:
            out.append(
                "**外盘指数：** 主源不可用或未合并 global_spot；请补采 tool_fetch_global_index_spot（含 ^DJI,^GSPC,^IXIC,^N225,^KS11），"
                "或检查网络/yfinance/新浪是否可达。"
            )
    return out


def _build_opening_overnight_outer_lines(report_data: Dict[str, Any]) -> List[str]:
    """
    兼容旧版「外盘隔夜」两行标题（美股隔夜 / 日韩当日开盘），供日报与单元测试使用。
    数据源与 `_opening_global_index_rows` 一致；无数值行时仅用 `global_market_digest` 摘要。
    """
    rows = _opening_global_index_rows(report_data)
    out: List[str] = []
    us = _fmt_opening_index_group("美股（隔夜）", _OPENING_US_CODES, rows)
    if us:
        out.append(us)
    eu = _fmt_opening_index_group("欧股（上一交易日收市）", _OPENING_EU_CODES, rows)
    if eu:
        out.append(eu)
    jk = _fmt_opening_index_group("日/韩（当日开盘）", _OPENING_JK_CODES, rows)
    if jk:
        out.append(jk)
    if not out:
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
    return out


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


def _build_northbound_lines(report_data: Dict[str, Any]) -> List[str]:
    import math

    nb = report_data.get("northbound")
    if not isinstance(nb, dict):
        cf = report_data.get("capital_flow")
        if isinstance(cf, dict):
            nb = cf.get("northbound")
    if not isinstance(nb, dict):
        return []
    if nb.get("status") == "error":
        return [f"北向：获取失败（{nb.get('error', '未知')}）"]
    if nb.get("status") != "success":
        return []
    data = nb.get("data") or {}
    stats = nb.get("statistics") or {}
    net_raw = data.get("total_net")
    net_f: Optional[float] = None
    try:
        net_f = float(net_raw)
    except (TypeError, ValueError):
        net_f = None
    if net_f is not None and isinstance(net_f, float) and math.isnan(net_f):
        net_s = "N/A（净流入暂不可用，勿采信方向性话术）"
    elif net_f is not None:
        net_s = f"{net_f:.2f}"
    else:
        net_s = "N/A"
    parts = [
        f"最新日 {nb.get('date', '')} 净流入 **{net_s}** 亿元（口径：昨日收盘后可见，非实时）",
    ]
    if stats.get("consecutive_days") is not None:
        parts.append(f"连续方向天数：{stats.get('consecutive_days')}")
    sig = nb.get("signal") or {}
    desc = sig.get("description") if isinstance(sig, dict) else None
    if isinstance(desc, str) and desc.strip():
        if net_s == "N/A" or (net_f is not None and isinstance(net_f, float) and math.isnan(net_f)):
            pass
        elif net_f == 0.0:
            pass
        else:
            parts.append(desc)
    return parts


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
    nb = _build_northbound_lines(report_data)
    if nb:
        for x in nb:
            lines.append(f"- {x}")
    else:
        lines.append("- （北向未合并）")
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
        "- 平开(±0.2%)：结构性轮动，结合北向与板块热度",
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
    lines: List[str] = [title, "", "## 📊 14:40 尾盘多角度建议报告", f"**分析时间：** {now}", ""]

    lines.append("### 一、尾盘快照")
    lines.append(
        f"- 513880 现价 {_fmt_num(snap.get('latest_price'), 3) or 'N/A'} / IOPV {_fmt_num(snap.get('iopv'), 3) or 'N/A'} / 溢价率 {_fmt_pct(snap.get('premium_pct')) or 'N/A'}"
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

    lines.append("### 二、周期与技术状态")
    lines.append(
        f"- N225 收盘 {(_fmt_num(analysis.get('index_close'), 2) or 'N/A')}，日涨跌 {_fmt_pct(analysis.get('index_day_ret_pct')) or 'N/A'}"
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
        f"- MA25 偏离 {_fmt_pct(analysis.get('ma25_dev_pct')) or 'N/A'}，RSI14 {_fmt_num(analysis.get('rsi14'), 2) or 'N/A'}，{streak_txt}"
    )
    lines.append("")

    lines.append("### 三、分层建议（不合成单一结论）")
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

    lines.append("### 四、用户可选路径")
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

    lines.append("### 五、风险提示与执行摩擦")
    notices = analysis.get("risk_notices") if isinstance(analysis.get("risk_notices"), list) else []
    if notices:
        for n in notices[:8]:
            lines.append(f"- {n}")
    else:
        lines.append("- 暂无触发的额外风险提示。")
    if amt is not None and amt <= 2e7:
        lines.append("- 尾盘成交额偏低，存在滑点与成交冲击，建议被动挂单或缩小单次交易量。")
    lines.append("")

    lines.append("### 六、用户决策声明")
    lines.append(f"- {analysis.get('user_decision_note') or '本系统仅提供多视角信息，不替代你的最终交易决策。'}")
    lines.append("---")
    lines.append(f"*分析完成时间：{now}*")
    return title, _dingtalk_trim("\n".join(lines).strip())


def _format_daily_report(report_data: Dict[str, Any], report_date: Optional[str]) -> Tuple[str, str]:
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
        title = "日经225ETF尾盘监控报告"
        subtitle = "## 📊 日经225ETF尾盘监控报告"
    else:
        title = "市场日报"
        subtitle = "## 📊 市场日报"

    if date_str and rt not in ("before_open",):
        title = f"{title} - {date_str}"

    # LLM摘要（优先使用已有 llm_summary；缺失时再尝试调用一次 LLM）
    llm_text = _extract_llm_summary(report_data)
    if not llm_text:
        # 复用 Prompt_config.yaml：用相同 analysis_type 生成摘要
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

    if rt == "limitup_after_close_enhanced":
        return _format_limitup_after_close_enhanced(
            report_data, analysis, date_str, now, llm_text or ""
        )

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
            lines.append("- （检索摘要归纳，非交易所逐指数实时行情）")
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
            lines.append("- 扩展查阅：https://data.eastmoney.com/zjlx/dpzjlx.html · https://data.eastmoney.com/bkzj/jlr.html · https://data.eastmoney.com/bkzj/hy.html")
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
                lines.append("- 暂无可用政策要闻摘要。")
            lines.append("")

            lines.append("### 三、隔夜指示（外盘·A50）")
            for ln in _build_opening_overnight_index_lines(report_data)[:3]:
                lines.append(f"- {ln}")
            a50_s = _fmt_pct(a50_change)
            if a50_s is None:
                if a50_status == "insufficient_data":
                    a50_display = "样本不足"
                elif a50_status == "error":
                    a50_display = "接口异常"
                else:
                    a50_display = "获取失败"
            else:
                a50_display = a50_s
            lines.append(f"- **A50期指（主源）：** {a50_display}")
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
        for ln in _build_opening_overnight_index_lines(report_data)[:2]:
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
        # 版式对齐「机构盘前晨报」：参考链接 → 政策 → 北向 → 趋势 → 关键位 → 波动 → 策略 → 情景 → 热点 → LLM；
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
            lines.append("- 暂无可用政策要闻摘要。")
        lines.append("")

        nb_lines = _build_northbound_lines(report_data)
        lines.append("### 💹 北向资金")
        if nb_lines:
            for ln in nb_lines:
                lines.append(f"- {ln}")
        else:
            lines.append("- 暂无可用北向数据（盘前通常为 T-1 收盘后口径）。")
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
    payload = report_data
    try:
        rt = _detect_report_type(report_data)
        if rt == "daily_market":
            analysis = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
            payload, _ = _normalize_daily_report_fields(report_data, analysis)
    except Exception:
        payload = report_data

    title, structured_message = _format_daily_report(report_data=payload, report_date=report_date)

    if str(mode).lower() != "prod":
        report_type = _detect_report_type(report_data)
        return {
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

    return tool_send_dingtalk_message(
        message=structured_message,
        title=title,
        webhook_url=webhook_url,
        secret=kwargs.get("secret"),
        keyword=kwargs.get("keyword"),
        mode=mode,
        split_markdown_sections=split_flag,
        max_chars_per_message=mc_opt,
    )


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

    ac = tool_analyze_after_close()
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
        from plugins.data_collection.northbound import tool_fetch_northbound_flow
        from plugins.data_collection.limit_up.sector_heat import tool_sector_heat_score
        from plugins.data_collection.morning_brief_fetchers import (
            tool_fetch_policy_news,
            tool_fetch_industry_news_brief,
            tool_fetch_announcement_digest,
        )
        from plugins.data_collection.a_share_fund_flow import tool_fetch_a_share_fund_flow
        from plugins.merged.fetch_etf_data import tool_fetch_etf_data
        from plugins.merged.fetch_index_data import tool_fetch_index_data
        from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range
        from src.signal_generation import tool_generate_option_trading_signals

        if "tool_fetch_northbound_flow" not in rd:
            rd["tool_fetch_northbound_flow"] = _safe_call(
                "tool_fetch_northbound_flow", tool_fetch_northbound_flow, lookback_days=5
            )
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
        if "a_share_capital_flow_market_history" not in rd:
            rd["a_share_capital_flow_market_history"] = _safe_call(
                "tool_fetch_a_share_fund_flow.market_history",
                tool_fetch_a_share_fund_flow,
                query_kind="market_history",
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
        if (
            not (isinstance(mh_blk, dict) and mh_blk.get("success"))
            and isinstance(proxy_blk, dict)
            and proxy_blk.get("success")
            and isinstance(proxy_blk.get("records"), list)
            and proxy_blk.get("records")
        ):
            def _to_float_like(v: Any) -> Optional[float]:
                if v is None:
                    return None
                if isinstance(v, (int, float)):
                    return float(v)
                s = str(v).strip().replace(",", "")
                if not s:
                    return None
                mul = 1.0
                if s.endswith("亿"):
                    s = s[:-1]
                elif s.endswith("万"):
                    s = s[:-1]
                    mul = 1.0 / 10000.0
                try:
                    return float(s) * mul
                except Exception:
                    return None
            total = 0.0
            cnt = 0
            for row in proxy_blk.get("records", []):
                if not isinstance(row, dict):
                    continue
                val = None
                for k in ("今日主力净流入-净额", "主力净流入-净额", "净流入", "净额"):
                    if row.get(k) is not None:
                        val = row.get(k)
                        break
                if val is None:
                    for k2, v2 in row.items():
                        ks = str(k2)
                        if ("净流入" in ks or "净额" in ks) and "占比" not in ks:
                            val = v2
                            break
                fv = _to_float_like(val)
                if fv is not None:
                    total += fv
                    cnt += 1
            if cnt > 0:
                try:
                    import pytz as _pytz

                    from src.config_loader import load_system_config as _load_cfg
                    from src.system_status import get_expected_latest_a_share_daily_bar_date as _exp_bar

                    _tz = _pytz.timezone("Asia/Shanghai")
                    _cfg = _load_cfg(use_cache=True)
                    _bar = _exp_bar(
                        datetime.now(_tz),
                        _cfg if isinstance(_cfg, dict) else None,
                    )
                    _date_disp = f"{_bar[:4]}-{_bar[4:6]}-{_bar[6:8]}"
                except Exception:
                    _date_disp = datetime.now().strftime("%Y-%m-%d")
                rd["a_share_capital_flow_market_history"] = {
                    "success": True,
                    "query_kind": "market_history",
                    "source": "stock_rank_proxy",
                    "records": [
                        {
                            "日期": _date_disp,
                            "主力净流入-净额": total,
                            "说明": f"由个股资金流排行样本({cnt})估算，非全市场精确口径",
                        }
                    ],
                }
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

    # 强门禁：关键字段缺失时直接按失败处理，并发送失败告警（同渠道）
    analysis_obj = rd.get("analysis") if isinstance(rd.get("analysis"), dict) else {}
    degraded, missing = _drn._assess_daily_report_completeness(rd, analysis_obj)
    ac_success = bool(isinstance(ac, dict) and ac.get("success"))
    if str(mode).lower() == "prod" and ((not ac_success) or degraded):
        reasons: List[str] = []
        if not ac_success:
            reasons.append(f"core analyze failed: {str((ac or {}).get('message') or (ac or {}).get('error') or 'unknown')}")
        if degraded:
            reasons.append("missing sections: " + ",".join(missing))
        log_path = _append_failure_log(
            {
                "task": "daily_market_report",
                "reason": " | ".join(reasons),
                "missing": missing,
                "analyze_success": ac_success,
                "report_date": report_date,
            }
        )
        alert = _send_failure_alert_to_dingtalk(
            title="每日市场分析报告",
            reason="日报关键数据不完整，已阻断正式发送",
            detail_lines=reasons + ([f"log: {log_path}"] if log_path else []),
            mode=mode,
            webhook_url=webhook_url,
            secret=secret,
            keyword=keyword,
        )
        return {
            "success": False,
            "error_code": "ERROR_INCOMPLETE_REPORT_DATA",
            "message": "daily report blocked due to missing critical sections",
            "data": {
                "missing_fields": missing,
                "analyze_success": ac_success,
                "failure_log_path": log_path,
                "alert_delivery": alert,
            },
        }

    send_kw: Dict[str, Any] = dict(kwargs)
    if secret is not None:
        send_kw["secret"] = secret
    if keyword is not None:
        send_kw["keyword"] = keyword
    send_kw["split_markdown_sections"] = split_markdown_sections
    if max_chars_per_message is not None:
        send_kw["max_chars_per_message"] = max_chars_per_message

    return tool_send_daily_report(
        report_data=rd,
        report_date=report_date,
        webhook_url=webhook_url,
        mode=mode,
        **send_kw,
    )


from plugins.notification import daily_report_normalization as _daily_norm

_flatten_md_headers_in_embedded_report_text = _daily_norm._flatten_md_headers_in_embedded_report_text
_normalize_daily_report_fields = _daily_norm._normalize_daily_report_fields
_build_daily_market_etf_universe_lines = _daily_norm._build_daily_market_etf_universe_lines
_build_a_share_market_flow_lines = _daily_norm._build_a_share_market_flow_lines
_build_daily_capital_flow_topic_lines = _daily_norm._build_daily_capital_flow_topic_lines
_capital_flow_topic_substantive = _daily_norm._capital_flow_topic_substantive
_capital_flow_exec_summary_fragment = _daily_norm._capital_flow_exec_summary_fragment
_coverage_semantic_present = _daily_norm._coverage_semantic_present
_looks_like_completed_tool_json = _daily_norm._looks_like_completed_tool_json
_merge_extra_report_data_skipping_tool_arg_stubs = _daily_norm._merge_extra_report_data_skipping_tool_arg_stubs
_maybe_autofill_cron_daily_market_p0 = _daily_norm._maybe_autofill_cron_daily_market_p0
_assess_daily_report_completeness = _daily_norm._assess_daily_report_completeness

