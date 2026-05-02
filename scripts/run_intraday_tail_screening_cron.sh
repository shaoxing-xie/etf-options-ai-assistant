#!/usr/bin/env bash
set -euo pipefail

# Load runtime env for cron context and export to child processes.
set -a
source /home/xie/.openclaw/.env || true
set +a

cd /home/xie/etf-options-ai-assistant

lock_file="/tmp/intraday_tail_screening_cron.lock"
exec 9>"${lock_file}"
if ! flock -n 9; then
  echo "SKIP_ALREADY_RUNNING:intraday_tail_screening"
  exit 0
fi

# 交易日与编排 state 对齐（上海日历），避免 orchestration 默认 UTC --trade-date 与落盘 run_date 漂移。
ORCH_TRADE_DATE="$(TZ=Asia/Shanghai date +%F)"
export ORCH_TRADE_DATE

td="${ORCH_TRADE_DATE}"
tail_file="data/tail_screening/${td}.json"
sem_dir="data/semantic/screening_view"
sem_file_today="${sem_dir}/${td}.json"

# 编排幂等：TaskStateManager 在「同 task + trade_date + trigger_window + session_type」且已成功时会
# already_executed，orchestration_entrypoint 将不会执行 --command，故同日第二次 openclaw cron run / 手工重跑
# 不会覆盖 tail_screening / screening_view。
# 默认把「上海时区分钟桶」拼进 session_type，使不同分钟的重跑使用新 idempotency_key；同分钟内仍受
# duplicate_trigger（running）保护。若需恢复「同日仅允许一次」（旧行为）：export ORCH_TAIL_IDEMPOTENCY=day
base_session="${ORCH_SESSION_TYPE:-cron}"
idemp_gran="${ORCH_TAIL_IDEMPOTENCY:-minute}"
if [[ "${idemp_gran}" == "day" ]]; then
  export ORCH_SESSION_TYPE="${base_session}"
else
  minute_bucket="$(TZ=Asia/Shanghai date +%Y%m%d%H%M)"
  export ORCH_SESSION_TYPE="${base_session}:${minute_bucket}"
fi

# 若同日、同 trigger_window 下编排已成功，仅删除 data/state 记录（不删 tail/semantic），
# 使本次仍能 claim；关闭：export ORCH_TAIL_PREFLIGHT_RESET_SAME_DAY=0
if [[ "${ORCH_TAIL_PREFLIGHT_RESET_SAME_DAY:-1}" != "0" ]]; then
  /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/preflight_reset_task_state_if_ran_today.py \
    --task-id intraday-tail-screening \
    --trade-date "${ORCH_TRADE_DATE}" \
    --trigger-window intraday-30m
fi

before_tail="$(stat -c %Y "${tail_file}" 2>/dev/null || echo 0)"
before_sem_latest_file="$(ls -1t "${sem_dir}"/*.json 2>/dev/null | sed -n '1p' || true)"
before_sem_latest_mtime="0"
if [[ -n "${before_sem_latest_file}" ]]; then
  before_sem_latest_mtime="$(stat -c %Y "${before_sem_latest_file}" 2>/dev/null || echo 0)"
fi

ORCH_TRIGGER_SOURCE=cron /home/xie/etf-options-ai-assistant/.venv/bin/python \
  scripts/orchestration_entrypoint.py \
  --task-id intraday-tail-screening \
  --trade-date "${ORCH_TRADE_DATE}" \
  --trigger-source cron \
  --trigger-window intraday-30m \
  --depends-on "" \
  --conditions is_trading_day,emergency_pause_active,sentiment_dispersion_low \
  --timeout-seconds 1800 \
  --session-type "${ORCH_SESSION_TYPE}" \
  --command "/bin/bash -lc \"set -euo pipefail; export ORCH_INNER_SKIP_ORCH_STATE=1; export TAIL_SCREENING_TIMEOUT_STOCK_RANK_SEC=1800; export TAIL_SCREENING_TIMEOUT_STOCK_HISTORY_SEC=45; export TAIL_SCREENING_TIMEOUT_SECTOR_SEC=60; timeout 1800s /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/intraday_tail_screening_and_persist.py --max-candidates 300; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/persist_screening_view_snapshot.py\""

# Keep ops dashboard in sync with latest task outcome.
/home/xie/etf-options-ai-assistant/.venv/bin/python scripts/persist_ops_events_snapshot.py >/dev/null

after_tail="$(stat -c %Y "${tail_file}" 2>/dev/null || echo 0)"
after_sem_today="$(stat -c %Y "${sem_file_today}" 2>/dev/null || echo 0)"
after_sem_latest_file="$(ls -1t "${sem_dir}"/*.json 2>/dev/null | sed -n '1p' || true)"
after_sem_latest_mtime="0"
if [[ -n "${after_sem_latest_file}" ]]; then
  after_sem_latest_mtime="$(stat -c %Y "${after_sem_latest_file}" 2>/dev/null || echo 0)"
fi

# Accept either fresh update or an already-produced artifact for today.
if [[ "${after_tail}" -le 0 ]]; then
  echo "ERROR_TAIL_ARTIFACT_MISSING:${tail_file}"
  exit 7
fi
if [[ "${before_tail}" -gt 0 && "${after_tail}" -le "${before_tail}" ]]; then
  echo "WARN_TAIL_NOT_ADVANCED:tail=${before_tail}->${after_tail}"
fi
if [[ "${after_sem_today}" -le 0 && "${after_sem_latest_mtime}" -le 0 ]]; then
  echo "ERROR_SCREENING_VIEW_MISSING:dir=${sem_dir}"
  exit 8
fi
if [[ "${after_sem_latest_mtime}" -le "${before_sem_latest_mtime}" ]]; then
  echo "WARN_VIEW_NOT_ADVANCED:latest=${before_sem_latest_mtime}->${after_sem_latest_mtime} file=${after_sem_latest_file:-none}"
fi

echo "OK_INTRADAY_TAIL_SCREENING td=${td} tail_mtime=${after_tail} sem_latest_file=${after_sem_latest_file:-none} sem_latest_mtime=${after_sem_latest_mtime}"
