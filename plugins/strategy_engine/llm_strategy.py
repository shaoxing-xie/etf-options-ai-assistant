"""
LLM / ML 策略占位：v1 默认不启用；结构化输出约定见架构文档。
"""

from __future__ import annotations

from typing import Any, Dict, List

from strategy_engine.schemas import SignalCandidate


def generate_llm_candidates(context: Dict[str, Any]) -> List[SignalCandidate]:
    """
    解析 LLM 结构化输出为 ``SignalCandidate``（未实现前恒为空列表）。

    调用约定：**仅**由 ``tool_strategy_engine`` 在
    ``config/strategy_fusion.yaml`` 的 ``providers.llm: true`` 时调用，并传入
    ``providers_llm=True``。不要在业务层再设独立的 ``llm_enabled`` 与 yaml 开关
    重复门控。其它入口若未传 ``providers_llm=True``，本函数直接返回空列表。
    """
    if context.get("providers_llm") is not True:
        return []
    return []


class MLStrategy:
    """可选插件占位，未实现。"""

    @staticmethod
    def generate(_market_data: Dict[str, Any]) -> List[SignalCandidate]:
        raise NotImplementedError("MLStrategy 未在 v1 实现；请使用 Rule + Fusion")
