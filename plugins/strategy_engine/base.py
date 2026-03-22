"""
轻量策略抽象：可扩展 Rule / LLM / ML Provider。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from strategy_engine.schemas import SignalCandidate


class BaseStrategy(ABC):
    """策略提供者：产出零条或多条 SignalCandidate。"""

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate(self, context: Dict[str, Any]) -> List[SignalCandidate]:
        raise NotImplementedError
