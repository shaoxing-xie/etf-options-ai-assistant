from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class WorkspaceService:
    """Persist chart workspaces for the research console."""

    def __init__(self, base_dir: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.base_dir = base_dir or (root / "data" / "chart_console")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.base_dir / "workspaces.json"

    def list_workspaces(self) -> list[dict[str, Any]]:
        payload = self._read_payload()
        items = payload.get("workspaces", [])
        if not isinstance(items, list):
            return []
        return [w for w in items if isinstance(w, dict)]

    def get_workspace(self, name: str) -> dict[str, Any] | None:
        if not name:
            return None
        for workspace in self.list_workspaces():
            if str(workspace.get("name", "")).strip() == name.strip():
                return workspace
        return None

    def save_workspace(self, name: str, state: dict[str, Any]) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("workspace name cannot be empty")
        payload = self._read_payload()
        items = self.list_workspaces()
        now = datetime.now().isoformat(timespec="seconds")
        history = []
        old_item = None
        for old in items:
            if str(old.get("name", "")).strip() == clean_name:
                old_item = old
                break
        if isinstance(old_item, dict):
            history = old_item.get("history", []) if isinstance(old_item.get("history"), list) else []
            history = history[-9:] + [{"updated_at": old_item.get("updated_at"), "state": old_item.get("state", {})}]

        record = {
            "name": clean_name,
            "updated_at": now,
            "state": state,
            "history": history,
        }
        inserted = False
        for idx, old in enumerate(items):
            if str(old.get("name", "")).strip() == clean_name:
                items[idx] = record
                inserted = True
                break
        if not inserted:
            items.append(record)
        payload["workspaces"] = sorted(items, key=lambda x: str(x.get("updated_at", "")), reverse=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def save_template(self, name: str, template: dict[str, Any]) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("template name cannot be empty")
        payload = self._read_payload()
        templates = payload.get("templates", [])
        if not isinstance(templates, list):
            templates = []
        now = datetime.now().isoformat(timespec="seconds")
        record = {"name": clean_name, "updated_at": now, "template": template}
        placed = False
        for idx, old in enumerate(templates):
            if str(old.get("name", "")).strip() == clean_name:
                templates[idx] = record
                placed = True
                break
        if not placed:
            templates.append(record)
        payload["templates"] = sorted(templates, key=lambda x: str(x.get("updated_at", "")), reverse=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    def list_templates(self) -> list[dict[str, Any]]:
        payload = self._read_payload()
        templates = payload.get("templates", [])
        if not isinstance(templates, list):
            return []
        return [t for t in templates if isinstance(t, dict)]

    def delete_workspace(self, name: str) -> bool:
        clean_name = name.strip()
        if not clean_name:
            return False
        items = self.list_workspaces()
        remain = [w for w in items if str(w.get("name", "")).strip() != clean_name]
        if len(remain) == len(items):
            return False
        payload = self._read_payload()
        payload["workspaces"] = remain
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"workspaces": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"workspaces": []}
        if not isinstance(payload, dict):
            return {"workspaces": []}
        if not isinstance(payload.get("workspaces"), list):
            payload["workspaces"] = []
        return payload
