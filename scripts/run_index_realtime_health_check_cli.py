#!/home/xie/etf-options-ai-assistant/.venv/bin/python
"""
关键指数实时可用性巡检（cron-safe）：
- 调用 tool_fetch_index_realtime 检查关键指数是否可实时获取；
- 命中缺失/兜底时，发送飞书摘要告警；
- 仅输出结构化 JSON，供 cron runs 审计。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODES = ["000688", "399673", "000300", "399006"]


def _safe_float(v: Any) -> float | None:
    try:
        if v in (None, ""):
            return None
        return float(v)
    except Exception:
        return None


def _normalize_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _evaluate(rows: list[dict[str, Any]], expect_codes: list[str], source: str) -> dict[str, Any]:
    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("code") or row.get("index_code") or "").strip()
        if code:
            by_code[code] = row

    missing: list[str] = [c for c in expect_codes if c not in by_code]
    bad_price: list[str] = []
    fallback_codes: list[str] = []
    for code in expect_codes:
        row = by_code.get(code)
        if not row:
            continue
        p = _safe_float(row.get("current_price"))
        if p is None or p <= 0:
            bad_price.append(code)
        msg = str(row.get("message") or "")
        if "暂时不可用" in msg:
            fallback_codes.append(code)

    source_lower = str(source or "").lower()
    source_is_fallback = "fallback" in source_lower
    degraded = bool(missing or bad_price or fallback_codes or source_is_fallback)
    return {
        "degraded": degraded,
        "missing_codes": missing,
        "bad_price_codes": sorted(set(bad_price)),
        "fallback_codes": sorted(set(fallback_codes)),
        "source": source,
        "source_is_fallback": source_is_fallback,
        "rows_count": len(rows),
    }


def _build_notify_message(result: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    title = "关键指数实时巡检告警"
    lines = [
        f"北京时间：{now}",
        "关键指数实时可用性巡检命中异常：",
        f"- source={result.get('source')}",
        f"- missing_codes={','.join(result.get('missing_codes') or []) or 'NONE'}",
        f"- bad_price_codes={','.join(result.get('bad_price_codes') or []) or 'NONE'}",
        f"- fallback_codes={','.join(result.get('fallback_codes') or []) or 'NONE'}",
        f"- rows_count={result.get('rows_count')}",
        f"- tool_message={payload.get('message')}",
    ]
    return title, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Realtime index health check + optional Feishu notify")
    parser.add_argument("--codes", default=",".join(DEFAULT_CODES), help="逗号分隔的指数代码")
    parser.add_argument("--mode", default="production", choices=["production", "test"])
    parser.add_argument("--no-notify", action="store_true", help="仅检查，不发送飞书")
    args = parser.parse_args()

    codes = [x.strip() for x in str(args.codes or "").split(",") if x.strip()]
    if not codes:
        print(json.dumps({"success": False, "error": "empty_codes"}, ensure_ascii=False))
        return 1

    sys.path.insert(0, str(ROOT))
    from plugins.data_collection.index.fetch_realtime import tool_fetch_index_realtime

    payload = tool_fetch_index_realtime(index_code=",".join(codes), mode=args.mode)
    rows = _normalize_rows(payload.get("data") if isinstance(payload, dict) else None)
    source = str((payload or {}).get("source") or "")
    eva = _evaluate(rows, codes, source)
    out: dict[str, Any] = {
        "success": bool(payload.get("success")) and (not eva["degraded"]),
        "degraded": eva["degraded"],
        "check_codes": codes,
        "source": eva["source"],
        "source_is_fallback": eva["source_is_fallback"],
        "missing_codes": eva["missing_codes"],
        "bad_price_codes": eva["bad_price_codes"],
        "fallback_codes": eva["fallback_codes"],
        "rows_count": eva["rows_count"],
        "tool_message": str(payload.get("message") or ""),
    }

    if not bool(payload.get("success")):
        out["success"] = False
        out["degraded"] = True

    if not out["degraded"] or args.no_notify:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["success"] else 1

    from plugins.merged.send_feishu_notification import tool_send_feishu_notification

    title, body = _build_notify_message(eva, payload if isinstance(payload, dict) else {})
    notify = tool_send_feishu_notification(
        "message",
        title=title,
        message=body,
        cooldown_minutes=0,
        cooldown_key=f"index-realtime-health:{datetime.now().strftime('%Y-%m-%d-%H')}",
    )
    out["notify_result"] = notify
    out["success"] = bool(notify.get("success")) and (not bool(out["degraded"]))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

