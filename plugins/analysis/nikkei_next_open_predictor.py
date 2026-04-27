from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

# --- 方法论常量（Phase A）---
WEIGHT_FUTURES = 0.50
WEIGHT_FX = 0.15
WEIGHT_EVENTS = 0.35

# 学术映射占位（Phase B 可回测校准）
SPX_TO_NIKKEI_BETA = 0.54
USDJPY_BETA = 0.15
LEVERAGE_THRESHOLD_PCT = -1.5

ALPHA = 1.5
EVENT_SHRINK_K = 0.8

MIN_BACKTEST_SAMPLES = 20

# TODO(PHASE_B): parameter calibration with rolling backtest
LEVERAGE_RISK_LIFT = 0.15
RSI_RISK_LIFT = 0.10
DEVIATION_RISK_LIFT = 0.10
DEVIATION_WARN_PCT = 5.0


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _sigmoid(x: float) -> float:
    x = _clip(float(x), -20.0, 20.0)
    return 1.0 / (1.0 + math.exp(-x))


def _parse_date(v: str) -> Optional[datetime]:
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _estimate_ready_date(trade_date: str, current_samples: int) -> Optional[str]:
    dt = _parse_date(trade_date)
    if dt is None:
        return None
    remaining = max(0, MIN_BACKTEST_SAMPLES - max(0, int(current_samples)))
    return (dt + timedelta(days=remaining)).strftime("%Y-%m-%d")


def predict_next_open_direction(report_data: Dict[str, Any]) -> Dict[str, Any]:
    analysis = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
    monitor_ctx = report_data.get("monitor_context") if isinstance(report_data.get("monitor_context"), dict) else {}
    futures_ref = analysis.get("futures_reference") if isinstance(analysis.get("futures_reference"), dict) else {}
    premium = report_data.get("analysis_premium") if isinstance(report_data.get("analysis_premium"), dict) else {}
    deviation_proxy = analysis.get("deviation_proxy") if isinstance(analysis.get("deviation_proxy"), dict) else {}

    trade_date = str(report_data.get("trade_date") or report_data.get("date") or "").strip()

    idx_ret_pct = _safe_float(analysis.get("index_day_ret_pct"))
    fut_change_pct = _safe_float(futures_ref.get("change_pct"))
    rsi14 = _safe_float(analysis.get("rsi14"))
    deviation_pct = _safe_float(deviation_proxy.get("deviation_pct"))

    degraded_reasons = []

    # Layer1: futures (明确公式，避免实现歧义)
    # score_futures = tanh(SPX_TO_NIKKEI_BETA * futures_change_pct / 0.5)
    # TODO(PHASE_B): 用滚动回测替换归一化尺度 0.5
    if fut_change_pct is not None:
        score_futures = math.tanh(SPX_TO_NIKKEI_BETA * float(fut_change_pct) / 0.5)
    else:
        score_futures = 0.0
        degraded_reasons.append("PREDICTOR_NO_FUTURES_DATA")

    # Layer2: FX (Phase A 不接入实时数据，保留权重结构并显式降级)
    score_fx = 0.0
    degraded_reasons.append("PREDICTOR_NO_FX_INTRADAY")

    # Layer3: events/risk gate proxy from existing fields
    score_events = 0.0
    event_risk = 0.0
    layer3_notes = []

    if idx_ret_pct is not None:
        if idx_ret_pct <= LEVERAGE_THRESHOLD_PCT:
            # 杠杆效应：负回报超过阈值时提高风险并给微弱反弹偏置
            event_risk += LEVERAGE_RISK_LIFT
            score_events += 0.05
            layer3_notes.append("leverage_effect_triggered")
        elif idx_ret_pct >= 1.5:
            # 大涨后次日开盘回调风险（轻微）
            score_events -= 0.10
            layer3_notes.append("overheat_pullback_risk")

    if rsi14 is not None and (rsi14 >= 70.0 or rsi14 <= 30.0):
        event_risk += RSI_RISK_LIFT
        layer3_notes.append("rsi_extreme")

    if deviation_pct is not None and abs(deviation_pct) >= DEVIATION_WARN_PCT:
        event_risk += DEVIATION_RISK_LIFT
        layer3_notes.append("deviation_extreme")

    premium_quality = str(premium.get("quality_status") or "").strip().lower()
    if premium_quality in {"degraded", "error"}:
        event_risk += 0.10
        layer3_notes.append(f"premium_quality_{premium_quality}")

    score_events = _clip(score_events, -0.8, 0.8)
    event_risk = _clip(event_risk, 0.0, 1.0)

    raw_score = (
        WEIGHT_FUTURES * score_futures
        + WEIGHT_FX * score_fx
        + WEIGHT_EVENTS * score_events
    )
    p_up_raw = _sigmoid(ALPHA * raw_score)
    p_up = 0.5 + (1.0 - EVENT_SHRINK_K * event_risk) * (p_up_raw - 0.5)
    p_up = _clip(p_up, 0.001, 0.999)

    direction = "up" if p_up >= 0.5 else "down"
    direction_prob = max(p_up, 1.0 - p_up)

    current_samples = 0
    if trade_date:
        current_samples = max(0, int(report_data.get("next_open_nikkei_samples") or 0))
    estimated_ready_date = _estimate_ready_date(trade_date, current_samples) if trade_date else None

    confidence_level = "medium"
    if (
        "PREDICTOR_NO_FUTURES_DATA" in degraded_reasons
        or event_risk > 0.5
        or current_samples < MIN_BACKTEST_SAMPLES
    ):
        confidence_level = "low"

    decision = {
        "direction": direction,
        "p_up": round(p_up, 4),
        "direction_prob": round(direction_prob, 4),
        "confidence_level": confidence_level,
        "components": [
            {
                "layer": "layer1_futures",
                "score": round(score_futures, 4),
                "weight": WEIGHT_FUTURES,
                "contribution": round(WEIGHT_FUTURES * score_futures, 4),
                "status": "ok" if fut_change_pct is not None else "degraded_no_data",
            },
            {
                "layer": "layer2_fx",
                "score": round(score_fx, 4),
                "weight": WEIGHT_FX,
                "contribution": round(WEIGHT_FX * score_fx, 4),
                "status": "degraded_no_data",
                "beta": USDJPY_BETA,
            },
            {
                "layer": "layer3_events",
                "score": round(score_events, 4),
                "weight": WEIGHT_EVENTS,
                "contribution": round(WEIGHT_EVENTS * score_events, 4),
                "event_risk": round(event_risk, 4),
                "notes": layer3_notes[:6],
            },
        ],
        "probability_debug": {
            "p_up_raw_pre_gate": round(p_up_raw, 6),
            "event_risk": round(event_risk, 6),
            "p_up_final": round(p_up, 6),
            "raw_score": round(raw_score, 6),
        },
        "backtest_stats": {
            "hit_rate_60d": None,
            "brier_60d": None,
            "n_60d": current_samples,
            "coverage_60d": None,
            "required_samples": MIN_BACKTEST_SAMPLES,
            "current_samples": current_samples,
            "estimated_ready_date": estimated_ready_date,
        },
        "method_note": "Phase A lightweight: no realtime USDJPY/V-Lab/calendar integration yet.",
        "limitation_note": "14:30 information is incomplete for next-open forecasting; confidence is capped conservatively.",
        "degraded_reason": ",".join(degraded_reasons) if degraded_reasons else None,
    }
    return {"success": True, "decision": decision}

