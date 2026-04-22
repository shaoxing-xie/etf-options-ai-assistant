#!/usr/bin/env bash
# 历史脚本名保留：以前只做「extensions 符号链接」。OpenClaw 2026.4.x 下仅 symlink 可能导致
# plugins.allow 校验报 plugin not found（knownIds 不含 option-trading-assistant）。
#
# 默认行为：转调 ./scripts/setup_openclaw_option_trading_assistant.sh
# （写入 plugins.load.paths + 可选 allow/entries，并移除与仓库重复的 extensions 符号链接）。
#
# 若仍需「仅符号链接」旧行为：OTA_LEGACY_EXTENSION_SYMLINK=1 ./scripts/link_openclaw_extension_option_trading_assistant.sh
# 覆盖实体目录：LINK_OTA_REPLACE_DIR=1（慎用）。
#
# 用法示例：
#   # 推荐：写入 plugins.load.paths（并清理重复 symlink）
#   ./scripts/link_openclaw_extension_option_trading_assistant.sh
#
#   # 旧行为：仅在 extensions 下建立仓库 symlink（不推荐）
#   OTA_LEGACY_EXTENSION_SYMLINK=1 ./scripts/link_openclaw_extension_option_trading_assistant.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY_BIN="${ROOT}/.venv/bin/python"
EXT_ROOT="${OPENCLAW_EXTENSIONS_DIR:-$HOME/.openclaw/extensions}"
DEST="$EXT_ROOT/option-trading-assistant"

if [[ "${OTA_LEGACY_EXTENSION_SYMLINK:-}" != "1" ]]; then
  exec "$ROOT/scripts/setup_openclaw_option_trading_assistant.sh"
fi

mkdir -p "$EXT_ROOT"

if [[ -e "$DEST" || -L "$DEST" ]]; then
  if [[ -L "$DEST" ]]; then
    rm -f "$DEST"
  elif [[ -d "$DEST" ]]; then
    if [[ "${LINK_OTA_REPLACE_DIR:-}" != "1" ]]; then
      echo "已存在目录（非符号链接）: $DEST" >&2
      echo "请先备份并删除，或: LINK_OTA_REPLACE_DIR=1 $0" >&2
      exit 1
    fi
    rm -rf "$DEST"
  else
    rm -f "$DEST"
  fi
fi

ln -sfn "$ROOT" "$DEST"
echo "OK: $DEST -> $(readlink -f "$DEST")"
echo "[link_openclaw_extension_option_trading_assistant] 同步 plugins.load.paths（避免 plugin not found）…"
"${PY_BIN}" "$ROOT/scripts/ensure_openclaw_plugin_load_paths.py" --config "${OPENCLAW_JSON:-$HOME/.openclaw/openclaw.json}" --repo-root "$ROOT" --ensure-allow --ensure-entry
echo "[link_openclaw_extension_option_trading_assistant] 警告：extensions 符号链接与 load.paths 可能重复扫描同一仓库；稳定环境请只用 setup_openclaw_option_trading_assistant.sh" >&2
