"""
专用工具：渲染并发送“信号+风控巡检”快报。

目标：
- 避免 LLM 直接生成最终群文案
- 由工具基于结构化字段渲染固定模板
- 统一 run_status 与缺省值口径
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional


PHASE_LABELS = {
    "morning": "早盘",
    "midday": "上午",
    "afternoon": "下午",
}

_STATE_MAP = {
    "after_close": "收盘后观望",
    "closed": "收盘后观望",
    "pre_open": "盘前观望",
    "lunch": "午休静置",
    "open": "盘中震荡",
    "ok": "盘中震荡",
}

_RISK_LEVEL_MAP = {
    "ok": "中",
    "normal": "中",
    "low": "低",
    "medium": "中",
    "high": "高",
}

_STRENGTH_MAP = {
    "strong": "偏强",
    "moderate": "中性",
    "neutral": "中性",
    "weak": "偏弱",
}

_ACTION_MAP = {
    "hold": "持有观望",
    "buy": "逢回调分批参与",
    "sell": "减仓观望",
}

_REQUIRED_REPORT_KEYS = (
    "date",
    "time",
    "time_ref",
    "hs300_change",
    "hs300_strength",
    "gem_change",
    "gem_strength",
    "zz500_change",
    "zz500_strength",
    "style_judgment",
    "510300_price",
    "510300_change",
    "510300_position",
    "510300_resist",
    "510300_support",
    "510500_price",
    "510500_change",
    "510500_position",
    "510500_resist",
    "510500_support",
    "159915_price",
    "159915_change",
    "159915_position",
    "159915_resist",
    "159915_support",
    "remain_window",
    "market_state",
    "focus1",
    "focus2",
    "focus3",
    "510300_action",
    "510500_action",
    "159915_action",
    "risk_level",
    "position_suggest",
    "next_update",
    "var_snapshot",
    "max_dd_snapshot",
    "current_dd_snapshot",
    "position_risk_snapshot",
)


def _clean_text(v: Any, default: str = "数据不足") -> str:
    if v is None:
        return default
    s = str(v).strip()
    if not s:
        return default
    # 去掉变量残片/内部元信息
    if "{" in s or "}" in s:
        return default
    lowered = s.lower()
    for bad in ("session", "webhook", "secret", "tool_call", "function=", "parameter="):
        if bad in lowered:
            return default
    return s


def _to_pct_text(v: Any) -> str:
    s = _clean_text(v, "数据不足")
    if s == "数据不足":
        return s
    if "%" in s:
        m = re.search(r"(-?\d+(?:\.\d+)?)", s)
        if not m:
            return "数据不足"
        pct = float(m.group(1))
        return s if abs(pct) <= 15 else "数据不足"
    try:
        x = float(s)
    except Exception:
        return "数据不足"
    # 兼容小数比例（如 0.070 -> 7.00%）
    if -1.2 <= x <= 1.2:
        pct = x * 100
        return f"{pct:.2f}%" if abs(pct) <= 15 else "数据不足"
    # 若已是百分比数值（如 1.23），直接补 %
    if -15 <= x <= 15:
        return f"{x:.2f}%"
    # 大于 1 的纯数字常是点位而非涨跌幅，避免错填
    return "数据不足"


def _normalize_phase_label(phase: str, report: Dict[str, Any]) -> str:
    label = PHASE_LABELS.get(phase, "上午")
    t = _clean_text(report.get("time"), "")
    m = re.search(r"\b(\d{1,2}):(\d{2})", t)
    if not m:
        return label
    hour = int(m.group(1))
    if hour >= 13:
        return "下午"
    if hour <= 10:
        return "早盘" if phase == "morning" else "上午"
    return "上午"


def _normalize_market_state(v: Any) -> str:
    s = _clean_text(v, "数据不足")
    if s == "数据不足":
        return s
    return _STATE_MAP.get(s.lower(), s)


def _normalize_risk_level(v: Any) -> str:
    s = _clean_text(v, "中")
    return _RISK_LEVEL_MAP.get(s.lower(), s)


def _normalize_remain_window(v: Any) -> str:
    s = _clean_text(v, "数据不足")
    if s == "数据不足":
        return s
    if s.lower() in ("closed", "after_close"):
        return "收盘"
    m = re.search(r"(\d+)", s)
    if m:
        mins = int(m.group(1))
        if mins > 360:
            return "数据不足"
    return s


def _normalize_time_ref(v: Any, fallback_time: str) -> str:
    s = _clean_text(v, "")
    if not s:
        return fallback_time
    if re.search(r"\b\d{1,2}:\d{2}\b", s):
        return s
    if s in ("午间", "上午", "早盘", "下午", "盘后"):
        return fallback_time
    return s


def _normalize_var_snapshot(v: Any) -> str:
    s = _clean_text(v, "数据不足")
    if s == "数据不足":
        return s
    m = re.search(r"(-?\d+(?:\.\d+)?)", s)
    if not m:
        return "数据不足"
    x = float(m.group(1))
    if "%" in s:
        return f"{x:.2f}%"
    if 0 <= x <= 10:
        return f"{x:.2f}%"
    return "数据不足"


def _normalize_drawdown_snapshot(v: Any, allow_positive: bool = False) -> str:
    s = _clean_text(v, "数据不足")
    if s == "数据不足":
        return s
    m = re.search(r"(-?\d+(?:\.\d+)?)", s)
    if not m:
        return "数据不足"
    x = float(m.group(1))
    if not allow_positive and x > 0:
        return "数据不足"
    return f"{x:.2f}%"


def _status_from_report(report: Dict[str, Any]) -> str:
    for v in report.values():
        s = str(v or "")
        if "数据不足" in s or "未接入" in s or "暂不可用" in s:
            return "data_source_degraded"
    return "ok"


def _normalize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(report or {})
    now = datetime.now()

    # 1) 基础时间兜底，避免“日期待定/时间待定”
    if not _clean_text(out.get("date"), ""):
        out["date"] = now.strftime("%Y-%m-%d")
    if not _clean_text(out.get("time"), ""):
        out["time"] = now.strftime("%H:%M")
    if not _clean_text(out.get("time_ref"), ""):
        out["time_ref"] = str(out.get("time"))

    # 2) 兼容旧键名（历史 prompt/记忆污染导致）
    alias = {
        "hs300_position": "hs300_strength",
        "gem_position": "gem_strength",
        "zz500_position": "zz500_strength",
        "position": "position_suggest",
        "etf_action": "510500_action",
    }
    for src, dst in alias.items():
        if not _clean_text(out.get(dst), ""):
            v = _clean_text(out.get(src), "")
            if v:
                out[dst] = v

    # 3) 对动作建议做最小补齐，避免整段空白
    if _clean_text(out.get("510300_action"), "") and not _clean_text(out.get("510500_action"), ""):
        out["510500_action"] = out["510300_action"]
    if _clean_text(out.get("510300_action"), "") and not _clean_text(out.get("159915_action"), ""):
        out["159915_action"] = "数据不足"

    # 4) 英文枚举归一，避免对外泄露 strong/hold/after_close
    for k in ("hs300_strength", "gem_strength", "zz500_strength"):
        v = _clean_text(out.get(k), "")
        if v:
            out[k] = _STRENGTH_MAP.get(v.lower(), v)
    for k in ("510300_action", "510500_action", "159915_action", "510300_position", "510500_position", "159915_position"):
        v = _clean_text(out.get(k), "")
        if v:
            out[k] = _ACTION_MAP.get(v.lower(), v)
    if _clean_text(out.get("time_ref"), "").lower() in ("after_close", "closed"):
        out["time_ref"] = "收盘后"

    # 5) 兼容上游把组合风控快照塞在嵌套字段里
    risk_obj = report.get("portfolio_risk_snapshot") or report.get("risk_snapshot")
    if isinstance(risk_obj, dict):
        if not _clean_text(out.get("var_snapshot"), ""):
            v = risk_obj.get("var_historical_pct")
            if isinstance(v, (int, float)):
                out["var_snapshot"] = f"{float(v):.2f}%"
        if not _clean_text(out.get("max_dd_snapshot"), ""):
            v = risk_obj.get("max_drawdown_pct")
            if isinstance(v, (int, float)):
                out["max_dd_snapshot"] = f"{float(v):.2f}%"
        if not _clean_text(out.get("current_dd_snapshot"), ""):
            v = risk_obj.get("current_drawdown_pct")
            if isinstance(v, (int, float)):
                out["current_dd_snapshot"] = f"{float(v):.2f}%"
        if not _clean_text(out.get("position_risk_snapshot"), ""):
            pos = risk_obj.get("current_position_pct")
            flag = _clean_text(risk_obj.get("position_risk_flag"), "")
            if isinstance(pos, (int, float)):
                out["position_risk_snapshot"] = f"{float(pos):.0f}% / {flag or '数据不足'}"

    return out


def _report_coverage(report: Dict[str, Any]) -> Dict[str, Any]:
    present = 0
    missing_keys = []
    for k in _REQUIRED_REPORT_KEYS:
        v = _clean_text(report.get(k), "")
        if v and v != "数据不足":
            present += 1
        else:
            missing_keys.append(k)
    total = len(_REQUIRED_REPORT_KEYS)
    ratio = (present / total) if total else 0.0
    return {
        "present": present,
        "total": total,
        "ratio": ratio,
        "missing_keys": missing_keys,
    }


def _build_degrade_reason(report: Dict[str, Any], coverage: Dict[str, Any]) -> str:
    reasons = []
    ratio = float(coverage.get("ratio") or 0.0)
    if ratio < 0.6:
        reasons.append(f"关键字段覆盖率偏低（{coverage.get('present')}/{coverage.get('total')}）")
    if _clean_text(report.get("zz500_change"), "数据不足") == "数据不足":
        reasons.append("中证500指数数据缺失")
    if _normalize_var_snapshot(report.get("var_snapshot")) == "数据不足":
        reasons.append("组合风控快照口径不足")
    if not reasons:
        reasons.append("部分数据源临时不可用")
    return "；".join(reasons[:3])


def _build_message(phase: str, report: Dict[str, Any], run_status: str, degrade_reason: str = "") -> str:
    label = _normalize_phase_label(phase, report)
    d = lambda k, default="数据不足": _clean_text(report.get(k), default)
    time_text = d("time", "时间待定")
    market_state = _normalize_market_state(report.get("market_state"))
    remain_window = _normalize_remain_window(report.get("remain_window"))
    # 收盘后兜底：避免出现“剩余交易时间约2小时”这类时序冲突
    if market_state.startswith("收盘") and remain_window not in ("收盘", "数据不足"):
        remain_window = "收盘"
    hs300_change = _to_pct_text(report.get("hs300_change"))
    gem_change = _to_pct_text(report.get("gem_change"))
    zz500_change = _to_pct_text(report.get("zz500_change"))
    # 兜底：当强弱字段被错填为百分比时，强弱回退为“中性”
    hs300_strength = d("hs300_strength", "中性")
    gem_strength = d("gem_strength", "中性")
    zz500_strength = d("zz500_strength", "中性")
    if "%" in hs300_strength:
        hs300_strength = "中性"
    if "%" in gem_strength:
        gem_strength = "中性"
    if "%" in zz500_strength:
        zz500_strength = "中性"
    reason_line = f"降级原因：{degrade_reason}\n\n" if degrade_reason else ""
    msg = (
        f"【宽基ETF巡检快报】 {d('date', '日期待定')} {label} {time_text}\n\n"
        "一、当前时段市场快照\n\n"
        "| 指数 | 涨跌幅 | 强弱判定 |\n"
        "|---|---:|---|\n"
        f"| 沪深300 | {hs300_change} | {hs300_strength} |\n"
        f"| 创业板指 | {gem_change} | {gem_strength} |\n"
        f"| 中证500 | {zz500_change} | {zz500_strength} |\n\n"
        f"风格判定：{d('style_judgment')}\n\n"
        f"二、重点ETF实时位置（{_normalize_time_ref(report.get('time_ref'), time_text)})\n\n"
        "| ETF | 名称 | 现价 | 涨跌幅 | 位置描述 | 阻力 | 支撑 |\n"
        "|---|---|---:|---:|---|---:|---:|\n"
        f"| 510300 | 沪深300ETF | {d('510300_price')} | {_to_pct_text(report.get('510300_change'))} | {d('510300_position')} | {d('510300_resist')} | {d('510300_support')} |\n"
        f"| 510500 | 中证500ETF | {d('510500_price')} | {_to_pct_text(report.get('510500_change'))} | {d('510500_position')} | {d('510500_resist')} | {d('510500_support')} |\n"
        f"| 159915 | 创业板ETF | {d('159915_price')} | {_to_pct_text(report.get('159915_change'))} | {d('159915_position')} | {d('159915_resist')} | {d('159915_support')} |\n\n"
        f"三、时段交易提示（{remain_window})\n\n"
        f"当前态势：{market_state}\n\n"
        "主要关注：\n"
        f"- {d('focus1')}\n"
        f"- {d('focus2')}\n"
        f"- {d('focus3')}\n\n"
        "操作指令建议：\n"
        f"- 510300：{d('510300_action')}\n"
        f"- 510500：{d('510500_action')}\n"
        f"- 159915：{d('159915_action')}\n\n"
        f"风险等级：{_normalize_risk_level(report.get('risk_level'))}　　建议仓位：{d('position_suggest')}\n"
        f"下次更新：{d('next_update')}\n\n"
        "四、组合风险快览（`tool_portfolio_risk_snapshot`）\n\n"
        "| 指标 | 数值 |\n"
        "|---|---|\n"
        f"| VaR（95% 历史模拟，单日百分比） | {_normalize_var_snapshot(report.get('var_snapshot'))} |\n"
        f"| 最大回撤（%） | {_normalize_drawdown_snapshot(report.get('max_dd_snapshot'), allow_positive=False)} |\n"
        f"| 当前回撤（%） | {_normalize_drawdown_snapshot(report.get('current_dd_snapshot'), allow_positive=False)} |\n"
        f"| 参考仓位占比 / 仓位标志 | {d('position_risk_snapshot', '数据不足') if d('position_risk_snapshot', '数据不足').lower() != 'ok' else '数据不足'} |\n\n"
        f"{reason_line}"
    )
    rotation_top = report.get("rotation_top5") if isinstance(report.get("rotation_top5"), list) else []
    rotation_quality = _clean_text(report.get("rotation_quality_status"), "degraded")
    if rotation_top:
        rows = []
        for row in rotation_top[:5]:
            if not isinstance(row, dict):
                continue
            code = _clean_text(row.get("symbol") or row.get("etf_code"), "")
            score = row.get("score") if row.get("score") is not None else row.get("total_score")
            score_text = "数据不足"
            if isinstance(score, (int, float)):
                score_text = f"{float(score):.2f}"
            if code:
                rows.append(f"- {code}（综合分 {score_text}）")
        if rows:
            msg += "轮动推荐池（L4语义）\n\n" + "\n".join(rows) + "\n\n"
    elif rotation_quality != "ok":
        r_reason = _clean_text(report.get("rotation_degrade_reason"), "rotation_latest 缺失")
        msg += f"轮动推荐池（L4语义）\n\n- 当前不可用（{r_reason}），已降级为宽基风险快照口径。\n\n"
    tail_enabled = bool(report.get("tail_section_enabled"))
    tail = report.get("tail_advice") if isinstance(report.get("tail_advice"), dict) else {}
    if tail_enabled and tail:
        trend = tail.get("trend") if isinstance(tail.get("trend"), dict) else {}
        timing = tail.get("timing") if isinstance(tail.get("timing"), dict) else {}
        risk = tail.get("risk") if isinstance(tail.get("risk"), dict) else {}
        paths = tail.get("paths") if isinstance(tail.get("paths"), dict) else {}
        overnight_refs = tail.get("overnight_refs") if isinstance(tail.get("overnight_refs"), list) else []
        cons = paths.get("conservative") if isinstance(paths.get("conservative"), dict) else {}
        neut = paths.get("neutral") if isinstance(paths.get("neutral"), dict) else {}
        aggr = paths.get("aggressive") if isinstance(paths.get("aggressive"), dict) else {}
        foci = tail.get("next_focus") if isinstance(tail.get("next_focus"), list) else []
        msg += (
            "五、尾盘操作建议（基于次日预判）\n\n"
            f"| 次日预判逻辑 | {_clean_text(tail.get('next_day_basis'), '结合当日结构与风险快照进行预判。')} |\n"
            "| 项目 | 内容 |\n"
            "|---|---|\n"
            f"| 趋势视角（大势） | 建议：{_clean_text(trend.get('action'), '持有')}；说明：{_clean_text(trend.get('reason'))} |\n"
            f"| 择时视角（节奏） | 建议：{_clean_text(timing.get('action'), '持有')}；说明：{_clean_text(timing.get('reason'))} |\n"
            f"| 风控视角（门槛） | 建议：{_clean_text(risk.get('action'), '持有')}；说明：{_clean_text(risk.get('reason'))} |\n"
            f"| 指标结论 | {_clean_text(tail.get('indicator_conclusion'), '信号中性，按既定仓位纪律执行。')} |\n"
            f"| 阈值命中说明 | 趋势依据={_clean_text(trend.get('basis'))}；择时依据={_clean_text(timing.get('basis'))}；风控依据={_clean_text(risk.get('basis'))} |\n"
            f"| 保守路径 | {_clean_text(cons.get('action'), '持有')}（仓位上限 {_clean_text(cons.get('cap'), '20%')}） |\n"
            f"| 中性路径 | {_clean_text(neut.get('action'), '持有')}（仓位上限 {_clean_text(neut.get('cap'), '40%')}） |\n"
            f"| 积极路径 | {_clean_text(aggr.get('action'), '持有')}（仓位上限 {_clean_text(aggr.get('cap'), '60%')}） |\n"
        )
        if overnight_refs:
            refs_text = " / ".join(
                f"{_clean_text(x.get('name'))}:{'可用' if str(x.get('status')) == 'available' else '缺失'}"
                for x in overnight_refs if isinstance(x, dict)
            )
            msg += f"| 隔夜变量可用性 | {refs_text} |\n"
        if _clean_text(tail.get("degrade_reason"), ""):
            msg += f"| 降级说明 | {_clean_text(tail.get('degrade_reason'))} |\n"
        if foci:
            f1 = _clean_text(foci[0]) if len(foci) > 0 else "数据不足"
            f2 = _clean_text(foci[1]) if len(foci) > 1 else "数据不足"
            f3 = _clean_text(foci[2]) if len(foci) > 2 else "数据不足"
            msg += f"| 次日开盘关注 | 1) {f1}；2) {f2}；3) {f3} |\n\n"
    msg += f"INSPECTION_RUN_STATUS: {run_status}"
    return msg


def tool_send_signal_risk_inspection(
    report: Dict[str, Any],
    phase: str = "midday",
    mode: str = "prod",
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Dict[str, Any]:
    """
    专用工具：接收结构化 report 字段，渲染巡检模板并发送到钉钉。
    """
    if not isinstance(report, dict):
        return {"success": False, "message": "report 必须是对象", "data": None}

    report = _normalize_report(report)
    coverage = _report_coverage(report)
    run_status = _status_from_report(report)
    degrade_reason = ""
    if run_status == "data_source_degraded" or float(coverage.get("ratio") or 0.0) < 0.6:
        run_status = "data_source_degraded"
        degrade_reason = _build_degrade_reason(report, coverage)
    message = _build_message(phase=phase, report=report, run_status=run_status, degrade_reason=degrade_reason)

    from .send_dingtalk_message import tool_send_dingtalk_message

    result = tool_send_dingtalk_message(
        message=message,
        mode=mode,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
        # 巡检快报默认整条发送，避免章节被分片打散导致标题/分组缺失。
        # 若正文超长，底层仍会按长度自动分片兜底。
        split_markdown_sections=False,
    )

    delivery = result.get("delivery") if isinstance(result, dict) else None
    if isinstance(delivery, dict) and not delivery.get("ok"):
        delivery["status"] = "dingtalk_fail"
    result.setdefault("data", {})
    if isinstance(result["data"], dict):
        result["data"]["rendered_message"] = message
        result["data"]["phase"] = phase
        result["data"]["coverage"] = coverage
        result["data"]["delivery_source_of_truth"] = "toolResult.delivery"
        result["data"]["delivery_aux_field"] = "runs.deliveryStatus"
        result["data"]["delivery_truth"] = {
            "ok": bool(delivery.get("ok")) if isinstance(delivery, dict) else False,
            "status": str(delivery.get("status") or "") if isinstance(delivery, dict) else "unknown",
            "reason": str(delivery.get("reason") or "") if isinstance(delivery, dict) else "",
        }
    return result

