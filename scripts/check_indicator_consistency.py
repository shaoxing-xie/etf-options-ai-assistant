#!/usr/bin/env python3
# 对比两条指标计算链路的一致性（标准服务 vs chart_console API fallback）。
#
# 用法示例（在项目根目录执行）：
#   python3 scripts/check_indicator_consistency.py

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.indicator_service import IndicatorService
from apps.chart_console.api.routes import ApiRoutes
from apps.chart_console.api.services import ApiServices


def main() -> int:
    symbol = "510300"
    lookback = 180
    ma_periods = [5, 10, 20, 60]
    svc = IndicatorService()
    std = svc.calculate(symbol=symbol, lookback_days=lookback, ma_periods=ma_periods)

    routes = ApiRoutes(ApiServices())
    fallback, _ = routes.handle_get(
        "/api/indicators",
        {"symbol": [symbol], "lookback_days": [str(lookback)], "timeframe_minutes": ["30"], "ma_periods": [",".join(str(x) for x in ma_periods)]},
    )
    out = {
        "symbol": symbol,
        "std_success": std.get("success"),
        "api_success": fallback.get("success"),
        "std_message": std.get("message"),
        "api_message": fallback.get("message"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
