from __future__ import annotations

from typing import Any, Dict, List

from .common import result, safe_float


def predict_shanghai(index_features: Dict[str, Any], *, trade_date: str, predict_for_trade_date: str) -> Dict[str, Any]:
    reasons: List[str] = []
    weights = index_features.get("weight_sector_changes") if isinstance(index_features.get("weight_sector_changes"), dict) else {}
    bank = safe_float(weights.get("bank"))
    non_bank = safe_float(weights.get("non_bank_fin"))
    petro = safe_float(weights.get("petro"))
    ret10 = safe_float(index_features.get("ret10"))
    volume_ratio = safe_float(index_features.get("volume_ratio_1d_5d"))

    if bank is None:
        reasons.append("missing_bank_sector_change")
        bank = 0.0
    if non_bank is None:
        reasons.append("missing_non_bank_sector_change")
        non_bank = 0.0
    if petro is None:
        reasons.append("missing_petro_sector_change")
        petro = 0.0
    if ret10 is None:
        reasons.append("missing_ret10")
        ret10 = 0.0
    if volume_ratio is None:
        reasons.append("missing_volume_ratio")
        volume_ratio = 1.0

    leading_pull = bank * 0.35 + non_bank * 0.25 + petro * 0.15
    if volume_ratio < 0.8:
        if ret10 > 0.05:
            reversal_signal = -0.15
        elif ret10 < -0.03:
            reversal_signal = 0.10
        else:
            reversal_signal = 0.0
    else:
        reversal_signal = 0.0
    momentum = 0.08 if ret10 > 0.02 else -0.05 if ret10 < -0.02 else 0.0

    score = leading_pull * 0.5 + reversal_signal * 0.3 + momentum * 0.2
    reasoning = (
        f"上证指数以权重板块牵引为主，银行={bank:.2%}、非银={non_bank:.2%}、石油石化={petro:.2%}，"
        f"量能比={volume_ratio:.2f}。"
    )
    return result(
        index_code="000001.SH",
        index_name="上证指数",
        trade_date=trade_date,
        predict_for_trade_date=predict_for_trade_date,
        score=score,
        signals={
            "leading_pull": round(leading_pull, 6),
            "reversal_signal": round(reversal_signal, 6),
            "momentum": round(momentum, 6),
            "volume_ratio_1d_5d": round(volume_ratio, 6),
        },
        reasoning=reasoning,
        model_family="rule_v1",
        degraded_reasons=reasons,
    )
