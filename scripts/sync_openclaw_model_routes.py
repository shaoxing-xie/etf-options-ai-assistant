#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelCfg:
    primary: str
    fallbacks: list[str]

    @staticmethod
    def from_obj(obj: dict[str, Any]) -> "ModelCfg":
        primary = obj.get("primary")
        fallbacks = obj.get("fallbacks") or []
        if not isinstance(primary, str) or not primary:
            raise ValueError("model.primary must be a non-empty string")
        if not isinstance(fallbacks, list) or any(not isinstance(x, str) for x in fallbacks):
            raise ValueError("model.fallbacks must be a list of strings")
        return ModelCfg(primary=primary, fallbacks=fallbacks)

    def to_obj(self) -> dict[str, Any]:
        return {"primary": self.primary, "fallbacks": self.fallbacks}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get(d: dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _ensure_dict(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    cur: dict[str, Any] = d
    for k in keys:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    return cur


def main() -> int:
    openclaw_json_path = Path(os.environ.get("OPENCLAW_JSON", "~/.openclaw/openclaw.json")).expanduser()
    routes_path = Path(
        os.environ.get(
            "OPENCLAW_MODEL_ROUTES",
            "~/.openclaw/workspaces/etf-options-ai-assistant/config/model_routes.json",
        )
    ).expanduser()
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
    preserve_freeride_defaults = os.environ.get("PRESERVE_FREERIDE_DEFAULTS", "").lower() in {"1", "true", "yes"}

    cfg = _read_json(openclaw_json_path)
    routes = _read_json(routes_path)

    groups = routes.get("groups") or {}
    agents_cfg = routes.get("agents") or {}
    defaults_group = agents_cfg.get("defaultsGroup", "F")
    overrides = agents_cfg.get("overrides") or {}

    if defaults_group not in groups:
        raise SystemExit(f"defaultsGroup '{defaults_group}' not found in groups")

    group_models: dict[str, ModelCfg] = {}
    for group_name, group_obj in groups.items():
        if not isinstance(group_obj, dict) or "model" not in group_obj:
            raise SystemExit(f"group '{group_name}' missing model")
        group_models[group_name] = ModelCfg.from_obj(group_obj["model"])

    changed = False

    # Apply defaults.model = group[defaultsGroup].model
    # Optional integration mode for FreeRide:
    # - PRESERVE_FREERIDE_DEFAULTS=1 -> keep existing agents.defaults.model/models untouched
    # - still apply per-agent overrides (M/S etc.) from model_routes.json
    defaults_model = group_models[defaults_group]
    agents_defaults = _ensure_dict(cfg, "agents", "defaults")
    if preserve_freeride_defaults:
        print("PRESERVE_FREERIDE_DEFAULTS=1 -> keeping agents.defaults.model/models unchanged.")
    else:
        desired_defaults = defaults_model.to_obj()
        if agents_defaults.get("model") != desired_defaults:
            agents_defaults["model"] = desired_defaults
            changed = True

    # Apply per-agent overrides
    agent_list = _get(cfg, "agents", "list") or []
    if not isinstance(agent_list, list):
        raise SystemExit("openclaw.json agents.list must be a list")

    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        agent_id = agent.get("id")
        if not isinstance(agent_id, str) or not agent_id:
            continue

        group = overrides.get(agent_id, defaults_group)
        if group not in group_models:
            raise SystemExit(f"agent '{agent_id}' references unknown group '{group}'")

        if group == defaults_group:
            # Inherit defaults: remove explicit model if present
            if "model" in agent:
                agent.pop("model", None)
                changed = True
            continue

        desired = group_models[group].to_obj()
        if agent.get("model") != desired:
            agent["model"] = desired
            changed = True

    if not changed:
        print("No changes needed (already in sync).")
        return 0

    if dry_run:
        print("DRY RUN: changes computed but not written.")
        return 0

    backup_path = openclaw_json_path.with_suffix(f".json.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    backup_path.write_text(openclaw_json_path.read_text(encoding="utf-8"), encoding="utf-8")
    _write_json(openclaw_json_path, cfg)
    print(f"Updated {openclaw_json_path} (backup: {backup_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

