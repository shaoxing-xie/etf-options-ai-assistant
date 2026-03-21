#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MovePlan:
    src: Path
    dst: Path


def _norm(p: str | Path) -> str:
    return str(Path(p).expanduser().resolve())


def _load_openclaw_agent_dirs(openclaw_json_path: Path) -> set[str]:
    data = json.loads(openclaw_json_path.read_text(encoding="utf-8"))
    agent_list = (data.get("agents") or {}).get("list") or []
    keep = set()
    for entry in agent_list:
        agent_dir = entry.get("agentDir")
        if agent_dir:
            keep.add(_norm(agent_dir))
    return keep


def _discover_agent_definition_dirs(agents_root: Path) -> list[Path]:
    """
    Discover agent definition directories by the presence of `agent/models.json`.
    We intentionally do NOT treat `sessions/` as agent definitions.
    """
    results: list[Path] = []
    for models_json in agents_root.glob("**/agent/models.json"):
        results.append(models_json.parent)  # .../agent
    # De-dup, stable sort
    uniq = sorted({p.resolve() for p in results})
    return uniq


def _build_move_plans(
    agent_def_dirs: list[Path],
    keep_agent_dirs: set[str],
    trash_root: Path,
) -> list[MovePlan]:
    plans: list[MovePlan] = []
    for agent_dir in agent_def_dirs:
        agent_dir_norm = _norm(agent_dir)
        if agent_dir_norm in keep_agent_dirs:
            continue

        rel = agent_dir.relative_to(agent_dir.anchor) if agent_dir.is_absolute() else agent_dir
        # Preserve path structure under trash to avoid collisions
        dst = trash_root / rel.as_posix().lstrip("/")
        plans.append(MovePlan(src=agent_dir, dst=dst))
    return plans


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    openclaw_json = Path(os.environ.get("OPENCLAW_CONFIG", "~/.openclaw/openclaw.json")).expanduser()
    agents_root = Path(os.environ.get("OPENCLAW_AGENTS_ROOT", "~/.openclaw/agents")).expanduser()

    if not openclaw_json.exists():
        print(f"ERROR: openclaw.json not found: {openclaw_json}", file=sys.stderr)
        return 2
    if not agents_root.exists():
        print(f"ERROR: agents root not found: {agents_root}", file=sys.stderr)
        return 2

    keep_agent_dirs = _load_openclaw_agent_dirs(openclaw_json)
    agent_def_dirs = _discover_agent_definition_dirs(agents_root)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    trash_root = Path("~/.openclaw/agents/_trash").expanduser() / ts
    plans = _build_move_plans(agent_def_dirs, keep_agent_dirs, trash_root)

    if not plans:
        print("No unused agent definition directories found.")
        return 0

    print("Will move the following unused agent definition dirs:")
    for plan in plans:
        print(f"- {plan.src}  ->  {plan.dst}")

    if os.environ.get("OPENCLAW_CLEANUP_DRY_RUN", "").lower() in {"1", "true", "yes"}:
        print("DRY RUN: no changes made.")
        return 0

    for plan in plans:
        if not plan.src.exists():
            continue
        _ensure_parent(plan.dst)
        shutil.move(str(plan.src), str(plan.dst))

    print(f"Done. Moved {len(plans)} dirs into: {trash_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

