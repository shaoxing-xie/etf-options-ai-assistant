"""
Runtime cross-checks after normalize_signal_generation_config.

消息分为 **hard**（破坏 Universe/合约一致性，CI 应失败）与 **soft**（运维提醒，CI 可仅打印）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

_HOLIDAY_NEXT_YEAR_HINT = "system.trading_hours.holidays has no year"


def classify_validation_messages(msgs: List[str]) -> Tuple[List[str], List[str]]:
    """(hard_errors, soft_warnings)"""
    soft = [m for m in msgs if m.startswith(_HOLIDAY_NEXT_YEAR_HINT)]
    hard = [m for m in msgs if m not in soft]
    return hard, soft


def universe_ssot_violations(config: Dict[str, Any]) -> List[str]:
    """仅 Universe / 合约骨架类 hard 问题（不含节假日次年提醒）。"""
    hard, _ = classify_validation_messages(cross_validate_runtime_config(config))
    return hard


def missing_runtime_surface_keys(config: Dict[str, Any], *, schema_path: Path) -> List[str]:
    """顶层键是否满足 ``runtime_surface.schema.json`` 的 ``required`` 列表。"""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = list(schema.get("required") or [])
    return [k for k in required if k not in config]


def cross_validate_runtime_config(config: Dict[str, Any]) -> List[str]:
    """Return human-readable warning messages (empty if nothing to flag)."""
    msgs: List[str] = []
    oc = config.get("option_contracts") or {}
    under = oc.get("underlyings") if isinstance(oc, dict) else None
    if not isinstance(under, list):
        return msgs

    for row in under:
        if not isinstance(row, dict):
            continue
        u = str(row.get("underlying") or "")
        for side in ("call_contracts", "put_contracts"):
            lst = row.get(side) or []
            if not isinstance(lst, list):
                continue
            codes: List[str] = []
            for it in lst:
                if isinstance(it, dict) and it.get("contract_code") is not None:
                    codes.append(str(it["contract_code"]).strip())
            dup = {c for c in codes if codes.count(c) > 1}
            if dup:
                msgs.append(f"duplicate contract_code in {u} {side}: {sorted(dup)}")

    dc = config.get("data_cache") or {}
    etf_codes = {str(x) for x in (dc.get("etf_codes") or []) if x is not None}
    etf_tr = config.get("etf_trading") or {}
    enabled_etfs = {str(x) for x in (etf_tr.get("enabled_etfs") or []) if x is not None}

    for row in under:
        if not isinstance(row, dict):
            continue
        u = str(row.get("underlying") or "")
        if u.isdigit() and len(u) == 6 and u.startswith(("51", "15")):
            if etf_codes and u not in etf_codes:
                msgs.append(
                    f"option underlying {u} not listed in data_cache.etf_codes (cache collection may miss it)"
                )
            if enabled_etfs and u not in enabled_etfs:
                msgs.append(f"option underlying {u} not in etf_trading.enabled_etfs")

    th = (config.get("system") or {}).get("trading_hours") or {}
    hol = th.get("holidays")
    if isinstance(hol, dict) and hol:
        years = sorted(int(y) for y in hol.keys() if str(y).isdigit())
        if years:
            next_y = datetime.now().year + 1
            if next_y not in years and max(years) < next_y:
                msgs.append(
                    f"{_HOLIDAY_NEXT_YEAR_HINT} {next_y} — see docs/configuration/trading_calendar_ops.md"
                )

    return msgs
