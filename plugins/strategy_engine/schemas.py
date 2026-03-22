"""
SignalCandidate / FusionResult — 全仓统一信号契约（v1.0）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class SignalCandidate:
    strategy_id: str
    symbol: str
    direction: str  # long | short | neutral
    score: float  # -1 .. 1
    confidence: float  # 0 .. 1
    rationale: str = ""
    rationale_refs: List[str] = field(default_factory=list)
    inputs_hash: str = ""
    features: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def direction_from_hold(d: str) -> str:
        """Grok hold -> neutral."""
        if not d:
            return "neutral"
        x = str(d).strip().lower()
        if x in ("hold", "wait", "none"):
            return "neutral"
        return x if x in ("long", "short", "neutral") else "neutral"


@dataclass
class FusionResult:
    strategy_id: str
    symbol: str
    direction: str
    score: float
    confidence: float
    rationale: str
    rationale_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
