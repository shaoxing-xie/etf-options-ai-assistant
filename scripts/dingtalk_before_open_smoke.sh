#!/usr/bin/env bash
# 盘前晨报钉钉测试：避免终端多行 JSON / heredoc 被复制损坏。
# 用法：
#   bash scripts/dingtalk_before_open_smoke.sh test   # 仅 dry-run，不发钉钉
#   bash scripts/dingtalk_before_open_smoke.sh prod   # 真发（需 ~/.openclaw/.env 里 webhook 与加签正确）
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

ARGS_FILE="${ROOT}/scripts/examples/before_open_dingtalk_args.${MODE}.json"
exec python3 "${ROOT}/tool_runner.py" tool_send_analysis_report "@${ARGS_FILE}"
