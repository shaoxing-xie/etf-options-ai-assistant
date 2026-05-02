from __future__ import annotations

from typing import Any, Dict, List

from .common import clamp, result, safe_float


def predict_chinext(index_features: Dict[str, Any], *, trade_date: str, predict_for_trade_date: str) -> Dict[str, Any]:
    reasons: List[str] = []
    style = index_features.get("style") if isinstance(index_features.get("style"), dict) else {}
    fund_flow = index_features.get("fund_flow") if isinstance(index_features.get("fund_flow"), dict) else {}
    percentile = safe_float(style.get("style_spread_percentile"))
    spread = safe_float(style.get("ret_spread_3m"))
    ret10 = safe_float(index_features.get("ret10"))
    fund_score = safe_float(fund_flow.get("market_main_force_score"))

    if percentile is None:
        reasons.append("missing_style_spread_percentile")
        percentile = 50.0
    if spread is None:
        spread = 0.0
    if ret10 is None:
        reasons.append("missing_ret10")
        ret10 = 0.0
    if fund_score is None:
        reasons.append("missing_fund_flow_score")
        fund_score = 0.0

    if percentile > 90:
        mean_reversion = -0.30
    elif percentile < 10:
        mean_reversion = 0.30
    else:
        mean_reversion = 0.0
    momentum_score = 0.15 if ret10 > 0 else -0.15 if ret10 < 0 else 0.0
    fund_component = clamp(fund_score * 0.25, -0.2, 0.2)
    score = mean_reversion * 0.6 + fund_component * 0.25 + momentum_score * 0.15

    reasoning = (
        f"创业板指以风格极值回归为主，3个月相对红利收益差={spread:.2%}，"
        f"历史分位={percentile:.1f}。"
    )
    return result(
        index_code="399006.SZ",
        index_name="创业板指",
        trade_date=trade_date,
        predict_for_trade_date=predict_for_trade_date,
        score=score,
        signals={
            "ret_spread_3m": round(spread, 6),
            "style_spread_percentile": round(percentile, 4),
            "mean_reversion_signal": round(mean_reversion, 6),
            "fund_flow_score": round(fund_component, 6),
            "momentum_score": round(momentum_score, 6),
        },
        reasoning=reasoning,
        model_family="rule_v1",
        degraded_reasons=reasons,
    )
