#!/usr/bin/env bash
set -euo pipefail

# 用法示例：
#   # 启动 Pro 版（API 服务）
#   ./scripts/run_chart_console_pro.sh
#
#   # 自定义监听地址/端口
#   CHART_CONSOLE_PRO_HOST=0.0.0.0 CHART_CONSOLE_PRO_PORT=8611 ./scripts/run_chart_console_pro.sh
#
#   # 数据仓库与当前脚本所在目录不一致时（侧车、screening 等），指向含 data/sentiment_check 的根目录
#   ETF_OPTIONS_ASSISTANT_ROOT=/path/to/etf-options-ai-assistant ./scripts/run_chart_console_pro.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${CHART_CONSOLE_PRO_HOST:-0.0.0.0}"
PORT="${CHART_CONSOLE_PRO_PORT:-8611}"

cd "${ROOT_DIR}"
echo "[run_chart_console_pro] ROOT=${ROOT_DIR}"
echo "[run_chart_console_pro] URL=http://localhost:${PORT}"
exec CHART_CONSOLE_PRO_HOST="${HOST}" CHART_CONSOLE_PRO_PORT="${PORT}" python3 apps/chart_console/api/server.py
