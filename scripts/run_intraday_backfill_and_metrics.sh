#!/usr/bin/env bash
set -euo pipefail

# 收盘后回填 + 分层监控一键执行脚本
# 用法:
#   bash scripts/run_intraday_backfill_and_metrics.sh
#   bash scripts/run_intraday_backfill_and_metrics.sh 20260403

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DATE_ARG="${1:-}"

if [[ -n "${DATE_ARG}" ]]; then
  python scripts/update_intraday_range_actuals.py --date "${DATE_ARG}"
  python scripts/monitor_intraday_range_method_metrics.py --start-date "${DATE_ARG}" --end-date "${DATE_ARG}"
  python scripts/prediction_metrics_weekly.py --end-date "${DATE_ARG}"
else
  python scripts/update_intraday_range_actuals.py
  python scripts/monitor_intraday_range_method_metrics.py
  python scripts/prediction_metrics_weekly.py
fi

echo "[done] intraday backfill + metrics completed."
