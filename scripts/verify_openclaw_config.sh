#!/usr/bin/env bash
set -euo pipefail

# CMEC P2：平台补丁（openclaw.json / cron/jobs.json）应用后的轻量校验。
# 用法示例：
#   # 校验默认位置（~/.openclaw/openclaw.json 与 ~/.openclaw/cron/jobs.json）
#   bash scripts/verify_openclaw_config.sh
#
#   # 额外校验 plugins.load.paths 已包含本仓库路径
#   VERIFY_OTA_LOAD_PATHS=1 bash scripts/verify_openclaw_config.sh
#
# 在 .handoff/verify.sh 中调用，例如：
#   exec "$(dirname "$0")/verify_openclaw_config.sh"
# 或：bash scripts/verify_openclaw_config.sh
#
# 可选：VERIFY_OTA_LOAD_PATHS=1 时检查 openclaw.json 的 plugins.load.paths 是否包含
# 本仓库绝对路径（与 scripts/ensure_openclaw_plugin_load_paths.py 一致，避免 plugin not found）。

ROOT_BASE="${OPENCLAW_CONFIG_HOME:-$HOME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
checked=0
for rel in .openclaw/openclaw.json .openclaw/cron/jobs.json; do
  f="$ROOT_BASE/$rel"
  if [[ -f "$f" ]]; then
    checked=1
    if ! python3 -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8'))" "$f"; then
      echo "[verify_openclaw_config] invalid JSON: $f" >&2
      exit 1
    fi
    echo "[verify_openclaw_config] ok: $f"
  fi
done

if [[ "${VERIFY_OTA_LOAD_PATHS:-}" == "1" && -f "$ROOT_BASE/.openclaw/openclaw.json" ]]; then
  python3 - "$ROOT_BASE/.openclaw/openclaw.json" "$REPO_ROOT" <<'PY'
import json, sys
from pathlib import Path
cfg, repo = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
data = json.loads(cfg.read_text(encoding="utf-8"))
paths = (data.get("plugins") or {}).get("load") or {}
raw = paths.get("paths") or []
need = str(repo)
norm = {str(Path(p).expanduser().resolve(strict=False)) for p in raw if isinstance(p, str)}
if need not in norm:
    print(f"[verify_openclaw_config] plugins.load.paths 缺少本仓库路径: {need}", file=sys.stderr)
    print("[verify_openclaw_config] 请运行: ./scripts/setup_openclaw_option_trading_assistant.sh", file=sys.stderr)
    sys.exit(1)
print(f"[verify_openclaw_config] plugins.load.paths 已包含仓库: {need}")
PY
fi

if [[ "$checked" -eq 0 ]]; then
  echo "[verify_openclaw_config] no openclaw json files present; skip"
fi
echo "[verify_openclaw_config] done"
