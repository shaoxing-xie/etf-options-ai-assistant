#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-}"
if [[ -z "$ROOT_DIR" ]]; then
  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

HANDOFF_DIR="$ROOT_DIR/.handoff"
WORKER="$ROOT_DIR/scripts/handoff_worker.sh"

if [[ ! -d "$HANDOFF_DIR" ]]; then
  echo "[handoff-start] error: handoff dir not found: $HANDOFF_DIR"
  exit 1
fi
if [[ ! -f "$WORKER" ]]; then
  echo "[handoff-start] error: worker script not found: $WORKER"
  exit 1
fi

echo "[handoff-start] root: $ROOT_DIR"
echo "[handoff-start] handoff: $HANDOFF_DIR"

echo "[handoff-start] cleanup old workers/inotifywait (best-effort)"
pkill -f "bash scripts/handoff_worker\\.sh" >/dev/null 2>&1 || true
pkill -f "inotifywait -m -e close_write,create,moved_to.*${HANDOFF_DIR//\//\\/}" >/dev/null 2>&1 || true

echo "[handoff-start] starting worker"
cd "$ROOT_DIR"
bash "$WORKER"

