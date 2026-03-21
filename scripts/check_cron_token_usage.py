#!/usr/bin/env python3
"""
汇总 ~/.openclaw/cron/runs/*.jsonl 中近期 finished 记录的 usage（input_tokens 等），
用于对比 P0/P1 优化前后的 token 消耗。用法：
  python scripts/check_cron_token_usage.py [--days 7] [--top 20]
"""
from pathlib import Path
import argparse
import json
from datetime import datetime, timezone, timedelta


def main() -> None:
    ap = argparse.ArgumentParser(description="汇总 cron 运行日志中的 token 使用")
    ap.add_argument("--days", type=int, default=7, help="统计最近 N 天")
    ap.add_argument("--top", type=int, default=20, help="输出 input_tokens 最高的前 N 条")
    args = ap.parse_args()

    runs_dir = Path.home() / ".openclaw" / "cron" / "runs"
    if not runs_dir.exists():
        print(f"目录不存在: {runs_dir}")
        return

    cutoff_ms = (datetime.now(timezone.utc) - timedelta(days=args.days)).timestamp() * 1000
    records: list[dict] = []

    for p in runs_dir.glob("*.jsonl"):
        try:
            for line in p.open(encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("action") != "finished" or "usage" not in obj:
                    continue
                run_at = obj.get("runAtMs") or 0
                if run_at < cutoff_ms:
                    continue
                usage = obj.get("usage") or {}
                inp = usage.get("input_tokens") or 0
                records.append({
                    "jobId": obj.get("jobId", ""),
                    "runAtMs": run_at,
                    "input_tokens": inp,
                    "output_tokens": usage.get("output_tokens") or 0,
                    "total_tokens": usage.get("total_tokens") or 0,
                    "status": obj.get("status", ""),
                    "durationMs": obj.get("durationMs"),
                })
        except OSError as e:
            print(f"读取 {p}: {e}", file=__import__("sys").stderr)

    records.sort(key=lambda x: x["input_tokens"], reverse=True)
    print(f"最近 {args.days} 天 finished 记录数: {len(records)}")
    print(f"input_tokens 最高的前 {args.top} 条:\n")
    for i, r in enumerate(records[: args.top], 1):
        ts = datetime.fromtimestamp(r["runAtMs"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"  {i}. jobId={r['jobId'][:20]}... runAt={ts} input_tokens={r['input_tokens']} total={r['total_tokens']} status={r['status']}")

    if records:
        avg_inp = sum(r["input_tokens"] for r in records) / len(records)
        print(f"\n平均 input_tokens: {avg_inp:.0f}")


if __name__ == "__main__":
    main()
