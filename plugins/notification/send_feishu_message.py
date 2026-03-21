"""
兼容层：发送飞书消息（旧入口）
将旧的 tool_send_feishu_message / send_feishu_message 统一转发到 merged 工具 tool_send_feishu_notification。
"""

from typing import Optional, Dict, Any


def send_feishu_message(
    content: str,
    title: Optional[str] = None,
    message_type: str = "text",
    **kwargs,
) -> Dict[str, Any]:
    """
    兼容旧接口：send_feishu_message(message_type, content, ...)
    这里只做文本消息转发；message_type 参数保留但目前仅支持 text。
    """
    try:
        from merged.send_feishu_notification import tool_send_feishu_notification
    except ImportError:
        from plugins.merged.send_feishu_notification import tool_send_feishu_notification  # type: ignore

    return tool_send_feishu_notification(
        notification_type="message",
        title=title,
        message=content,
        **kwargs,
    )


def tool_send_feishu_message(
    message: str,
    title: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """OpenClaw 工具：发送飞书文本消息（兼容层）"""
    return send_feishu_message(content=message, title=title, **kwargs)

