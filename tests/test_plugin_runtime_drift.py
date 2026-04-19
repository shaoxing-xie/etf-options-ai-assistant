"""
Optional: compare installed OpenClaw runtime plugin version vs local dev repo (if paths exist).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _read_version(p: Path) -> str | None:
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return str(data.get("version") or "")
    except Exception:
        return None


def test_runtime_plugin_version_matches_src_when_both_present():
    runtime = Path.home() / ".openclaw/extensions/openclaw-data-china-stock/openclaw.plugin.json"
    src = Path(os.getenv("OPENCLAW_CHINA_STOCK_SRC", "")).expanduser()
    if not src.is_file():
        assistant_root = Path(__file__).resolve().parents[1]
        candidate = assistant_root.parent / "openclaw-data-china-stock" / "openclaw.plugin.json"
        if candidate.is_file():
            src = candidate
    rv = _read_version(runtime)
    sv = _read_version(src) if src.is_file() else None
    if not rv or not sv:
        pytest.skip("runtime or src openclaw.plugin.json not found")
    assert rv == sv, f"Plugin drift: runtime={rv} src={sv} (sync via install_plugin_to_runtime.sh)"
