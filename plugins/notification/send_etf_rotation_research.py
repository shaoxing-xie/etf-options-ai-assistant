from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from analysis.etf_rotation_research import tool_etf_rotation_research

from .send_analysis_report import tool_send_analysis_report
from .send_etf_rotation_research_last_report import tool_send_etf_rotation_research_last_report


def tool_send_etf_rotation_research_report(
    *,
    etf_pool: str = "",
    trade_date: str = "",
    lookback_days: int = 120,
    top_k: int = 3,
    mode: str = "prod",
    config_path: Optional[str] = None,
    max_runtime_seconds: float = 1200.0,
    retry_runtime_seconds: float = 300.0,
    allow_online_backfill: bool = False,
    retry_allow_online_backfill: bool = True,
    idempotency_scope: str = "run",
) -> Dict[str, Any]:
    """
    封装工具：只用一次 toolCall 完成 ETF 轮动研究计算 + 发送分析报告。

    目的：
    - 强制 cron `etf-rotation-research` 只“发一次”，避免 agentTurn 重复调用导致的双投递。
    - 发送内容走同一份 report_data（与原先 tool_send_analysis_report 逻辑一致），降低 N/A 退化概率。
    """
    scope = str(idempotency_scope or "").strip().lower()
    if scope in {"run", "per_run", "auto"}:
        # 每次调用一个新 scope，保证“每次任务都发当次报告”，且不会被同日幂等挡住
        scope = "run_" + datetime.now().strftime("%Y%m%dT%H%M%S")
    rotation_out = tool_etf_rotation_research(
        etf_pool=etf_pool,
        trade_date=trade_date,
        lookback_days=lookback_days,
        top_k=top_k,
        mode=mode,
        config_path=config_path,
        max_runtime_seconds=float(max_runtime_seconds or 1200.0),
        light_mode=False,
        allow_online_backfill=bool(allow_online_backfill),
    )
    # Cron 常见失败为 pipeline_timeout（重计算阶段卡住）。触发后做一次轻量降级重试，
    # 以优先保证“可发送报告骨架”而非整轮失败。
    if isinstance(rotation_out, dict) and not rotation_out.get("success"):
        msg = str(rotation_out.get("message") or "")
        data = rotation_out.get("data") if isinstance(rotation_out.get("data"), dict) else {}
        errs = data.get("errors") if isinstance(data.get("errors"), list) else []
        warns = data.get("warnings") if isinstance(data.get("warnings"), list) else []
        merged = " | ".join([msg] + [str(x) for x in errs] + [str(x) for x in warns]).lower()
        try:
            retry_budget = float(retry_runtime_seconds)
        except Exception:
            retry_budget = 300.0
        if "pipeline_timeout" in merged and retry_budget > 0:
            rotation_out = tool_etf_rotation_research(
                etf_pool=etf_pool,
                trade_date=trade_date,
                lookback_days=min(int(lookback_days), 90),
                top_k=top_k,
                mode=mode,
                config_path=config_path,
                max_runtime_seconds=retry_budget,
                light_mode=True,
                allow_online_backfill=bool(retry_allow_online_backfill),
            )
    if not isinstance(rotation_out, dict) or not rotation_out.get("success"):
        # 兜底：计算阶段失败时尝试发送最近可用缓存，优先恢复钉钉送达链路。
        fallback_send = tool_send_etf_rotation_research_last_report(mode=mode, max_age_days=3, idempotency_scope=scope)
        if isinstance(fallback_send, dict) and fallback_send.get("success"):
            return {
                "success": True,
                "run_quality": "ok_degraded",
                "failure_code": "rotation_compute_failed_sent_cached_report",
                "message": "rotation compute failed, cached report sent",
                "data": {"rotation": rotation_out, "fallback_send": fallback_send},
            }
        return {
            "success": False,
            "run_quality": "error",
            "failure_code": "rotation_research_failed",
            "message": "etf rotation research failed",
            "data": {"rotation": rotation_out},
        }

    data = rotation_out.get("data") or {}
    report_data = data.get("report_data")
    if not isinstance(report_data, dict):
        # Some degraded-success paths return semantic artifacts but no report_data.
        # In that case, send last cached report to keep cron delivery healthy.
        fallback_send = tool_send_etf_rotation_research_last_report(mode=mode, max_age_days=3, idempotency_scope=scope)
        if isinstance(fallback_send, dict) and fallback_send.get("success"):
            return {
                "success": True,
                "run_quality": "ok_degraded",
                "failure_code": "missing_report_data_sent_cached_report",
                "message": "missing report_data, cached report sent",
                "data": {"rotation": rotation_out, "fallback_send": fallback_send},
            }
        return {
            "success": False,
            "run_quality": "error",
            "failure_code": "missing_report_data",
            "message": "missing report_data in rotation output",
            "data": {"rotation": rotation_out, "fallback_send": fallback_send},
        }

    # 幂等/锁统一由下游 send_analysis_report 负责，避免双层锁冲突导致“假成功未发送”
    send_out = tool_send_analysis_report(report_data=report_data, mode=mode, idempotency_scope=scope)
    send_ok = bool(isinstance(send_out, dict) and send_out.get("success"))
    send_skipped = bool(isinstance(send_out, dict) and send_out.get("skipped"))
    # 下游同日幂等：success=True + skipped=True（不再发第二条 Ding），对 cron/VERIFY 仍算「投递责任已满足」
    if send_ok and send_skipped:
        return {
            "success": True,
            "skipped": True,
            "run_quality": "ok_degraded",
            "failure_code": "none",
            "message": send_out.get("message") or "duplicate send skipped (idempotent)",
            "data": {"rotation": rotation_out.get("data"), "send": send_out},
        }
    if send_skipped and not send_ok:
        return {
            "success": False,
            "skipped": True,
            "run_quality": "error",
            "failure_code": "send_skipped_downstream",
            "error_code": "SEND_SKIPPED_DOWNSTREAM",
            "message": send_out.get("message") or "downstream send skipped",
            "data": {"rotation": rotation_out, "send": send_out},
        }
    if not send_ok:
        return {
            "success": False,
            "run_quality": "error",
            "failure_code": "send_analysis_report_failed",
            "message": "send analysis report failed",
            "data": {"rotation": rotation_out, "send": send_out},
        }

    return {
        "success": True,
        "run_quality": "ok_full",
        "failure_code": "none",
        "message": "etf rotation research report sent (single-send wrapper)",
        "data": {"rotation": rotation_out.get("data"), "send": locals().get("send_out", {})},
    }

