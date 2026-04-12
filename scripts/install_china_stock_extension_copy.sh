#!/usr/bin/env bash
# 将 openclaw-data-china-stock 插件目录「复制」到 OpenClaw 扩展目录（非 git clone；适合与发布包/本地仓库同步）。
# 复制后请运行本脚本末尾提示的 link + OpenClaw 注册步骤，并重启 Gateway。
#
# 用法（在 etf-options-ai-assistant 仓库根）:
#   ./scripts/install_china_stock_extension_copy.sh
#   ./scripts/install_china_stock_extension_copy.sh /path/to/openclaw-data-china-stock
#
# 环境变量:
#   OPENCLAW_DATA_CHINA_STOCK_SRC   插件源目录（覆盖第一个参数）
#   OPENCLAW_EXTENSIONS_DIR         默认 ~/.openclaw/extensions
#   CHINA_STOCK_RSYNC_DELETE=1      使用 rsync --delete（与源完全一致，会删目标多出的文件；慎用）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXT_ROOT="${OPENCLAW_EXTENSIONS_DIR:-$HOME/.openclaw/extensions}"
DEST="$EXT_ROOT/openclaw-data-china-stock"
SRC="${OPENCLAW_DATA_CHINA_STOCK_SRC:-${1:-$ROOT/../openclaw-data-china-stock}}"
SRC="$(cd "$SRC" && pwd)"

if [[ ! -f "$SRC/package.json" || ! -f "$SRC/openclaw.plugin.json" ]]; then
  echo "源目录不是有效的 openclaw-data-china-stock 根目录（缺少 package.json 或 openclaw.plugin.json）: $SRC" >&2
  exit 1
fi

mkdir -p "$EXT_ROOT"
RSYNC=(rsync -a)
[[ "${CHINA_STOCK_RSYNC_DELETE:-}" == "1" ]] && RSYNC+=(--delete)
RSYNC+=(
  --exclude '.git/'
  --exclude '.venv/'
  --exclude 'venv/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.pytest_cache/'
  --exclude 'node_modules/'
  --exclude 'data/'
  --exclude 'logs/'
  --exclude '*.parquet'
  --exclude 'tool_test_report*.json'
  --exclude '*.tgz'
  --exclude '.npmrc'
)
"${RSYNC[@]}" "$SRC/" "$DEST/"

echo "[install_china_stock_extension_copy] 已复制: $SRC -> $DEST"
echo "[install_china_stock_extension_copy] 版本线索: $(grep -m1 '"version"' "$DEST/package.json" 2>/dev/null | tr -d '\r' || true)"

echo ""
echo "下一步（在同一台机器、etf-options-ai-assistant 根目录执行）:"
echo "  1) 注册 Gateway 插件并写 openclaw.json:"
echo "       python3 scripts/ensure_openclaw_china_stock_plugin.py --ensure-allow --ensure-entry"
echo "  2) 主仓 Python 仍通过符号链接 import plugins.data_collection:"
echo "       OPENCLAW_DATA_CHINA_STOCK_ROOT=\"$DEST\" ./scripts/link_china_stock_data_collection.sh"
echo "  3) 若尚未合并 load.paths，可再执行:"
echo "       ./scripts/setup_openclaw_option_trading_assistant.sh"
echo "  4) 重启 Gateway（例如）: systemctl --user restart openclaw-gateway.service"
