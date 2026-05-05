"""L3 决策记忆：契约化 JSONL 与预测验证反思（append-only）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.data_layer import MetaEnvelope, append_contract_jsonl
from src.orchestrator.registry import project_root


def _ymd_from_any(date_str: str) -> str:
    """YYYYMMDD 或 YYYY-MM-DD -> YYYY-MM-DD。"""
    s = (date_str or "").strip().replace("-", "")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(date_str) == 10 and date_str[4] == "-":
        return date_str
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def memory_jsonl_path(root: Path | None, trade_date: str) -> Path:
    r = project_root() if root is None else root
    td = _ymd_from_any(trade_date)
    return r / "data" / "decisions" / "memory" / f"decisions_{td}.jsonl"


def append_decision_memory_entry(
    *,
    task_id: str,
    run_id: str,
    trade_date: str,
    entity: str,
    decision: dict[str, Any],
    signals: list[dict[str, Any]] | None = None,
    step_id: str = "",
    root: Path | None = None,
    quality_status: str = "ok",
    lineage_refs: list[str] | None = None,
) -> str:
    """写入 decision_memory_entry_v1；返回 decision_id。"""
    r = project_root() if root is None else root
    td = _ymd_from_any(trade_date)
    decision_id = f"dec_{uuid.uuid4().hex[:16]}"
    payload: dict[str, Any] = {
        "decision_id": decision_id,
        "entity": entity,
        "decision": decision,
        "signals": signals or [],
        "step_id": step_id,
    }
    path = memory_jsonl_path(r, td)
    append_contract_jsonl(
        path,
        payload=payload,
        meta=MetaEnvelope(
            schema_name="decision_memory_entry_v1",
            schema_version="1.0.0",
            task_id=task_id,
            run_id=run_id,
            data_layer="L3_decision",
            trade_date=td,
            quality_status=quality_status,
            lineage_refs=lineage_refs or [],
        ),
    )
    return decision_id


def append_decision_reflection(
    *,
    task_id: str,
    run_id: str,
    trade_date: str,
    entity: str,
    reflection: dict[str, Any],
    root: Path | None = None,
    quality_status: str = "ok",
    lineage_refs: list[str] | None = None,
) -> None:
    """写入 decision_reflection_v1。"""
    r = project_root() if root is None else root
    td = _ymd_from_any(trade_date)
    path = memory_jsonl_path(r, td)
    append_contract_jsonl(
        path,
        payload={"entity": entity, "reflection": reflection},
        meta=MetaEnvelope(
            schema_name="decision_reflection_v1",
            schema_version="1.0.0",
            task_id=task_id,
            run_id=run_id,
            data_layer="L3_decision",
            trade_date=td,
            quality_status=quality_status,
            lineage_refs=lineage_refs or [],
        ),
    )


def read_recent_reflection_lines(
    *,
    entity: str,
    trade_date: str,
    lookback_days: int = 30,
    limit: int = 20,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """读取近若干自然日 JSONL 中含该 entity 的反思/决策摘要（轻量）。"""
    r = project_root() if root is None else root
    end = datetime.strptime(_ymd_from_any(trade_date), "%Y-%m-%d").date()
    out: list[dict[str, Any]] = []
    for d in range(lookback_days + 1):
        day = end - timedelta(days=d)
        td = day.strftime("%Y-%m-%d")
        path = memory_jsonl_path(r, td)
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if len(out) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = row.get("data") if isinstance(row, dict) else None
            meta = row.get("_meta") if isinstance(row, dict) else None
            if not isinstance(data, dict):
                continue
            if str(data.get("entity") or "") != entity:
                continue
            sn = meta.get("schema_name") if isinstance(meta, dict) else ""
            out.append(
                {
                    "schema_name": sn,
                    "trade_date": meta.get("trade_date") if isinstance(meta, dict) else td,
                    "data": data,
                }
            )
    return out


def build_memory_injection_text(
    *,
    entity: str,
    trade_date: str,
    lookback_days: int = 30,
    limit: int = 8,
    root: Path | None = None,
) -> str:
    """供 LLM / 工具上下文注入的短文本。"""
    rows = read_recent_reflection_lines(
        entity=entity, trade_date=trade_date, lookback_days=lookback_days, limit=limit, root=root
    )
    if not rows:
        return ""
    lines: list[str] = [
        f"## 历史决策记忆摘录（标的 {entity}，最近 {lookback_days} 日内至多 {limit} 条）",
    ]
    for r in rows:
        data = r.get("data") or {}
        if r.get("schema_name") == "decision_reflection_v1":
            ref = data.get("reflection") if isinstance(data.get("reflection"), dict) else {}
            lesson = ref.get("key_lesson") or ref.get("summary")
            if lesson:
                lines.append(f"- ({r.get('trade_date')}) 反思: {lesson}")
        else:
            dec = data.get("decision")
            if isinstance(dec, dict):
                lines.append(f"- ({r.get('trade_date')}) 决策摘要键: {list(dec.keys())[:6]}")
    return "\n".join(lines)


def rule_reflection_from_range_hit(*, symbol: str, hit: bool, coverage_rate: float | None) -> dict[str, Any]:
    """区间预测验证后的规则化反思。"""
    if hit:
        lesson = "区间预测命中：实际高低价落在预测区间内。"
        sug = "可保持当前区间预测与质量门禁参数。"
    else:
        lesson = "区间预测未命中：实际价格突破预测上下轨。"
        sug = "建议复查波动率假设与 prediction_quality 门闸；关注是否需扩大区间或缩短持有期。"
    return {
        "was_correct": bool(hit),
        "key_lesson": lesson,
        "improvement_suggestions": sug,
        "coverage_rate": coverage_rate,
        "symbol": symbol,
        "source": "prediction_range_verification",
    }


def rule_reflection_from_direction(
    *,
    symbol: str,
    predicted: str,
    actual: str,
    hit: bool,
) -> dict[str, Any]:
    """方向预测验证后的规则化反思。"""
    if hit:
        lesson = f"方向预测正确：预测 {predicted} vs 实际 {actual}。"
    else:
        lesson = f"方向预测错误：预测 {predicted} vs 实际 {actual}；需审视趋势信号与阈值。"
    return {
        "was_correct": bool(hit),
        "key_lesson": lesson,
        "predicted_direction": predicted,
        "actual_direction": actual,
        "symbol": symbol,
        "source": "prediction_direction_verification",
    }
