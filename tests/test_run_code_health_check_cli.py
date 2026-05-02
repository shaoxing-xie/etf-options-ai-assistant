"""Smoke tests for scripts/run_code_health_check_cli.py (Feishu body builder)."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_cli_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "run_code_health_check_cli.py"
    spec = importlib.util.spec_from_file_location("run_code_health_check_cli", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_feishu_body_bandit_rc1_style() -> None:
    mod = _load_cli_module()
    data = {
        "auto_fixed_count": 0,
        "bare_except_fixed": 0,
        "ruff_remaining": [],
        "mypy": {"returncode": 0},
        "pytest": {"returncode": 0},
        "bandit": {"returncode": 1},
    }
    md = Path("/tmp/code-health-autofix-2026-04-18.md")
    js = Path("/tmp/code-health-autofix-2026-04-18.json")
    title, body = mod.build_feishu_body(data, md, js, tz_name="Asia/Shanghai")
    assert title == "每日代码健康体检"
    assert "已自动修复：0 项" in body
    assert "Bandit: 返回码 1" in body
    assert "P0：" in body and "Bandit" in body
    assert str(md) in body and str(js) in body
