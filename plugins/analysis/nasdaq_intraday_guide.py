"""
513300 模式 A：基于动量、溢价、可选 VIX 的轻量规则摘要（非唯一交易结论）。
不包含 QQQ 资金流 / 期权 PCR（无契约数据源）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from plugins.analysis.nasdaq_next_open_predictor import _premium_thresholds_config, premium_risk_from_pct


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _guide_tier_from_replay_gate() -> tuple[str, Dict[str, Any]]:
    """experimental 直至 data/meta/intraday_guide_replay_gate.json passes_gate=true（计划 §4.6b）。"""
    p = _repo_root() / "data" / "meta" / "intraday_guide_replay_gate.json"
    meta: Dict[str, Any] = {}
    if not p.is_file():
        return "experimental", meta
    try:
        g = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(g, dict) and g.get("passes_gate") is True:
            meta = {"replay_generated_at": g.get("generated_at"), "metrics": g.get("metrics")}
            return "production", meta
    except Exception:
        pass
    return "experimental", meta


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _apply_premium_weight(weight: float, premium_pct: Optional[float]) -> float:
    if premium_pct is None:
        return weight
    x = float(premium_pct)
    if x >= 5.0:
        return weight * 0.5
    if x >= 4.0:
        return weight * 0.8
    if x < 2.0:
        return min(0.95, weight * 1.2)
    return weight


def build_intraday_guide(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    返回结构化摘要，供模板与 L4 追溯；不构成投资建议。
    """
    mc = report_data.get("monitor_context") if isinstance(report_data.get("monitor_context"), dict) else {}
    mp = str(mc.get("monitor_point") or report_data.get("monitor_point") or "M7").strip().upper()
    ana = report_data.get("analysis") if isinstance(report_data.get("analysis"), dict) else {}
    snap = report_data.get("tail_session_snapshot") if isinstance(report_data.get("tail_session_snapshot"), dict) else {}
    futures_ref = ana.get("futures_reference") if isinstance(ana.get("futures_reference"), dict) else {}
    momentum_pct = _safe_float(futures_ref.get("change_pct")) or _safe_float(ana.get("index_day_ret_pct"))
    premium_pct = _safe_float(ana.get("premium_rate_pct")) or _safe_float(snap.get("premium_pct"))

    global_snap = ana.get("global_risk_snapshot") if isinstance(ana.get("global_risk_snapshot"), dict) else {}
    vix = _safe_float(global_snap.get("vix")) or _safe_float(global_snap.get("^VIX"))
    usd_cnh = _safe_float(global_snap.get("usd_cnh")) or _safe_float(global_snap.get("USDCNH"))

    cfgp = _premium_thresholds_config()
    prem_risk = premium_risk_from_pct(premium_pct, cfgp)

    base_signal = "HOLD"
    weight = 0.5
    reasons: List[str] = []

    if momentum_pct is not None:
        if float(momentum_pct) > 0.5:
            base_signal = "BUY"
            weight = min(0.8, 0.5 + abs(float(momentum_pct)) / 100.0)
            reasons.append(f"NQ动量约{momentum_pct:.2f}%")
        elif float(momentum_pct) < -0.5:
            base_signal = "SELL"
            weight = min(0.8, 0.5 + abs(float(momentum_pct)) / 100.0)
            reasons.append(f"NQ动量约{momentum_pct:.2f}%")

    if vix is not None:
        if float(vix) > 25 and base_signal == "BUY":
            weight = max(0.3, weight - 0.3)
            reasons.append(f"VIX={vix:.1f} 偏高，买入权重下调")
        elif float(vix) < 15 and base_signal != "HOLD":
            weight = min(0.9, weight + 0.1)
            reasons.append(f"VIX={vix:.1f} 偏低，趋势确认略强化")

    weight = _apply_premium_weight(weight, premium_pct)
    if premium_pct is not None:
        reasons.append(f"溢价率约{premium_pct:.2f}%")

    # M2：开盘确认阶段「一致性降权」——动量弱于阈值时不强化方向信念
    if mp == "M2":
        if momentum_pct is None:
            weight = max(0.25, float(weight) * 0.9)
            mp_notes_pre_m2 = ["M2：动量缺失，一致性降权"]
        elif abs(float(momentum_pct)) < 0.35:
            weight = max(0.25, float(weight) * 0.88)
            mp_notes_pre_m2 = ["M2：动量偏弱，一致性降权（避免过早追涨/杀跌）"]
        else:
            mp_notes_pre_m2 = []
    else:
        mp_notes_pre_m2 = []

    # 时点提示（与计划 M1/M7 对齐；其余时点仅覆写文案权重）
    mp_notes: List[str] = list(mp_notes_pre_m2)
    if mp == "M1" and premium_pct is not None:
        if float(premium_pct) < 2.0:
            mp_notes.append("M1：溢价偏低区间，注意开盘流动性")
        elif float(premium_pct) > 4.0:
            mp_notes.append("M1：溢价偏高，慎追开盘")
    if mp == "M7":
        nod = report_data.get("next_open_direction") if isinstance(report_data.get("next_open_direction"), dict) else {}
        pdbg = nod.get("probability_debug") if isinstance(nod.get("probability_debug"), dict) else {}
        p_up = _safe_float(pdbg.get("p_up_final"))
        if p_up is None:
            p_up = _safe_float(nod.get("p_up"))
        if p_up is not None and premium_pct is not None:
            if float(p_up) > 0.6 and float(premium_pct) < 4.0:
                mp_notes.append("M7：次日看涨概率与溢价组合相对温和，可结合自身风控审视尾盘")
            elif float(p_up) < 0.4:
                mp_notes.append("M7：次日看跌概率偏高，注意隔夜风险")

    risk_gate = ana.get("risk_gate") if isinstance(ana.get("risk_gate"), dict) else {}
    gate_action = str(risk_gate.get("action") or risk_gate.get("action_state") or risk_gate.get("decision") or "").strip()
    conflict_flags: List[str] = []
    if gate_action and base_signal == "BUY" and gate_action in {"WAIT", "EXIT_REDUCE"}:
        conflict_flags.append("guide_buy_vs_risk_gate_conservative")
    if gate_action and base_signal == "SELL" and gate_action in {"GO", "GO_LIGHT"}:
        conflict_flags.append("guide_sell_vs_risk_gate_aggressive")

    guide_tier, replay_gate_meta = _guide_tier_from_replay_gate()

    out: Dict[str, Any] = {
        "monitor_point": mp,
        "signal": base_signal,
        "weight": round(float(weight), 4),
        "confidence_pct": round(float(weight) * 100.0, 2),
        "guide_tier": guide_tier,
        "replay_gate": replay_gate_meta,
        "rationale": "；".join(reasons + mp_notes) if (reasons or mp_notes) else "规则输入不足，倾向观望",
        "inputs": {
            "momentum_pct": momentum_pct,
            "premium_pct": premium_pct,
            "vix": vix,
            "usd_cnh": usd_cnh,
            "premium_risk_hint": round(float(prem_risk), 4),
            "fx_quality": global_snap.get("usd_cnh_quality") or global_snap.get("fx_quality"),
        },
        "notes": mp_notes,
        "conflict_flags": conflict_flags,
        "disclaimer": "非唯一参考倾向，不构成投资建议。",
    }
    return out
