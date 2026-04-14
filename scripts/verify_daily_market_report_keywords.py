#!/usr/bin/env python3
"""
弱校验：每日市场分析报告（daily_market）正文中是否出现计划章节关键词。
用法:
  python3 scripts/verify_daily_market_report_keywords.py --file path/to/body.md
  python3 scripts/verify_daily_market_report_keywords.py --stdin < body.md
  printf '%s\\n' '## 执行摘要' '## 大盘与量能' '## 资金' '## 展望' '`DAILY_REPORT_STATUS=OK`' \\
    | python3 scripts/verify_daily_market_report_keywords.py --stdin --fast
  （勿用「echo sample」：正文须含 --fast 所需章节标题与审计行。）
退出码 0=通过；1=缺失过多；2=参数错误。

注意：未指定 --file / --stdin 时**不得**隐式读 stdin（易在 CI/无管道时永久阻塞）。

--fast：仅校验核心小节关键词（适合 CI 快速门禁）。
"""
from __future__ import annotations

import argparse
import sys


KEYWORDS = (
    "大盘与量能",
    "主要 ETF",
    "结构与主线",
    "板块",
    "资金",
    "信息面",
    "外围",
    "波动",
    "信号",
    "展望",
    "DAILY_REPORT_STATUS",
)

# CI 快速门禁：章节骨架 + 审计行（允许缺失若干增强小节）
KEYWORDS_FAST = (
    "执行摘要",
    "大盘与量能",
    "资金",
    "展望",
    "DAILY_REPORT_STATUS",
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", help="Markdown 正文文件")
    p.add_argument("--stdin", action="store_true", help="从 stdin 读取")
    p.add_argument(
        "--fast",
        action="store_true",
        help="仅校验 KEYWORDS_FAST（子集），适合 pytest/CI 快速跑",
    )
    args = p.parse_args()
    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.stdin:
        text = sys.stdin.read()
    else:
        print(
            "ERROR: 请指定 --file PATH 或 --stdin（勿无参数运行，否则易误阻塞）",
            file=sys.stderr,
        )
        return 2
    if not text.strip():
        print("ERROR: empty body", file=sys.stderr)
        return 1
    keys = KEYWORDS_FAST if args.fast else KEYWORDS
    missing = [k for k in keys if k not in text]
    ok = len(missing) <= (1 if args.fast else 2)
    if missing:
        print("missing:", ", ".join(missing))
    print(f"matched {len(keys) - len(missing)}/{len(keys)} keywords ({'fast' if args.fast else 'full'})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
