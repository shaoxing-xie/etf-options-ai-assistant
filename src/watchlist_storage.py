"""观察池 JSON 持久化（相对项目根 data/watchlist/）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def watchlist_dir() -> Path:
    d = _root() / "data" / "watchlist"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_watchlist_path() -> Path:
    return watchlist_dir() / "default.json"


def read_watchlist(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or default_watchlist_path()
    if not p.is_file():
        return {"version": 1, "updated_at": None, "symbols": [], "meta": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def write_watchlist(payload: Dict[str, Any], path: Optional[Path] = None) -> Path:
    p = path or default_watchlist_path()
    payload = dict(payload)
    payload.setdefault("version", 1)
    payload["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def merge_screening_picks(
    screening_tool_json: Dict[str, Any],
    *,
    top_k: Optional[int] = None,
    path: Optional[Path] = None,
) -> Path:
    """
    将 tool_screen_equity_factors 成功返回的 data 列表合并写入观察池。
    保留 meta.last_screening 供跟踪工作流读取。
    """
    rows = screening_tool_json.get("data") if screening_tool_json.get("success") else None
    if not isinstance(rows, list):
        rows = []
    if top_k is not None:
        rows = rows[: max(0, int(top_k))]
    symbols: List[str] = []
    for r in rows:
        if isinstance(r, dict) and r.get("symbol"):
            symbols.append(str(r["symbol"]).strip())
    cur = read_watchlist(path)
    cur["symbols"] = symbols
    cur.setdefault("meta", {})
    cur["meta"]["last_screening"] = {
        "quality_score": screening_tool_json.get("quality_score"),
        "degraded": screening_tool_json.get("degraded"),
        "config_hash": screening_tool_json.get("config_hash"),
        "plugin_version": screening_tool_json.get("plugin_version"),
        "universe": screening_tool_json.get("universe"),
    }
    return write_watchlist(cur, path=path)
