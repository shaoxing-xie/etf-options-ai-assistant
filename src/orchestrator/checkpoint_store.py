"""Orchestrator 步骤级 checkpoint（task_id + trade_date 键，TTL）。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> datetime | None:
    s = (ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


@dataclass
class OrchestratorCheckpoint:
    task_id: str
    trade_date: str
    run_id: str
    next_step_id: str | None
    ctx_snapshot: dict[str, Any]
    saved_at: str
    version: str = "1.0"


class CheckpointStore:
    def __init__(self, root: Path, *, ttl_hours: float = 24.0) -> None:
        self._root = root.resolve()
        self._ttl_hours = max(0.5, float(ttl_hours))
        self._dir = self._root / "data" / "meta" / "orchestrator_checkpoints"

    def _path(self, task_id: str, trade_date: str) -> Path:
        safe_tid = task_id.replace(os.sep, "_").replace(" ", "")[:120]
        safe_td = (trade_date or "unknown").replace(os.sep, "_")
        return self._dir / f"{safe_tid}_{safe_td}.json"

    def load(self, task_id: str, trade_date: str | None) -> OrchestratorCheckpoint | None:
        td = trade_date or "unknown"
        path = self._path(task_id, td)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None
        saved_at = str(raw.get("saved_at") or raw.get("timestamp") or "")
        t0 = _parse_iso(saved_at)
        if t0 is not None:
            age_h = (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0
            if age_h > self._ttl_hours:
                self.clear(task_id, trade_date)
                return None
        next_sid = raw.get("next_step_id")
        ctx = raw.get("ctx_snapshot")
        if not isinstance(ctx, dict):
            ctx = {}
        return OrchestratorCheckpoint(
            task_id=str(raw.get("task_id") or task_id),
            trade_date=str(raw.get("trade_date") or td),
            run_id=str(raw.get("run_id") or ""),
            next_step_id=str(next_sid).strip() if next_sid else None,
            ctx_snapshot=ctx,
            saved_at=saved_at or _utc_now_iso(),
            version=str(raw.get("version") or "1.0"),
        )

    def save(
        self,
        task_id: str,
        trade_date: str | None,
        *,
        run_id: str,
        next_step_id: str | None,
        ctx_snapshot: dict[str, Any],
    ) -> Path:
        td = trade_date or "unknown"
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(task_id, td)
        payload = {
            "task_id": task_id,
            "trade_date": td,
            "run_id": run_id,
            "next_step_id": next_step_id,
            "ctx_snapshot": ctx_snapshot,
            "saved_at": _utc_now_iso(),
            "version": "1.0",
        }
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), prefix=".ckpt.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return path

    def clear(self, task_id: str, trade_date: str | None) -> None:
        path = self._path(task_id, trade_date or "unknown")
        try:
            path.unlink(missing_ok=True)
        except TypeError:  # py3.10
            if path.is_file():
                path.unlink()


def filter_checkpoint_context(
    ctx: dict[str, Any],
    allowlist: tuple[str, ...] | None,
    *,
    max_bytes: int = 256_000,
) -> dict[str, Any]:
    """可序列化子集；allowlist None 表示常用键 + step_results 精简。"""
    default_keys = (
        "memory_injection",
        "last_l4_result",
        "job",
        "phase",
        "notify",
        "throttle_stock",
        "feishu_title",
        "profile",
        "skip_file_lock",
        "last_step_result",
    )
    keys = allowlist if allowlist else default_keys
    out: dict[str, Any] = {}
    for k in keys:
        if k not in ctx:
            continue
        v = ctx[k]
        try:
            json.dumps(v, ensure_ascii=False)
            out[k] = v
        except (TypeError, ValueError):
            continue
    if "step_results" in ctx and (allowlist is None or "step_results" in allowlist):
        sr = ctx.get("step_results")
        if isinstance(sr, dict):
            slim: dict[str, Any] = {}
            for sid, doc in sr.items():
                if not isinstance(doc, dict):
                    continue
                o = doc.get("output")
                slim[sid] = {
                    "step_id": doc.get("step_id", sid),
                    "ok": doc.get("ok"),
                    "output": _slim_output(o) if isinstance(o, dict) else {},
                }
            try:
                json.dumps(slim, ensure_ascii=False)
                out["step_results"] = slim
            except (TypeError, ValueError):
                pass
    raw = json.dumps(out, ensure_ascii=False)
    if len(raw.encode("utf-8")) > max_bytes:
        out.pop("step_results", None)
        out.pop("last_l4_result", None)
    return out


def _slim_output(o: dict[str, Any]) -> dict[str, Any]:
    """保留 success、error、quality、_meta、小 data。"""
    keys = ("success", "error", "quality_status", "data", "_meta", "stderr", "stdout")
    slim = {k: o[k] for k in keys if k in o}
    if isinstance(slim.get("data"), dict) and len(json.dumps(slim["data"], ensure_ascii=False)) > 8000:
        slim["data"] = {"_truncated": True, "keys": list(slim["data"].keys())[:40]}
    return slim
