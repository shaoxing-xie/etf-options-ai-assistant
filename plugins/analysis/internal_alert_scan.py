"""OpenClaw tool wrapper for internal chart alert scanning."""

from __future__ import annotations

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from src.alerts.engine import tool_internal_alert_scan  # noqa: E402,F401

