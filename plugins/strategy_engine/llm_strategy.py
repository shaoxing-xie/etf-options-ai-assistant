"""
LLM / ML 策略占位：v1 默认不启用；结构化输出约定见架构文档。
"""

from __future__ import annotations

from typing import Any, Dict, List

from strategy_engine.schemas import SignalCandidate


def generate_llm_candidates(_context: Dict[str, Any]) -> List[SignalCandidate]:
    """未来：解析 LLM JSON -> SignalCandidate。v1 返回空列表。"""
    return []


class MLStrategy:
    """可选插件占位，未实现。"""

    @staticmethod
    def generate(_market_data: Dict[str, Any]) -> List[SignalCandidate]:
        raise NotImplementedError("MLStrategy 未在 v1 实现；请使用 Rule + Fusion")
