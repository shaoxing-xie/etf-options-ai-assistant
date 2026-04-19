"""Ensure cron toolsAllow tool_* names exist in config/tools_manifest.json."""

from __future__ import annotations

import json
from pathlib import Path


def test_send_etf_rotation_research_report_in_manifest() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config" / "tools_manifest.json").read_text(encoding="utf-8"))
    ids = {t.get("id") for t in (manifest.get("tools") or []) if isinstance(t, dict)}
    assert "tool_send_etf_rotation_research_report" in ids
    assert "tool_etf_rotation_research" in ids
    assert "tool_screen_equity_factors" in ids
    assert "tool_quantitative_screening" not in ids
