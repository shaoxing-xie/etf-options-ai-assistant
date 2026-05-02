"""Unit tests for semantic L4 quality backstop staleness policy."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "semantic_quality_backstop_audit",
    _ROOT / "scripts" / "semantic_quality_backstop_audit.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_snapshot_stale = _mod._snapshot_stale
_resolve_dataset_expected_trade_date_hyphen = _mod._resolve_dataset_expected_trade_date_hyphen


def test_stale_when_latest_trade_date_before_expected() -> None:
    now = datetime(2026, 4, 28, 8, 52, 0, tzinfo=timezone.utc)
    gen = now - timedelta(hours=30)
    stale, basis = _snapshot_stale(
        now,
        latest_trade_date="2026-04-22",
        generated_at=gen,
        expected_trade_date="2026-04-27",
    )
    assert stale is True
    assert basis == "trade_calendar_lag"


def test_not_stale_when_latest_matches_expected_despite_old_generated_at() -> None:
    """主口径为交易日对齐时，不因墙钟超过 24h 单独判 stale。"""
    now = datetime(2026, 4, 28, 8, 52, 0, tzinfo=timezone.utc)
    gen = now - timedelta(hours=72)
    stale, basis = _snapshot_stale(
        now,
        latest_trade_date="2026-04-27",
        generated_at=gen,
        expected_trade_date="2026-04-27",
    )
    assert stale is False
    assert basis == "trade_calendar_ok"


def test_fallback_wall_clock_when_no_expected_calendar() -> None:
    now = datetime(2026, 4, 28, 8, 52, 0, tzinfo=timezone.utc)
    gen = now - timedelta(hours=30)
    stale, basis = _snapshot_stale(
        now,
        latest_trade_date="2026-04-27",
        generated_at=gen,
        expected_trade_date=None,
    )
    assert stale is True
    assert basis == "generated_at_wall_clock"


def test_fallback_ok_when_no_expected_and_recent_generated_at() -> None:
    now = datetime(2026, 4, 28, 8, 52, 0, tzinfo=timezone.utc)
    gen = now - timedelta(hours=2)
    stale, basis = _snapshot_stale(
        now,
        latest_trade_date="2026-04-27",
        generated_at=gen,
        expected_trade_date=None,
    )
    assert stale is False
    assert basis == "generated_at_ok"


def test_dataset_cutoff_keeps_nightly_screening_on_previous_trade_day_at_1630() -> None:
    now = datetime(2026, 4, 28, 8, 30, 0, tzinfo=timezone.utc)  # 16:30 Asia/Shanghai
    expected = _resolve_dataset_expected_trade_date_hyphen(now, "screening_candidates", "2026-04-28")
    assert expected == "2026-04-27"


def test_dataset_cutoff_keeps_ops_events_on_previous_trade_day_before_1640() -> None:
    now = datetime(2026, 4, 28, 8, 30, 0, tzinfo=timezone.utc)  # 16:30 Asia/Shanghai
    expected = _resolve_dataset_expected_trade_date_hyphen(now, "ops_events", "2026-04-28")
    assert expected == "2026-04-27"


def test_dataset_cutoff_allows_intraday_screening_same_day_after_1405() -> None:
    now = datetime(2026, 4, 28, 6, 10, 0, tzinfo=timezone.utc)  # 14:10 Asia/Shanghai
    expected = _resolve_dataset_expected_trade_date_hyphen(now, "screening_view", "2026-04-28")
    assert expected == "2026-04-28"
