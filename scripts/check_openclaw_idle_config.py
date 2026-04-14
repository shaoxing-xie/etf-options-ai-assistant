#!/usr/bin/env python3
"""读取 OpenClaw openclaw.json 中 agents.defaults.llm.idleTimeoutSeconds（不重启动网关即可自检）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    p = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / ".openclaw" / "openclaw.json")
    if not p.is_file():
        print(f"ERROR: not found: {p}", file=sys.stderr)
        return 2
    j = json.loads(p.read_text(encoding="utf-8"))
    idle = (j.get("agents") or {}).get("defaults", {}).get("llm", {}).get("idleTimeoutSeconds")
    print(f"idleTimeoutSeconds={idle!r}  file={p}")
    if idle is None:
        return 1
    if int(idle) < 300:
        print("WARN: idle < 300s may hit LLM idle timeout on long tool chains", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
