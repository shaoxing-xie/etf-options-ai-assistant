from datetime import datetime
from pathlib import Path

import pytest

from src.config_validate import (
    classify_validation_messages,
    cross_validate_runtime_config,
    missing_runtime_surface_keys,
    universe_ssot_violations,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "config" / "schema" / "runtime_surface.schema.json"


def test_cross_validate_duplicate_contract_code():
    cfg = {
        "option_contracts": {
            "underlyings": [
                {
                    "underlying": "510300",
                    "call_contracts": [],
                    "put_contracts": [
                        {"contract_code": "10000001", "strike_price": 1.0, "expiry_date": "2026-01-01"},
                        {"contract_code": "10000001", "strike_price": 1.1, "expiry_date": "2026-01-01"},
                    ],
                }
            ]
        },
        "data_cache": {"etf_codes": ["510300"]},
        "etf_trading": {"enabled_etfs": ["510300"]},
        "system": {"trading_hours": {"holidays": {2099: ["20990101"]}}},
    }
    msgs = cross_validate_runtime_config(cfg)
    assert any("duplicate contract_code" in m for m in msgs)


def test_classify_holiday_hint_is_soft():
    y = datetime.now().year
    cfg = {
        "option_contracts": {
            "underlyings": [
                {
                    "underlying": "510300",
                    "call_contracts": [{"contract_code": "10000001", "strike_price": 1.0, "expiry_date": "2026-01-01"}],
                    "put_contracts": [{"contract_code": "10000002", "strike_price": 1.0, "expiry_date": "2026-01-01"}],
                }
            ]
        },
        "data_cache": {"etf_codes": ["510300"]},
        "etf_trading": {"enabled_etfs": ["510300"]},
        "system": {"trading_hours": {"holidays": {y: []}}},
    }
    msgs = cross_validate_runtime_config(cfg)
    hard, soft = classify_validation_messages(msgs)
    assert any("holidays has no year" in s for s in soft)
    assert not hard


def test_universe_ssot_omits_holiday_soft():
    y = datetime.now().year
    cfg = {
        "option_contracts": {
            "underlyings": [
                {
                    "underlying": "510300",
                    "call_contracts": [],
                    "put_contracts": [],
                }
            ]
        },
        "data_cache": {"etf_codes": ["510300"]},
        "etf_trading": {"enabled_etfs": ["510300"]},
        "system": {"trading_hours": {"holidays": {y: []}}},
    }
    assert universe_ssot_violations(cfg) == []


def test_missing_runtime_surface_keys_detects_gap():
    cfg = {"notification": {}, "logging": {}}
    miss = missing_runtime_surface_keys(cfg, schema_path=SCHEMA)
    assert "option_contracts" in miss


@pytest.mark.skipif(not SCHEMA.is_file(), reason="schema file missing")
def test_merged_repo_config_satisfies_surface_schema():
    from src.config_loader import load_system_config

    cfg = load_system_config(use_cache=False)
    assert missing_runtime_surface_keys(cfg, schema_path=SCHEMA) == []
