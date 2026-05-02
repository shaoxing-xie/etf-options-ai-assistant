"""Layered config merge semantics (list replace at key)."""

from pathlib import Path

import yaml

from src.config_loader import (
    _backfill_feishu_webhook_from_env,
    get_default_config,
    merge_config,
    load_layered_user_config,
)


def test_backfill_feishu_webhook_from_env(monkeypatch):
    cfg = merge_config(get_default_config(), {"notification": {"feishu_webhook": None}})
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/testdummy")
    _backfill_feishu_webhook_from_env(cfg)
    assert str(cfg["notification"]["feishu_webhook"]).startswith("https://")


def test_merge_config_list_replaces_not_appends():
    base = {"option_contracts": {"underlyings": [{"underlying": "510300"}]}}
    over = {"option_contracts": {"underlyings": [{"underlying": "510500"}]}}
    out = merge_config(base, over)
    assert len(out["option_contracts"]["underlyings"]) == 1
    assert out["option_contracts"]["underlyings"][0]["underlying"] == "510500"


def test_load_layered_user_config_reads_base(tmp_path, monkeypatch):
    """Synthetic mini tree: only base.yaml required."""
    env_dir = tmp_path / "config" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "base.yaml").write_text(
        yaml.dump({"foo": {"bar": 1}, "listy": [1, 2]}, allow_unicode=True),
        encoding="utf-8",
    )
    (env_dir / "prod.yaml").write_text(
        yaml.dump({"foo": {"baz": 2}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ETF_OPTIONS_CONFIG_PROFILE", "prod")
    out = load_layered_user_config(tmp_path)
    assert out["foo"]["bar"] == 1
    assert out["foo"]["baz"] == 2


def test_load_layered_user_config_merges_domains_and_calendar_files(tmp_path, monkeypatch):
    env_dir = tmp_path / "config" / "environments"
    domain_dir = tmp_path / "config" / "domains"
    ref_dir = tmp_path / "config" / "reference"
    env_dir.mkdir(parents=True)
    domain_dir.mkdir(parents=True)
    ref_dir.mkdir(parents=True)

    (env_dir / "base.yaml").write_text(
        yaml.dump({"base_only": 1}, allow_unicode=True),
        encoding="utf-8",
    )
    (env_dir / "prod.yaml").write_text(
        yaml.dump({"foo": {"baz": 2}}),
        encoding="utf-8",
    )
    (domain_dir / "signals.yaml").write_text(
        yaml.dump({"foo": {"bar": 1}}, allow_unicode=True),
        encoding="utf-8",
    )
    (domain_dir / "platform.yaml").write_text(
        yaml.dump(
            {
                "system": {
                    "trading_hours": {
                        "calendar_source": "files",
                        "calendar_path_glob": "config/reference/holidays_*.yaml",
                        "holidays": {},
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (ref_dir / "holidays_2026.yaml").write_text("- '20260101'\n", encoding="utf-8")
    (ref_dir / "holidays_2027.yaml").write_text("[]\n", encoding="utf-8")

    monkeypatch.setenv("ETF_OPTIONS_CONFIG_PROFILE", "prod")
    out = load_layered_user_config(tmp_path)
    assert out["foo"]["bar"] == 1
    assert out["foo"]["baz"] == 2
    assert out["system"]["trading_hours"]["holidays"]["2026"] == ["20260101"]
    assert out["system"]["trading_hours"]["holidays"]["2027"] == []


def test_repo_base_yaml_loads():
    """Smoke: real repo has base.yaml and load_layered returns non-empty."""
    root = Path(__file__).resolve().parents[1]
    base = root / "config" / "environments" / "base.yaml"
    assert base.is_file(), "expected config/environments/base.yaml in repo"
    data = load_layered_user_config(root)
    assert "notification" in data
    assert "signal_generation" in data
    assert data["system"]["trading_hours"]["calendar_source"] == "files"
