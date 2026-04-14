#!/usr/bin/env bash
# 信号+风控巡检同款钉钉投递冒烟（tool_send_signal_risk_inspection）。
# 用法：
#   bash scripts/dingtalk_signal_inspection_smoke.sh test   # dry-run，不发钉钉
#   bash scripts/dingtalk_signal_inspection_smoke.sh prod    # 真发（需 ~/.openclaw/.env）
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "${HOME}/.openclaw/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${HOME}/.openclaw/.env"
  set +a
fi

MODE="${1:-test}"
case "$MODE" in
  test|prod) ;;
  *)
    echo "用法: $0 [test|prod]" >&2
    exit 1
    ;;
esac

ARGS_FILE="${ROOT}/scripts/examples/signal_inspection_dingtalk_smoke.${MODE}.json"
exec python3 "${ROOT}/tool_runner.py" tool_send_signal_risk_inspection "@${ARGS_FILE}"
