"""
发送分析类报告到钉钉自定义机器人（支持 SEC 加签）。

目标：
- 将“交易时间分析类报告/研究类报告”从原先的飞书日报发送，切换为钉钉 webhook 发送
- 不影响运维类消息：风控预警、信号提醒等仍走飞书（tool_send_risk_alert / tool_send_signal_alert）
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .send_dingtalk_message import _split_markdown_for_dingtalk, tool_send_dingtalk_message
from .send_daily_report import _format_daily_report


def tool_send_analysis_report(
    report_data: Dict[str, Any],
    report_date: Optional[str] = None,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    mode: str = "prod",
    split_markdown_sections: bool = False,
    max_chars_per_message: int = 1750,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    工具：发送分析类报告到钉钉（自定义机器人 webhook）

    Args:
        report_data: 报告数据（结构同 tool_send_daily_report）
        report_date: 报告日期（可选）
        webhook_url: 可选：自定义机器人 webhook（包含 access_token）
        secret: 可选：SEC 安全模式密钥（用于 sign）
        keyword: 可选：关键词安全校验用（如果机器人启用关键词）
        mode: prod|test（test 不发网络请求）
    """

    title, structured_message = _format_daily_report(report_data=report_data, report_date=report_date)

    if str(mode).lower() != "prod":
        parts = (
            _split_markdown_for_dingtalk(structured_message, max_chars_per_message)
            if split_markdown_sections
            else [structured_message]
        )
        return {
            "success": True,
            "skipped": True,
            "message": f"dry-run: {title}",
            "data": {
                "title": title,
                "preview": structured_message[:1800],
                "report_type": report_data.get("report_type"),
                "split_markdown_sections": split_markdown_sections,
                "multipart_parts": len(parts),
                "multipart_previews": [p[:320] for p in parts[:5]],
            },
        }

    # 复用现有 DingTalk tool：它会根据 secret 进行 SEC 加签，并在正文中按关键词校验要求补前缀
    return tool_send_dingtalk_message(
        message=structured_message,
        title=title,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
        mode=mode,
        split_markdown_sections=split_markdown_sections,
        max_chars_per_message=max_chars_per_message,
    )

