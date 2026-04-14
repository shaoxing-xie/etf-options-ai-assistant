#!/usr/bin/env python3
"""
趋势分析插件联网冒烟（盘后 / 盘前 / 开盘）。

在项目根目录执行（需已激活 .venv、能访问行情与缓存）：

  python scripts/smoke_trend_analysis.py
  python scripts/smoke_trend_analysis.py --mode after_close
  python scripts/smoke_trend_analysis.py --mode all
  python scripts/smoke_trend_analysis.py --mode opening_market --full-json out.json

说明：
  - after_close：拉 overlay（北向/全球/关键位/板块/可选 ADX）+ report_meta，并尝试 save_trend_analysis。
  - before_open：会拉隔夜 A50 与金龙 HXC（仅盘前使用）；样本不足或 yfinance 限流只影响本模式，盘后/开盘不依赖。
  - opening_market：依赖原系统与数据源，非交易日可能仍返回数据或提示。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_path() -> None:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _summarize_payload(name: str, result: Dict[str, Any]) -> None:
    print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
    print("success:", result.get("success"))
    print("message:", result.get("message"))
    data = result.get("data")
    if not isinstance(data, dict):
        print("data:", type(data).__name__, data)
        return
    print("data top-level keys:", sorted(data.keys())[:40], "..." if len(data) > 40 else "")
    rm = data.get("report_meta")
    if isinstance(rm, dict):
        print("report_meta:", json.dumps(rm, ensure_ascii=False, indent=2)[:4000])
        if len(json.dumps(rm, ensure_ascii=False)) > 4000:
            print("... (report_meta truncated)")
    overlay = data.get("daily_report_overlay")
    if overlay is None:
        print("daily_report_overlay: (none)")
    elif isinstance(overlay, dict):
        print("daily_report_overlay keys:", list(overlay.keys()))
        ts = overlay.get("trend_strength")
        if ts:
            print("  trend_strength:", ts)
    else:
        print("daily_report_overlay:", type(overlay).__name__)


def run_mode(mode: str) -> Dict[str, Any]:
    from plugins.analysis.trend_analysis import trend_analysis

    return trend_analysis(analysis_type=mode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test trend_analysis plugin (network).")
    parser.add_argument(
        "--mode",
        choices=("after_close", "before_open", "opening_market", "all"),
        default="after_close",
        help="分析类型；all 依次跑三种",
    )
    parser.add_argument(
        "--full-json",
        metavar="PATH",
        help="将每次完整 API 结果写入该文件（JSON Lines，一行一次调用）",
    )
    args = parser.parse_args()

    _ensure_path()
    os_cwd = Path.cwd()
    try:
        os.chdir(_repo_root())
    except Exception:
        pass

    modes = (
        ["after_close", "before_open", "opening_market"]
        if args.mode == "all"
        else [args.mode]
    )

    out_lines: list[str] = []
    code = 0
    for m in modes:
        try:
            result = run_mode(m)
        except Exception as e:
            print(f"\n[ERROR] {m}: {e}")
            code = 1
            continue
        _summarize_payload(m, result)
        if args.full_json:
            out_lines.append(json.dumps({"mode": m, "result": result}, ensure_ascii=False))

    if args.full_json and out_lines:
        p = Path(args.full_json)
        p.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"\nWrote {len(out_lines)} record(s) to {p.resolve()}")

    try:
        os.chdir(os_cwd)
    except Exception:
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
