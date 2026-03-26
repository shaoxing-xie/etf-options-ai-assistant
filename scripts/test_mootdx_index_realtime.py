#!/usr/bin/env python3
"""
对比 mootdx 对「指数」的实时接口 quotes 与 K 线 bars（含 1 分钟 / 当前 fetch_index 使用的 frequency）。

用法（在项目根或任意目录，需能 import mootdx）：
  cd /home/xie/etf-options-ai-assistant
  python3 scripts/test_mootdx_index_realtime.py
  python3 scripts/test_mootdx_index_realtime.py --codes 000300,000001,399006

依赖：pip install mootdx（及 tdxpy 等 mootdx 依赖）
注意：通达信远程对指数 quotes 是否可用因线路/时段而异，以你本机实测为准。
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment,misc]


def _print_df(title: str, df: Any) -> None:
    print(f"\n=== {title} ===")
    if df is None:
        print("None")
        return
    try:
        empty = df.empty  # type: ignore[attr-defined]
    except Exception:
        empty = True
    if empty:
        print("(empty)")
        return
    try:
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(df)
    except Exception:
        print(df)


def main() -> int:
    parser = argparse.ArgumentParser(description="mootdx 指数 quotes vs bars 诊断")
    parser.add_argument(
        "--codes",
        type=str,
        default="000300,000001,399006",
        help="逗号分隔指数代码，默认 000300,000001,399006",
    )
    args = parser.parse_args()
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    if pd is None:
        print("需要 pandas", file=sys.stderr)
        return 1

    try:
        from mootdx.quotes import Quotes
    except ImportError:
        print(
            "未安装 mootdx：请先 pip install mootdx（建议在项目所用 venv 中执行）。",
            file=sys.stderr,
        )
        return 1

    # 与股票实时通道一致：尝试绕过 tdx 交易时间限制（部分环境需要）
    try:
        import tdxpy.hq as _tdx_hq  # type: ignore

        _tdx_hq.time_frame = lambda: True  # type: ignore[attr-defined]
    except Exception:
        pass

    print("指数代码:", codes)
    client = Quotes.factory(market="std")

    # ---------- 1) quotes：通达信「实时行情」接口（与 plugins/.../stock/fetch_realtime 同源思路） ----------
    for variant_name, sym_arg in [
        ("quotes(symbol=list)", codes),
        ("quotes(symbol=单码)", codes[0] if len(codes) == 1 else None),
    ]:
        if sym_arg is None:
            continue
        try:
            qdf = client.quotes(symbol=sym_arg)  # type: ignore[arg-type]
        except Exception as e:
            _print_df(f"{variant_name} 异常", None)
            print(repr(e))
            continue
        _print_df(variant_name, qdf)

    # ---------- 2) bars：1 分钟最后一根（盘中更接近「当前」）----------
    for code in codes:
        try:
            df_1m = client.bars(symbol=code, frequency=7, offset=8)
            _print_df(f"bars 1分钟 frequency=7 offset=8 | {code}", df_1m)
        except Exception as e:
            print(f"\n[bars 1m {code}] 异常: {e!r}")

    # ---------- 3) bars：旧版指数曾用 frequency=9 日 K 近似（业务代码已弃用，仅作对照） ----------
    for code in codes:
        try:
            df_d = client.bars(symbol=code, frequency=9, offset=2)
            _print_df(f"[对照] bars frequency=9（历史：日K近似，已不再用于 index 实时）| {code}", df_d)
        except Exception as e:
            print(f"\n[bars f9 {code}] 异常: {e!r}")

    try:
        client.close()
    except Exception:
        pass

    print(
        "\n解读建议：\n"
        "- 若 quotes 有非空 DataFrame 且 price 合理，指数实时应优先走 quotes。\n"
        "- 若 quotes 为空但 frequency=7 有数据，可用最后一根 1 分钟 close 作盘中近似。\n"
        "- frequency=9 仅为对照；项目内 index 实时已不再用日 K 充当现价。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
