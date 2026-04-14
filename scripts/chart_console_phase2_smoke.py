#!/usr/bin/env python3
# Chart Console Pro（API 服务）冒烟：拉起 server.py 并请求若干关键端点。
#
# 用法示例（在项目根目录执行）：
#   python3 scripts/chart_console_phase2_smoke.py

from __future__ import annotations

import json
import subprocess
import time
import urllib.request


def get(url: str):
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    proc = subprocess.Popen(["python3", "apps/chart_console/api/server.py"])
    try:
        for _ in range(20):
            time.sleep(1)
            try:
                if get("http://127.0.0.1:8611/api/health").get("success"):
                    break
            except Exception:
                continue
        checks = {
            "ohlcv": get("http://127.0.0.1:8611/api/ohlcv?symbol=510300&lookback_days=120").get("success"),
            "indicators": get(
                "http://127.0.0.1:8611/api/indicators?symbol=510300&lookback_days=120&timeframe_minutes=30&ma_periods=5,10,20,60"
            ).get("success"),
            "backtest": get(
                "http://127.0.0.1:8611/api/backtest?symbol=510300&lookback_days=180&fast_ma=10&slow_ma=30&fee_bps=3&slippage_bps=2"
            ).get("success"),
            "workspace_list": get("http://127.0.0.1:8611/api/workspaces").get("success"),
            "alert_replay": get("http://127.0.0.1:8611/api/alerts/replay").get("success"),
        }
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
