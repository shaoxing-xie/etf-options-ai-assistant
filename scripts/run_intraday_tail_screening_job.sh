#!/usr/bin/env bash
set -euo
set -o pipefail

cd /home/xie/etf-options-ai-assistant
source /home/xie/.openclaw/.env >/dev/null 2>&1 || true

export FUND_FLOW_ENABLE_EASTMONEY_FALLBACK=true
export TAIL_SCREENING_DEFAULT_REGIME="${TAIL_SCREENING_DEFAULT_REGIME:-oscillation}"
export TAIL_SCREENING_TIMEOUT_STOCK_MINUTE_SEC="${TAIL_SCREENING_TIMEOUT_STOCK_MINUTE_SEC:-20}"
export TAIL_SCREENING_TIMEOUT_STOCK_HISTORY_SEC="${TAIL_SCREENING_TIMEOUT_STOCK_HISTORY_SEC:-10}"
export PYTHONPATH=/home/xie/etf-options-ai-assistant

LATEST="data/tail_screening/latest.json"
before="$(stat -c %Y "$LATEST" 2>/dev/null || echo 0)"

# 1) Run the job with a hard timeout (should finish < 20m).
JOB_TIMEOUT_SEC="${TAIL_SCREENING_JOB_TIMEOUT_SEC:-1100}"
PY_BIN="/home/xie/etf-options-ai-assistant/.venv/bin/python"

timeout "${JOB_TIMEOUT_SEC}s" "$PY_BIN" scripts/intraday_tail_screening_and_persist.py --max-candidates 50 --notify

# 2) Confirm latest.json updated; allow short filesystem settle window.
deadline=$(( $(date +%s) + 30 ))
after="$before"
while [[ "$(date +%s)" -lt "$deadline" ]]; do
  after="$(stat -c %Y "$LATEST" 2>/dev/null || echo 0)"
  if [[ "$after" -gt "$before" ]]; then
    break
  fi
  sleep 1
done

if [[ "$after" -le "$before" ]]; then
  echo "ERROR_LATEST_NOT_UPDATED"
  exit 7
fi

echo "UPDATED_LATEST_TS=$after"

