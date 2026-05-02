#!/usr/bin/env bash
set -euo pipefail

set -a
source /home/xie/.openclaw/.env || true
set +a

cd /home/xie/etf-options-ai-assistant

td="$(TZ=Asia/Shanghai date +%F)"
side_file="data/sentiment_check/${td}.json"
sem_file="data/semantic/sentiment_snapshot/${td}.json"
dash_file="data/semantic/dashboard_snapshot/${td}.json"

before_side="$(stat -c %Y "${side_file}" 2>/dev/null || echo 0)"
before_sem="$(stat -c %Y "${sem_file}" 2>/dev/null || echo 0)"
before_dash="$(stat -c %Y "${dash_file}" 2>/dev/null || echo 0)"

orch_out="$(
  ORCH_TRIGGER_SOURCE=cron /home/xie/etf-options-ai-assistant/.venv/bin/python \
    scripts/orchestration_entrypoint.py \
    --task-id pre-market-sentiment-check \
    --trade-date "${td}" \
    --trigger-source cron \
    --trigger-window daily \
    --depends-on "" \
    --conditions is_trading_day \
    --timeout-seconds 300 \
    --command "/bin/bash -lc \"set -euo pipefail; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/pre_market_sentiment_check_and_persist.py\"" \
    2>&1
)"
echo "${orch_out}"

# If orchestration reports idempotent skip but today's artifacts are missing,
# run once directly to self-heal stale state.
if [[ "${orch_out}" == *"already_executed"* || "${orch_out}" == *"duplicate_trigger"* ]]; then
  if [[ ! -f "${side_file}" || ! -f "${sem_file}" || ! -f "${dash_file}" ]]; then
    if [[ "${orch_out}" == *"duplicate_trigger"* ]]; then
      echo "WARN_PRE_MARKET_RUNNING_AND_MISSING:side=${side_file}"
      exit 0
    fi
    /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/preflight_reset_task_state_if_ran_today.py \
      --task-id pre-market-sentiment-check \
      --trade-date "${td}" \
      --trigger-window daily
    /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/pre_market_sentiment_check_and_persist.py
  fi
fi

after_side="$(stat -c %Y "${side_file}" 2>/dev/null || echo 0)"
after_sem="$(stat -c %Y "${sem_file}" 2>/dev/null || echo 0)"
after_dash="$(stat -c %Y "${dash_file}" 2>/dev/null || echo 0)"

if [[ "${after_side}" -le 0 ]]; then
  echo "ERROR_SENTIMENT_CHECK_MISSING:${side_file}"
  exit 7
fi
if [[ "${after_sem}" -le 0 ]]; then
  echo "ERROR_SENTIMENT_SNAPSHOT_MISSING:${sem_file}"
  exit 8
fi
if [[ "${after_dash}" -le 0 ]]; then
  echo "ERROR_DASHBOARD_SNAPSHOT_MISSING:${dash_file}"
  exit 9
fi

if [[ "${before_side}" -gt 0 && "${after_side}" -le "${before_side}" && "${after_sem}" -le "${before_sem}" ]]; then
  echo "WARN_SENTIMENT_NOT_ADVANCED:side=${before_side}->${after_side},sem=${before_sem}->${after_sem},dash=${before_dash}->${after_dash}"
fi

echo "OK_PRE_MARKET_SENTIMENT td=${td} side_mtime=${after_side} sem_mtime=${after_sem} dash_mtime=${after_dash}"
