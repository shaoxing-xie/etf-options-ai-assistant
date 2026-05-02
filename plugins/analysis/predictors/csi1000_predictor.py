from __future__ import annotations

from typing import Any, Dict, List

from .common import clamp, result, safe_float


def predict_csi1000(index_features: Dict[str, Any], *, trade_date: str, predict_for_trade_date: str) -> Dict[str, Any]:
    reasons: List[str] = []
    ret10 = safe_float(index_features.get("ret10"))
    ret5 = safe_float(index_features.get("ret5"))
    smb_limit_ratio = safe_float(index_features.get("smallcap_limit_up_ratio"))
    margin_change = safe_float(index_features.get("margin_change_proxy"))
    market_main_force_score = safe_float((index_features.get("market_main_force") or {}).get("market_main_force_score"))
    kronos_available = bool(index_features.get("kronos_available"))
    kronos_score = safe_float(index_features.get("kronos_score"))
    kronos_reason = str(index_features.get("degraded_reason") or "").strip()

    if ret10 is None:
        reasons.append("missing_ret10")
        ret10 = 0.0
    if ret5 is None:
        reasons.append("missing_ret5")
        ret5 = 0.0
    if smb_limit_ratio is None:
        reasons.append("missing_smallcap_limit_up_ratio")
        smb_limit_ratio = 0.0
    if margin_change is None:
        reasons.append("missing_margin_change_proxy")
        margin_change = 0.0
    if market_main_force_score is None:
        market_main_force_score = 0.0
    if kronos_available and kronos_score is None:
        reasons.append("kronos_score_missing")
        kronos_available = False
    elif (not kronos_available) and kronos_reason:
        reasons.append(kronos_reason)

    if ret10 > 0.08:
        reversal_score = -0.35
    elif ret10 > 0.04:
        reversal_score = -0.20
    elif ret10 < -0.08:
        reversal_score = 0.35
    elif ret10 < -0.04:
        reversal_score = 0.20
    else:
        reversal_score = 0.0

    sentiment_score = -0.15 if smb_limit_ratio > 0.25 else -0.08 if smb_limit_ratio > 0.18 else 0.0
    momentum_adjust = -0.05 if ret5 > 0.02 else 0.05 if ret5 < -0.02 else 0.0
    margin_score = clamp(margin_change, -0.1, 0.1) if margin_change is not None else 0.0
    money_score = clamp(market_main_force_score * 0.15, -0.08, 0.08)

    kronos_component = (kronos_score or 0.0) * 0.2 if kronos_available else 0.0
    score = reversal_score * 0.45 + sentiment_score * 0.2 + margin_score * 0.1 + momentum_adjust * 0.1 + money_score * 0.05 + kronos_component

    signals = {
        "ret10": round(ret10, 6),
        "ret5": round(ret5, 6),
        "reversal_score": round(reversal_score, 6),
        "smallcap_limit_up_ratio": round(smb_limit_ratio, 6),
        "sentiment_score": round(sentiment_score, 6),
        "margin_change_proxy": round(margin_change, 6),
        "market_main_force_score": round(market_main_force_score, 6),
        "kronos_available": kronos_available,
        "kronos_score": round(float(kronos_score or 0.0), 6),
    }
    reasoning = (
        f"中证1000以短期反转为主，ret10={ret10:.2%}、ret5={ret5:.2%}，"
        f"小盘涨停占比={smb_limit_ratio:.2%}。"
    )
    return result(
        index_code="000852.SH",
        index_name="中证1000",
        trade_date=trade_date,
        predict_for_trade_date=predict_for_trade_date,
        score=score,
        signals=signals,
        reasoning=reasoning,
        model_family="rule_plus_kronos_v1" if kronos_available else "rule_v1",
        degraded_reasons=reasons,
    )
