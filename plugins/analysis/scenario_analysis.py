"""
涨停回马枪盘后：情景推演 JSON 拼装（不调用 LLM）。
仅基于已传入字段生成占位结构，供 Agent 写正文。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _pick_nb_direction(nb: Any) -> Optional[str]:
    if not isinstance(nb, dict):
        return None
    if nb.get("status") != "success":
        return None
    sig = nb.get("signal")
    if isinstance(sig, dict):
        s = sig.get("strength") or sig.get("direction")
        if s is not None:
            return str(s)
    data = nb.get("data") or {}
    try:
        net = data.get("total_net")
        if net is None:
            return None
        v = float(net)
        if v > 0.5:
            return "northbound_net_in_positive"
        if v < -0.5:
            return "northbound_net_in_negative"
        return "northbound_neutral"
    except (TypeError, ValueError):
        return None


def _pick_calib(cal: Any) -> Optional[float]:
    if not isinstance(cal, dict):
        return None
    d = cal.get("data") if isinstance(cal.get("data"), dict) else cal
    if not isinstance(d, dict):
        return None
    v = d.get("impact_score")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def tool_build_limitup_scenarios(
    *,
    global_spot: Any = None,
    macro_commodities: Any = None,
    a50: Any = None,
    northbound: Any = None,
    overnight_calibration: Any = None,
    key_levels: Any = None,
    extra: Any = None,
) -> Dict[str, Any]:
    """
    根据已采集片段拼装 3 情景骨架；不得填充未提供的具体涨跌幅数字。
    """
    nb_dir = _pick_nb_direction(northbound)
    impact = _pick_calib(overnight_calibration)

    cond_up: List[str] = []
    cond_mid: List[str] = []
    cond_down: List[str] = []
    if nb_dir:
        cond_up.append(f"北向信号类别: {nb_dir}")
        cond_mid.append(f"北向信号类别: {nb_dir}")
        cond_down.append(f"北向信号类别: {nb_dir}")
    if impact is not None and impact > 0.15:
        cond_up.append(f"隔夜校准 impact_score>0（{impact}）")
        cond_down.append("若 impact 反向转负则需下调预期（以最新工具为准）")
    elif impact is not None and impact < -0.15:
        cond_down.append(f"隔夜校准 impact_score<0（{impact}）")
        cond_up.append("若 impact 显著转正需重新评估（以最新工具为准）")
    else:
        cond_mid.append(
            "隔夜校准偏离居中或数据不足 — 以实际 tool_overnight_calibration 输出为准"
        )

    for label, blob in (
        ("global_spot", global_spot),
        ("macro_commodities", macro_commodities),
        ("a50", a50),
        ("key_levels", key_levels),
        ("extra", extra),
    ):
        if blob is not None:
            cond_mid.append(f"已合并字段: {label}（正文请引用工具原始输出，勿编造细项）")

    disclaimer = (
        "以下情景仅为结构化研究提纲，不构成投资建议；所有数值须来自工具返回或明确标注缺失。"
    )

    out = {
        "optimistic": {
            "title": "情景A（偏乐观）",
            "conditions": cond_up or ["待补充：需引用外盘/北向/板块实际读数"],
            "position_hint": "风险承受范围内轻仓试多，设好止损",
        },
        "neutral": {
            "title": "情景B（震荡）",
            "conditions": cond_mid
            or ["待补充：区间上沿下设观察，量能验证"],
            "position_hint": "控制仓位，结构化轮动",
        },
        "pessimistic": {
            "title": "情景C（偏悲观）",
            "conditions": cond_down
            or ["待补充：若主线退潮与资金流出共振则偏守"],
            "position_hint": "防守为主，减少追高",
        },
        "disclaimer": disclaimer,
    }
    return {"success": True, "message": "ok", "data": out}
