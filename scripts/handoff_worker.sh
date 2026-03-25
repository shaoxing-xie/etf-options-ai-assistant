#!/usr/bin/env bash
set -euo pipefail

# OpenClaw <-> Cursor 代码维护执行通道（CMEC）：自动监听并应用补丁

WORKER_VERSION="2026-03-25.p2.2"

ROOT_DIR="${1:-$HOME/etf-options-ai-assistant}"
HANDOFF_DIR="$ROOT_DIR/.handoff"
PATCH_FILE="$HANDOFF_DIR/changes.diff"
TASK_FILE="$HANDOFF_DIR/task.md"
VERIFY_FILE="$HANDOFF_DIR/verify.sh"
RESULT_FILE="$HANDOFF_DIR/result.md"
BACKUP_DIR="$HANDOFF_DIR/.backup"
LOCK_FILE="$HANDOFF_DIR/.worker.lock"
APPROVAL_FILE="$HANDOFF_DIR/approval.txt"

mkdir -p "$BACKUP_DIR"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[error] missing command: $1"
    exit 1
  fi
}

append_cmec_audit() {
  # P2：追加审计行（JSONL），便于日后聚合成功率 / 失败原因。
  local status="$1"
  local apply_method="$2"
  local verify_result="$3"
  local patch_kind="$4"
  local note="$5"
  CMEC_AUDIT_NOTE="$note" python3 - "$HANDOFF_DIR" "$status" "$apply_method" "$verify_result" "$patch_kind" "$WORKER_VERSION" <<'PY'
import json, sys, datetime, os
from pathlib import Path

handoff = Path(sys.argv[1])
note = os.environ.get("CMEC_AUDIT_NOTE", "").strip()[:1200]
rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "status": sys.argv[2],
    "apply_method": sys.argv[3],
    "verify": sys.argv[4],
    "patch_kind": sys.argv[5],
    "worker": sys.argv[6],
    "note": note,
}
path = handoff / "cmec-audit.jsonl"
try:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
except OSError:
    pass
PY
}

write_result_with_audit() {
  local status="$1"
  local note="$2"
  local verify_result="$3"
  local apply_method="${4:-unknown}"
  local patch_kind="${5:-unknown}"
  write_result "$status" "$note" "$verify_result" "$apply_method"
  append_cmec_audit "$status" "$apply_method" "$verify_result" "$patch_kind" "$note"
}

write_result() {
  local status="$1"
  local note="$2"
  local verify_result="$3"
  local apply_method="${4:-unknown}"
  local vlog=""
  if [[ -n "${CMEC_VERIFY_LOG_PATH:-}" ]]; then
    vlog=$(printf '\n- log: %s' "$CMEC_VERIFY_LOG_PATH")
  fi
  cat > "$RESULT_FILE" <<EOF
## status: $status

### worker
- version: $WORKER_VERSION
- apply_method: $apply_method
- audit_log: $HANDOFF_DIR/cmec-audit.jsonl

### applied
- time: $(date '+%F %T')
- files: see git status / patch summary

### verify
- command: $VERIFY_FILE
- result: $verify_result$vlog

### notes
- $note
EOF
}

read_risk_level() {
  # reads risk_level from TASK_FILE; default guarded
  python3 - "$TASK_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
default = "guarded"
try:
    s = path.read_text(encoding="utf-8", errors="ignore")
except FileNotFoundError:
    print(default)
    raise SystemExit(0)

lvl = default
for ln in s.splitlines():
    raw = ln.strip()
    if not raw or raw.startswith("#"):
        continue
    # task.md often uses list markers like "- risk_level: guarded"
    if raw.startswith("-"):
        raw = raw.lstrip("-").strip()
    if raw.lower().startswith("risk_level:"):
        v = raw.split(":", 1)[1].strip().strip("`").strip()
        if v:
            lvl = v.lower()
        break

if lvl not in {"auto", "guarded", "approval"}:
    lvl = default
print(lvl)
PY
}

patch_sha256() {
  python3 - "$PATCH_FILE" <<'PY'
from pathlib import Path
import hashlib, sys

p = Path(sys.argv[1])
data = p.read_bytes() if p.exists() else b""
print(hashlib.sha256(data).hexdigest())
PY
}

list_patch_paths() {
  # Extract changed file paths from unified diff.
  # Supports:
  # - --- a/xxx / +++ b/xxx
  # - diff --git a/xxx b/xxx
  python3 - "$PATCH_FILE" <<'PY'
from __future__ import annotations
from pathlib import Path
import sys

patch_path = Path(sys.argv[1])
try:
    s = patch_path.read_text(encoding="utf-8", errors="ignore")
except FileNotFoundError:
    raise SystemExit(0)

paths: set[str] = set()

def norm(p: str) -> str:
    p = p.strip()
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    if p == "/dev/null":
        return ""
    return p

for ln in s.splitlines():
    if ln.startswith("diff --git "):
        # diff --git a/foo b/foo
        parts = ln.split()
        if len(parts) >= 4:
            a = norm(parts[2])
            b = norm(parts[3])
            if a:
                paths.add(a)
            if b:
                paths.add(b)
        continue
    if ln.startswith("--- "):
        p = norm(ln[4:])
        if p:
            paths.add(p)
        continue
    if ln.startswith("+++ "):
        p = norm(ln[4:])
        if p:
            paths.add(p)
        continue

for p in sorted(paths):
    print(p)
PY
}

classify_patch_allowlist() {
  # P2 β: repo allowlist (P1) + optional ~/.openclaw platform files ONLY when
  # task.md has risk_level: approval (sha checked later in bash).
  # Mixed repo + platform in one diff -> MIXED (not supported).
  python3 - "$ROOT_DIR" "$PATCH_FILE" "$1" <<'PY'
from __future__ import annotations

import sys
from fnmatch import fnmatch
from pathlib import Path

root = Path(sys.argv[1]).resolve()
patch_file = Path(sys.argv[2])
risk_level = (sys.argv[3] if len(sys.argv) > 3 else "guarded").strip().lower()
if risk_level not in {"auto", "guarded", "approval"}:
    risk_level = "guarded"

allow_globs = [
    "docs/**",
    "plugins/**",
    "scripts/**",
    "workflows/**",
    "config/**",
    "README.md",
    "TOOL_LIST.md",
]

home = Path.home().resolve()
platform_targets: set[Path] = {
    (home / ".openclaw" / "openclaw.json").resolve(),
    (home / ".openclaw" / "cron" / "jobs.json").resolve(),
}


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except FileNotFoundError:
        return ""


def norm_seg(p: str) -> str:
    p = p.strip().strip('"').strip("'").replace("\\", "/")
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    return p


def resolve_to_path(seg: str) -> Path | None:
    seg = norm_seg(seg)
    if not seg or seg == "/dev/null":
        return None
    if seg.startswith("/"):
        return Path(seg).resolve()
    # Unusual: "home/user/.openclaw/..." without leading slash (after stripping a/)
    if "/.openclaw/" in seg and not seg.startswith(".."):
        return (Path("/") / seg).resolve()
    return (root / seg).resolve()


def paths_from_diff(diff_text: str) -> set[Path]:
    found: set[Path] = set()
    for ln in diff_text.splitlines():
        if ln.startswith("diff --git "):
            parts = ln.split()
            if len(parts) >= 4:
                for seg in (parts[2], parts[3]):
                    rp = resolve_to_path(seg)
                    if rp is not None:
                        found.add(rp)
            continue
        if ln.startswith("--- ") or ln.startswith("+++ "):
            rp = resolve_to_path(ln[4:])
            if rp is not None:
                found.add(rp)
    return found


def ok_repo_rel(rel_posix: str) -> bool:
    rel_posix = rel_posix.replace("\\", "/").lstrip("/")
    if not rel_posix:
        return True
    if rel_posix.startswith("../") or "/../" in rel_posix or rel_posix == "..":
        return False
    if rel_posix.startswith(".") and rel_posix not in {".gitignore"}:
        return False
    for g in allow_globs:
        if fnmatch(rel_posix, g) or fnmatch(rel_posix, g.rstrip("/**")):
            return True
    return False


diff_text = read_text(patch_file)
if not diff_text.strip():
    print("DENY")
    print("empty patch")
    raise SystemExit(0)

unique = paths_from_diff(diff_text)
repo_rels: list[str] = []
platform_hits: list[Path] = []
outside: list[Path] = []

for p in sorted(unique):
    if p in platform_targets:
        platform_hits.append(p)
        continue
    try:
        rel = p.relative_to(root)
    except ValueError:
        outside.append(p)
        continue
    repo_rels.append(rel.as_posix())

if outside:
    print("DENY")
    for o in outside:
        print(f"outside root and not P2 platform allowlist: {o}")
    raise SystemExit(0)

if platform_hits and repo_rels:
    print("MIXED")
    print("repo paths and ~/.openclaw platform paths in one diff are not supported; split into two handoffs")
    raise SystemExit(0)

if platform_hits:
    if risk_level != "approval":
        print("DENY")
        print("~/.openclaw patches require risk_level: approval in .handoff/task.md")
        raise SystemExit(0)
    print("OK_PLATFORM")
    for p in platform_hits:
        print(p)
    raise SystemExit(0)

# repo-only
bad = [r for r in repo_rels if not ok_repo_rel(r)]
if bad:
    print("DENY")
    for b in bad:
        print(b)
    raise SystemExit(0)

print("OK_REPO")
for r in repo_rels:
    print(r)
PY
}

is_effective_patch() {
  # ignore empty file or comment-only content
  if [[ ! -s "$PATCH_FILE" ]]; then
    return 1
  fi
  python3 - "$PATCH_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
try:
    s = path.read_text(encoding="utf-8", errors="ignore")
except FileNotFoundError:
    print("0")
    raise SystemExit(0)

effective = False
for ln in s.splitlines():
    if not ln.strip():
        continue
    if ln.lstrip().startswith("#"):
        continue
    effective = True
    break

print("1" if effective else "0")
PY
}

apply_patch_file() {
  # Single-instance guard for apply.
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "[handoff] another worker is applying; skip"
    return 0
  fi

  unset CMEC_VERIFY_LOG_PATH

  local eff
  eff="$(is_effective_patch | tail -n 1 || true)"
  if [[ "$eff" != "1" ]]; then
    echo "[handoff] skip empty/comment-only patch"
    return 0
  fi

  local risk_level
  risk_level="$(read_risk_level | tail -n 1 || true)"
  if [[ -z "$risk_level" ]]; then
    risk_level="guarded"
  fi

  local allow_out
  allow_out="$(classify_patch_allowlist "$risk_level" || true)"
  local allow_head
  allow_head="$(printf '%s\n' "$allow_out" | head -n 1 || true)"
  if [[ "$allow_head" == "DENY" ]]; then
    local bad_list
    bad_list="$(printf '%s\n' "$allow_out" | tail -n +2 | tr '\n' ' ' | sed -e 's/[[:space:]]\+$//')"
    write_result_with_audit "failed" "path allowlist denied. bad_paths: $bad_list" "not-run" "guard" "precheck"
    echo "[handoff] denied by allowlist: $bad_list"
    return 1
  fi
  if [[ "$allow_head" == "MIXED" ]]; then
    local mixed_note
    mixed_note="$(printf '%s\n' "$allow_out" | tail -n +2 | tr '\n' ' ' | sed -e 's/[[:space:]]\+$//')"
    write_result_with_audit "failed" "mixed patch not supported: $mixed_note" "not-run" "guard" "precheck"
    echo "[handoff] denied: mixed repo + openclaw in one diff"
    return 1
  fi

  local patch_kind
  if [[ "$allow_head" == "OK_PLATFORM" ]]; then
    patch_kind="platform"
  elif [[ "$allow_head" == "OK_REPO" ]]; then
    patch_kind="repo"
  else
    write_result_with_audit "failed" "allowlist classifier error (head=$allow_head)" "not-run" "guard" "precheck"
    return 1
  fi

  if [[ "$risk_level" == "approval" ]]; then
    local sha
    sha="$(patch_sha256 | tail -n 1 || true)"
    if [[ -z "$sha" ]]; then
      sha="(unknown)"
    fi
    if [[ ! -f "$APPROVAL_FILE" ]] || ! grep -q "$sha" "$APPROVAL_FILE" 2>/dev/null; then
      write_result_with_audit "failed" "approval required. write the patch sha256 into .handoff/approval.txt to proceed. sha256: $sha" "not-run" "approval" "$patch_kind"
      echo "[handoff] approval required; sha256=$sha"
      return 1
    fi
  fi

  local ts
  ts="$(date '+%Y%m%d_%H%M%S')"
  local one_backup="$BACKUP_DIR/$ts"
  mkdir -p "$one_backup"
  cp -f "$PATCH_FILE" "$one_backup/changes.diff" || true
  cp -f "$TASK_FILE" "$one_backup/task.md" || true
  cp -f "$VERIFY_FILE" "$one_backup/verify.sh" || true
  cp -f "$RESULT_FILE" "$one_backup/result.before.md" 2>/dev/null || true

  local patch_dir patch_strip apply_tag
  if [[ "$patch_kind" == "platform" ]]; then
    patch_dir="/"
    patch_strip=0
    apply_tag="patch-openclaw"
    echo "[handoff] applying platform patch (P2): $PATCH_FILE -> -d / -p0"
  else
    patch_dir="$ROOT_DIR"
    patch_strip=1
    apply_tag="patch"
    echo "[handoff] applying patch: $PATCH_FILE"
  fi
  # Prefer patch. --batch: non-interactive. -N: skip if hunk already applied (no silent reverse).
  local patch_opts
  patch_opts=(--binary --batch -N)
  # 1) forward dry-run; if it would apply -> apply
  if patch -d "$patch_dir" -p"$patch_strip" "${patch_opts[@]}" --dry-run -i "$PATCH_FILE" >/dev/null 2>&1; then
    if ! patch -d "$patch_dir" -p"$patch_strip" "${patch_opts[@]}" -i "$PATCH_FILE"; then
      write_result_with_audit "failed" "patch apply failed (unexpected; dry-run passed)" "not-run" "$apply_tag" "$patch_kind"
      return 1
    fi
  # 2) reverse dry-run succeeds -> already applied (forward -N skipped the hunk)
  elif patch -d "$patch_dir" -p"$patch_strip" "${patch_opts[@]}" --dry-run -R -i "$PATCH_FILE" >/dev/null 2>&1; then
    write_result_with_audit "ok" "patch already applied; skipped re-apply" "skipped" "$apply_tag" "$patch_kind"
    echo "[handoff] already applied; skip"
    return 0
  else
    write_result_with_audit "failed" "patch does not apply (invalid diff or context mismatch)" "not-run" "$apply_tag" "$patch_kind"
    return 1
  fi

  if [[ -f "$VERIFY_FILE" && -s "$VERIFY_FILE" ]]; then
    echo "[handoff] running verify: $VERIFY_FILE"
    CMEC_VERIFY_LOG_PATH="$HANDOFF_DIR/verify.last.log"
    export CMEC_VERIFY_LOG_PATH
    {
      echo "=== CMEC verify $(date '+%F %T %z') ==="
      echo "command: $VERIFY_FILE"
      echo "---"
    } >"$CMEC_VERIFY_LOG_PATH"
    if bash "$VERIFY_FILE" >>"$CMEC_VERIFY_LOG_PATH" 2>&1; then
      write_result_with_audit "ok" "patch applied and verify passed" "passed" "$apply_tag" "$patch_kind"
    else
      write_result_with_audit "failed" "patch applied but verify failed (see verify log)" "failed" "$apply_tag" "$patch_kind"
      unset CMEC_VERIFY_LOG_PATH
      return 1
    fi
    unset CMEC_VERIFY_LOG_PATH
  else
    write_result_with_audit "ok" "patch applied, verify skipped" "skipped" "$apply_tag" "$patch_kind"
  fi

  echo "[handoff] done -> $RESULT_FILE"
  return 0
}

main() {
  require_cmd inotifywait
  require_cmd patch
  require_cmd flock
  require_cmd python3

  if [[ ! -d "$HANDOFF_DIR" ]]; then
    echo "[error] handoff dir not found: $HANDOFF_DIR"
    exit 1
  fi

  echo "[watch] listening: $HANDOFF_DIR"
  echo "[watch] target file: $PATCH_FILE"
  local fifo
  fifo="$(mktemp -u "$HANDOFF_DIR/.inotify.fifo.XXXXXX")"
  mkfifo "$fifo"
  local inotify_pid=""
  cleanup_watch() {
    [[ -n "$inotify_pid" ]] && kill "$inotify_pid" >/dev/null 2>&1 || true
    rm -f "$fifo" >/dev/null 2>&1 || true
  }
  trap cleanup_watch EXIT INT TERM

  inotifywait -m -e close_write,create,moved_to "$HANDOFF_DIR" --format '%w%f' >"$fifo" &
  inotify_pid="$!"

  while read -r f; do
    if [[ "$f" == "$PATCH_FILE" ]]; then
      apply_patch_file || true
    fi
  done <"$fifo"
}

# One-shot apply for CI / manual E2E (no inotifywait). Usage:
#   bash scripts/handoff_worker.sh [ROOT] apply-once
#   bash scripts/handoff_worker.sh apply-once   # ROOT defaults to $HOME/etf-options-ai-assistant
if [[ "${1:-}" == "apply-once" ]] || [[ "${1:-}" == "once" ]]; then
  ROOT_DIR="${2:-$HOME/etf-options-ai-assistant}"
elif [[ "${2:-}" == "apply-once" ]] || [[ "${2:-}" == "once" ]]; then
  ROOT_DIR="${1:-$HOME/etf-options-ai-assistant}"
else
  ROOT_DIR="${1:-$HOME/etf-options-ai-assistant}"
fi

HANDOFF_DIR="$ROOT_DIR/.handoff"
PATCH_FILE="$HANDOFF_DIR/changes.diff"
TASK_FILE="$HANDOFF_DIR/task.md"
VERIFY_FILE="$HANDOFF_DIR/verify.sh"
RESULT_FILE="$HANDOFF_DIR/result.md"
BACKUP_DIR="$HANDOFF_DIR/.backup"
LOCK_FILE="$HANDOFF_DIR/.worker.lock"
APPROVAL_FILE="$HANDOFF_DIR/approval.txt"

if [[ "${1:-}" == "apply-once" ]] || [[ "${1:-}" == "once" ]] || [[ "${2:-}" == "apply-once" ]] || [[ "${2:-}" == "once" ]]; then
  require_cmd patch
  require_cmd flock
  require_cmd python3
  if [[ ! -d "$HANDOFF_DIR" ]]; then
    echo "[error] handoff dir not found: $HANDOFF_DIR"
    exit 1
  fi
  apply_patch_file
  ec=$?
  exit "$ec"
fi

main "$@"
