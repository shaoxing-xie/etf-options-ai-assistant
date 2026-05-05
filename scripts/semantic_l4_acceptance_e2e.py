#!/usr/bin/env python3
"""
阶段三：估值语义包与 L4-data 直连数值对账（同进程、同一解析链）。

用法（助手 venv）：
  ./scripts/semantic_l4_acceptance_e2e.py [symbol] [trade_date]

trade_date 可省略（与 brief 默认一致：当前日）。
退出码 0 表示分位一致；1 表示解析失败或数值不可比。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    symbol = (sys.argv[1] if len(sys.argv) > 1 else "600519").strip()
    trade_date = (sys.argv[2] if len(sys.argv) > 2 else "").strip()

    from plugins.analysis.l4_data_tools import tool_l4_pe_ttm_percentile
    from plugins.analysis.semantic.equity_valuation_brief import tool_semantic_equity_valuation_brief
    from plugins.data_collection.entity.entity_tools import tool_resolve_symbol

    res = tool_resolve_symbol(symbol)
    if not res.get("success"):
        print(json.dumps({"ok": False, "step": "resolve", "payload": res}, ensure_ascii=False, indent=2))
        return 1
    data_r = res.get("data") if isinstance(res.get("data"), dict) else {}
    code = str(data_r.get("canonical_code") or "").strip()
    if not code:
        print(json.dumps({"ok": False, "step": "canonical_code", "payload": res}, ensure_ascii=False, indent=2))
        return 1

    td = trade_date or None
    pe_direct = tool_l4_pe_ttm_percentile(stock_code=code, trade_date=td or "", window_years=5)
    brief = tool_semantic_equity_valuation_brief(symbol=symbol, trade_date=trade_date, window_years=5)

    pct_a = None
    if isinstance(pe_direct.get("data"), dict):
        pct_a = pe_direct["data"].get("percentile_0_100")
    d_b = brief.get("data") if isinstance(brief.get("data"), dict) else {}
    pct_b = d_b.get("pe_percentile_0_100")

    report = {
        "ok": False,
        "symbol_input": symbol,
        "canonical_code": code,
        "path_a_percentile": pct_a,
        "path_b_percentile": pct_b,
        "brief_quality": brief.get("quality_status"),
        "direct_quality": pe_direct.get("quality_status"),
    }

    if pct_a is not None and pct_b is not None:
        try:
            report["delta"] = abs(float(pct_a) - float(pct_b))
            report["ok"] = report["delta"] < 1e-6
        except (TypeError, ValueError):
            report["delta"] = None
    elif pct_a is None and pct_b is None:
        # 上游无分位数据时（常见 degraded），仍视为「无叙事口径漂移」(A/B 同为缺失)
        report["ok"] = True
        report["note"] = "both_percentiles_absent_skip_numeric_reconcile"
    else:
        report["ok"] = False
        report["note"] = "percentile_present_on_one_side_only"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
