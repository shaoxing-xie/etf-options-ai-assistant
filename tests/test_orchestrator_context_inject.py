"""data_pipeline：context 覆盖 job/notify 等（B+C 管道）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from src.orchestrator.dag_executor import DAGExecutor
from src.orchestrator.registry import load_tasks_registry


def test_tool_run_data_cache_job_merges_context_job(tmp_path: Path):
    reg_path = tmp_path / "tasks_registry.yaml"
    reg_path.write_text(
        yaml.safe_dump(
            {
                "version": "1",
                "orchestrator": {"enabled": True},
                "defaults": {},
                "tasks": [
                    {
                        "id": "pipe",
                        "enabled": True,
                        "steps": [
                            {
                                "id": "run_cache_job",
                                "kind": "tool",
                                "tool": "tool_run_data_cache_job",
                                "params": {"job": "morning_daily", "notify": False},
                            }
                        ],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    reg = load_tasks_registry(reg_path)
    ex = DAGExecutor(registry=reg)
    with patch("src.orchestrator.dag_executor._invoke_tool") as m:
        m.return_value = {"success": True}
        res = ex.execute("pipe", context={"job": "intraday_minute", "notify": False}, dry_run=False)
        assert res.success is True
        m.assert_called_once()
        _tool, params, _root = m.call_args[0]
        assert _tool == "tool_run_data_cache_job"
        assert params.get("job") == "intraday_minute"
        assert params.get("notify") is False


def test_params_from_context_overrides_phase(tmp_path: Path):
    reg_path = tmp_path / "tasks_registry.yaml"
    reg_path.write_text(
        """
version: "1"
orchestrator:
  enabled: true
defaults: {}
tasks:
  - id: intraday
    enabled: true
    steps:
      - id: sig
        kind: tool
        tool: tool_run_signal_risk_inspection_and_send
        params:
          mode: test
          fetch_mode: test
          phase: morning
        params_from_context:
          - phase
""",
        encoding="utf-8",
    )
    reg = load_tasks_registry(reg_path)
    ex = DAGExecutor(registry=reg)
    with patch("src.orchestrator.dag_executor._invoke_tool") as m:
        m.return_value = {"success": True}
        ex.execute("intraday", context={"phase": "afternoon"}, dry_run=False)
        _tool, params, _root = m.call_args[0]
        assert _tool == "tool_run_signal_risk_inspection_and_send"
        assert params.get("phase") == "afternoon"
