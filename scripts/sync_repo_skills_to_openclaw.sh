#!/usr/bin/env bash
# Copy first-party skills from repo skills/ to OpenClaw load paths.
# Only copies immediate subdirectories that contain SKILL.md; does not delete other skills in target dirs.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT_DIR}/skills"

GLOBAL_DIR="${OPENCLAW_SKILLS_DIR:-${HOME}/.openclaw/skills}"
SHARED_DIR="${OPENCLAW_SHARED_SKILLS_DIR:-${HOME}/.openclaw/workspaces/shared/skills}"
SYNC_SHARED="${SYNC_SHARED_SKILLS:-1}"

usage() {
  echo "Usage: $0"
  echo "  Copies each <repo>/skills/<name>/ with SKILL.md to:"
  echo "    - ${GLOBAL_DIR}"
  echo "    - ${SHARED_DIR} (unless missing or SYNC_SHARED_SKILLS=0)"
  echo "Env: OPENCLAW_SKILLS_DIR, OPENCLAW_SHARED_SKILLS_DIR, SYNC_SHARED_SKILLS (default 1)"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -d "$SRC" ]]; then
  echo "error: missing skills source: $SRC" >&2
  exit 1
fi

mkdir -p "$GLOBAL_DIR"

count=0
for item in "$SRC"/*/; do
  [[ -d "$item" ]] || continue
  base="$(basename "$item")"
  [[ "$base" == "*" ]] && continue
  if [[ ! -f "${item}SKILL.md" ]]; then
    continue
  fi
  echo "rsync -> ${GLOBAL_DIR}/${base}/"
  rsync -a --delete "${item%/}/" "${GLOBAL_DIR}/${base}/"
  count=$((count + 1))
done

if [[ "$SYNC_SHARED" == "1" && -d "$SHARED_DIR" ]]; then
  for item in "$SRC"/*/; do
    [[ -d "$item" ]] || continue
    base="$(basename "$item")"
    [[ "$base" == "*" ]] && continue
    if [[ ! -f "${item}SKILL.md" ]]; then
      continue
    fi
    echo "rsync -> ${SHARED_DIR}/${base}/"
    rsync -a --delete "${item%/}/" "${SHARED_DIR}/${base}/"
  done
elif [[ "$SYNC_SHARED" == "1" ]]; then
  echo "skip shared skills dir (not found): ${SHARED_DIR}"
fi

if [[ "$count" -eq 0 ]]; then
  echo "No first-party skills under ${SRC} (need subdirs with SKILL.md). Nothing copied to ${GLOBAL_DIR}."
else
  echo "Done. Synced ${count} skill(s) to ${GLOBAL_DIR}."
fi
