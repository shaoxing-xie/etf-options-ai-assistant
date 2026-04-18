from __future__ import annotations

from typing import Any, Dict, Optional

from analysis.etf_rotation_research import tool_etf_rotation_research

from .send_analysis_report import tool_send_analysis_report


def tool_send_etf_rotation_research_report(
    *,
    etf_pool: str = "",
    lookback_days: int = 120,
    top_k: int = 3,
    mode: str = "prod",
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    封装工具：只用一次 toolCall 完成 ETF 轮动研究计算 + 发送分析报告。

    目的：
    - 强制 cron `etf-rotation-research` 只“发一次”，避免 agentTurn 重复调用导致的双投递。
    - 发送内容走同一份 report_data（与原先 tool_send_analysis_report 逻辑一致），降低 N/A 退化概率。
    """
    rotation_out = tool_etf_rotation_research(
        etf_pool=etf_pool,
        lookback_days=lookback_days,
        top_k=top_k,
        mode=mode,
        config_path=config_path,
    )
    if not isinstance(rotation_out, dict) or not rotation_out.get("success"):
        return {"success": False, "message": "etf rotation research failed", "data": {"rotation": rotation_out}}

    data = rotation_out.get("data") or {}
    report_data = data.get("report_data")
    if not isinstance(report_data, dict):
        return {"success": False, "message": "missing report_data in rotation output", "data": {"rotation": rotation_out}}

    # 幂等/锁统一由下游 send_analysis_report 负责，避免双层锁冲突导致“假成功未发送”
    send_out = tool_send_analysis_report(report_data=report_data, mode=mode)
    send_ok = bool(isinstance(send_out, dict) and send_out.get("success"))
    send_skipped = bool(isinstance(send_out, dict) and send_out.get("skipped"))
    # 下游同日幂等：success=True + skipped=True（不再发第二条 Ding），对 cron/VERIFY 仍算「投递责任已满足」
    if send_ok and send_skipped:
        return {
            "success": True,
            "skipped": True,
            "message": send_out.get("message") or "duplicate send skipped (idempotent)",
            "data": {"rotation": rotation_out.get("data"), "send": send_out},
        }
    if send_skipped and not send_ok:
        return {
            "success": False,
            "skipped": True,
            "error_code": "SEND_SKIPPED_DOWNSTREAM",
            "message": send_out.get("message") or "downstream send skipped",
            "data": {"rotation": rotation_out, "send": send_out},
        }
    if not send_ok:
        return {"success": False, "message": "send analysis report failed", "data": {"rotation": rotation_out, "send": send_out}}

    return {
        "success": True,
        "message": "etf rotation research report sent (single-send wrapper)",
        "data": {"rotation": rotation_out.get("data"), "send": locals().get("send_out", {})},
    }

