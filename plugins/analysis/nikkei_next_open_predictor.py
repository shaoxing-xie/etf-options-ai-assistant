from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from plugins.analysis.nikkei_event_gate import calculate_event_gate

# --- 权重：期货 + 跨境估值（折价/收敛）+ 事件噪声；FX 占位 ---
WEIGHT_FUTURES = 0.38
WEIGHT_VALUATION = 0.22
WEIGHT_EVENTS = 0.25
WEIGHT_FX = 0.15

SPX_TO_NIKKEI_BETA = 0.54
USDJPY_BETA = 0.15
LEVERAGE_THRESHOLD_PCT = -1.5
FUTURES_SCORE_SCALE = 1.5
USE_BETA_IN_FUTURES_SCORE = False

# 略低于原 1.5，避免 sigmoid 过快饱和
ALPHA = 1.35
# 事件收缩略放松，避免 event_risk→1 时概率恒贴 0.5 却硬判「跌」
EVENT_SHRINK_K = 0.62

MIN_BACKTEST_SAMPLES = 20
EMPIRICAL_LOOKBACK = 60
EMPIRICAL_BLEND_MAX = 0.24
INTRINSIC_RISK_CAP = 0.26

LEVERAGE_RISK_LIFT = 0.12
RSI_RISK_LIFT = 0.08
DEVIATION_RISK_LIFT = 0.08
DEVIATION_WARN_PCT = 5.0

EVENT_TRIGGER_SCORE_PER = 0.028
EVENT_TRIGGER_SCORE_CAP = 0.16
OVERHEAT_PULLBACK_SCORE = -0.045

# 行业惯例：|P(up)−0.5| 过小不强行二元标签
EDGE_NO_SIGNAL_ABS = 0.018


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


def _empirical_prior_513880(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """513880 日线 close→次日 open 标签的滚动基率（与纳指预测器同源抽取逻辑）。"""
    try:
        from plugins.analysis.nasdaq_next_open_predictor import (
            _calc_close_to_next_open_labels,
            _extract_etf_klines,
        )
    except Exception:
        return {"p_base": None, "n": 0, "labels_count": 0}

    klines = _extract_etf_klines(report_data)
    labels = _calc_close_to_next_open_labels(klines)
    if not labels:
        return {"p_base": None, "n": 0, "labels_count": 0}
    dates = sorted(labels.keys())
    recent = dates[-EMPIRICAL_LOOKBACK :] if len(dates) > EMPIRICAL_LOOKBACK else dates
    if len(recent) < 12:
        return {"p_base": None, "n": len(recent), "labels_count": len(labels)}
    up = sum(int(labels[d]) for d in recent)
    n = len(recent)
    p_base = up / float(n)
    return {"p_base": p_base, "n": n, "labels_count": len(labels), "hit_rate_window_up": round(p_base, 4)}


def _valuation_score_next_open(
    premium: Dict[str, Any],
    analysis: Dict[str, Any],
    deviation_proxy: Dict[str, Any],
) -> Tuple[float, List[str]]:
    """
    跨境 ETF：深度折价 + 偏离收敛 → 次日 A 股开盘相对前收更易「修复性高开」的先验（有符号）。
    高溢价则略偏负（获利了结/溢价压缩），幅度保守。
    """
    prem = _safe_float(premium.get("premium_rate_pct"))
    if prem is None:
        prem = _safe_float(analysis.get("premium_rate_pct"))
    trend = str(deviation_proxy.get("deviation_trend") or "").strip().lower()
    score_v = 0.0
    notes: List[str] = []
    if prem is not None:
        if prem <= -1.2:
            score_v += _clip(abs(float(prem)) / 11.0, 0.0, 0.42)
            notes.append("discount_reopen_prior")
        if prem >= 2.0:
            score_v -= 0.11
            notes.append("premium_rich_soft_bear")
    if trend == "converging" and prem is not None and float(prem) < -1.0:
        score_v += 0.11
        notes.append("convergence_with_discount")
    return _clip(score_v, -0.5, 0.55), notes


def _is_signal_consistent(layer1_score: float, layer3_score: float, layer_val: float) -> bool:
    struct = float(layer1_score) + 0.45 * float(layer_val)
    return struct * float(layer3_score) > 0.0


def _calc_confidence(
    *,
    data_quality_normal: bool,
    event_risk: float,
    samples_count: int,
    signal_consistent: bool,
    monitor_point: str,
    no_statistical_edge: bool,
) -> Dict[str, str]:
    if not data_quality_normal:
        return {"level": "low", "reason": "数据质量降级"}
    if samples_count < MIN_BACKTEST_SAMPLES:
        return {"level": "low", "reason": f"样本不足({samples_count}/{MIN_BACKTEST_SAMPLES})"}
    if no_statistical_edge:
        return {"level": "medium", "reason": "概率接近均衡，无统计显著边际（不强行判定涨跌）"}
    if event_risk > 0.62:
        return {"level": "low", "reason": f"事件风险过高({event_risk:.2f})"}
    if event_risk > 0.34:
        return {"level": "medium", "reason": f"事件风险中等({event_risk:.2f})"}
    if signal_consistent:
        level = "high"
        reason = "数据质量正常+无重大事件+信号一致"
    else:
        level = "medium"
        reason = "信号一致性不足"
    if str(monitor_point or "").upper() in {"M1", "M2", "M3", "M4", "M5", "M6"} and level == "high":
        return {"level": "medium", "reason": "时点信息不完整，置信度上限为medium"}
    return {"level": level, "reason": reason}


def predict_next_open_direction(report_data: Dict[str, Any]) -> Dict[str, Any]:
    analysis = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
    monitor_ctx = report_data.get("monitor_context") if isinstance(report_data.get("monitor_context"), dict) else {}
    futures_ref = analysis.get("futures_reference") if isinstance(analysis.get("futures_reference"), dict) else {}
    premium = report_data.get("analysis_premium") if isinstance(report_data.get("analysis_premium"), dict) else {}
    deviation_proxy = analysis.get("deviation_proxy") if isinstance(analysis.get("deviation_proxy"), dict) else {}
    snap = report_data.get("tail_session_snapshot") if isinstance(report_data.get("tail_session_snapshot"), dict) else {}

    trade_date = str(report_data.get("trade_date") or report_data.get("date") or "").strip()
    monitor_point = str(monitor_ctx.get("monitor_point") or "M7").strip().upper()

    idx_ret_pct = _safe_float(analysis.get("index_day_ret_pct"))
    fut_change_pct = _safe_float(futures_ref.get("change_pct"))
    rsi14 = _safe_float(analysis.get("rsi14"))
    deviation_pct = _safe_float(deviation_proxy.get("deviation_pct"))

    degraded_reasons: List[str] = []

    if fut_change_pct is not None:
        beta = SPX_TO_NIKKEI_BETA if USE_BETA_IN_FUTURES_SCORE else 1.0
        score_futures = math.tanh(beta * float(fut_change_pct) / FUTURES_SCORE_SCALE)
    else:
        score_futures = 0.0
        degraded_reasons.append("PREDICTOR_NO_FUTURES_DATA")

    score_fx = 0.0
    degraded_reasons.append("PREDICTOR_NO_FX_INTRADAY")

    score_val, val_notes = _valuation_score_next_open(premium, analysis, deviation_proxy)

    event_gate = calculate_event_gate(trade_date)
    score_events = 0.0
    event_risk_calendar = _safe_float(event_gate.get("event_risk")) or 0.0
    layer3_notes: List[str] = []
    event_triggers = event_gate.get("event_triggers") if isinstance(event_gate.get("event_triggers"), list) else []
    impact_templates = event_gate.get("impact_templates") if isinstance(event_gate.get("impact_templates"), list) else []
    if str(event_gate.get("source_status") or "").strip().lower() != "ok":
        degraded_reasons.append("PREDICTOR_EVENT_GATE_DEGRADED")
    if event_triggers:
        score_events -= min(EVENT_TRIGGER_SCORE_CAP, EVENT_TRIGGER_SCORE_PER * float(len(event_triggers)))
        layer3_notes.append("event_gate_triggered")

    intrinsic_stack = 0.0
    if idx_ret_pct is not None:
        if idx_ret_pct <= LEVERAGE_THRESHOLD_PCT:
            intrinsic_stack += LEVERAGE_RISK_LIFT
            score_events += 0.05
            layer3_notes.append("leverage_effect_triggered")
        elif idx_ret_pct >= 1.5:
            score_events += OVERHEAT_PULLBACK_SCORE
            layer3_notes.append("overheat_pullback_risk")

    if rsi14 is not None and (rsi14 >= 70.0 or rsi14 <= 30.0):
        intrinsic_stack += RSI_RISK_LIFT
        layer3_notes.append("rsi_extreme")

    if deviation_pct is not None and abs(deviation_pct) >= DEVIATION_WARN_PCT:
        intrinsic_stack += DEVIATION_RISK_LIFT
        layer3_notes.append("deviation_extreme")

    premium_quality = str(premium.get("quality_status") or "").strip().lower()
    if premium_quality in {"degraded", "error"}:
        intrinsic_stack += 0.08
        layer3_notes.append(f"premium_quality_{premium_quality}")

    intrinsic_capped = min(INTRINSIC_RISK_CAP, intrinsic_stack)
    event_risk = _clip(float(event_risk_calendar) + intrinsic_capped, 0.0, 0.96)

    score_events = _clip(score_events, -0.8, 0.8)

    raw_score = (
        WEIGHT_FUTURES * score_futures
        + WEIGHT_VALUATION * score_val
        + WEIGHT_FX * score_fx
        + WEIGHT_EVENTS * score_events
    )
    p_up_raw = _sigmoid(ALPHA * raw_score)
    p_up_shrunk = 0.5 + (1.0 - EVENT_SHRINK_K * event_risk) * (p_up_raw - 0.5)
    p_up_shrunk = _clip(p_up_shrunk, 0.001, 0.999)

    emp = _empirical_prior_513880(report_data)
    p_base = emp.get("p_base")
    n_emp = int(emp.get("n") or 0)
    p_up = float(p_up_shrunk)
    empirical_weight = 0.0
    if p_base is not None and n_emp >= 18:
        empirical_weight = EMPIRICAL_BLEND_MAX * min(1.0, (n_emp - 12) / 48.0)
        p_up = (1.0 - empirical_weight) * p_up + empirical_weight * float(p_base)
        p_up = _clip(p_up, 0.001, 0.999)

    no_statistical_edge = abs(p_up - 0.5) < EDGE_NO_SIGNAL_ABS
    if no_statistical_edge:
        direction = "flat"
    else:
        direction = "up" if p_up >= 0.5 else "down"
    direction_prob = max(p_up, 1.0 - p_up)

    cfg_samples = max(0, int(report_data.get("next_open_nikkei_samples") or 0))
    current_samples = max(cfg_samples, n_emp, int(emp.get("labels_count") or 0))
    estimated_ready_date = _estimate_ready_date(trade_date, current_samples) if trade_date else None

    snap_dq = str(snap.get("data_quality") or "").strip().lower()
    premium_quality_bad = premium_quality in {"degraded", "error", "partial"}
    data_quality_normal = (
        not premium_quality_bad
        and snap_dq not in {"partial", "degraded", "error", "unknown"}
        and "PREDICTOR_NO_FUTURES_DATA" not in degraded_reasons
    )
    conf = _calc_confidence(
        data_quality_normal=data_quality_normal,
        event_risk=float(event_risk),
        samples_count=current_samples,
        signal_consistent=_is_signal_consistent(float(score_futures), float(score_events), float(score_val)),
        monitor_point=monitor_point,
        no_statistical_edge=no_statistical_edge,
    )
    confidence_level = conf["level"]
    confidence_reason = conf["reason"]

    decision = {
        "direction": direction,
        "p_up": round(p_up, 4),
        "direction_prob": round(direction_prob, 4),
        "confidence_level": confidence_level,
        "edge_mode": "no_statistical_edge" if no_statistical_edge else "directional",
        "components": [
            {
                "layer": "layer1_futures",
                "score": round(score_futures, 4),
                "weight": WEIGHT_FUTURES,
                "contribution": round(WEIGHT_FUTURES * score_futures, 4),
                "status": "ok" if fut_change_pct is not None else "degraded_no_data",
                "formula": "tanh(beta*futures_change_pct/FUTURES_SCORE_SCALE)",
                "futures_scale": FUTURES_SCORE_SCALE,
                "beta_used": (SPX_TO_NIKKEI_BETA if USE_BETA_IN_FUTURES_SCORE else 1.0),
            },
            {
                "layer": "layer1b_cross_border_valuation",
                "score": round(score_val, 4),
                "weight": WEIGHT_VALUATION,
                "contribution": round(WEIGHT_VALUATION * score_val, 4),
                "status": "ok",
                "notes": val_notes[:4],
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
                "event_risk_calendar": round(float(event_risk_calendar), 4),
                "intrinsic_risk_capped": round(intrinsic_capped, 4),
                "notes": layer3_notes[:8],
                "event_triggers": event_triggers[:5],
            },
        ],
        "event_gate": {
            "event_risk": round(event_risk, 4),
            "event_triggers": event_triggers[:8],
            "trigger_count": len(event_triggers),
            "impact_templates": impact_templates[:5],
            "source_status": event_gate.get("source_status"),
            "event_note": event_gate.get("event_note"),
        },
        "probability_debug": {
            "p_up_raw_pre_gate": round(p_up_raw, 6),
            "p_up_post_shrink": round(p_up_shrunk, 6),
            "event_risk": round(event_risk, 6),
            "p_up_final": round(p_up, 6),
            "raw_score": round(raw_score, 6),
            "empirical_blend_weight": round(empirical_weight, 4),
            "empirical_p_up_window": round(float(p_base), 6) if p_base is not None else None,
            "empirical_n_days": n_emp,
            "edge_threshold_abs": EDGE_NO_SIGNAL_ABS,
        },
        "backtest_stats": {
            "hit_rate_60d": emp.get("hit_rate_window_up"),
            "brier_60d": None,
            "n_60d": n_emp,
            "coverage_60d": None,
            "required_samples": MIN_BACKTEST_SAMPLES,
            "current_samples": current_samples,
            "estimated_ready_date": estimated_ready_date,
        },
        "method_note": "Phase B−lite: 513880 滚动基率校准 + 折价/收敛先验 + 事件收缩与无边际区；FX 仍待接入。",
        "limitation_note": "14:30 口径下真实收盘价未定型；次日开盘指 A 股交易时段开盘相对前收，不等同于日经现货隔夜涨跌。",
        "confidence_reason": confidence_reason,
        "degraded_reason": ",".join(degraded_reasons) if degraded_reasons else None,
        "probability_source": "rule+calibrated_prior",
    }
    return {"success": True, "decision": decision}
