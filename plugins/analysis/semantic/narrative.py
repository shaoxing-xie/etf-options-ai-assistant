from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from plugins.analysis.semantic.common import project_root

_RULES: Optional[Dict[str, Any]] = None


def load_rules() -> Dict[str, Any]:
    global _RULES
    if _RULES is not None:
        return _RULES
    p = project_root() / "config" / "semantic_context_rules.yaml"
    if not p.is_file():
        _RULES = {}
        return _RULES
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    _RULES = raw if isinstance(raw, dict) else {}
    return _RULES


def pick_percentile_label(pct: Optional[float], rules: Dict[str, Any]) -> str:
    if pct is None or pct != pct:
        return "percentile_unknown"
    bands = (rules.get("valuation") or {}).get("pe_percentile_bands") or []
    for b in bands:
        try:
            mx = float(b.get("max_exclusive", 101))
        except (TypeError, ValueError):
            continue
        if float(pct) < mx:
            return str(b.get("label_key") or "percentile_mid")
    return "percentile_mid"


def flow_score_label(score: Optional[float], rules: Dict[str, Any]) -> str:
    bands = (rules.get("flow_sentiment") or {}).get("flow_score_bands") or []
    if score is None or score != score:
        return "flow_unknown"
    for b in bands:
        try:
            mx = float(b.get("max_exclusive", 0))
        except (TypeError, ValueError):
            continue
        if float(score) < mx:
            return str(b.get("label_key") or "flow_neutral")
    return "flow_neutral"


def regime_display_key(regime: str, rules: Dict[str, Any]) -> str:
    m = (rules.get("market_regime") or {}).get("regime_labels") or {}
    return str(m.get(regime) or regime or "regime_unknown")


# Minimal CN snippets (deterministic; no LLM)
_LABEL_CN = {
    "percentile_low": "PE 分位偏低（相对历史样本偏便宜一侧）",
    "percentile_mid": "PE 分位处于中性区间",
    "percentile_high": "PE 分位偏高（相对历史样本偏贵一侧）",
    "percentile_unknown": "PE 分位暂不可用（样本或上游不足）",
    "flow_weak": "整体净流入偏弱",
    "flow_neutral": "整体净流入中性",
    "flow_strong": "整体净流入偏强",
    "flow_unknown": "资金流情绪刻画受限",
    "regime_uptrend": "趋势向上（研究标签）",
    "regime_downtrend": "趋势向下（研究标签）",
    "regime_range": "震荡整理（研究标签）",
    "regime_high_vol": "高波动风险（研究标签）",
    "regime_unknown": "市场状态刻画受限",
}


def cn_for_key(key: str) -> str:
    return _LABEL_CN.get(key, key)


def template_valuation_summary(
    *,
    name: str,
    code: str,
    pe: Optional[float],
    pb: Optional[float],
    pct: Optional[float],
    label_key: str,
    window_years: int,
) -> str:
    pe_s = f"{pe:.2f}" if pe is not None and pe == pe else "—"
    pb_s = f"{pb:.2f}" if pb is not None and pb == pb else "—"
    pct_s = f"{pct:.1f}" if pct is not None and pct == pct else "—"
    band = cn_for_key(label_key)
    return (
        f"{name}（{code}）：当前 PE(TTM)≈{pe_s}，PB≈{pb_s}；"
        f"近{window_years}年报告期 PE 经验分位≈{pct_s}%；{band}。"
    )
