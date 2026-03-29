"""
发送市场日报（飞书通知）

说明：
- 工作流脚本期望存在 `notification.send_daily_report.tool_send_daily_report`
- 实际发送能力复用合并工具 `merged.send_feishu_notification.tool_send_feishu_notification`
- 默认 mode="prod"：真实发送到飞书 webhook
- mode="test"：仅做格式化/校验，不发出网络请求（用于 step_by_step 工作流测试，避免刷屏）
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List, Tuple
import json
from datetime import datetime
from pathlib import Path


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
        lines.append("参考链接： " + " | ".join(str(u) for u in urls[:3]))
    if not lines and analysis.get("overnight_overlay_degraded"):
        lines.append("隔夜 A50/金龙主源不可用；请依赖上方全球指数或工作流检索摘要。")
    return lines


def _as_tool_data_payload(d: Any) -> Dict[str, Any]:
    """兼容直接把工具返回 { success, data: {...} } 塞进 report_data 的情况。"""
    if isinstance(d, dict) and isinstance(d.get("data"), dict):
        return d["data"]
    return d if isinstance(d, dict) else {}


def _build_industry_news_lines(report_data: Dict[str, Any]) -> List[str]:
    ind = _as_tool_data_payload(report_data.get("industry_news"))
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


def _build_policy_news_lines(report_data: Dict[str, Any]) -> List[str]:
    pn = _as_tool_data_payload(report_data.get("policy_news"))
    if not isinstance(pn, dict):
        return []
    items = pn.get("items")
    if not isinstance(items, list) or not items:
        return []
    lines: List[str] = []
    if pn.get("brief_answer"):
        lines.append(f"提要：{str(pn['brief_answer'])[:400]}")
    for i, it in enumerate(items[:8], 1):
        if not isinstance(it, dict):
            continue
        t = it.get("title") or ""
        u = it.get("url") or ""
        lines.append(f"{i}. {t[:120]} {u[:120]}".strip())
    return lines


def _build_northbound_lines(report_data: Dict[str, Any]) -> List[str]:
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
    try:
        net = data.get("total_net")
        net_s = f"{float(net):.2f}" if net is not None else "N/A"
    except Exception:
        net_s = str(data.get("total_net"))
    parts = [
        f"最新日 {nb.get('date', '')} 净流入 **{net_s}** 亿元（口径：昨日收盘后可见，非实时）",
    ]
    if stats.get("consecutive_days") is not None:
        parts.append(f"连续方向天数：{stats.get('consecutive_days')}")
    sig = nb.get("signal") or {}
    if isinstance(sig, dict) and sig.get("description"):
        parts.append(sig["description"])
    return parts


def _build_key_levels_lines(report_data: Dict[str, Any]) -> List[str]:
    kl = report_data.get("key_levels")
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
    ad = _as_tool_data_payload(report_data.get("announcement_digest"))
    if not isinstance(ad, dict):
        return []
    items = ad.get("items")
    if not isinstance(items, list) or not items:
        return []
    lines: List[str] = []
    for i, it in enumerate(items[:6], 1):
        if not isinstance(it, dict):
            continue
        lines.append(f"{i}. {(it.get('title') or '')[:100]} {(it.get('url') or '')[:80]}".strip())
    return lines


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


def _build_sector_rotation_lines(report_data: Dict[str, Any]) -> List[str]:
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


def _build_institutional_extras_lines() -> List[str]:
    return [
        "### 情景推演（参考沪深主指 ±0.5% / ±0.2% 粗分档）",
        "- 高开(>0.5%)：关注 5 分钟量能验证，策略偏多但设止损",
        "- 平开(±0.2%)：结构性轮动，结合北向与板块热度",
        "- 低开(<-0.5%)：偏防守，反弹注意减仓节奏",
        "",
        "### 盘中时间锚点",
        "- 09:35：开盘 5 分钟量能与方向验证",
        "- 10:30：首小时换手与板块轮动",
        "- 13:30：午后资金回流与再定价",
    ]


def _dingtalk_trim(text: str, max_len: int = 1950) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 40] + "\n\n…（正文已截断，详见 data/ 落盘）"


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
    if isinstance(vol_txt, str) and vol_txt.strip():
        # 取前几行，避免过长刷屏
        head = "\n".join([ln for ln in vol_txt.strip().splitlines() if ln.strip()][:18])
        lines.append("波动区间（摘要）：")
        lines.append(head)
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


def _build_signals_lines(report_data: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    sig = report_data.get("signals")
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

    # 标题（尽量贴近原系统/示例文案）
    if rt == "before_open":
        title = "开盘前市场趋势分析报告"
        subtitle = "## 📊 开盘前市场趋势分析报告"
    elif rt in ("opening", "opening_market"):
        title = "开盘行情分析报告"
        subtitle = "## 📊 开盘行情分析报告"
    elif rt == "after_close":
        title = "盘后市场复盘报告"
        subtitle = "## 📊 盘后市场复盘报告"
    else:
        title = "市场日报"
        subtitle = "## 📊 市场日报"

    if date_str:
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
    if date_str:
        lines.append(f"**日期：** {date_str}")
    lines.append(f"**分析时间：** {now}")
    lines.append("")

    # 开盘独立完整版：与 before_open 同一套机构晨报章节（非盘前简报增量）；标题仍用「开盘行情分析报告」
    _full_morning_brief = rt in ("before_open", "opening", "opening_market")

    if _full_morning_brief:
        if rt in ("opening", "opening_market"):
            lines.append(
                "- **报告形态：** 开盘独立完整版（与同结构盘前晨报并列展示所需字段；非盘前增量摘要）"
            )
            lines.append("")
        mo_lines = _build_market_overview_lines(report_data)
        if mo_lines:
            lines.append("### 🌏 隔夜外盘与指数")
            for ln in mo_lines:
                lines.append(f"- {ln}")
            lines.append("")
        od_lines = _build_overnight_digest_lines(report_data, analysis)
        if od_lines:
            for ln in od_lines:
                lines.append(f"- {ln}")
            lines.append("")

        pol = _build_policy_news_lines(report_data)
        lines.append("### 📰 政策要闻（检索摘要，请以原文链接为准）")
        if pol:
            for ln in pol:
                lines.append(f"- {ln}")
        else:
            lines.append("- （未合并政策要闻；工作流可调用 tool_fetch_policy_news）")
        lines.append("")

        nb_lines = _build_northbound_lines(report_data)
        lines.append("### 💹 北向资金")
        if nb_lines:
            for ln in nb_lines:
                lines.append(f"- {ln}")
        else:
            lines.append("- （未合并北向；工作流可调用 tool_fetch_northbound_flow）")
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
            if isinstance(hxc_reason, str) and hxc_reason.strip():
                hxc_display = f"{hxc_display}（{hxc_reason.strip()}）"
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
            for ln in vol_lines[:24]:
                lines.append(ln)
            lines.append("")

        if rt in ("opening", "opening_market"):
            sig_lines = _build_signals_lines(report_data)
            if sig_lines:
                lines.append("### 📌 信号（开盘）")
                lines.extend(sig_lines)
                lines.append("")

        lines.extend(_build_institutional_extras_lines())
        lines.append("")

        sec_lines = _build_sector_rotation_lines(report_data)
        lines.append("### 🔥 热点与板块")
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
            lines.append(llm_text.strip()[:1200])
            lines.append("")

        lines.append("---")
        lines.append(f"*分析完成时间：{now}*")
        body = _dingtalk_trim("\n".join(lines).strip())
        return title, body

    if llm_text:
        lines.append(llm_text.strip())
        lines.append("")

    lines.append("### 🔍 趋势分析结果")
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
    lines.append(f"- **A50期指数据：** {a50_display}")

    hxc_s = _fmt_pct(hxc_change)
    if hxc_s is None:
        if hxc_status == "insufficient_data":
            hxc_display = "样本不足"
        elif hxc_status == "error":
            hxc_display = "接口异常"
        else:
            hxc_display = "获取失败"
        if isinstance(hxc_reason, str) and hxc_reason.strip():
            hxc_display = f"{hxc_display}（{hxc_reason.strip()}）"
    else:
        hxc_display = hxc_s
    lines.append(f"- **纳斯达克中国金龙指数：** {hxc_display}")
    lines.append("")

    # 外盘/指数概览（如有）
    mo_lines = _build_market_overview_lines(report_data)
    if mo_lines:
        lines.append("### 🌏 外盘/指数概览")
        for ln in mo_lines:
            lines.append(f"- {ln}")
        lines.append("")

    # 策略建议（如有）
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

    # 波动区间（摘要）
    vol_lines = _build_volatility_lines(report_data)
    if vol_lines:
        lines.append("### 📈 波动/区间（摘要）")
        for ln in vol_lines[:30]:
            lines.append(ln)
        lines.append("")

    # 信号（盘后可能有）
    sig_lines = _build_signals_lines(report_data)
    if sig_lines:
        lines.append("### 📌 信号")
        lines.extend(sig_lines)
        lines.append("")

    # 数据过期提示（如有）
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
    """
    title, structured_message = _format_daily_report(report_data=report_data, report_date=report_date)

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

    return tool_send_dingtalk_message(
        message=structured_message,
        title=title,
        webhook_url=webhook_url,
        secret=kwargs.get("secret"),
        keyword=kwargs.get("keyword"),
        mode=mode,
        split_markdown_sections=bool(kwargs.get("split_markdown_sections")),
        max_chars_per_message=int(kwargs.get("max_chars_per_message") or 1750),
    )

