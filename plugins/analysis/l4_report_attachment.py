"""
T2 Cron：可选附加 `tool_l4_*` 估值摘要块（失败降级，不阻断主报告）。

环境：`ASSISTANT_INCLUDE_L4_SNAPSHOT=1`（默认）附加；`0`/`false`/`off` 关闭（基线 parity）。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

L4_MARKDOWN_HEADING = "## L4 / 估值摘要"
_SCHEMA = "report_l4_snapshot_attachment_v1"
_SCHEMA_VER = "1.0.0"


def include_l4_snapshot() -> bool:
    v = os.environ.get("ASSISTANT_INCLUDE_L4_SNAPSHOT", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def strip_l4_section(markdown: str) -> str:
    if not markdown:
        return markdown
    idx = markdown.find(L4_MARKDOWN_HEADING)
    if idx < 0:
        return markdown
    return markdown[:idx].rstrip()


_time_line_re = re.compile(r"^\*\*分析时间：\*\*.+$", re.MULTILINE)
_done_line_re = re.compile(r"^\*分析完成时间：.+$", re.MULTILINE)


def normalize_core_markdown_for_parity(text: str) -> str:
    """剔除 L4 块与常见时间戳行，供确定性 parity。"""
    t = strip_l4_section(text or "")
    lines_out: List[str] = []
    for ln in t.splitlines():
        if _time_line_re.match(ln.strip()):
            continue
        if _done_line_re.match(ln.strip()):
            continue
        lines_out.append(ln)
    return "\n".join(lines_out).strip()


def normalize_symbol(sym: str) -> str:
    s = str(sym).strip().lower().replace(".sh", "").replace(".sz", "")
    if s.startswith("sh") or s.startswith("sz"):
        s = s[2:]
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return s[:8] if s else ""


def dedupe_symbols(codes: Iterable[str], *, max_n: int = 8) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for c in codes:
        n = normalize_symbol(c)
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
        if len(out) >= max_n:
            break
    return out


def _extract_confidence(val_payload: Dict[str, Any]) -> Optional[float]:
    data = val_payload.get("data") if isinstance(val_payload.get("data"), dict) else {}
    c = data.get("confidence")
    if isinstance(c, (int, float)):
        return float(c)
    meta = val_payload.get("_meta") if isinstance(val_payload.get("_meta"), dict) else {}
    c2 = meta.get("confidence")
    if isinstance(c2, (int, float)):
        return float(c2)
    return None


def _extract_pe_hint(pe_payload: Dict[str, Any]) -> str:
    data = pe_payload.get("data") if isinstance(pe_payload.get("data"), dict) else {}
    for k in ("band_label", "percentile_label", "bucket", "summary"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:80]
    return ""


def build_l4_bundle_for_symbols(
    symbols: List[str],
    *,
    trade_date: str,
    task_id: str,
    run_id: str = "",
    max_symbols: int = 8,
) -> Dict[str, Any]:
    """调用插件 L4 工具；单标的失败不抛。"""
    from plugins.analysis.l4_data_tools import tool_l4_pe_ttm_percentile, tool_l4_valuation_context

    codes = dedupe_symbols(symbols, max_n=max_symbols)
    rid = (run_id or "").strip() or datetime.now().strftime("%Y%m%dT%H%M%S")
    lineage_refs: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    ok_n = 0

    for code in codes:
        val: Dict[str, Any] = {}
        pe: Dict[str, Any] = {}
        try:
            val = tool_l4_valuation_context(stock_code=code, trade_date=trade_date or "")
        except Exception as exc:  # noqa: BLE001
            val = {"success": False, "message": str(exc)}
        try:
            pe = tool_l4_pe_ttm_percentile(stock_code=code, trade_date=trade_date or "")
        except Exception as exc:  # noqa: BLE001
            pe = {"success": False, "message": str(exc)}

        v_ok = bool(isinstance(val, dict) and val.get("success", True))
        p_ok = bool(isinstance(pe, dict) and pe.get("success", True))
        if v_ok:
            ok_n += 1
        lineage_refs.append({"tool": "tool_l4_valuation_context", "symbol": code, "success": v_ok})
        lineage_refs.append({"tool": "tool_l4_pe_ttm_percentile", "symbol": code, "success": p_ok})

        rows.append(
            {
                "symbol": code,
                "valuation_ok": v_ok,
                "pe_ok": p_ok,
                "confidence": _extract_confidence(val) if isinstance(val, dict) else None,
                "pe_hint": _extract_pe_hint(pe) if isinstance(pe, dict) else "",
            }
        )

    if not codes:
        q = "error"
    elif ok_n == len(codes):
        q = "ok"
    elif ok_n > 0:
        q = "degraded"
    else:
        q = "error"

    return {
        "per_symbol": rows,
        "_meta": {
            "schema_name": _SCHEMA,
            "schema_version": _SCHEMA_VER,
            "data_layer": "L4_data",
            "task_id": task_id,
            "run_id": rid,
            "trade_date": trade_date or None,
            "quality_status": q,
            "lineage_refs": lineage_refs,
            "source_tools": ["tool_l4_valuation_context", "tool_l4_pe_ttm_percentile"],
        },
    }


def format_l4_appendix_markdown(bundle: Dict[str, Any]) -> str:
    meta = bundle.get("_meta") if isinstance(bundle.get("_meta"), dict) else {}
    q = str(meta.get("quality_status") or "unknown")
    lines: List[str] = [L4_MARKDOWN_HEADING, ""]
    if q == "error":
        lines.append("*L4 暂缺（不可用）。*")
        return "\n".join(lines)
    if q == "degraded":
        lines.append("*L4 部分降级：下列条目可能缺失 PE 分位或估值置信度。*")
        lines.append("")
    per = bundle.get("per_symbol") if isinstance(bundle.get("per_symbol"), list) else []
    if not per:
        lines.append("*无标的。*")
        return "\n".join(lines)
    lines.append("| 标的 | 估值置信度 | PE 分位/摘要 |")
    lines.append("| --- | --- | --- |")
    for row in per:
        if not isinstance(row, dict):
            continue
        sym = row.get("symbol") or ""
        conf = row.get("confidence")
        conf_s = f"{float(conf):.3f}" if isinstance(conf, (int, float)) else ("—" if not row.get("valuation_ok") else "N/A")
        pe_s = str(row.get("pe_hint") or "").strip() or ("—" if not row.get("pe_ok") else "N/A")
        lines.append(f"| {sym} | {conf_s} | {pe_s} |")
    return "\n".join(lines)


def attach_l4_snapshot_to_report_data(
    rd: Dict[str, Any],
    *,
    symbols: List[str],
    trade_date: str,
    task_id: str,
    run_id: str = "",
    max_symbols: int = 8,
) -> None:
    """就地写入 `l4_snapshot` / `l4_markdown_appendix`。"""
    if not include_l4_snapshot():
        return
    bundle = build_l4_bundle_for_symbols(
        symbols, trade_date=trade_date, task_id=task_id, run_id=run_id, max_symbols=max_symbols
    )
    rd["l4_snapshot"] = bundle
    rd["l4_markdown_appendix"] = format_l4_appendix_markdown(bundle)
    ls = rd.get("lineage_struct")
    if isinstance(ls, list):
        meta = bundle.get("_meta") if isinstance(bundle.get("_meta"), dict) else {}
        q = str(meta.get("quality_status") or "")
        ls.append(
            {
                "stage": "l4_attachment",
                "tool_key": "report_l4_snapshot_attachment_v1",
                "success": q != "error",
                "quality_status": "ok" if q == "ok" else ("degraded" if q == "degraded" else "error"),
                "source_hint": f"symbols={len(bundle.get('per_symbol') or [])}",
            }
        )


def symbols_from_daily_report_data(rd: Dict[str, Any]) -> List[str]:
    """宽基 ETF 代码：优先实时块，其次默认清单。"""
    out: List[str] = []
    etf_rt = rd.get("tool_fetch_etf_realtime")
    payload = etf_rt.get("data") if isinstance(etf_rt, dict) else None
    rows = payload if isinstance(payload, list) else []
    for item in rows[:12]:
        if not isinstance(item, dict):
            continue
        c = str(item.get("etf_code") or item.get("code") or item.get("symbol") or "").strip()
        if c:
            out.append(c)
    if not out:
        out = ["510300", "510500", "510050", "159919", "159915", "588000"]
    return dedupe_symbols(out, max_n=8)


def symbols_from_opening_report_data(rd: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    etf_rt = rd.get("tool_fetch_etf_realtime")
    if isinstance(etf_rt, dict) and isinstance(etf_rt.get("data"), list):
        for item in (etf_rt.get("data") or [])[:12]:
            if isinstance(item, dict):
                c = str(item.get("etf_code") or item.get("code") or "").strip()
                if c:
                    out.append(c)
    if not out:
        out = ["510300", "510500", "588000"]
    return dedupe_symbols(out, max_n=8)
