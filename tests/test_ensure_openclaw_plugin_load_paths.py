"""Unit tests for scripts/ensure_openclaw_plugin_load_paths.py"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "ensure_openclaw_plugin_load_paths.py"


def _run(*args: str, input_obj: dict | None = None, tmp_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    cfg = tmp_path / "openclaw.json" if tmp_path else None
    argv = [sys.executable, str(SCRIPT), *args]
    if cfg is not None:
        assert input_obj is not None
        cfg.write_text(json.dumps(input_obj, ensure_ascii=False), encoding="utf-8")
        argv.extend(["--config", str(cfg)])
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def test_merge_load_paths_and_dedupe(tmp_path: Path) -> None:
    ext = tmp_path / "extensions"
    ext.mkdir()
    repo = tmp_path / "etf-options-ai-assistant"
    repo.mkdir()
    data = {"plugins": {"load": {"paths": [str(repo)]}}}
    r = _run(
        "--repo-root",
        str(repo),
        "--extensions-dir",
        str(ext),
        input_obj=data,
        tmp_path=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads((tmp_path / "openclaw.json").read_text(encoding="utf-8"))
    paths = out["plugins"]["load"]["paths"]
    # 保留已有顺序并追加缺失项；须同时含 extensions 与 repo，且无重复
    assert set(paths) == {str(ext.resolve()), str(repo.resolve())}
    assert len(paths) == 2


def test_ensure_allow_and_entry(tmp_path: Path) -> None:
    ext = tmp_path / "extensions"
    ext.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    data: dict = {"plugins": {"load": {"paths": []}}}
    r = _run(
        "--repo-root",
        str(repo),
        "--extensions-dir",
        str(ext),
        "--ensure-allow",
        "--ensure-entry",
        input_obj=data,
        tmp_path=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads((tmp_path / "openclaw.json").read_text(encoding="utf-8"))
    assert "option-trading-assistant" in out["plugins"]["allow"]
    assert out["plugins"]["entries"]["option-trading-assistant"] == {"enabled": True}


def test_dry_run_no_write(tmp_path: Path) -> None:
    ext = tmp_path / "extensions"
    ext.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    original = {"plugins": {"load": {"paths": []}}}
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps(original), encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--repo-root",
            str(repo),
            "--extensions-dir",
            str(ext),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert json.loads(cfg.read_text(encoding="utf-8")) == original
