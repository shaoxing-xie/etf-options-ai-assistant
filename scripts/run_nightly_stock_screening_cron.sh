#!/usr/bin/env bash
set -euo pipefail

# Load runtime env for cron context and export to child processes.
set -a
source /home/xie/.openclaw/.env || true
set +a

cd /home/xie/etf-options-ai-assistant

# 与编排、落盘统一用上海日历日（A 股主时钟），避免 entrypoint 默认 UTC 与 `date +%F` 漂移。
ORCH_TRADE_DATE="$(TZ=Asia/Shanghai date +%F)"
export ORCH_TRADE_DATE
td="${ORCH_TRADE_DATE}"
screen_file="data/screening/${td}.json"
sem_file="data/semantic/screening_candidates/${td}.json"
view_file="data/semantic/screening_view/${td}.json"
session_type="${ORCH_SESSION_TYPE:-}"
if [[ ! -f "${screen_file}" ]]; then
  # If today's nightly artifact is missing, force a unique recovery idempotency scope.
  if [[ -n "${session_type}" ]]; then
    session_type="${session_type}-recovery-$(date +%s)"
  else
    session_type="auto-recovery-$(date +%s)"
  fi
fi

before_screen="$(stat -c %Y "${screen_file}" 2>/dev/null || echo 0)"
before_sem="$(stat -c %Y "${sem_file}" 2>/dev/null || echo 0)"
before_view="$(stat -c %Y "${view_file}" 2>/dev/null || echo 0)"

# 同日已成功时删 data/state（不删 screening），与尾盘 preflight 同思路；关闭：ORCH_NIGHTLY_PREFLIGHT_RESET_SAME_DAY=0
if [[ "${ORCH_NIGHTLY_PREFLIGHT_RESET_SAME_DAY:-1}" != "0" ]]; then
  /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/preflight_reset_task_state_if_ran_today.py \
    --task-id nightly-stock-screening \
    --trade-date "${td}" \
    --trigger-window daily
fi

ORCH_TRIGGER_SOURCE=cron /home/xie/etf-options-ai-assistant/.venv/bin/python \
  scripts/orchestration_entrypoint.py \
  --task-id nightly-stock-screening \
  --trade-date "${td}" \
  --trigger-source cron \
  --trigger-window daily \
  --depends-on "" \
  --conditions is_trading_day,position_ceiling_positive,sentiment_stage_not_extreme,emergency_pause_active \
  --timeout-seconds 120 \
  --session-type "${session_type}" \
  --command "/bin/bash -lc \"set -euo pipefail; export ORCH_INNER_SKIP_ORCH_STATE=1; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/nightly_screening_and_persist.py --max-universe-size 0; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/persist_screening_semantic_snapshot.py; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/persist_screening_view_snapshot.py --trade-date ${td}\""

# Keep ops dashboard in sync with latest task outcome.
/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/persist_ops_events_snapshot.py >/dev/null

after_screen="$(stat -c %Y "${screen_file}" 2>/dev/null || echo 0)"
after_sem="$(stat -c %Y "${sem_file}" 2>/dev/null || echo 0)"
after_view="$(stat -c %Y "${view_file}" 2>/dev/null || echo 0)"

if [[ "${after_screen}" -le 0 ]]; then
  echo "ERROR_SCREENING_ARTIFACT_MISSING:${screen_file}"
  exit 7
fi
if [[ "${after_sem}" -le 0 ]]; then
  echo "ERROR_SCREENING_CANDIDATES_MISSING:${sem_file}"
  exit 8
fi
if [[ "${after_view}" -le 0 ]]; then
  echo "ERROR_SCREENING_VIEW_MISSING:${view_file}"
  exit 9
fi
if [[ "${after_screen}" -le "${before_screen}" && "${after_sem}" -le "${before_sem}" ]]; then
  echo "WARN_ARTIFACT_NOT_ADVANCED:screen=${before_screen}->${after_screen},sem=${before_sem}->${after_sem},view=${before_view}->${after_view}"
fi

echo "OK_NIGHTLY_STOCK_SCREENING td=${td} screen_mtime=${after_screen} sem_mtime=${after_sem} view_mtime=${after_view}"
