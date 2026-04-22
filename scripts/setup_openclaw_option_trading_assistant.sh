#!/usr/bin/env bash
# 一键配置 option-trading-assistant 的 OpenClaw 发现路径（推荐入口，替代「仅符号链接」老流程）。
# - 写入 ~/.openclaw/openclaw.json：plugins.load.paths 含 extensions 目录与本仓库绝对路径
# - 可选：plugins.allow / plugins.entries 补全 option-trading-assistant
# - 默认移除 ~/.openclaw/extensions/option-trading-assistant → 本仓库的符号链接，避免与 load.paths 重复加载
#
# 用法（在仓库根）:
#   ./scripts/setup_openclaw_option_trading_assistant.sh
# 环境变量:
#   OPENCLAW_JSON=path/to/openclaw.json
#   OPENCLAW_EXTENSIONS_DIR=...   （与 ensure 脚本一致）
#   OTA_KEEP_EXTENSION_SYMLINK=1  不删除 extensions 下的 option-trading-assistant 符号链接（不推荐）
#   OTA_KEEP_EXTENSION_DIR_COPY=1 保留 extensions 下的同名物理目录副本（不推荐）
#   OTA_SKIP_ENSURE_ALLOW=1       不向 plugins.allow 追加
#   OTA_SKIP_ENSURE_ENTRY=1       不向 plugins.entries 追加
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY_BIN="${ROOT}/.venv/bin/python"
OPENCLAW_JSON="${OPENCLAW_JSON:-$HOME/.openclaw/openclaw.json}"
EXT_ROOT="${OPENCLAW_EXTENSIONS_DIR:-$HOME/.openclaw/extensions}"
DEST="$EXT_ROOT/option-trading-assistant"

ENSURE_ARGS=(--config "$OPENCLAW_JSON" --repo-root "$ROOT")
[[ "${OTA_SKIP_ENSURE_ALLOW:-}" == "1" ]] || ENSURE_ARGS+=(--ensure-allow)
[[ "${OTA_SKIP_ENSURE_ENTRY:-}" == "1" ]] || ENSURE_ARGS+=(--ensure-entry)

"${PY_BIN}" "$ROOT/scripts/ensure_openclaw_plugin_load_paths.py" "${ENSURE_ARGS[@]}"

if [[ "${OTA_KEEP_EXTENSION_SYMLINK:-}" == "1" ]]; then
  echo "[setup_openclaw_option_trading_assistant] OTA_KEEP_EXTENSION_SYMLINK=1：保留 $DEST（可能与 load.paths 重复扫描，仅调试用）"
else
  if [[ -L "$DEST" ]]; then
    target="$(readlink -f "$DEST" 2>/dev/null || true)"
    root_real="$(readlink -f "$ROOT" 2>/dev/null || true)"
    if [[ -n "$target" && "$target" == "$root_real" ]]; then
      rm -f "$DEST"
      echo "[setup_openclaw_option_trading_assistant] 已移除重复符号链接: $DEST（与 load.paths 指向同一仓库）"
    fi
  fi
fi

if [[ -d "$DEST" && ! -L "$DEST" ]]; then
  if [[ "${OTA_KEEP_EXTENSION_DIR_COPY:-}" == "1" ]]; then
    echo "[setup_openclaw_option_trading_assistant] OTA_KEEP_EXTENSION_DIR_COPY=1：保留 $DEST 物理目录副本（可能导致重复加载，不推荐）"
  else
    ts="$(date +%Y%m%d_%H%M%S)"
    bak="${DEST}.duplicate_backup_${ts}"
    mv "$DEST" "$bak"
    echo "[setup_openclaw_option_trading_assistant] 已归档重复物理目录: $DEST -> $bak"
    echo "[setup_openclaw_option_trading_assistant] 当前仅保留项目目录作为 OTA 单一物理来源。"
  fi
fi

echo "[setup_openclaw_option_trading_assistant] 完成。请重启 Gateway: systemctl --user restart openclaw-gateway.service（或你的 restart 脚本）"
