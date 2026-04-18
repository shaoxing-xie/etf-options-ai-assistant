#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize OpenClaw token usage by day/agent/session.")
    ap.add_argument("--date", required=True, help="Date in YYYY-MM-DD, e.g. 2026-04-17")
    ap.add_argument("--top", type=int, default=20, help="Top N sessions")
    ap.add_argument("--agents-root", default=str(Path.home() / ".openclaw/agents"))
    args = ap.parse_args()

    root = Path(args.agents_root)
    by_session = []
    by_agent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for p in root.glob("*/sessions/*.jsonl"):
        agent = p.parts[-3]
        in_tok = out_tok = total = retries = 0
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if args.date not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") == "message":
                m = obj.get("message") or {}
                if m.get("role") == "assistant":
                    u = m.get("usage") or {}
                    in_tok += int(u.get("input") or 0)
                    out_tok += int(u.get("output") or 0)
                    total += int(u.get("totalTokens") or 0)
            elif obj.get("type") == "custom" and obj.get("customType") == "openclaw:prompt-error":
                retries += 1
        if total > 0 or retries > 0:
            by_session.append((total, in_tok, out_tok, retries, agent, p.name))
            by_agent[agent]["total"] += total
            by_agent[agent]["input"] += in_tok
            by_agent[agent]["output"] += out_tok
            by_agent[agent]["retries"] += retries
            by_agent[agent]["sessions"] += 1

    by_session.sort(reverse=True, key=lambda x: x[0])
    print(f"Top {args.top} sessions on {args.date}:")
    for total, in_tok, out_tok, retries, agent, name in by_session[: args.top]:
        print(
            f"{total:>9}  agent={agent:<28} in={in_tok:<9} out={out_tok:<8} retries={retries:<2} session={name}"
        )

    print("\nBy agent:")
    for agent, m in sorted(by_agent.items(), key=lambda kv: kv[1]["total"], reverse=True):
        print(
            f"{agent:<28} total={m['total']:<10} in={m['input']:<10} out={m['output']:<8} retries={m['retries']:<4} sessions={m['sessions']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

