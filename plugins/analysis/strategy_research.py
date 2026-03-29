from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_strategy_research_config() -> Dict[str, Any]:
    path = _project_root() / "config" / "strategy_research.yaml"
    defaults: Dict[str, Any] = {
        "data_split": {"is_ratio": 0.5, "oos_ratio": 0.3, "holdback_ratio": 0.2},
        "enable_split_analysis": True,
        "trading_costs": {"enabled": False, "commission": 0.0, "slippage": 0.0},
        "wfe": {"warn_threshold": 0.5, "min_closed_is": 3, "min_closed_oos": 3},
        "complexity_penalty": {"enabled": True, "per_param": 0.02, "cap": 0.30},
        "strategy_param_counts": {},
        "holdback_gate": {"min_avg_return": 0.0, "min_gross_sharpe_like": 0.0},
        "backtest_log": {"enabled": False, "path": "data/backtest_logs/research_runs.jsonl"},
    }
    raw: Dict[str, Any] = {}
    try:
        import yaml  # type: ignore

        if yaml is not None and path.exists():
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
    except Exception:
        raw = {}
    merged = {**defaults, **raw}
    merged["data_split"] = {**defaults["data_split"], **(raw.get("data_split") or {})}
    merged["trading_costs"] = {**defaults["trading_costs"], **(raw.get("trading_costs") or {})}
    merged["wfe"] = {**defaults["wfe"], **(raw.get("wfe") or {})}
    merged["complexity_penalty"] = {**defaults["complexity_penalty"], **(raw.get("complexity_penalty") or {})}
    merged["strategy_param_counts"] = {**defaults["strategy_param_counts"], **(raw.get("strategy_param_counts") or {})}
    merged["holdback_gate"] = {**defaults["holdback_gate"], **(raw.get("holdback_gate") or {})}
    merged["backtest_log"] = {**defaults["backtest_log"], **(raw.get("backtest_log") or {})}
    return merged


def _allocate_split_days(total: int, is_r: float, oos_r: float, hb_r: float) -> Tuple[int, int, int]:
    total = max(3, int(total))
    s = float(is_r) + float(oos_r) + float(hb_r)
    if s <= 0:
        is_r, oos_r, hb_r = 0.5, 0.3, 0.2
        s = 1.0
    is_r, oos_r, hb_r = is_r / s, oos_r / s, hb_r / s
    n_is = max(1, int(round(total * is_r)))
    n_oos = max(1, int(round(total * oos_r)))
    n_hb = total - n_is - n_oos
    while n_hb < 1 and (n_is > 1 or n_oos > 1):
        if n_is >= n_oos and n_is > 1:
            n_is -= 1
        elif n_oos > 1:
            n_oos -= 1
        n_hb = total - n_is - n_oos
    if n_hb < 1:
        n_hb = 1
        if n_oos > 1:
            n_oos -= 1
        elif n_is > 1:
            n_is -= 1
        n_hb = total - n_is - n_oos
    if n_is + n_oos + n_hb > total:
        over = n_is + n_oos + n_hb - total
        take = min(over, max(0, n_is - 1))
        n_is -= take
        over -= take
        if over > 0:
            take2 = min(over, max(0, n_oos - 1))
            n_oos -= take2
            over -= take2
        n_hb = total - n_is - n_oos
    elif n_is + n_oos + n_hb < total:
        n_hb += total - (n_is + n_oos + n_hb)
    return n_is, n_oos, n_hb


def _split_segment_dates(lookback_days: int, is_r: float, oos_r: float, hb_r: float) -> Dict[str, str]:
    tz = pytz.timezone("Asia/Shanghai")
    end = datetime.now(tz).date()
    start = end - timedelta(days=int(lookback_days))
    total_days = max(3, (end - start).days + 1)
    n_is, n_oos, n_hb = _allocate_split_days(total_days, is_r, oos_r, hb_r)
    cur = start
    is_start = cur
    is_end = is_start + timedelta(days=n_is - 1)
    oos_start = is_end + timedelta(days=1)
    oos_end = oos_start + timedelta(days=n_oos - 1)
    hb_start = oos_end + timedelta(days=1)
    hb_end = end
    return {
        "is_start": is_start.strftime("%Y%m%d"),
        "is_end": is_end.strftime("%Y%m%d"),
        "oos_start": oos_start.strftime("%Y%m%d"),
        "oos_end": oos_end.strftime("%Y%m%d"),
        "holdback_start": hb_start.strftime("%Y%m%d"),
        "holdback_end": hb_end.strftime("%Y%m%d"),
        "n_is": n_is,
        "n_oos": n_oos,
        "n_holdback": n_hb,
    }


def _append_research_backtest_log(record: Dict[str, Any], rel_path: str) -> None:
    root = _project_root()
    log_path = root / rel_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def tool_strategy_research(
    *,
    lookback_days: int = 120,
    strategies: str = "trend_following,mean_reversion,breakout",
    adjustment_rate: float = 0.1,
    mode: str = "prod",
    enable_split_analysis: Optional[bool] = None,
    include_regime_breakdown: bool = False,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：策略研究与回放评估（研究级）

    目标：
    - 复用现有策略表现/评分/权重工具，生成一份研究报告（Markdown llm_summary）
    - 输出“权重调整建议”，但不直接强制线上生效（是否落盘由上层工作流/人工决定）
    """
    cfg = _load_strategy_research_config()
    if enable_split_analysis is None:
        enable_split_analysis = bool(cfg.get("enable_split_analysis", True))

    trading_costs = cfg.get("trading_costs") if isinstance(cfg.get("trading_costs"), dict) else None
    wfe_cfg = cfg.get("wfe") if isinstance(cfg.get("wfe"), dict) else {}
    cpx = cfg.get("complexity_penalty") if isinstance(cfg.get("complexity_penalty"), dict) else {}
    param_counts = cfg.get("strategy_param_counts") if isinstance(cfg.get("strategy_param_counts"), dict) else {}
    hb_gate = cfg.get("holdback_gate") if isinstance(cfg.get("holdback_gate"), dict) else {}
    ds = cfg.get("data_split") if isinstance(cfg.get("data_split"), dict) else {}

    from merged.strategy_analytics import tool_strategy_analytics
    from merged.strategy_weights import tool_strategy_weights

    try:
        from analysis.market_regime import tool_detect_market_regime
    except Exception:
        tool_detect_market_regime = None  # type: ignore[assignment]

    try:
        from analysis.strategy_evaluator import calculate_wfe_style_metrics
    except Exception:
        calculate_wfe_style_metrics = None  # type: ignore[assignment]

    strategy_list = [s.strip() for s in (strategies or "").split(",") if s.strip()]
    if not strategy_list:
        return {"success": False, "message": "strategies 不能为空", "data": None}

    perf_results: Dict[str, Any] = {}
    score_results: Dict[str, Any] = {}
    errors: List[str] = []
    split_metrics: Dict[str, Any] = {}
    wfe_by_strategy: Dict[str, Any] = {}
    holdback_flags: Dict[str, Any] = {}

    weights_out = tool_strategy_weights(action="get")
    current_weights = (weights_out.get("data") or {}).get("weights") if isinstance(weights_out, dict) else None

    cpx_enabled = bool(cpx.get("enabled", True))
    per_param = float(cpx.get("per_param", 0.02))
    cap_pen = float(cpx.get("cap", 0.30))

    for st in strategy_list:
        pcount = int(param_counts.get(st, 0) or 0)
        try:
            perf = tool_strategy_analytics(
                action="performance",
                strategy=st,
                lookback_days=int(lookback_days),
                trading_costs=trading_costs,
                by_regime=include_regime_breakdown,
            )
            perf_results[st] = perf
        except Exception as e:
            errors.append(f"{st}: performance error: {e}")
            perf_results[st] = {"success": False, "message": str(e), "data": None}

        try:
            sc = tool_strategy_analytics(
                action="score",
                strategy=st,
                lookback_days=int(lookback_days),
                min_signals=10,
                trading_costs=trading_costs,
                param_count=pcount,
                complexity_penalty_per_param=per_param,
                complexity_penalty_cap=cap_pen,
                apply_complexity_penalty=cpx_enabled,
            )
            score_results[st] = sc
        except Exception as e:
            errors.append(f"{st}: score error: {e}")
            score_results[st] = {"success": False, "message": str(e), "data": None}

        if enable_split_analysis and calculate_wfe_style_metrics is not None:
            try:
                seg = _split_segment_dates(
                    int(lookback_days),
                    float(ds.get("is_ratio", 0.5)),
                    float(ds.get("oos_ratio", 0.3)),
                    float(ds.get("holdback_ratio", 0.2)),
                )
                split_metrics[st] = {"segments": seg, "windows": {}}
                for label, a, b in (
                    ("is", seg["is_start"], seg["is_end"]),
                    ("oos", seg["oos_start"], seg["oos_end"]),
                    ("holdback", seg["holdback_start"], seg["holdback_end"]),
                ):
                    split_metrics[st]["windows"][label] = tool_strategy_analytics(
                        action="performance",
                        strategy=st,
                        lookback_days=1,
                        start_date=a,
                        end_date=b,
                        trading_costs=trading_costs,
                    )
                wf = calculate_wfe_style_metrics(
                    strategy=st,
                    is_start=seg["is_start"],
                    is_end=seg["is_end"],
                    oos_start=seg["oos_start"],
                    oos_end=seg["oos_end"],
                    trading_costs=trading_costs,
                    min_closed_is=int(wfe_cfg.get("min_closed_is", 3)),
                    min_closed_oos=int(wfe_cfg.get("min_closed_oos", 3)),
                    wfe_warn_threshold=float(wfe_cfg.get("warn_threshold", 0.5)),
                )
                wfe_by_strategy[st] = wf
                hb = split_metrics[st]["windows"].get("holdback") or {}
                hb_data = hb.get("data") if isinstance(hb, dict) else None
                if isinstance(hb_data, dict):
                    min_ar = float(hb_gate.get("min_avg_return", 0.0))
                    min_sh = float(hb_gate.get("min_gross_sharpe_like", 0.0))
                    fail = False
                    if float(hb_data.get("avg_return") or 0.0) < min_ar:
                        fail = True
                    if float(hb_data.get("gross_sharpe_like") or 0.0) < min_sh:
                        fail = True
                    holdback_flags[st] = {
                        "HOLDBACK_FAIL": fail,
                        "holdback_avg_return": hb_data.get("avg_return"),
                        "holdback_gross_sharpe_like": hb_data.get("gross_sharpe_like"),
                    }
            except Exception as e:
                errors.append(f"{st}: split/wfe error: {e}")
                split_metrics[st] = {"error": str(e)}

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
    research_disclaimer = (
        "研究级启发式指标（含务实版 WFE、样本切分、可选交易成本），不构成交易指令；"
        "完整 Walk-Forward 需参数网格与优化器，详见 plugins/analysis/README.md。"
    )

    any_holdback_fail = any(
        isinstance(v, dict) and v.get("HOLDBACK_FAIL") for v in holdback_flags.values()
    )
    any_wfe_warn = False
    for w in wfe_by_strategy.values():
        d = (w or {}).get("data") if isinstance(w, dict) else None
        if isinstance(d, dict) and d.get("overfit_warn"):
            any_wfe_warn = True

    lines: List[str] = []
    lines.append("**📊 核心结论**：策略研究与回放评估已完成（研究级，不构成交易指令）。")
    if any_holdback_fail:
        lines.append("- **HOLDBACK_FAIL**：至少一策略在 Holdback 窗口未通过门禁（见下表），建议人工审核后再调整权重。")
    if any_wfe_warn:
        lines.append("- **WFE 衰减警告**：样本外相对样本内年化收益代理比低于阈值，存在过拟合或失效风险（务实版指标，非完整 WF 优化）。")
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
    lines.append(f"- {research_disclaimer}")
    if errors:
        lines.append(f"- 本次评估存在 {len(errors)} 条警告/失败（详见 data.errors）。")
    lines.append("")
    lines.append("**📂 数据与来源**：")
    lines.append("- 来源：tool_strategy_analytics(performance/score) 与 tool_strategy_weights(get/adjust)。")
    lines.append(f"- 时间窗口：最近 {int(lookback_days)} 天；切分与 WFE 见下方表格。")
    lines.append("")
    lines.append("**🧭 下一步行动建议**：")
    lines.append("- 建议将策略表现按 Market Regime（趋势/震荡/高波动风险）分 bucket；可通过 `signal_regime_labels` 表为 signal_id 标注 regime 后启用 `include_regime_breakdown`。")
    lines.append("")
    lines.append("**🔍 高密度要点总结**：")
    lines.append(f"- 时间：{ts}")
    lines.append(f"- 策略集合：{', '.join(strategy_list)}")
    lines.append(f"- 权重建议：{'已生成' if (isinstance(proposal_out, dict) and proposal_out.get('success')) else '未生成/失败'}")
    lines.append(f"- 交易成本模型：{'已应用(净额见 split)' if (trading_costs and trading_costs.get('enabled')) else '未启用'}")

    table = [
        "| 策略 | performance | score | 备注 |",
        "|---|---:|---:|---|",
    ]
    for st in strategy_list:
        p_ok = bool((perf_results.get(st) or {}).get("success"))
        s_ok = bool((score_results.get(st) or {}).get("success"))
        note = ""
        if not p_ok:
            note = str((perf_results.get(st) or {}).get("message", ""))[:60]
        elif not s_ok:
            note = str((score_results.get(st) or {}).get("message", ""))[:60]
        table.append(f"| {st} | {str(p_ok).lower()} | {str(s_ok).lower()} | {note} |")

    split_table: List[str] = []
    if enable_split_analysis and split_metrics:

        def _fmt_window(d: Any) -> str:
            if not isinstance(d, dict) or not d.get("success"):
                return "n/a"
            g = float(d.get("avg_return") or 0.0)
            if d.get("trading_costs_applied"):
                cl = max(1, int(d.get("closed_signals") or 0))
                n = float(d.get("sum_closed_return_net") or 0) / cl
            else:
                n = g
            return f"{g:.4f}/{n:.4f}"

        split_table.append("### 样本切分 IS / OOS / Holdback（日历比例）")
        split_table.append(
            "- 均收益列为 **毛/净**（启用交易成本时净额为扣成本后）；"
            "**WFE 比** 为务实版样本外效率（无 IS 内参数寻优）。"
        )
        split_table.append(
            "| 策略 | IS(毛/净) | OOS(毛/净) | Holdback(毛/净) | HOLDBACK_FAIL | WFE比 | OOS警告 |"
        )
        split_table.append("|---|---|---|---|---|---|---|")
        for st in strategy_list:
            sm = split_metrics.get(st) or {}
            wins = sm.get("windows") if isinstance(sm, dict) else None
            is_p = (wins or {}).get("is") or {}
            oos_p = (wins or {}).get("oos") or {}
            hb_p = (wins or {}).get("holdback") or {}
            wf = wfe_by_strategy.get(st) or {}
            wf_d = wf.get("data") if isinstance(wf, dict) else None
            ratio = "N/A"
            warn = ""
            if isinstance(wf_d, dict):
                r = wf_d.get("wfe_return_ratio")
                ratio = f"{r:.3f}" if r is not None else "N/A"
                if wf_d.get("overfit_warn"):
                    warn = "yes"
            hf = holdback_flags.get(st) or {}
            hfail = str(hf.get("HOLDBACK_FAIL", False)).lower()
            split_table.append(
                f"| {st} | {_fmt_window(is_p)} | {_fmt_window(oos_p)} | {_fmt_window(hb_p)} | {hfail} | {ratio} | {warn} |"
            )

    weight_section: List[str] = []
    weight_section.append("### 🧮 权重建议（研究级）")
    if isinstance(proposal_out, dict) and proposal_out.get("success"):
        weight_section.append("已生成权重调整建议（建议人工审核后再落盘）：")
        weight_section.append("```json")
        weight_section.append(str((proposal_out.get("data") or {}) if isinstance(proposal_out, dict) else {}))
        weight_section.append("```")
    else:
        weight_section.append("本次未生成权重调整建议（可能是当前权重缺失或评分数据不足）。")

    llm_summary = (
        "\n".join(lines)
        + "\n\n"
        + "\n".join(table)
        + "\n\n"
        + ("\n".join(split_table) + "\n\n" if split_table else "")
        + "\n".join(weight_section)
    )

    report_payload = {
        "timestamp": ts,
        "lookback_days": int(lookback_days),
        "strategies": strategy_list,
        "performance": perf_results,
        "scores": score_results,
        "current_weights": current_weights,
        "proposal": proposal_out,
        "regime": regime_info,
        "errors": errors,
        "split_metrics": split_metrics,
        "wfe_by_strategy": wfe_by_strategy,
        "holdback_flags": holdback_flags,
        "research_disclaimer": research_disclaimer,
        "config_snapshot": {
            "enable_split_analysis": enable_split_analysis,
            "trading_costs_enabled": bool(trading_costs and trading_costs.get("enabled")),
            "include_regime_breakdown": include_regime_breakdown,
        },
    }

    blog = cfg.get("backtest_log") if isinstance(cfg.get("backtest_log"), dict) else {}
    if blog.get("enabled"):
        try:
            _append_research_backtest_log(
                {
                    "timestamp": ts,
                    "lookback_days": int(lookback_days),
                    "strategies": strategy_list,
                    "holdback_flags": holdback_flags,
                    "wfe_by_strategy": wfe_by_strategy,
                },
                str(blog.get("path") or "data/backtest_logs/research_runs.jsonl"),
            )
        except Exception as e:
            errors.append(f"backtest_log: {e}")

    return {
        "success": True,
        "message": "strategy_research ok",
        "data": {
            **report_payload,
            "report_data": {
                "report_type": "strategy_research",
                "llm_summary": llm_summary,
                "research_disclaimer": research_disclaimer,
                "raw": {
                    "performance": perf_results,
                    "scores": score_results,
                    "current_weights": current_weights,
                    "proposal": proposal_out,
                    "errors": errors,
                    "split_metrics": split_metrics,
                    "wfe_by_strategy": wfe_by_strategy,
                    "holdback_flags": holdback_flags,
                },
            },
        },
    }


def tool_get_strategy_research_history(*, limit: int = 20) -> Dict[str, Any]:
    """读取 `config/strategy_research.yaml` 中 backtest_log.path 的最近若干条 JSONL 运行记录。"""
    cfg = _load_strategy_research_config()
    blog = cfg.get("backtest_log") if isinstance(cfg.get("backtest_log"), dict) else {}
    rel = str(blog.get("path") or "data/backtest_logs/research_runs.jsonl")
    path = _project_root() / rel
    if not path.is_file():
        return {
            "success": True,
            "message": "no log file",
            "data": {"entries": [], "path": str(path)},
        }
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    lines = [ln for ln in lines if ln.strip()]
    tail = lines[-max(1, int(limit)) :]
    entries: List[Any] = []
    for ln in tail:
        try:
            entries.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return {"success": True, "message": "ok", "data": {"entries": entries, "path": str(path)}}
