"""选股结果通知正文（钉钉/飞书结构化消息可复用）。"""

from __future__ import annotations

from typing import Any, Dict

from src.screening_utils import picks_for_notification


def format_screening_notice(payload: Dict[str, Any]) -> str:
    """将 `tool_screen_equity_factors` 返回 JSON 格式化为可读短讯。"""
    return picks_for_notification(payload)
