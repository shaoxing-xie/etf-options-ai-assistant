#!/usr/bin/env bash
set -euo pipefail

set -a
source /home/xie/.openclaw/.env || true
set +a

cd /home/xie/etf-options-ai-assistant

lock_file="/tmp/rotation_research_cron.lock"
exec 9>"${lock_file}"
if ! flock -n 9; then
  echo "SKIP_ALREADY_RUNNING:rotation_research"
  exit 0
fi

td="$(TZ=Asia/Shanghai date +%F)"
rot_file="data/semantic/rotation_latest/${td}.json"
heat_file="data/semantic/rotation_heatmap/${td}.json"

before_rot="$(stat -c %Y "${rot_file}" 2>/dev/null || echo 0)"
before_heat="$(stat -c %Y "${heat_file}" 2>/dev/null || echo 0)"

/usr/bin/timeout 1800s /home/xie/etf-options-ai-assistant/.venv/bin/python \
  /home/xie/etf-options-ai-assistant/scripts/run_rotation_research_cron_exec.py \
  --mode prod \
  --trade-date "${td}" \
  --lookback-days 120 \
  --top-k 3 \
  --runner-timeout-seconds 900

after_rot="$(stat -c %Y "${rot_file}" 2>/dev/null || echo 0)"
after_heat="$(stat -c %Y "${heat_file}" 2>/dev/null || echo 0)"

if [[ "${after_rot}" -le 0 ]]; then
  echo "ERROR_ROTATION_LATEST_MISSING:${rot_file}"
  exit 7
fi
if [[ "${after_heat}" -le 0 ]]; then
  echo "ERROR_ROTATION_HEATMAP_MISSING:${heat_file}"
  exit 8
fi
if [[ "${before_rot}" -gt 0 && "${after_rot}" -le "${before_rot}" ]]; then
  echo "WARN_ROTATION_NOT_ADVANCED:latest=${before_rot}->${after_rot},heat=${before_heat}->${after_heat}"
fi

echo "OK_ROTATION_RESEARCH td=${td} latest_mtime=${after_rot} heat_mtime=${after_heat}"
