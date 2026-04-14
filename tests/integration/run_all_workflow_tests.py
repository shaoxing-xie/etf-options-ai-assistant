#!/usr/bin/env python3
"""
Workflow smoke checks for CI / local runs.

1. Validates every `tool:` in workflows/*.yaml against config/tools_manifest.yaml
   plus config/workflow_external_tool_ids.txt (extension-registered fetch/read tools).

Run from repo root:
  python tests/integration/run_all_workflow_tests.py

Legacy note: historical per-step scripts under workflows/test_*.py were never committed;
use scripts/validate_workflows.py as the maintained gate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKS = [
    ROOT / "scripts" / "validate_workflows.py",
    ROOT / "scripts" / "validate_tool_runner_manifest.py",
    ROOT / "scripts" / "validate_agent_yaml_tools.py",
]


def main() -> int:
    for script in CHECKS:
        if not script.is_file():
            print(f"Missing {script}", file=sys.stderr)
            return 1
        proc = subprocess.run([sys.executable, str(script)], cwd=str(ROOT))
        if proc.returncode != 0:
            return int(proc.returncode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
