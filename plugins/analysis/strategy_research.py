from __future__ import annotations

from typing import Any, Dict, List, Optional


def tool_strategy_research(
    *,
    lookback_days: int = 120,
    strategies: str = "trend_following,mean_reversion,breakout",
    adjustment_rate: float = 0.1,
    mode: str = "prod",
) -> Dict[str, Any]:
    """
    OpenClaw 工具：策略研究与回放评估（研究级）

    目标：
    - 复用现有策略表现/评分/权重工具，生成一份研究报告（Markdown llm_summary）
    - 输出“权重调整建议”，但不直接强制线上生效（是否落盘由上层工作流/人工决定）
    """
    from datetime import datetime

    from merged.strategy_analytics import tool_strategy_analytics
    from merged.strategy_weights import tool_strategy_weights
    try:
        from analysis.market_regime import tool_detect_market_regime
    except Exception:
        tool_detect_market_regime = None  # type: ignore[assignment]

    # Parse strategies
    strategy_list = [s.strip() for s in (strategies or "").split(",") if s.strip()]
    if not strategy_list:
        return {"success": False, "message": "strategies 不能为空", "data": None}

    perf_results: Dict[str, Any] = {}
    score_results: Dict[str, Any] = {}
    errors: List[str] = []

    # 1) Current weights
    weights_out = tool_strategy_weights(action="get")
    current_weights = (weights_out.get("data") or {}).get("weights") if isinstance(weights_out, dict) else None

    # 2) Per-strategy performance + score (best-effort)
    for st in strategy_list:
        try:
            perf = tool_strategy_analytics(action="performance", strategy=st, lookback_days=int(lookback_days))
            perf_results[st] = perf
        except Exception as e:
            errors.append(f"{st}: performance error: {e}")
            perf_results[st] = {"success": False, "message": str(e), "data": None}

        try:
            sc = tool_strategy_analytics(action="score", strategy=st, lookback_days=int(lookback_days), min_signals=10)
            score_results[st] = sc
        except Exception as e:
            errors.append(f"{st}: score error: {e}")
            score_results[st] = {"success": False, "message": str(e), "data": None}

    # 3) Market Regime (best-effort)
    regime_info: Dict[str, Any] = {}
    regime_line = ""
    if tool_detect_market_regime is not None:
        try:
            r_out = tool_detect_market_regime(symbol="510300", mode="prod")
            if isinstance(r_out, dict) and r_out.get("success"):
                data = r_out.get("data") or {}
                regime_info = data
                regime = data.get("regime")
                conf = data.get("confidence")
                if regime:
                    regime_line = f"- 当前 Market Regime（基于 510300）: **{regime}**（置信度约 {conf:.2f}），后文策略表现与权重建议均应在该状态下理解。"
        except Exception:
            regime_info = {}
            regime_line = ""

    # 4) Proposed weight adjustments (best-effort)
    proposal_out: Optional[Dict[str, Any]] = None
    try:
        proposal_out = tool_strategy_weights(
            action="adjust",
            current_weights=current_weights,
            lookback_days=int(lookback_days),
            adjustment_rate=float(adjustment_rate),
        )
    except Exception as e:
        errors.append(f"weights adjust error: {e}")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build Markdown summary (research mode one friendly)
    lines: List[str] = []
    lines.append("**📊 核心结论**：策略研究与回放评估已完成（研究级，不构成交易指令）。")
    lines.append("")
    lines.append("**📉 可执行建议 / 参数方案**：")
    lines.append("- 建议将本报告作为“策略启停/权重微调”的依据之一；实际执行仍需通过 risk_check 与人工审核。")
    if regime_line:
        lines.append(regime_line)
    if isinstance(proposal_out, dict) and proposal_out.get("success"):
        lines.append("- 已生成权重调整建议（见下方“权重建议”小节）。")
    lines.append("")
    lines.append("**⚠️ 风险提示**：")
    lines.append("- 回放评估依赖历史信号与缓存行情，存在样本外失效风险；需按 Market Regime 分层持续验证。")
    if errors:
        lines.append(f"- 本次评估存在 {len(errors)} 条警告/失败（详见 data.errors）。")
    lines.append("")
    lines.append("**📂 数据与来源**：")
    lines.append("- 来源：tool_strategy_analytics(performance/score) 与 tool_strategy_weights(get/adjust)。")
    lines.append(f"- 时间窗口：最近 {int(lookback_days)} 天。")
    lines.append("")
    lines.append("**🧭 下一步行动建议**：")
    lines.append("- 建议将策略表现按 Market Regime（趋势/震荡/高波动风险）分 bucket，避免“单一权重适配所有行情”。")
    lines.append("")
    lines.append("**🔍 高密度要点总结**：")
    lines.append(f"- 时间：{ts}")
    lines.append(f"- 策略集合：{', '.join(strategy_list)}")
    lines.append(f"- 权重建议：{'已生成' if (isinstance(proposal_out, dict) and proposal_out.get('success')) else '未生成/失败'}")

    # Compact table (best-effort: read common fields if present)
    table = [
        "| 策略 | performance.success | score.success | 备注 |",
        "|---|---:|---:|---|",
    ]
    for st in strategy_list:
        p_ok = bool((perf_results.get(st) or {}).get("success"))
        s_ok = bool((score_results.get(st) or {}).get("success"))
        note = ""
        if not p_ok:
            note = (perf_results.get(st) or {}).get("message", "")[:60]
        elif not s_ok:
            note = (score_results.get(st) or {}).get("message", "")[:60]
        table.append(f"| {st} | {str(p_ok).lower()} | {str(s_ok).lower()} | {note} |")

    weight_section = []
    weight_section.append("### 🧮 权重建议（研究级）")
    if isinstance(proposal_out, dict) and proposal_out.get("success"):
        weight_section.append("已生成权重调整建议（建议人工审核后再落盘）：")
        weight_section.append("```json")
        weight_section.append(str((proposal_out.get('data') or {}) if isinstance(proposal_out, dict) else {}))
        weight_section.append("```")
    else:
        weight_section.append("本次未生成权重调整建议（可能是当前权重缺失或评分数据不足）。")

    llm_summary = "\n".join(lines) + "\n\n" + "\n".join(table) + "\n\n" + "\n".join(weight_section)

    return {
        "success": True,
        "message": "strategy_research ok",
        "data": {
            "timestamp": ts,
            "lookback_days": int(lookback_days),
            "strategies": strategy_list,
            "performance": perf_results,
            "scores": score_results,
            "current_weights": current_weights,
            "proposal": proposal_out,
            "regime": regime_info,
            "errors": errors,
            "report_data": {
                "report_type": "strategy_research",
                "llm_summary": llm_summary,
                "raw": {
                    "performance": perf_results,
                    "scores": score_results,
                    "current_weights": current_weights,
                    "proposal": proposal_out,
                    "errors": errors,
                },
            },
        },
    }

