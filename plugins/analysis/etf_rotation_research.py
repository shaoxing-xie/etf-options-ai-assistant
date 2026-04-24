from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from analysis.etf_rotation_core import (
    append_rotation_history,
    read_last_rotation_runs,
    resolve_etf_pool,
    run_rotation_pipeline,
)
from src.rotation_config_loader import load_rotation_config
from src.services.indicator_runtime import resolve_indicator_runtime
from plugins.analysis.three_factor_engine_v3 import compute_three_factor_v3_candidates


DEFAULT_ETF_NAME_MAP: Dict[str, str] = {
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "510050": "上证50ETF",
    "159915": "创业板ETF",
    "512100": "中证1000ETF",
    "512880": "证券ETF",
    "512690": "酒ETF",
    "515400": "中证煤炭ETF",
    "159819": "农业ETF",
    "159992": "消费ETF",
    "516160": "化工ETF",
    "512400": "军工ETF",
    "513310": "恒生生科ETF",
    "513130": "恒生科技ETF",
    "520500": "科技ETF",
    "159748": "医疗ETF",
    "560260": "家电ETF",
}


def _load_etf_name_map() -> Dict[str, str]:
    p = Path(__file__).resolve().parents[2] / "config" / "etf_name_map.json"
    try:
        if p.exists():
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return {str(k): str(v) for k, v in obj.items() if str(k).strip() and str(v).strip()}
    except Exception:
        pass
    return DEFAULT_ETF_NAME_MAP


def _memory_dir() -> Path:
    # 与 openclaw 约定：落在用户内存目录，避免污染项目目录
    p = Path(os.environ.get("OPENCLAW_MEMORY_DIR", str(Path.home() / ".openclaw" / "memory")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _today_key(tz_name: str = "Asia/Shanghai") -> str:
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d")


def _safe_write_json(path: Path, obj: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_nikkei_premium_gate_snapshot(trade_date: str) -> Dict[str, Any]:
    """
    读取 513880（日经）当日溢价门禁快照，用于轮动“跨境溢价风险扣分/门禁”。

    约定由 tail_session runner 落盘：
    - data/semantic/nikkei_513880_intraday_dashboard_view/{trade_date}_M7.json
    """
    root = _project_root()
    p = root / "data" / "semantic" / "nikkei_513880_intraday_dashboard_view" / f"{trade_date}_M7.json"
    if not p.is_file():
        return {"status": "unavailable", "reason": "nikkei_semantic_missing"}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unavailable", "reason": "nikkei_semantic_parse_failed"}
    if not isinstance(obj, dict):
        return {"status": "unavailable", "reason": "nikkei_semantic_invalid"}
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    risk_gate = data.get("risk_gate") if isinstance(data.get("risk_gate"), dict) else {}
    return {
        "status": "ok",
        "premium_rate_pct": data.get("premium_rate_pct"),
        "premium_percentile_20d": data.get("premium_percentile_20d"),
        "temperature_band": data.get("temperature_band"),
        "temperature_position_ceiling": data.get("temperature_position_ceiling"),
        "risk_gate_action": risk_gate.get("action"),
        "risk_gate_position_ceiling": risk_gate.get("position_ceiling"),
        "risk_gate_reasons": risk_gate.get("reasons") if isinstance(risk_gate.get("reasons"), list) else [],
        "meta": obj.get("_meta") if isinstance(obj.get("_meta"), dict) else {},
        "path": str(p),
    }


def _apply_cross_border_premium_penalty(
    ranked_payload: List[Dict[str, Any]],
    *,
    nikkei_snap: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    对跨境ETF（当前仅 513880）施加溢价风险扣分/门禁标记。
    - 不改变 pipeline 的原始打分逻辑，只做结果端的可解释调整（并写入 three_factor/risk_override）。
    """
    warnings: List[str] = []
    if not ranked_payload:
        return ranked_payload, warnings
    if not isinstance(nikkei_snap, dict) or nikkei_snap.get("status") != "ok":
        return ranked_payload, warnings

    band = str(nikkei_snap.get("temperature_band") or "").strip().lower()
    action = str(nikkei_snap.get("risk_gate_action") or "").strip().upper()
    # 扣分强度：warm/hot 或 action=WAIT/GO_LIGHT 时更保守
    penalty_mult = 1.0
    if action == "WAIT":
        penalty_mult = 0.70
    elif action == "GO_LIGHT":
        penalty_mult = 0.85
    elif band == "hot":
        penalty_mult = 0.75
    elif band == "warm":
        penalty_mult = 0.90

    if penalty_mult >= 0.999:
        return ranked_payload, warnings

    out: List[Dict[str, Any]] = []
    for row in ranked_payload:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip() != "513880":
            out.append(row)
            continue
        nr = dict(row)
        try:
            base_score = float(nr.get("score") or 0.0)
        except Exception:
            base_score = 0.0
        nr["score_before_premium_penalty"] = base_score
        nr["score"] = round(base_score * penalty_mult, 6)
        override = {
            "type": "cross_border_premium_penalty",
            "multiplier": penalty_mult,
            "nikkei_snapshot": {
                "premium_rate_pct": nikkei_snap.get("premium_rate_pct"),
                "premium_percentile_20d": nikkei_snap.get("premium_percentile_20d"),
                "temperature_band": nikkei_snap.get("temperature_band"),
                "risk_gate_action": nikkei_snap.get("risk_gate_action"),
                "risk_gate_reasons": nikkei_snap.get("risk_gate_reasons"),
            },
        }
        nr["risk_override"] = override
        tf = nr.get("three_factor") if isinstance(nr.get("three_factor"), dict) else {}
        tf2 = dict(tf)
        tf2["cross_border_premium_penalty"] = {"multiplier": penalty_mult, "action": action, "band": band}
        nr["three_factor"] = tf2
        out.append(nr)

    warnings.append(f"cross_border_premium_penalty_applied:513880×{penalty_mult:.2f}")
    # 重新按 score 排序，保证输出一致
    out_sorted = sorted(out, key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return out_sorted, warnings


def _load_latest_sentiment_snapshot() -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    base = _project_root() / "data" / "semantic" / "sentiment_snapshot"
    if not base.is_dir():
        warnings.append("sentiment_snapshot_missing")
        return {}, warnings
    files = sorted([p for p in base.glob("*.json") if p.is_file()])
    if not files:
        warnings.append("sentiment_snapshot_empty")
        return {}, warnings
    path = files[-1]
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        warnings.append("sentiment_snapshot_parse_failed")
        return {}, warnings
    if not isinstance(obj, dict):
        warnings.append("sentiment_snapshot_invalid")
        return {}, warnings
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    meta = obj.get("_meta") if isinstance(obj.get("_meta"), dict) else {}
    if str(meta.get("quality_status") or "ok") != "ok":
        warnings.append("sentiment_snapshot_degraded")
    return {
        "overall_score": data.get("overall_score"),
        "sentiment_stage": data.get("sentiment_stage"),
        "sentiment_dispersion": data.get("sentiment_dispersion"),
        "factor_attribution": data.get("factor_attribution") if isinstance(data.get("factor_attribution"), dict) else {},
        "meta": meta,
    }, warnings


def _persist_rotation_artifacts(
    *,
    task_id: str,
    run_id: str,
    symbols: List[str],
    ranked_payload: List[Dict[str, Any]],
    top5_payload: List[Dict[str, Any]],
    ranked_by_pool: Dict[str, Any],
    readiness: Dict[str, Any],
    warnings: List[str],
    errors: List[str],
    three_factor_context: Dict[str, Any],
    trade_date: str,
    generated_at: str,
) -> Dict[str, str]:
    root = _project_root()
    events_path = root / "data" / "decisions" / "orchestration" / "events" / f"{trade_date}.jsonl"
    decision_candidates_path = root / "data" / "decision" / "rotation_candidates" / f"{trade_date}.jsonl"
    decision_risk_path = root / "data" / "decision" / "risk_events" / f"{trade_date}.jsonl"
    semantic_path = root / "data" / "semantic" / "rotation_latest" / f"{trade_date}.json"
    semantic_heatmap_path = root / "data" / "semantic" / "rotation_heatmap" / f"{trade_date}.json"
    semantic_share_path = root / "data" / "semantic" / "etf_share_dashboard" / f"{trade_date}.json"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    decision_candidates_path.parent.mkdir(parents=True, exist_ok=True)
    decision_risk_path.parent.mkdir(parents=True, exist_ok=True)
    semantic_path.parent.mkdir(parents=True, exist_ok=True)
    semantic_heatmap_path.parent.mkdir(parents=True, exist_ok=True)
    semantic_share_path.parent.mkdir(parents=True, exist_ok=True)

    quality_status = "ok"
    degraded_reasons = list(readiness.get("degraded_reasons") or [])
    if bool(readiness.get("degraded")) or warnings:
        quality_status = "degraded"
    # errors 多数是“个别标的缺历史/加载失败”，并不代表结果不可用；
    # 仅当结果为空或明显不可用时才升级为 error。
    if errors:
        if not ranked_payload and not top5_payload:
            quality_status = "error"
        else:
            quality_status = "degraded"
            if "partial_symbol_data_missing" not in degraded_reasons:
                degraded_reasons.append("partial_symbol_data_missing")

    event_time = generated_at
    event_id = f"{task_id}.{run_id}.{uuid.uuid4().hex[:8]}"
    source_tools = [
        "tool_etf_rotation_research",
        "tool_fetch_sector_data",
        "tool_fetch_a_share_fund_flow",
        "tool_fetch_northbound_flow",
        "pre-market-sentiment-check",
    ]
    event_payload = {
        "_meta": {
            "schema_name": "etf_rotation_research_event_v1",
            "schema_version": "1.0.0",
            "task_id": task_id,
            "run_id": run_id,
            "data_layer": "L3",
            "generated_at": generated_at,
            "trade_date": trade_date,
            "source_tools": source_tools,
            "lineage_refs": [str(semantic_path)],
            "quality_status": quality_status,
        },
        "data": {
            "event_id": event_id,
            "event_time": event_time,
            "initial_pool": symbols,
            "scores": ranked_payload,
            "top5": top5_payload,
            "environment_gate": (three_factor_context.get("gate") or {}),
            "capital_resonance_signals": [x.get("capital_resonance_type") for x in top5_payload],
            "degraded_reasons": degraded_reasons,
            "warnings": warnings,
            "errors": errors,
            "source_tools": source_tools,
        },
    }

    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event_payload, ensure_ascii=False) + "\n")

    heat_counter: Dict[str, int] = {}
    for row in top5_payload:
        sec = str(row.get("pool_type") or "unknown")
        heat_counter[sec] = heat_counter.get(sec, 0) + 1
    heatmap = [{"sector_name": k, "count": v} for k, v in sorted(heat_counter.items(), key=lambda x: (-x[1], x[0]))]

    v3 = compute_three_factor_v3_candidates(ranked_payload)
    decision_candidates = v3.get("candidates") if isinstance(v3, dict) else []
    risk_events = v3.get("risk_events") if isinstance(v3, dict) else []
    semantic_payload = {
        "_meta": {
            "schema_name": "etf_rotation_latest_semantic_v1",
            "schema_version": "1.0.0",
            "task_id": task_id,
            "run_id": run_id,
            "data_layer": "L4",
            "generated_at": generated_at,
            "trade_date": trade_date,
            "quality_status": quality_status,
            "lineage_refs": [str(events_path)],
        },
        "data": {
            "trade_date": trade_date,
            "top5": top5_payload,
            "top10": ranked_payload[:10],
            "heatmap": heatmap,
            "environment": {
                "stage": (three_factor_context.get("sentiment") or {}).get("stage"),
                "dispersion": (three_factor_context.get("sentiment") or {}).get("dispersion"),
                "gate_multiplier": (three_factor_context.get("gate") or {}).get("total_multiplier"),
            },
            "data_quality": {
                "quality_status": quality_status,
                "degraded_reasons": degraded_reasons,
                "warnings": warnings,
                "errors": errors,
            },
            "links": {
                "event_file": str(events_path),
                "event_id": event_id,
            },
            "ranked_by_pool": ranked_by_pool,
            "three_factor_context": three_factor_context,
        },
    }
    _safe_write_json(semantic_path, semantic_payload)
    with decision_candidates_path.open("a", encoding="utf-8") as f:
        for row in decision_candidates:
            f.write(
                json.dumps(
                    {
                        "_meta": {
                            "schema_name": "decision_rotation_candidates_v1",
                            "schema_version": "1.0.0",
                            "task_id": task_id,
                            "run_id": run_id,
                            "data_layer": "L3",
                            "generated_at": generated_at,
                            "trade_date": trade_date,
                            "source_tools": source_tools,
                            "lineage_refs": [str(events_path), str(semantic_path)],
                            "quality_status": quality_status,
                        },
                        "data": {
                            "symbol": row.get("symbol"),
                            "pool_type": row.get("pool_type"),
                            "composite_score": row.get("composite_score_v3", row.get("score")),
                            "score_breakdown": row.get("score_breakdown_v3", row.get("three_factor", {})),
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    with decision_risk_path.open("a", encoding="utf-8") as f:
        # 即使本轮无风险事件，也要落盘一个“空事件”记录，保证可回放与血缘完整性（避免出现文件缺失）。
        if not risk_events:
            risk_events = [
                {
                    "event_type": "none",
                    "severity": "info",
                    "details": {"note": "no risk events emitted by v3 engine"},
                }
            ]
        for idx, ev in enumerate(risk_events):
            f.write(
                json.dumps(
                    {
                        "_meta": {
                            "schema_name": "decision_risk_events_v1",
                            "schema_version": "1.0.0",
                            "task_id": task_id,
                            "run_id": run_id,
                            "data_layer": "L3",
                            "generated_at": generated_at,
                            "trade_date": trade_date,
                            "source_tools": source_tools,
                            "lineage_refs": [str(decision_candidates_path)],
                            "quality_status": quality_status,
                        },
                        "data": {
                            "event_id": f"{event_id}.risk.{idx}",
                            "event_type": ev.get("event_type"),
                            "severity": ev.get("severity"),
                            "details": ev.get("details", {}),
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    _safe_write_json(
        semantic_heatmap_path,
        {
            "_meta": {
                "schema_name": "semantic_rotation_heatmap_v1",
                "schema_version": "1.0.0",
                "task_id": task_id,
                "run_id": run_id,
                "data_layer": "L4",
                "generated_at": generated_at,
                "trade_date": trade_date,
                "quality_status": quality_status,
                "lineage_refs": [str(decision_candidates_path), str(decision_risk_path)],
            },
            "data": {
                "trade_date": trade_date,
                "heatmap": heatmap,
                "top5": top5_payload,
                "environment": semantic_payload["data"]["environment"],
                "explanations": {"degraded_reasons": degraded_reasons, "warnings": warnings},
            },
        },
    )
    _safe_write_json(
        semantic_share_path,
        {
            "_meta": {
                "schema_name": "semantic_etf_share_dashboard_v1",
                "schema_version": "1.0.0",
                "task_id": task_id,
                "run_id": run_id,
                "data_layer": "L4",
                "generated_at": generated_at,
                "trade_date": trade_date,
                "quality_status": quality_status,
                "lineage_refs": [str(decision_candidates_path)],
            },
            "data": {
                "trade_date": trade_date,
                "rows": [
                    {
                        "etf_code": row.get("symbol"),
                        "trend_score": ((row.get("score_breakdown_v3") or {}).get("share_trend")),
                        "divergence_flags": [
                            "price_share_divergence_gate"
                            if ((row.get("score_breakdown_v3") or {}).get("share_trend", 0) or 0) < 0
                            and ((row.get("score_breakdown_v3") or {}).get("momentum", 0) or 0) > 0
                            else "none"
                        ],
                        "interpretation": "proxy from v3 engine",
                    }
                    for row in decision_candidates[:10]
                ],
            },
        },
    )
    return {
        "event_file": str(events_path),
        "semantic_file": str(semantic_path),
        "decision_candidates_file": str(decision_candidates_path),
        "decision_risk_file": str(decision_risk_path),
        "semantic_heatmap_file": str(semantic_heatmap_path),
        "semantic_share_file": str(semantic_share_path),
    }


def _etf_display(symbol: str, name_map: Dict[str, str]) -> str:
    name = name_map.get(str(symbol), "")
    return f"{symbol}({name})" if name else str(symbol)


def _turnover_top5(ranked: List[Any], last_three: List[Dict[str, Any]]) -> Tuple[float, str]:
    """与报告尾部一致的 Top5 换手率标签。"""
    if not ranked:
        return 0.0, "轮动正常"

    def _to_set(items: List[str]) -> set[str]:
        return {str(x) for x in items if str(x).strip()}

    prev_top5 = _to_set((last_three[-1].get("top_symbols") if last_three else [])[:5]) if last_three else set()
    curr_top5 = _to_set([r.symbol for r in ranked[:5]])
    turnover = 1.0 - (len(prev_top5 & curr_top5) / 5.0) if prev_top5 else 0.0
    if turnover < 0.3:
        turn_label = "主线稳定"
    elif turnover < 0.6:
        turn_label = "轮动正常"
    else:
        turn_label = "轮动加快"
    return turnover, turn_label


def _warnings_plain_zh(warnings: List[str]) -> List[str]:
    """将 pipeline 告警转为一行可读中文，便于报告阅读。"""
    if not warnings:
        return []
    out: List[str] = []
    joined = "; ".join(warnings)
    if "correlation_skipped" in joined or "correlation_fell_back" in joined:
        out.append("相关性矩阵本轮为近似或未完全生效，「平均相关性」惩罚可能偏弱，排名更偏动量/波动/回撤。")
    if "aligned_trading_days_insufficient" in joined:
        out.append("跨市场日历对齐偏紧，已尝试自动收缩相关窗口或位置近似；若仍告警，请视为跨池可比性有限。")
    if "correlation_lookback_auto_reduced" in joined:
        out.append("相关窗口已自动缩短以适配交集长度，与配置中的长期相关设定可能不完全一致。")
    if not out:
        out.append("详见告警原文（技术字段）。")
    return out


def _operational_guidance_lines(
    *,
    top_syms: List[str],
    ind_rank: List[Any],
    con_rank: List[Any],
    ranked: List[Any],
    turnover: float,
    turn_label: str,
    regime: Optional[str],
    regime_conf: Optional[float],
    warnings: List[str],
    readiness: Dict[str, Any],
    fallback: bool,
    errors: List[str],
    etf_name_map: Dict[str, str],
) -> List[str]:
    """
    研究级「可执行」表述：仅描述观察与配置思路，不构成投资建议。
    """
    lines: List[str] = []
    lines.append("## 📌 近期板块轮动操作指引（研究用，非投资建议）")
    lines.append("")
    lines.append("以下为**流程化观察与复盘清单**，便于近期（约 1～5 个交易日）对照执行；不涉及具体买卖价位与保证金。")
    lines.append("")

    top_disp = ", ".join([_etf_display(s, etf_name_map) for s in top_syms])
    lines.append(f"- **当前综合强弱（Top 参考）**：{top_disp}")
    lines.append(
        f"- **榜单稳定性**：Top5 换手率约 **{turnover*100:.1f}%**（{turn_label}）。"
        "换手率偏低时可侧重「主线延续」；偏高时以「验证新主线是否成立」为主，避免同日频繁反手。"
    )

    ind3 = [r.symbol for r in ind_rank[:3]] if ind_rank else []
    con3 = [r.symbol for r in con_rank[:3]] if con_rank else []
    overlap = [s for s in ind3 if s in set(con3)]
    if overlap:
        lines.append(
            f"- **行业池 vs 概念池共识**：{', '.join([_etf_display(s, etf_name_map) for s in overlap])} "
            "在两层榜中均靠前，可作**短期主线观察**（仍须结合波动与回撤）。"
        )
    elif ind3 and con3:
        lines.append(
            "- **行业池 vs 概念池**：当前 Top 重合度不高，宜**分层跟踪**（行业偏内资结构、概念偏主题/海外映射），避免混为一谈。"
        )

    rg = (regime or "").strip().lower()
    conf_s = f"{float(regime_conf):.2f}" if regime_conf is not None else "—"
    if rg in ("trending_up", "up", "bull"):
        lines.append(
            f"- **与宽基环境（Regime≈上行，置信度 {conf_s}）**：风格上可更重视**动量延续与趋势 R² 较高**的标的；"
            "若单标的波动分位与池内高位接近，注意分批与波动上限。"
        )
    elif rg in ("trending_down", "down", "bear"):
        lines.append(
            f"- **与宽基环境（Regime≈下行，置信度 {conf_s}）**：优先**控波动、看回撤与胜率**；"
            "轮动榜中偏反弹属性的标的更适合小仓验证，不宜与长线多头混谈。"
        )
    elif rg in ("range", "sideways"):
        lines.append(
            f"- **与宽基环境（Regime≈震荡，置信度 {conf_s}）**：适合**板块强弱切换与再平衡式观察**；"
            "关注排名在 3～5 日内是否反复，而非单日跳变。"
        )
    elif rg in ("high_vol_risk", "high_vol"):
        lines.append(
            f"- **与宽基环境（Regime≈高波动风险，置信度 {conf_s}）**："
            "宜缩短评估周期、降低单次权重调整幅度，优先流动性好的宽基/行业龙头 ETF。"
        )
    else:
        lines.append(
            "- **与宽基环境**：Regime 未能可靠识别时，以**榜单稳定性与波动/回撤**为主，"
            "避免在数据告警较多时把排名当作强信号。"
        )

    if ranked:
        vols_top = [float(getattr(r, "vol_20d", 0.0)) for r in ranked[:10]]
        mdd_top = [float(getattr(r, "max_drawdown_60d", 0.0)) for r in ranked[:10]]
        if vols_top:
            avg_v = sum(vols_top) / len(vols_top)
            lines.append(
                f"- **波动与回撤刻度**：观察榜前段平均 20 日年化波动约 **{avg_v*100:.1f}%**；"
                f"样本平均 60 日最大回撤约 **{sum(mdd_top)/len(mdd_top)*100:.1f}%**（用于衡量持有体验，非预测收益）。"
            )

    if bool(readiness.get("degraded")) or fallback:
        lines.append(
            "- **数据/模型状态**：本轮存在降级或 legacy 排名回退——请将本报告**仅作观察列表**，"
            "待覆盖与告警恢复后再提高权重。"
        )

    wzh = _warnings_plain_zh(warnings)
    if wzh:
        lines.append("- **告警摘要（人话）**：" + " ".join(wzh))

    if errors:
        lines.append(
            f"- **数据缺口**：存在 {len(errors)} 条加载/计算异常，结论偏「方向性」；"
            "若用于内部复盘，建议先修复数据源再对比两轮排名。"
        )

    lines.append(
        "- **近期执行节奏（建议）**：① 未来 1～3 个交易日对照 Top 是否**自我强化**；"
        "② 5 个交易日内看**行业/概念是否同向**；③ 任一单日剧烈波动时，以**配置与风控规则**为准，勿单独依赖本榜单。"
    )
    lines.append("")
    return lines


def _run_rotation_pipeline_with_timeout(
    *,
    symbols: List[str],
    cfg: Dict[str, Any],
    lookback_days: int,
    score_engine: str,
    runtime_inputs: Dict[str, Any],
    max_runtime_seconds: float,
    allow_multiprocessing: bool = True,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    硬超时包装：将重计算放入子进程，超时则终止进程并返回降级结果，避免联调卡死。
    """
    import multiprocessing as mp
    import time

    warnings: List[str] = []
    if not allow_multiprocessing:
        try:
            pipe = run_rotation_pipeline(
                symbols,
                cfg,
                lookback_days=lookback_days,
                score_engine=score_engine,
                runtime_inputs=runtime_inputs,
            )
            return (pipe if isinstance(pipe, dict) else {"ranked_active": [], "ranked_by_pool": {}, "errors": ["invalid_pipe"]}), warnings
        except Exception as e:  # noqa: BLE001
            warnings.append(f"pipeline_direct_failed:{type(e).__name__}")
            return (
                {
                    "ranked_active": [],
                    "ranked_by_pool": {},
                    "ranked_all_for_display": [],
                    "inactive": [],
                    "fallback_legacy_ranking": True,
                    "correlation_matrix": None,
                    "correlation_symbols": [],
                    "warnings": ["pipeline_direct_failed"],
                    "config_snapshot": {"lookback_days": lookback_days, "score_engine": score_engine},
                    "data_readiness": {"degraded": True, "degraded_reasons": ["pipeline_direct_failed"]},
                    "pool_type_map": {},
                    "errors": [str(e)],
                    "three_factor_context": {"enabled": False},
                },
                warnings,
            )
    timeout_s = float(max(0.1, max_runtime_seconds))
    ctx = mp.get_context("fork") if hasattr(mp, "get_context") else mp  # type: ignore[assignment]
    q: Any = ctx.Queue(maxsize=1)

    def _child() -> None:
        try:
            pipe = run_rotation_pipeline(
                symbols,
                cfg,
                lookback_days=lookback_days,
                score_engine=score_engine,
                runtime_inputs=runtime_inputs,
            )
            q.put({"ok": True, "pipe": pipe})
        except Exception as e:  # noqa: BLE001
            q.put({"ok": False, "error": str(e), "type": type(e).__name__})

    t0 = time.monotonic()
    p = ctx.Process(target=_child, daemon=True)
    p.start()
    p.join(timeout=timeout_s)
    if p.is_alive():
        try:
            p.terminate()
            p.join(timeout=2.0)
        except Exception:
            pass
        warnings.append(f"pipeline_timeout:{timeout_s:.1f}s")
        return (
            {
                "ranked_active": [],
                "ranked_by_pool": {},
                "ranked_all_for_display": [],
                "inactive": [],
                "fallback_legacy_ranking": True,
                "correlation_matrix": None,
                "correlation_symbols": [],
                "warnings": ["pipeline_timeout"],
                "config_snapshot": {"lookback_days": lookback_days, "score_engine": score_engine},
                "data_readiness": {"degraded": True, "degraded_reasons": ["pipeline_timeout"]},
                "pool_type_map": {},
                "errors": ["pipeline_timeout"],
                "three_factor_context": {"enabled": False},
            },
            warnings,
        )
    try:
        msg = q.get_nowait()
    except Exception:
        warnings.append("pipeline_result_missing")
        return (
            {
                "ranked_active": [],
                "ranked_by_pool": {},
                "ranked_all_for_display": [],
                "inactive": [],
                "fallback_legacy_ranking": True,
                "correlation_matrix": None,
                "correlation_symbols": [],
                "warnings": ["pipeline_result_missing"],
                "config_snapshot": {"lookback_days": lookback_days, "score_engine": score_engine},
                "data_readiness": {"degraded": True, "degraded_reasons": ["pipeline_result_missing"]},
                "pool_type_map": {},
                "errors": ["pipeline_result_missing"],
                "three_factor_context": {"enabled": False},
            },
            warnings,
        )
    if not isinstance(msg, dict) or not msg.get("ok"):
        err = str((msg or {}).get("error") or "child_failed")
        warnings.append(f"pipeline_child_failed:{err[:80]}")
        return (
            {
                "ranked_active": [],
                "ranked_by_pool": {},
                "ranked_all_for_display": [],
                "inactive": [],
                "fallback_legacy_ranking": True,
                "correlation_matrix": None,
                "correlation_symbols": [],
                "warnings": ["pipeline_child_failed"],
                "config_snapshot": {"lookback_days": lookback_days, "score_engine": score_engine},
                "data_readiness": {"degraded": True, "degraded_reasons": ["pipeline_child_failed"]},
                "pool_type_map": {},
                "errors": [err],
                "three_factor_context": {"enabled": False},
            },
            warnings,
        )
    pipe = msg.get("pipe")
    if not isinstance(pipe, dict):
        warnings.append("pipeline_invalid_pipe")
        pipe = {
            "ranked_active": [],
            "ranked_by_pool": {},
            "ranked_all_for_display": [],
            "inactive": [],
            "fallback_legacy_ranking": True,
            "correlation_matrix": None,
            "correlation_symbols": [],
            "warnings": ["pipeline_invalid_pipe"],
            "config_snapshot": {"lookback_days": lookback_days, "score_engine": score_engine},
            "data_readiness": {"degraded": True, "degraded_reasons": ["pipeline_invalid_pipe"]},
            "pool_type_map": {},
            "errors": ["pipeline_invalid_pipe"],
            "three_factor_context": {"enabled": False},
        }
    elapsed = time.monotonic() - t0
    if elapsed > timeout_s * 0.9:
        warnings.append(f"pipeline_near_timeout:{elapsed:.1f}s")
    return pipe, warnings


def tool_etf_rotation_research(
    *,
    etf_pool: str = "",
    etal_pool: Optional[str] = None,
    lookback_days: int = 120,
    top_k: int = 3,
    mode: str = "prod",
    config_path: Optional[str] = None,
    max_runtime_seconds: float = 35.0,
    light_mode: bool = False,
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
        max_runtime_seconds: 硬超时秒数（子进程超时终止），避免联调卡死
        light_mode: 轻量模式：关闭相关性等重计算，缩短窗口，禁用 dual_run
    """
    from datetime import datetime

    try:
        from analysis.market_regime import tool_detect_market_regime
    except Exception:
        tool_detect_market_regime = None  # type: ignore[assignment]

    # 兼容：某些模型/agent 会把 etf_pool 拼成 etal_pool，导致工具直接失败。
    # 这里做容错兜底，避免 VERIFY_SEND 因为 toolResult failure 而判失败。
    if (etf_pool or "").strip() == "" and isinstance(etal_pool, str) and etal_pool.strip():
        etf_pool = etal_pool.strip()

    cfg = load_rotation_config(config_path)
    explicit_pool = bool((etf_pool or "").strip())
    symbols = resolve_etf_pool(etf_pool if explicit_pool else None, cfg)
    if not symbols:
        return {"success": False, "message": "etf_pool 解析为空", "data": None}

    # 显式传入自定义池：不强制 industry/concept 覆盖阈值（避免“混合池误降级”）。
    # 覆盖率仍会被展示，但不应触发 DEGRADED 分支影响报告质量/投递策略。
    if explicit_pool:
        de = dict(cfg.get("degradation") or {})
        de.setdefault("industry_min_available", 0)
        de.setdefault("concept_min_available", 0)
        de["industry_min_available"] = 0
        de["concept_min_available"] = 0
        cfg = dict(cfg)
        cfg["degradation"] = de

    rt = resolve_indicator_runtime("etf_rotation_research")
    mig = cfg.get("indicator_migration") if isinstance(cfg.get("indicator_migration"), dict) else {}
    task_cfg = ((mig.get("tasks") if isinstance(mig.get("tasks"), dict) else {}).get("etf_rotation_research"))
    task_cfg = task_cfg if isinstance(task_cfg, dict) else {}
    primary_engine = str(task_cfg.get("score_engine_primary") or "three_factor_v2")
    shadow_engine = str(task_cfg.get("score_engine_shadow") or "legacy")

    engine = primary_engine
    if rt.rollback_enabled and str(task_cfg.get("force_rollback_to_legacy", "")).lower() == "true":
        engine = "legacy"

    if light_mode:
        cfg = dict(cfg)
        f = dict(cfg.get("filters") or {})
        f["correlation_mode"] = "off"
        try:
            f["correlation_lookback"] = min(int(f.get("correlation_lookback") or 252), 60)
        except Exception:
            f["correlation_lookback"] = 60
        cfg["filters"] = f
        feats = dict(cfg.get("features") or {})
        feats["use_correlation"] = False
        cfg["features"] = feats
        lookback_days = min(int(lookback_days or 0), 90) if lookback_days else 90

    sentiment_inputs, sentiment_warnings = _load_latest_sentiment_snapshot()
    factor_attr = sentiment_inputs.get("factor_attribution") if isinstance(sentiment_inputs.get("factor_attribution"), dict) else {}
    fund_flow = factor_attr.get("fund_flow") if isinstance(factor_attr.get("fund_flow"), dict) else {}
    northbound = factor_attr.get("northbound") if isinstance(factor_attr.get("northbound"), dict) else {}
    runtime_inputs = {
        "sentiment": {
            "overall_score": sentiment_inputs.get("overall_score"),
            "sentiment_stage": sentiment_inputs.get("sentiment_stage"),
            "sentiment_dispersion": sentiment_inputs.get("sentiment_dispersion"),
        },
        "flow": {
            "fund_flow_score": fund_flow.get("score"),
            "northbound_score": northbound.get("score"),
        },
    }
    pipe, timeout_warnings = _run_rotation_pipeline_with_timeout(
        symbols=symbols,
        cfg=cfg,
        lookback_days=lookback_days,
        score_engine=engine,
        runtime_inputs=runtime_inputs,
        max_runtime_seconds=float(max_runtime_seconds or 35.0),
        allow_multiprocessing=(str(mode).lower() != "test"),
    )
    shadow_compare: Dict[str, Any] = {}
    if rt.dual_run and (not light_mode) and (not any("pipeline_timeout" in w for w in timeout_warnings)):
        try:
            shadow_pipe, _shadow_warn = _run_rotation_pipeline_with_timeout(
                symbols=symbols,
                cfg=cfg,
                lookback_days=lookback_days,
                score_engine=shadow_engine,
                runtime_inputs=runtime_inputs,
                max_runtime_seconds=max(5.0, float(max_runtime_seconds or 35.0) * 0.5),
                allow_multiprocessing=(str(mode).lower() != "test"),
            )
            p_rank = [r.symbol for r in (pipe.get("ranked_active") or [])[:10]]
            s_rank = [r.symbol for r in (shadow_pipe.get("ranked_active") or [])[:10]]
            overlap = len(set(p_rank) & set(s_rank))
            shadow_compare = {
                "primary_engine": engine,
                "shadow_engine": shadow_engine,
                "top10_overlap": overlap,
                "top10_overlap_ratio": (overlap / 10.0) if p_rank and s_rank else 0.0,
                "primary_top3": p_rank[:3],
                "shadow_top3": s_rank[:3],
            }
        except Exception as e:
            shadow_compare = {"error": f"shadow_run_failed: {e}"}
    errors = list(pipe.get("errors") or [])
    ranked = pipe.get("ranked_active") or []
    ranked_by_pool = pipe.get("ranked_by_pool") or {}
    warnings = list(pipe.get("warnings") or []) + sentiment_warnings + timeout_warnings
    fallback = bool(pipe.get("fallback_legacy_ranking"))
    corr_mat = pipe.get("correlation_matrix")
    corr_syms = pipe.get("correlation_symbols") or []
    config_snap = pipe.get("config_snapshot") or {}
    readiness = pipe.get("data_readiness") or {}
    three_factor_context = pipe.get("three_factor_context") or {}

    if not ranked:
        return {
            "success": False,
            "message": "无法生成轮动评分（无可用ETF数据）",
            "data": {
                "errors": errors,
                "warnings": warnings,
                "config_snapshot": config_snap,
                "data_readiness": readiness,
            },
        }

    top_k = max(1, min(int(top_k), len(ranked)))
    top = ranked[:top_k]
    top_syms = [r.symbol for r in top]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    etf_name_map = _load_etf_name_map()

    prev_runs = read_last_rotation_runs(3, cfg)

    if mode != "test":
        try:
            append_rotation_history(
                top_symbols=top_syms,
                top_k=top_k,
                pool_syms=symbols,
                ranked_symbols=[r.symbol for r in ranked],
                config=cfg,
            )
        except Exception:
            pass

    last_three = prev_runs
    turnover, turn_label = _turnover_top5(ranked, last_three)

    def fmt_pct(x: float) -> str:
        return f"{x*100:.2f}%"

    regime_info: Dict[str, Any] = {}
    regime_line = ""
    regime_str: Optional[str] = None
    regime_conf_val: Optional[float] = None
    if tool_detect_market_regime is not None:
        try:
            r_out = tool_detect_market_regime(symbol="510300", mode="prod")
            if isinstance(r_out, dict) and r_out.get("success"):
                data = r_out.get("data") or {}
                regime_info = data
                regime = data.get("regime")
                conf = data.get("confidence")
                if regime is not None:
                    regime_str = str(regime).strip()
                if conf is not None:
                    try:
                        regime_conf_val = float(conf)
                    except (TypeError, ValueError):
                        regime_conf_val = None
                if regime:
                    regime_line = f"- 当前 Market Regime（基于 510300）: **{regime}**（置信度约 {conf:.2f}，用于理解轮动评分所处的市场环境）。"
        except Exception:
            regime_info = {}
            regime_line = ""

    top_disp = ", ".join([_etf_display(s, etf_name_map) for s in top_syms])

    lines: List[str] = []
    lines.append(
        f"**📊 核心结论**：综合强弱 Top{top_k} 为 **{top_disp}**；"
        f"Top5 换手率 **{turnover*100:.1f}%**（{turn_label}）。"
        "本报告为**研究级**板块轮动观察，**不构成投资建议或交易指令**。"
    )
    if fallback:
        lines.append("- **说明**：过滤后无可用标的，已退回 **legacy 评分** 排名。")
    lines.append("")
    lines.append("**📉 研究结论 / 因子说明**：")
    lines.append(f"- 全池综合 Top {top_k}：{top_disp}")
    lines.append(
        "- 因子口径：动量（M5/M20/M60）、20 日波动与分位、60 日回撤、20 日胜率、"
        "趋势 R²、历史排名稳定性、**技术簇（P0/58 指标映射至综合分）**、"
        "以及池内平均相关性惩罚（若本轮相关性告警较多，该项可能偏弱）。"
    )
    lines.append("")
    ind_rank = ranked_by_pool.get("industry") or []
    con_rank = ranked_by_pool.get("concept") or []
    lines.append("## 🧩 分层轮动榜")
    lines.append(
        f"- 行业池 Top5：{', '.join([_etf_display(r.symbol, etf_name_map) for r in ind_rank[:5]]) if ind_rank else 'N/A'}"
    )
    lines.append(
        f"- 概念池 Top5：{', '.join([_etf_display(r.symbol, etf_name_map) for r in con_rank[:5]]) if con_rank else 'N/A'}"
    )
    lines.append("- 全池观察榜 Top10 仅用于跨池信号观察，不替代行业/概念池独立结论。")
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
        lines.append(f"- 相关性与对齐告警（技术字段）：{'; '.join(warnings)}")
        for plain in _warnings_plain_zh(warnings):
            lines.append(f"- **解读**：{plain}")
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
    ind_cov = readiness.get("industry_coverage") or {}
    con_cov = readiness.get("concept_coverage") or {}
    lines.append("## 🧪 数据覆盖与降级")
    lines.append(
        f"- 行业池覆盖率：{ind_cov.get('available', 0)}/{ind_cov.get('total', 0)}；概念池覆盖率：{con_cov.get('available', 0)}/{con_cov.get('total', 0)}"
    )
    if readiness.get("degraded"):
        lines.append(f"- 状态：DEGRADED（{'; '.join(readiness.get('degraded_reasons') or [])}）")
        lines.append("- DEGRADED_EVIDENCE：见 data.data_readiness.degraded_evidence")
    else:
        lines.append("- 状态：OK")
    lines.append("")
    lines.extend(
        _operational_guidance_lines(
            top_syms=top_syms,
            ind_rank=ind_rank,
            con_rank=con_rank,
            ranked=ranked,
            turnover=turnover,
            turn_label=turn_label,
            regime=regime_str,
            regime_conf=regime_conf_val,
            warnings=warnings,
            readiness=readiness,
            fallback=fallback,
            errors=errors,
            etf_name_map=etf_name_map,
        )
    )
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
    if three_factor_context.get("enabled"):
        gate = three_factor_context.get("gate") if isinstance(three_factor_context.get("gate"), dict) else {}
        sent = three_factor_context.get("sentiment") if isinstance(three_factor_context.get("sentiment"), dict) else {}
        lines.append(
            f"- 三维共振门闸：阶段={sent.get('stage') or '未知'}，分歧度={sent.get('dispersion')}, 门闸系数={gate.get('total_multiplier')}。"
        )
    lines.append("")
    lines.append("## 📂 数据与来源")
    lines.append("- 行情：read_cache_data → etf_daily（显式起止日期）。")
    lines.append("- 配置：`config/rotation_config.yaml`（权重、过滤、标的池）。")
    lines.append("")
    lines.append("## 🔍 高密度要点总结")
    lines.append(f"- 时间：{ts}")
    lines.append(f"- Regime：{regime_info.get('regime') or 'unknown'}")
    lines.append(f"- Top{top_k}：{', '.join([_etf_display(s, etf_name_map) for s in top_syms])}")
    lines.append("- 用途：研究级关注列表，不构成建仓指令")
    if shadow_compare:
        lines.append(
            f"- 双跑对照：{shadow_compare.get('primary_engine')} vs {shadow_compare.get('shadow_engine')}，"
            f"Top10重叠 {shadow_compare.get('top10_overlap', 0)}/10"
        )

    table = [
        "| ETF | 名称 | Pool | M5 | M20 | M60 | vol20分位 | 20日波动 | 60日回撤 | 20日胜率 | 稳定性 | R² | mean_abs_corr | Score |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in ranked[: min(len(ranked), 10)]:
        nm = etf_name_map.get(r.symbol, "-")
        table.append(
            f"| {r.symbol} | {nm} | {getattr(r, 'pool_type', 'unknown')} | {fmt_pct(getattr(r, 'momentum_5d', 0.0))} | "
            f"{fmt_pct(r.momentum_20d)} | {fmt_pct(r.momentum_60d)} | {getattr(r, 'vol20_percentile', 0.0):.2f} | "
            f"{fmt_pct(r.vol_20d)} | {fmt_pct(r.max_drawdown_60d)} | {getattr(r, 'win_rate_20d', 0.5):.2f} | "
            f"{getattr(r, 'stability_score', 0.5):.2f} | {r.trend_r2:.3f} | {r.mean_abs_corr:.3f} | {r.score:.4f} |"
        )

    lines.append("## 🔄 轮动状态")
    lines.append(f"- Top5 换手率：{turnover*100:.1f}%（{turn_label}）")
    high_persist = [r.symbol for r in ranked[:10] if getattr(r, "win_rate_20d", 0.0) >= 0.6][:5]
    low_persist = [r.symbol for r in ranked[:10] if getattr(r, "win_rate_20d", 1.0) <= 0.4][:5]
    if high_persist:
        lines.append(f"- 高持续性：{', '.join(high_persist)}")
    if low_persist:
        lines.append(f"- 低持续性/反弹属性：{', '.join(low_persist)}")

    llm_summary = "\n".join(lines) + "\n\n" + "\n".join(table)

    ranked_payload = [
        {
            "symbol": r.symbol,
            "pool_type": getattr(r, "pool_type", "unknown"),
            "score": r.score,
            "legacy_score": r.legacy_score,
            "momentum_5d": getattr(r, "momentum_5d", 0.0),
            "momentum_20d": r.momentum_20d,
            "momentum_60d": r.momentum_60d,
            "vol_20d": r.vol_20d,
            "vol20_percentile": getattr(r, "vol20_percentile", 0.5),
            "max_drawdown_60d": r.max_drawdown_60d,
            "win_rate_20d": getattr(r, "win_rate_20d", 0.5),
            "trend_r2": r.trend_r2,
            "mean_abs_corr": r.mean_abs_corr,
            "stability_score": getattr(r, "stability_score", 0.5),
            "above_ma": r.above_ma,
            "excluded": r.excluded,
            "exclude_reason": r.exclude_reason,
            "soft_penalties": r.soft_penalties,
            "three_factor": (three_factor_context.get("by_symbol") or {}).get(r.symbol, {}),
        }
        for r in ranked
    ]
    trade_date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    nikkei_snap = _read_nikkei_premium_gate_snapshot(trade_date)
    ranked_payload, cross_border_warn = _apply_cross_border_premium_penalty(ranked_payload, nikkei_snap=nikkei_snap)
    warnings.extend(cross_border_warn)
    top5_payload = ranked_payload[:5]

    task_id = "etf-rotation-research"
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S")
    generated_at = datetime.now().isoformat()
    artifact_refs = {}
    if mode != "test":
        artifact_refs = _persist_rotation_artifacts(
            task_id=task_id,
            run_id=run_id,
            symbols=symbols,
            ranked_payload=ranked_payload,
            top5_payload=top5_payload,
            ranked_by_pool={
                "industry": [{"symbol": r.symbol, "score": r.score} for r in (ind_rank[:10] if ind_rank else [])],
                "concept": [{"symbol": r.symbol, "score": r.score} for r in (con_rank[:10] if con_rank else [])],
            },
            readiness=readiness,
            warnings=warnings,
            errors=errors,
            three_factor_context=three_factor_context,
            trade_date=trade_date,
            generated_at=generated_at,
        )

    # 落盘：给“发送工具（按 last report 读取）”提供稳定数据源，避免 agent 大段传参导致 summary 丢失/退化。
    try:
        date_key = _today_key()
        report_data = {
            "report_type": "etf_rotation_research",
            "llm_summary": llm_summary,
            "raw": {
                "ranked": ranked_payload,
                "errors": errors,
                "shadow_compare": shadow_compare,
                "artifact_refs": artifact_refs,
            },
        }
        _safe_write_json(
            _memory_dir() / f"etf_rotation_last_report_{date_key}.json",
            {"sentable": True, "date_key": date_key, "report_data": report_data},
        )
    except Exception:
        # 落盘失败不影响主流程返回（发送工具可降级走其他路径/重算）
        pass

    return {
        "success": True,
        "message": "etf_rotation_research ok",
        "data": {
            "timestamp": ts,
            "etf_pool": symbols,
            "top_k": top_k,
            "ranked": ranked_payload,
            "ranked_by_pool": {
                "industry": [
                    {
                        "symbol": r.symbol,
                        "score": r.score,
                        "momentum_5d": getattr(r, "momentum_5d", 0.0),
                        "momentum_20d": r.momentum_20d,
                        "momentum_60d": r.momentum_60d,
                    }
                    for r in (ind_rank[:10] if ind_rank else [])
                ],
                "concept": [
                    {
                        "symbol": r.symbol,
                        "score": r.score,
                        "momentum_5d": getattr(r, "momentum_5d", 0.0),
                        "momentum_20d": r.momentum_20d,
                        "momentum_60d": r.momentum_60d,
                    }
                    for r in (con_rank[:10] if con_rank else [])
                ],
            },
            "warnings": warnings,
            "correlation_matrix": corr_mat,
            "fallback_legacy_ranking": fallback,
            "regime": regime_info,
            "rotation_state": {"turnover_top5": turnover, "turnover_label": turn_label},
            "data_readiness": readiness,
            "three_factor_context": three_factor_context,
            "errors": errors,
            "config_snapshot": config_snap,
            "artifacts": artifact_refs,
            "indicator_runtime": {
                "task": "etf_rotation_research",
                "route": rt.route,
                "enabled": rt.migration_enabled,
                "dual_run": rt.dual_run,
                "rollback_enabled": rt.rollback_enabled,
                "primary_engine": engine,
                "shadow_engine": shadow_engine if rt.dual_run else None,
                "notes": rt.notes,
            },
            "shadow_compare": shadow_compare,
            "report_data": {
                "report_type": "etf_rotation_research",
                "llm_summary": llm_summary,
                # 勿把 run_rotation_pipeline 全量 pipe 塞进 toolResult：含 EtfRotationRow repr 等，
                # 易达数万 token，触发 LLM 空闲超时 / 模型降级后工具路由失败（cron 误调 research 时尤甚）。
                "raw": {
                    "ranked": ranked_payload,
                    "errors": errors,
                    "shadow_compare": shadow_compare,
                    "three_factor_context": three_factor_context,
                    "artifacts": artifact_refs,
                },
            },
        },
    }

