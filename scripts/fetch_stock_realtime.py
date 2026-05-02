#!/usr/bin/env python3
"""
实时行情获取模块（供 alert_engine 使用）

约束：
- 优先/默认通过采集插件现成工具 `tool_fetch_stock_realtime` 获取数据
- 不在助手侧脚本里直连 akshare / mootdx，避免口径漂移
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        # Some tool variants return dict rows keyed by code.
        if all(isinstance(v, dict) for v in data.values()):
            rows: list[dict[str, Any]] = []
            for k, v in data.items():
                row = dict(v)
                row.setdefault("stock_code", str(k))
                rows.append(row)
            return rows
        return [data]
    return []


def fetch_batch(codes: list[str]) -> dict:
    """批量获取 A 股实时行情（统一走 tool_fetch_stock_realtime）。"""
    uniq_codes = [str(c).strip() for c in codes if str(c).strip()]
    uniq_codes = [c for i, c in enumerate(uniq_codes) if c not in uniq_codes[:i]]
    if not uniq_codes:
        return {}

    runner = _repo_root() / "tool_runner.py"
    if not runner.is_file():
        return {}

    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(runner),
                "tool_fetch_stock_realtime",
                json.dumps({"stock_code": ",".join(uniq_codes), "mode": "production"}, ensure_ascii=False),
            ],
            cwd=str(_repo_root()),
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
        out = json.loads((proc.stdout or "").strip() or "{}")
    except Exception:
        return {}

    if not isinstance(out, dict) or not bool(out.get("success")):
        return {}

    rows = _normalize_rows(out.get("data"))
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("stock_code") or row.get("代码") or row.get("symbol") or "").strip()
        if not code:
            continue
        result[code] = {
            "current": row.get("current_price", row.get("最新价")),
            "change_pct": row.get("change_pct", row.get("涨跌幅")),
            "high": row.get("high_price", row.get("最高")),
            "low": row.get("low_price", row.get("最低")),
            "volume": row.get("volume", row.get("成交量")),
            "prev_close": row.get("prev_close", row.get("昨收")),
            "open": row.get("open_price", row.get("开盘")),
            "name": row.get("name", row.get("股票简称", "")),
        }
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fetch_stock_realtime.py <code1> [code2] ...")
        sys.exit(1)
    
    codes = sys.argv[1:]
    data = fetch_batch(codes)
    print(json.dumps(data, ensure_ascii=False, indent=2))
