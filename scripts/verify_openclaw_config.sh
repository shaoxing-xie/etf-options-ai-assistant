#!/usr/bin/env bash
set -euo pipefail

# CMEC P2：平台补丁（openclaw.json / cron/jobs.json）应用后的轻量校验。
# 在 .handoff/verify.sh 中调用，例如：
#   exec "$(dirname "$0")/verify_openclaw_config.sh"
# 或：bash scripts/verify_openclaw_config.sh

ROOT_BASE="${OPENCLAW_CONFIG_HOME:-$HOME}"
checked=0
for rel in .openclaw/openclaw.json .openclaw/cron/jobs.json; do
  f="$ROOT_BASE/$rel"
  if [[ -f "$f" ]]; then
    checked=1
    if ! python3 -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8'))" "$f"; then
      echo "[verify_openclaw_config] invalid JSON: $f" >&2
      exit 1
    fi
    echo "[verify_openclaw_config] ok: $f"
  fi
done
if [[ "$checked" -eq 0 ]]; then
  echo "[verify_openclaw_config] no openclaw json files present; skip"
fi
echo "[verify_openclaw_config] done"
