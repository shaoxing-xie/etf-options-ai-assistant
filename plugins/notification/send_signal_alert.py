"""
发送交易信号提醒（飞书通知）

说明：
- 工作流脚本期望存在 `notification.send_signal_alert.tool_send_signal_alert`
- 实际发送能力复用合并工具 `merged.send_feishu_notification.tool_send_feishu_notification`
- 默认 mode="prod"：真实发送到飞书 webhook
- mode="test"：仅做格式化/校验，不发出网络请求（用于 step_by_step 工作流测试，避免刷屏）
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import json


def _strength_level(s: Optional[str]) -> int:
    if not s:
        return 0
    s2 = str(s).strip().lower()
    mapping = {
        "low": 1,
        "weak": 1,
        "medium": 2,
        "mid": 2,
        "high": 3,
        "strong": 3,
        "very_high": 4,
        "veryhigh": 4,
    }
    return mapping.get(s2, 0)


def _should_send(signal_strength: Optional[str], min_signal_strength: str) -> Tuple[bool, str]:
    cur = _strength_level(signal_strength)
    min_lv = _strength_level(min_signal_strength)
    if min_lv <= 0:
        min_lv = 2  # 默认 medium
    return cur >= min_lv, f"{signal_strength or 'unknown'} >= {min_signal_strength}"


def _to_pretty_text(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(data)


def tool_send_signal_alert(
    signal_data: Dict[str, Any],
    min_signal_strength: str = "medium",
    webhook_url: Optional[str] = None,
    mode: str = "prod",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    工具：发送交易信号提醒到飞书。

    Args:
        signal_data: 信号数据（建议包含 signal_type / signal_strength / underlying 等字段）
        min_signal_strength: 最小发送强度（low/medium/high/very_high）
        webhook_url: 覆盖配置中的 notification.feishu_webhook（可选）
        mode: "prod" 真实发送；"test" 不发送（dry-run）
    """
    signal_strength = None
    if isinstance(signal_data, dict):
        signal_strength = signal_data.get("signal_strength")

    ok, cmp_desc = _should_send(signal_strength, min_signal_strength)
    if not ok:
        return {
            "success": True,
            "skipped": True,
            "message": f"条件跳过: 信号强度不满足 ({cmp_desc})",
            "data": {
                "signal_strength": signal_strength,
                "min_signal_strength": min_signal_strength,
            },
        }

    signal_type = None
    underlying = None
    if isinstance(signal_data, dict):
        signal_type = signal_data.get("signal_type") or signal_data.get("action")
        underlying = signal_data.get("underlying") or signal_data.get("symbol") or signal_data.get("etf_symbol")

    title = "交易信号提醒"
    if signal_type or underlying:
        parts = []
        if signal_type:
            parts.append(str(signal_type))
        if underlying:
            parts.append(str(underlying))
        title += f" ({' '.join(parts)})"

    structured_message = _to_pretty_text(signal_data)

    if str(mode).lower() != "prod":
        return {
            "success": True,
            "skipped": True,
            "message": f"dry-run: {title}",
            "data": {
                "title": title,
                "signal_strength": signal_strength,
                "min_signal_strength": min_signal_strength,
            },
        }

    try:
        from merged.send_feishu_notification import tool_send_feishu_notification
    except ImportError:
        from plugins.merged.send_feishu_notification import tool_send_feishu_notification  # type: ignore

    return tool_send_feishu_notification(
        notification_type="signal_alert",
        title=title,
        structured_message=structured_message,
        signal_data=signal_data,
        webhook_url=webhook_url,
        **kwargs,
    )

