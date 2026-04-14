#!/usr/bin/env python3
"""
本地验证 tool_assess_risk / assess_risk（需项目根目录执行，建议先 .venv）。

用法：
  cd /path/to/etf-options-ai-assistant
  .venv/bin/python scripts/test_risk_assessment.py

个股拉数需外网；可选：
  RISK_ASSESS_STOCK_SMOKE=1 .venv/bin/python scripts/test_risk_assessment.py

仅跑 tool_runner JSON 输出（与 Agent 调用一致）：
  .venv/bin/python tool_runner.py tool_assess_risk '{"symbol":"510300","entry_price":4.6,"position_size":500,"account_value":100000,"asset_type":"auto"}'
"""

from __future__ import annotations

import json
import os
import sys


def _root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    root = _root()
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(root)

    from plugins.analysis.risk_assessment import assess_risk, _normalize_symbol, tool_assess_risk

    print("=== 1. _normalize_symbol ===")
    for s in ("510300", "sh510300", "600000.SH", "sz000001"):
        a, e = _normalize_symbol(s)
        print(f"  {s!r} -> {a!r} err={e!r}")

    print("\n=== 2. 错误路径 ===")
    r1 = assess_risk(symbol="bad", position_size=1, entry_price=1.0, account_value=1000)
    print("  invalid symbol:", r1.get("success"), r1.get("message"))
    r2 = assess_risk(
        symbol="510300",
        position_size=1,
        entry_price=1.0,
        account_value=1000,
        asset_type="typo",
    )
    print("  bad asset_type:", r2.get("success"), r2.get("message"))

    print("\n=== 3. assess_risk 510300 asset_type=auto（需外网/数据源）===")
    r3 = assess_risk(
        symbol="510300",
        position_size=500,
        entry_price=4.6,
        account_value=100_000,
        asset_type="auto",
        lookback_trading_days=60,
    )
    print("  success:", r3.get("success"))
    if r3.get("data"):
        d = r3["data"]
        print(
            "  volatility(%%):",
            d.get("volatility"),
            "source:",
            d.get("price_data_source"),
            "stop:",
            d.get("stop_loss"),
            "risk_level:",
            d.get("risk_level"),
        )
    else:
        print("  message:", r3.get("message"))

    print("\n=== 4. tool_assess_risk（OpenClaw 入口，参数与 manifest 一致）===")
    r4 = tool_assess_risk(
        symbol="510300",
        position_size=500,
        entry_price=4.6,
        account_value=100_000,
        asset_type="etf",
        lookback_trading_days=60,
    )
    print("  success:", r4.get("success"))
    if r4.get("data"):
        print("  data keys:", sorted(r4["data"].keys()))

    if os.environ.get("RISK_ASSESS_STOCK_SMOKE") == "1":
        print("\n=== 5. 个股（RISK_ASSESS_STOCK_SMOKE=1，依赖 akshare/东财）===")
        r5 = assess_risk(
            symbol="600519",
            position_size=100,
            entry_price=1500.0,
            account_value=1_000_000,
            asset_type="stock",
        )
        print("  success:", r5.get("success"), "msg:", r5.get("message"))
        if r5.get("data"):
            print("  volatility:", r5["data"].get("volatility"))
    else:
        print("\n=== 5. 跳过个股（设 RISK_ASSESS_STOCK_SMOKE=1 可测）===")

    print("\n=== JSON（最后一项主用例）===")
    print(json.dumps(r4, ensure_ascii=False, indent=2))
    return 0 if r3.get("success") and r4.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
