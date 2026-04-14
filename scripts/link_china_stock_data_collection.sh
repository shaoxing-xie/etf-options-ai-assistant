#!/usr/bin/env bash
# 将 plugins/data_collection 符号链接到 OpenClaw 数据插件目录：
#   默认 ~/.openclaw/extensions/openclaw-data-china-stock/plugins/data_collection
# 覆盖顺序：
#   1) OPENCLAW_DATA_CHINA_STOCK_ROOT（插件仓库根目录）
#   2) $OPENCLAW_EXTENSIONS_DIR/openclaw-data-china-stock（默认 $HOME/.openclaw/extensions）
#   3) 与本仓库同级的 ../openclaw-data-china-stock（便于 CI / 本地双仓）
# 若存在同名目录（非链接），默认报错退出；需替换时设 LINK_CHINA_STOCK_REPLACE_DIR=1。
#
# 用法示例：
#   ./scripts/link_china_stock_data_collection.sh
#   OPENCLAW_EXTENSIONS_DIR="$HOME/.openclaw/extensions" ./scripts/link_china_stock_data_collection.sh
#   OPENCLAW_DATA_CHINA_STOCK_ROOT="$HOME/.openclaw/extensions/openclaw-data-china-stock" ./scripts/link_china_stock_data_collection.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LINK_PATH="$ROOT/plugins/data_collection"
EXT_ROOT="${OPENCLAW_EXTENSIONS_DIR:-$HOME/.openclaw/extensions}"
DEFAULT_PLUGIN="${EXT_ROOT}/openclaw-data-china-stock"
SIBLING="${ROOT}/../openclaw-data-china-stock"

if [[ -n "${OPENCLAW_DATA_CHINA_STOCK_ROOT:-}" ]]; then
  TARGET="$(cd "$OPENCLAW_DATA_CHINA_STOCK_ROOT" && pwd)"
elif [[ -d "${DEFAULT_PLUGIN}/plugins/data_collection" ]]; then
  TARGET="$(cd "$DEFAULT_PLUGIN" && pwd)"
elif [[ -d "${SIBLING}/plugins/data_collection" ]]; then
  TARGET="$(cd "$SIBLING" && pwd)"
else
  echo "未找到数据插件目录。请安装扩展 openclaw-data-china-stock 到 ${EXT_ROOT}，或克隆仓库到 ${SIBLING}，或设置 OPENCLAW_DATA_CHINA_STOCK_ROOT" >&2
  exit 1
fi

DC="$TARGET/plugins/data_collection"
if [[ ! -d "$DC" ]]; then
  echo "未找到 $DC" >&2
  exit 1
fi

if [[ -e "$LINK_PATH" || -L "$LINK_PATH" ]]; then
  if [[ -L "$LINK_PATH" ]]; then
    rm -f "$LINK_PATH"
  elif [[ -d "$LINK_PATH" ]]; then
    if [[ "${LINK_CHINA_STOCK_REPLACE_DIR:-}" != "1" ]]; then
      echo "存在目录（非符号链接）: $LINK_PATH" >&2
      echo "请先备份并删除该目录，或执行: LINK_CHINA_STOCK_REPLACE_DIR=1 $0 （将 rm -rf 该目录）" >&2
      exit 1
    fi
    rm -rf "$LINK_PATH"
  else
    rm -f "$LINK_PATH"
  fi
fi

ln -sfn "$DC" "$LINK_PATH"
echo "OK: $LINK_PATH -> $(readlink -f "$LINK_PATH")"
