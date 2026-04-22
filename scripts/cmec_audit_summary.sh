#!/usr/bin/env bash
set -euo pipefail

# 汇总 .handoff/cmec-audit.jsonl（默认 ETF 仓库）。用途：日报 / 巡检。
# 用法: bash scripts/cmec_audit_summary.sh [REPO_ROOT]

ROOT_DIR="${1:-$HOME/etf-options-ai-assistant}"
AUDIT="$ROOT_DIR/.handoff/cmec-audit.jsonl"
PY_BIN="$ROOT_DIR/.venv/bin/python"

if [[ ! -f "$AUDIT" ]]; then
  echo "no audit file: $AUDIT"
  exit 0
fi

"$PY_BIN" - "$AUDIT" <<'PY'
import collections
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
rows = []
for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        continue

print(f"cmec-audit: {path} | entries={len(rows)}")
if not rows:
    raise SystemExit(0)

st = collections.Counter(r.get("status", "?") for r in rows)
pk = collections.Counter(r.get("patch_kind", "?") for r in rows)
am = collections.Counter(r.get("apply_method", "?") for r in rows)
print("by status:", dict(st))
print("by patch_kind:", dict(pk))
print("by apply_method:", dict(am))
last = rows[-1]
print("last:", last.get("ts"), last.get("status"), last.get("apply_method"), last.get("patch_kind"))
PY
