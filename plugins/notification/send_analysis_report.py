"""
发送分析类报告到钉钉自定义机器人（支持 SEC 加签）。

实现说明：
- **统一委托** `send_daily_report.tool_send_daily_report`，确保与「市场日报」共用同一套
  prod 门禁、字段归一化与钉钉投递逻辑。
- 历史上 `tool_runner` 曾将 `tool_send_daily_report` 别名到本函数并直接调 `_format_daily_report`，
  会**绕过** `tool_send_daily_report` 内的校验，已改为在 `tool_runner` 中注册真实 `tool_send_daily_report`。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .send_daily_report import tool_send_daily_report


def tool_send_analysis_report(
    report_data: Optional[Dict[str, Any]] = None,
    report_date: Optional[str] = None,
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    keyword: Optional[str] = None,
    mode: str = "prod",
    split_markdown_sections: bool = True,
    max_chars_per_message: Optional[int] = None,
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
        split_markdown_sections: 默认 True，与「每日市场分析报告」一致按章节分条；需单条推送时显式 False。
    """
    return tool_send_daily_report(
        report_data=report_data,
        report_date=report_date,
        webhook_url=webhook_url,
        secret=secret,
        keyword=keyword,
        mode=mode,
        split_markdown_sections=split_markdown_sections,
        max_chars_per_message=max_chars_per_message,
        **kwargs,
    )
