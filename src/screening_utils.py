"""选股插件 JSON 校验与观察池载荷构造。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def validate_screening_response(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """检查 tool_screen_equity_factors 契约字段；返回 (ok, issues)。"""
    issues: List[str] = []
    if not isinstance(payload, dict):
        return False, ["not_a_dict"]
    for k in ("success", "quality_score", "degraded", "config_hash", "elapsed_ms", "plugin_version"):
        if k not in payload:
            issues.append(f"missing:{k}")
    if payload.get("success"):
        data = payload.get("data")
        if not isinstance(data, list):
            issues.append("data_not_list")
        else:
            for i, row in enumerate(data):
                if not isinstance(row, dict):
                    issues.append(f"row_{i}_not_object")
                    continue
                for col in ("symbol", "score", "factors"):
                    if col not in row:
                        issues.append(f"row_{i}_missing_{col}")
    return len(issues) == 0, issues


def picks_for_notification(payload: Dict[str, Any], max_lines: int = 12) -> str:
    """生成钉钉/飞书用的短文本摘要。"""
    if not payload.get("success"):
        return f"[screening] success=false message={payload.get('message')!r}"
    lines: List[str] = []
    rows = payload.get("data") or []
    for row in rows[:max_lines]:
        if not isinstance(row, dict):
            continue
        sym = row.get("symbol")
        sc = row.get("score")
        lines.append(f"- {sym}: score={sc}")
    tail = f"\n…(截断至{max_lines}条)" if len(rows) > max_lines else ""
    hdr = (
        f"quality={payload.get('quality_score')} degraded={payload.get('degraded')} "
        f"hash={payload.get('config_hash')} version={payload.get('plugin_version')}"
    )
    return hdr + "\n" + "\n".join(lines) + tail
