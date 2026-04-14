from __future__ import annotations

from typing import Any, Dict, List, Optional

from analysis.etf_rotation_core import (
    append_rotation_history,
    read_last_rotation_runs,
    resolve_etf_pool,
    run_rotation_pipeline,
)
from src.rotation_config_loader import load_rotation_config


def tool_etf_rotation_research(
    *,
    etf_pool: str = "",
    lookback_days: int = 120,
    top_k: int = 3,
    mode: str = "prod",
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：ETF 轮动研究（研究级）

    - 从本地缓存读取 ETF 日线（显式日期区间以支持 MA/相关性长窗）
    - 计算动量/波动/回撤/趋势 R²/平均相关性，并按配置过滤与加权
    - 输出排名与 Markdown 研究摘要

    Args:
        etf_pool: 逗号分隔 ETF 代码；留空则从 config/rotation_config.yaml + symbols.json 解析池
        lookback_days: 与 data_need 取较大值作为尾部截断下限
        top_k: 输出前 K 名
        mode: prod|test
        config_path: 可选，自定义 rotation 配置文件路径
    """
    from datetime import datetime

    try:
        from analysis.market_regime import tool_detect_market_regime
    except Exception:
        tool_detect_market_regime = None  # type: ignore[assignment]

    cfg = load_rotation_config(config_path)
    symbols = resolve_etf_pool(etf_pool if (etf_pool or "").strip() else None, cfg)
    if not symbols:
        return {"success": False, "message": "etf_pool 解析为空", "data": None}

    pipe = run_rotation_pipeline(symbols, cfg, lookback_days=lookback_days)
    errors = list(pipe.get("errors") or [])
    ranked = pipe.get("ranked_active") or []
    warnings = list(pipe.get("warnings") or [])
    fallback = bool(pipe.get("fallback_legacy_ranking"))
    corr_mat = pipe.get("correlation_matrix")
    corr_syms = pipe.get("correlation_symbols") or []
    config_snap = pipe.get("config_snapshot") or {}

    if not ranked:
        return {
            "success": False,
            "message": "无法生成轮动评分（无可用ETF数据）",
            "data": {"errors": errors, "warnings": warnings, "pipeline": pipe},
        }

    top_k = max(1, min(int(top_k), len(ranked)))
    top = ranked[:top_k]
    top_syms = [r.symbol for r in top]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    prev_runs = read_last_rotation_runs(3, cfg)

    if mode != "test":
        try:
            append_rotation_history(
                top_symbols=top_syms,
                top_k=top_k,
                pool_syms=symbols,
                config=cfg,
            )
        except Exception:
            pass

    last_three = prev_runs

    def fmt_pct(x: float) -> str:
        return f"{x*100:.2f}%"

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
                    regime_line = f"- 当前 Market Regime（基于 510300）: **{regime}**（置信度约 {conf:.2f}，用于理解轮动评分所处的市场环境）。"
        except Exception:
            regime_info = {}
            regime_line = ""

    lines: List[str] = []
    lines.append("**📊 核心结论**：ETF 轮动研究结果已生成（研究级，不构成交易指令）。")
    if fallback:
        lines.append("- **说明**：过滤后无可用标的，已退回 **legacy 评分** 排名。")
    lines.append("")
    lines.append("**📉 可执行建议 / 参数方案**：")
    lines.append(f"- 今日轮动候选（Top {top_k}）：{', '.join(top_syms)}")
    lines.append("- 建议用途：作为盘前/盘后研究参考；不直接替代工作流A的信号与风控结论。")
    lines.append("")
    lines.append("## 📈 市场状态（Market Regime）")
    if regime_line:
        lines.append(regime_line)
    else:
        lines.append("- 当前 Regime 暂未能可靠识别。")
    lines.append("")
    lines.append("## 🔗 相关性 / 均线诊断")
    lines.append(f"- 数据加载区间：{config_snap.get('load_range')}")
    lines.append(f"- 相关性模式：{config_snap.get('correlation_mode')}")
    if warnings:
        lines.append(f"- 相关性与对齐告警：{'; '.join(warnings)}")
    lines.append("")
    if corr_mat and corr_syms and len(corr_syms) <= 12:
        lines.append("相关矩阵（Pearson，收益样本；节选）：")
        hdr = "| | " + " | ".join(corr_syms) + " |"
        sep = "|---|" + "|".join(["---:"] * len(corr_syms)) + "|"
        lines.append(hdr)
        lines.append(sep)
        for a in corr_syms:
            row = [a]
            row_d = corr_mat.get(a) or {}
            for b in corr_syms:
                v = row_d.get(b)
                row.append(f"{float(v):.2f}" if v is not None else "")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    ma_lines = [f"| {r.symbol} | {'Above' if r.above_ma else 'Below' if r.above_ma is False else 'N/A'} | {r.mean_abs_corr:.3f} |" for r in ranked[:15]]
    if ma_lines:
        lines.append("| ETF | vs MA200 | 平均|ρ|（他标的）|")
        lines.append("|---|---:|---:|")
        lines.extend(ma_lines)
        lines.append("")
    vols = [r.vol_20d for r in ranked]
    if vols:
        lines.append(f"- 池内波动率（20d 年化）：min {fmt_pct(min(vols))} / max {fmt_pct(max(vols))}")
        lines.append("")
    if last_three:
        lines.append("## 📜 最近轮动记录（不含本轮）")
        for p in last_three:
            lines.append(
                f"- {p.get('timestamp')}: Top{p.get('top_k')} → {','.join(p.get('top_symbols') or [])}"
            )
        lines.append("")
    lines.append("## ⚠️ 风险提示")
    lines.append("- 轮动基于缓存日线与配置因子；对突发事件与流动性冲击敏感。")
    if errors:
        lines.append(f"- 数据缺失/计算失败：{len(errors)} 条（见 data.errors）。")
    lines.append("")
    lines.append("## 📂 数据与来源")
    lines.append("- 行情：read_cache_data → etf_daily（显式起止日期）。")
    lines.append("- 配置：`config/rotation_config.yaml`（权重、过滤、标的池）。")
    lines.append("")
    lines.append("## 🧭 下一步行动建议")
    lines.append("- 明日开盘前可再次运行，观察排名是否稳定。")
    lines.append("")
    lines.append("## 🔍 高密度要点总结")
    lines.append(f"- 时间：{ts}")
    lines.append(f"- Regime：{regime_info.get('regime') or 'unknown'}")
    lines.append(f"- Top{top_k}：{', '.join(top_syms)}")
    lines.append("- 用途：研究级关注列表，不构成建仓指令")

    table = [
        "| ETF | 20日动量 | 60日动量 | 20日波动 | 60日回撤 | R² | mean_abs_corr | Legacy | Score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in ranked[: min(len(ranked), 12)]:
        table.append(
            f"| {r.symbol} | {fmt_pct(r.momentum_20d)} | {fmt_pct(r.momentum_60d)} | {fmt_pct(r.vol_20d)} | "
            f"{fmt_pct(r.max_drawdown_60d)} | {r.trend_r2:.3f} | {r.mean_abs_corr:.3f} | {r.legacy_score:.4f} | {r.score:.4f} |"
        )

    llm_summary = "\n".join(lines) + "\n\n" + "\n".join(table)

    ranked_payload = [
        {
            "symbol": r.symbol,
            "score": r.score,
            "legacy_score": r.legacy_score,
            "momentum_20d": r.momentum_20d,
            "momentum_60d": r.momentum_60d,
            "vol_20d": r.vol_20d,
            "max_drawdown_60d": r.max_drawdown_60d,
            "trend_r2": r.trend_r2,
            "mean_abs_corr": r.mean_abs_corr,
            "above_ma": r.above_ma,
            "excluded": r.excluded,
            "exclude_reason": r.exclude_reason,
            "soft_penalties": r.soft_penalties,
        }
        for r in ranked
    ]

    return {
        "success": True,
        "message": "etf_rotation_research ok",
        "data": {
            "timestamp": ts,
            "etf_pool": symbols,
            "top_k": top_k,
            "ranked": ranked_payload,
            "warnings": warnings,
            "correlation_matrix": corr_mat,
            "fallback_legacy_ranking": fallback,
            "regime": regime_info,
            "errors": errors,
            "config_snapshot": config_snap,
            "report_data": {
                "report_type": "etf_rotation_research",
                "llm_summary": llm_summary,
                "raw": {
                    "ranked": ranked_payload,
                    "errors": errors,
                    "pipeline": pipe,
                },
            },
        },
    }
