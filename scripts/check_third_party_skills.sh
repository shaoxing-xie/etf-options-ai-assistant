#!/usr/bin/env bash
set -euo pipefail

# One-shot checker for OpenClaw third-party skills required/recommended by this repo.
# It scans common skill locations and reports which skills are installed.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SKILL_DIRS=(
  "${HOME}/.openclaw/skills"
  "${HOME}/.openclaw/workspaces/shared/skills"
)

# Recommended skills for "watching the market" / "event sentinel" / "external info".
RECOMMENDED_SKILLS=(
  "tavily-search"
  "topic-monitor"
  "qmd-cli"
)

# Optional skills (useful for expansion).
OPTIONAL_SKILLS=(
  "mootdx-china-stock-data"
  "capability-evolver"
  "Capability Evolver"
)

color() {
  local code="$1"
  shift
  # If not a TTY (e.g., cron logs), avoid ANSI escape sequences.
  if [[ -t 1 ]]; then
    # shellcheck disable=SC2059
    printf "\033[%sm%s\033[0m" "${code}" "$*"
  else
    printf "%s" "$*"
  fi
}

exists_dir() {
  [[ -d "$1" ]]
}

find_skill_path() {
  local name="$1"
  local d
  for d in "${SKILL_DIRS[@]}"; do
    if [[ -d "${d}/${name}" ]]; then
      echo "${d}/${name}"
      return 0
    fi
  done
  return 1
}

has_skill_md() {
  local skill_path="$1"
  [[ -f "${skill_path}/SKILL.md" ]]
}

print_header() {
  echo "OpenClaw third-party skills checker"
  echo "Repo: ${ROOT_DIR}"
  echo
  echo "Scanning skill directories:"
  local d
  for d in "${SKILL_DIRS[@]}"; do
    if exists_dir "$d"; then
      echo "  - ${d}"
    else
      echo "  - ${d} (missing)"
    fi
  done
  echo
}

check_one() {
  local name="$1"
  local path=""
  if path="$(find_skill_path "$name" 2>/dev/null)"; then
    if has_skill_md "$path"; then
      echo "  - $(color 32 "OK")  ${name}  (${path})"
      return 0
    fi
    echo "  - $(color 33 "WARN") ${name}  (${path})  (missing SKILL.md)"
    return 0
  fi
  echo "  - $(color 31 "MISS") ${name}"
  return 1
}

main() {
  print_header

  echo "Recommended:"
  local missing_recommended=0
  local s
  for s in "${RECOMMENDED_SKILLS[@]}"; do
    if ! check_one "$s"; then
      missing_recommended=$((missing_recommended + 1))
    fi
  done
  echo

  echo "Optional:"
  for s in "${OPTIONAL_SKILLS[@]}"; do
    # optional -> don't affect exit code
    check_one "$s" || true
  done
  echo

  if [[ $missing_recommended -gt 0 ]]; then
    echo "$(color 31 "Result: FAIL") - missing ${missing_recommended} recommended skill(s)."
    echo "See: docs/getting-started/third-party-skills.md"
    exit 2
  fi

  echo "$(color 32 "Result: OK") - all recommended skills found."
}

main "$@"

