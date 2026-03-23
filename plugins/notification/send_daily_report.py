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
        return rt.strip()
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
    if isinstance(mo, dict):
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

    return lines


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
            }
            llm_text, _ = enhance_with_llm(payload, analysis_type=analysis_type, config=cfg)
        except Exception:
            llm_text = ""

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

    # 组织正文（参考你贴的两种示例：先给自然语言摘要，再给指标结构）
    lines: List[str] = []
    lines.append(title)
    lines.append("")
    if llm_text:
        lines.append(llm_text.strip())
        lines.append("")

    lines.append(subtitle)
    if date_str:
        lines.append(f"**日期：** {date_str}")
    lines.append(f"**分析时间：** {now}")
    lines.append("")

    # 趋势结果
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
    lines.append(f"- **A50期指数据：** {a50_s if a50_s is not None else '获取失败'}")
    hxc_s = _fmt_pct(hxc_change)
    lines.append(f"- **纳斯达克中国金龙指数：** {hxc_s if hxc_s is not None else '获取失败'}")
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

    return title, "\n".join(lines).strip()


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
    )

