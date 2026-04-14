#!/usr/bin/env bash
set -euo pipefail

# 用法示例：
#   # 启动 Streamlit 控制台（默认 8511）
#   ./scripts/run_chart_console.sh
#
#   # 自定义端口
#   STREAMLIT_PORT=8512 STREAMLIT_HOST=0.0.0.0 ./scripts/run_chart_console.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
APP_PATH="${ROOT_DIR}/apps/chart_console/app.py"
HOST="${STREAMLIT_HOST:-0.0.0.0}"
PORT="${STREAMLIT_PORT:-8511}"

cd "${ROOT_DIR}"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "[run_chart_console] .venv 不存在，正在创建并安装依赖..."
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install streamlit
fi

if [[ ! -x "${VENV_DIR}/bin/streamlit" ]]; then
  echo "[run_chart_console] 未发现 streamlit，正在安装..."
  "${VENV_DIR}/bin/pip" install streamlit
fi

# Ensure runtime deps used by app.py are present.
if ! "${VENV_DIR}/bin/python" -c "import plotly" >/dev/null 2>&1; then
  echo "[run_chart_console] 未发现 plotly，正在安装..."
  "${VENV_DIR}/bin/pip" install plotly
fi

echo "[run_chart_console] ROOT=${ROOT_DIR}"
echo "[run_chart_console] APP=${APP_PATH}"
echo "[run_chart_console] URL=http://localhost:${PORT}"

exec "${VENV_DIR}/bin/streamlit" run "${APP_PATH}" \
  --server.headless true \
  --server.address "${HOST}" \
  --server.port "${PORT}" \
  --client.showSidebarNavigation true
