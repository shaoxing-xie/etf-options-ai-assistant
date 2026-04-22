from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data_layer import MetaEnvelope, append_contract_jsonl

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


VALID_STATES = {"queued", "running", "succeeded", "failed", "skipped"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class DependencyWaitResult:
    satisfied: bool
    missing: list[str]
    reason: str


class TaskStateManager:
    def __init__(
        self,
        *,
        root: Path,
        task_id: str,
        trade_date: str,
        run_id: str,
        trigger_source: str,
        trigger_window: str = "daily",
        session_type: str = "",
    ) -> None:
        self.root = root.resolve()
        self.task_id = task_id
        self.trade_date = trade_date
        self.run_id = run_id
        self.trigger_source = trigger_source if trigger_source in {"dependency", "cron"} else "cron"
        self.trigger_window = trigger_window or "daily"
        self.session_type = session_type.strip()
        self._state_dir = self.root / "data" / "state"
        self._events_path = self.root / "data" / "decisions" / "orchestration" / "events" / f"{trade_date}.jsonl"
        self._lock_path = self._state_dir / ".orchestration.lock"

    @property
    def idempotency_key(self) -> str:
        base = f"{self.task_id}:{self.trade_date}:{self.trigger_window}"
        if self.session_type:
            return f"{base}:{self.session_type}"
        return base

    def _state_path(self, task_id: str | None = None) -> Path:
        return self._state_dir / f"{task_id or self.task_id}.json"

    def _load_state(self, task_id: str | None = None) -> dict[str, Any]:
        path = self._state_path(task_id)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def _file_lock(self):
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._lock_path.touch(exist_ok=True)
        f = self._lock_path.open("r+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return f

    def _file_unlock(self, lock_file) -> None:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    def _append_event(self, from_state: str, to_state: str, reason: str, depends_on: list[str], condition_met: bool) -> None:
        if to_state not in VALID_STATES:
            raise ValueError(f"invalid state: {to_state}")
        payload = {
            "event_id": f"{self.task_id}.{self.run_id}.{to_state}",
            "event_time": _utc_now(),
            "task_id": self.task_id,
            "run_id": self.run_id,
            "trade_date": self.trade_date,
            "idempotency_key": self.idempotency_key,
            "trigger_source": self.trigger_source,
            "trigger_window": self.trigger_window,
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            "depends_on": depends_on,
            "condition_met": condition_met,
            "lineage_refs": [str(self._state_path())],
        }
        append_contract_jsonl(
            self._events_path,
            payload=payload,
            meta=MetaEnvelope(
                schema_name="orchestration_event_v1",
                schema_version="1.0.0",
                task_id=self.task_id,
                run_id=self.run_id,
                data_layer="L3",
                trade_date=self.trade_date,
                quality_status="ok" if to_state in {"queued", "running", "succeeded"} else "degraded",
                lineage_refs=[str(self._state_path())],
                source_tools=["task_state_manager"],
            ),
        )

    def _write_state(self, state: str, reason: str, depends_on: list[str]) -> dict[str, Any]:
        if state not in VALID_STATES:
            raise ValueError(f"invalid state: {state}")
        current = self._load_state()
        payload = {
            "task_id": self.task_id,
            "trade_date": self.trade_date,
            "run_id": self.run_id,
            "state": state,
            "reason": reason,
            "depends_on": depends_on,
            "trigger_source": self.trigger_source,
            "trigger_window": self.trigger_window,
            "idempotency_key": self.idempotency_key,
            "updated_at": _utc_now(),
            "quality_status": "ok" if state == "succeeded" else ("error" if state == "failed" else "degraded"),
            "lineage_refs": [str(self._events_path)],
        }
        if isinstance(current, dict):
            payload["previous_state"] = current.get("state")
        self._atomic_write_json(self._state_path(), payload)
        return payload

    def dependency_snapshot(self, depends_on: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for dep in depends_on:
            out[dep] = self._load_state(dep)
        return out

    def has_succeeded(self) -> bool:
        state = self._load_state()
        return (
            state.get("state") == "succeeded"
            and state.get("trade_date") == self.trade_date
            and state.get("idempotency_key") == self.idempotency_key
        )

    def claim_execution(self, depends_on: list[str]) -> tuple[bool, str]:
        lock = self._file_lock()
        try:
            if self.has_succeeded():
                self._append_event("succeeded", "skipped", "already_executed", depends_on, True)
                self._write_state("skipped", "already_executed", depends_on)
                return False, "already_executed"
            current = self._load_state()
            if (
                current.get("state") == "running"
                and current.get("trade_date") == self.trade_date
                and current.get("idempotency_key") == self.idempotency_key
            ):
                self._append_event("running", "skipped", "duplicate_trigger", depends_on, True)
                self._write_state("skipped", "duplicate_trigger", depends_on)
                return False, "duplicate_trigger"
            self._append_event(str(current.get("state") or "none"), "queued", "queued", depends_on, True)
            self._write_state("queued", "queued", depends_on)
            self._append_event("queued", "running", "running", depends_on, True)
            self._write_state("running", "running", depends_on)
            return True, "running"
        finally:
            self._file_unlock(lock)

    def wait_for_dependencies(self, depends_on: list[str], timeout_seconds: int, poll_seconds: float = 1.0) -> DependencyWaitResult:
        if not depends_on:
            return DependencyWaitResult(True, [], "dependencies_satisfied")
        deadline = time.time() + max(1, timeout_seconds)
        while time.time() <= deadline:
            snapshot = self.dependency_snapshot(depends_on)
            missing = [
                dep
                for dep in depends_on
                if not (
                    isinstance(snapshot.get(dep), dict)
                    and snapshot[dep].get("trade_date") == self.trade_date
                    and (
                        snapshot[dep].get("state") == "succeeded"
                        # If an upstream task has already succeeded for this window,
                        # a later duplicate trigger may record `skipped(already_executed)`
                        # in the state snapshot. Treat that as dependency-satisfied.
                        or (
                            snapshot[dep].get("state") == "skipped"
                            and snapshot[dep].get("reason") == "already_executed"
                            and snapshot[dep].get("previous_state") == "succeeded"
                        )
                    )
                )
            ]
            if not missing:
                return DependencyWaitResult(True, [], "dependencies_satisfied")
            time.sleep(max(0.1, poll_seconds))
        return DependencyWaitResult(False, missing, f"dependency_timeout:{','.join(missing)}")

    def finish(self, *, to_state: str, reason: str, depends_on: list[str], condition_met: bool = True) -> dict[str, Any]:
        if to_state not in {"succeeded", "failed", "skipped"}:
            raise ValueError("finish only supports succeeded|failed|skipped")
        lock = self._file_lock()
        try:
            current = self._load_state()
            from_state = str(current.get("state") or "running")
            self._append_event(from_state, to_state, reason, depends_on, condition_met)
            return self._write_state(to_state, reason, depends_on)
        finally:
            self._file_unlock(lock)
