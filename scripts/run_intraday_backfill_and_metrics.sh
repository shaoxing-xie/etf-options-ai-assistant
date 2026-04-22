#!/usr/bin/env bash
set -euo pipefail

# Run intraday backfill and metrics.
# Usage:
#   bash scripts/run_intraday_backfill_and_metrics.sh
#   bash scripts/run_intraday_backfill_and_metrics.sh 20260403

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="${ROOT_DIR}/.venv/bin/python"
cd "${ROOT_DIR}"

DATE_ARG="${1:-}"

if [[ -n "${DATE_ARG}" ]]; then
  "${PY_BIN}" scripts/update_intraday_range_actuals.py --date "${DATE_ARG}"
  "${PY_BIN}" scripts/monitor_intraday_range_method_metrics.py --start-date "${DATE_ARG}" --end-date "${DATE_ARG}"
  "${PY_BIN}" scripts/prediction_metrics_weekly.py --end-date "${DATE_ARG}"
else
  "${PY_BIN}" scripts/update_intraday_range_actuals.py
  "${PY_BIN}" scripts/monitor_intraday_range_method_metrics.py
  "${PY_BIN}" scripts/prediction_metrics_weekly.py
fi

echo "[done] intraday backfill and metrics completed."
