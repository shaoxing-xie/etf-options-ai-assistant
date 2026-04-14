"""verify_daily_market_report_keywords.py CLI：禁止无参阻塞、--fast 子集。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "verify_daily_market_report_keywords.py"
PY = sys.executable


def test_verify_script_exits_2_without_input_source() -> None:
    r = subprocess.run([PY, str(SCRIPT)], capture_output=True, text=True, timeout=5)
    assert r.returncode == 2
    assert "ERROR" in (r.stderr or "") or "指定" in (r.stderr or "")


def test_verify_stdin_fast_passes_minimal_body() -> None:
    body = "\n".join(
        [
            "## 执行摘要",
            "## 大盘与量能",
            "## 资金",
            "## 展望",
            "`DAILY_REPORT_STATUS=OK`",
        ]
    )
    r = subprocess.run(
        [PY, str(SCRIPT), "--stdin", "--fast"],
        input=body,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert r.returncode == 0, r.stderr + r.stdout


def test_verify_full_needs_more_sections() -> None:
    body = "执行摘要 only"
    r = subprocess.run(
        [PY, str(SCRIPT), "--stdin"],
        input=body,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert r.returncode == 1
