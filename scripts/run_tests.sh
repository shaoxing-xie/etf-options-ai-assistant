#!/usr/bin/env bash
# 使用项目 .venv 运行 pytest，避免系统 Python 缺 pandas/numpy 导致收集失败。
# 用法示例：
#   # 运行全部测试
#   ./scripts/run_tests.sh
#
#   # 仅运行某个文件/用例（原样透传给 pytest）
#   ./scripts/run_tests.sh tests/test_daily_volatility_range_tool.py -m "not integration"
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "未找到 ${PY}。请先: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt" >&2
  exit 1
fi
exec "$PY" -m pytest "$@"
