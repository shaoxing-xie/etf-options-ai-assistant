"""Tests for scripts/run_quality_autofix_runner_cli.py outcome classification."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "run_quality_autofix_runner_cli.py"
    spec = importlib.util.spec_from_file_location("qa_runner", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_classify_skipped_no_audit() -> None:
    mod = _load()
    label, _ = mod.classify_outcome("AUTOFIX_SKIPPED_NO_TODAY_AUDIT_RECORD\n", 0)
    assert label == "已跳过"


def test_classify_triggered_ok() -> None:
    mod = _load()
    label, reason = mod.classify_outcome("AUTOFIX_TRIGGER_COMMAND=openclaw ...\n", 0)
    assert label == "已触发"
    assert "0" in reason


def test_classify_triggered_fail() -> None:
    mod = _load()
    label, _ = mod.classify_outcome("AUTOFIX_TRIGGER_COMMAND=openclaw ...\n", 3)
    assert label == "已触发（失败）"
