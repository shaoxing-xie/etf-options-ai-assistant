import pandas as pd

from src.features.six_index_features import _margin_change_metrics, _normalize_records, build_feature_snapshot


def test_normalize_records_supports_sector_all_data_payload() -> None:
    payload = {
        "success": True,
        "all_data": [
            {"sector_name": "银行", "change_percent": 1.2},
            {"sector_name": "石油石化", "change_percent": -0.5},
        ],
    }

    rows = _normalize_records(payload)

    assert len(rows) == 2
    assert rows[0]["sector_name"] == "银行"


def test_normalize_records_supports_nested_sector_map_payload() -> None:
    payload = {
        "success": True,
        "sectors": {
            "industry": [
                {"sector_name": "证券", "change_percent": 1.5},
                {"sector_name": "保险", "change_percent": 0.7},
            ]
        },
    }

    rows = _normalize_records(payload)

    assert len(rows) == 2
    assert {row["sector_name"] for row in rows} == {"证券", "保险"}


def test_margin_change_metrics_computes_proxy_from_sh_sz(monkeypatch) -> None:
    sh = pd.DataFrame(
        [
            {"日期": "2026-04-27", "融资融券余额": 100.0, "融资余额": 90.0},
            {"日期": "2026-04-28", "融资融券余额": 105.0, "融资余额": 95.0},
        ]
    )
    sz = pd.DataFrame(
        [
            {"日期": "2026-04-27", "融资融券余额": 200.0, "融资余额": 180.0},
            {"日期": "2026-04-28", "融资融券余额": 210.0, "融资余额": 190.0},
        ]
    )

    class _AkStub:
        @staticmethod
        def macro_china_market_margin_sh():
            return sh

        @staticmethod
        def macro_china_market_margin_sz():
            return sz

    monkeypatch.setitem(__import__("sys").modules, "akshare", _AkStub)

    out = _margin_change_metrics()

    assert out["quality_status"] == "info"
    assert out["margin_total"] == 315.0
    assert out["margin_change_pct"] == 0.05
    assert out["margin_change_proxy"] == 0.3


def test_margin_change_metrics_degrades_when_sources_fail(monkeypatch) -> None:
    class _AkStub:
        @staticmethod
        def macro_china_market_margin_sh():
            raise RuntimeError("boom")

        @staticmethod
        def macro_china_market_margin_sz():
            raise RuntimeError("boom")

    monkeypatch.setitem(__import__("sys").modules, "akshare", _AkStub)

    out = _margin_change_metrics()

    assert out["quality_status"] == "degraded"
    assert out["margin_change_proxy"] is None
    assert "margin_data_unavailable" in str(out["degraded_reason"])


def test_build_feature_snapshot_includes_margin_snapshot(monkeypatch) -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-07", "2026-04-08"]),
            "close": [10, 10.1, 10.2, 10.3, 10.4, 10.5],
            "volume": [1, 2, 3, 4, 5, 6],
        }
    )

    monkeypatch.setattr("src.features.six_index_features.next_trading_day", lambda trade_date: "2026-04-09")
    monkeypatch.setattr("src.features.six_index_features.tool_fetch_sector_data", lambda **kwargs: {"success": True, "all_data": []})
    monkeypatch.setattr("src.features.six_index_features.tool_fetch_northbound_flow", lambda **kwargs: {"success": True, "records": []})
    monkeypatch.setattr("src.features.six_index_features.tool_fetch_macro_snapshot", lambda **kwargs: {"success": True, "data": {}})
    monkeypatch.setattr("src.features.six_index_features._limit_up_metrics", lambda trade_date: {"limit_up_count": 1, "limit_up_ratio_smallcap_proxy": 0.1, "limit_up_ratio_kc50_proxy": 0.05, "degraded_reason": None})
    monkeypatch.setattr("src.features.six_index_features._fund_flow_metrics", lambda: {"market_main_force_score": 0.1, "degraded_reason": None})
    monkeypatch.setattr("src.features.six_index_features._style_spread_metrics", lambda: {"style_spread_percentile": 55.0})
    monkeypatch.setattr("src.features.six_index_features._margin_change_metrics", lambda: {"margin_change_proxy": 0.12, "quality_status": "info", "degraded_reason": None})
    monkeypatch.setattr(
        "src.features.six_index_features._hotspot_metrics",
        lambda trade_date: {
            "top_hotspots": ["半导体", "通信设备"],
            "top_hotspot_score": 81.5,
            "snapshot": {"hotspots": []},
            "degraded_reason": None,
        },
    )
    monkeypatch.setattr("src.features.six_index_features.load_kronos_signal", lambda index_code, feature_payload=None: {"kronos_available": False, "kronos_score": None, "degraded_reason": None})
    monkeypatch.setattr("src.features.six_index_features._daily_df", lambda symbol, lookback_days=320: df)

    doc = build_feature_snapshot("2026-04-08")

    assert doc["global_features"]["margin_change_proxy"] == 0.12
    assert doc["indices"]["000852"]["margin_change_proxy"] == 0.12
    assert doc["indices"]["000852"]["margin_snapshot"]["quality_status"] == "info"
    assert doc["global_features"]["top_hotspots"] == ["半导体", "通信设备"]
    assert doc["_meta"]["quality_status"] == "info"


def test_build_feature_snapshot_backfills_shanghai_finance_split_when_only_broad_finance(monkeypatch) -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-07", "2026-04-08"]),
            "close": [10, 10.1, 10.2, 10.3, 10.4, 10.5],
            "volume": [1, 2, 3, 4, 5, 6],
        }
    )

    monkeypatch.setattr("src.features.six_index_features.next_trading_day", lambda trade_date: "2026-04-09")
    monkeypatch.setattr(
        "src.features.six_index_features.tool_fetch_sector_data",
        lambda **kwargs: {
            "success": True,
            "all_data": [
                {"sector_name": "金融行业", "change_percent": 1.0},
                {"sector_name": "石油石化", "change_percent": 0.5},
            ],
        },
    )
    monkeypatch.setattr("src.features.six_index_features.tool_fetch_northbound_flow", lambda **kwargs: {"success": True, "records": []})
    monkeypatch.setattr("src.features.six_index_features.tool_fetch_macro_snapshot", lambda **kwargs: {"success": True, "data": {}})
    monkeypatch.setattr(
        "src.features.six_index_features._limit_up_metrics",
        lambda trade_date: {
            "limit_up_count": 1,
            "limit_up_ratio_smallcap_proxy": 0.1,
            "limit_up_ratio_kc50_proxy": 0.05,
            "quality_status": "info",
            "degraded_reason": None,
        },
    )
    monkeypatch.setattr(
        "src.features.six_index_features._fund_flow_metrics",
        lambda: {"market_main_force_score": 0.1, "quality_status": "info", "degraded_reason": None},
    )
    monkeypatch.setattr(
        "src.features.six_index_features._style_spread_metrics",
        lambda: {"style_spread_percentile": 55.0, "quality_status": "info", "degraded_reason": None},
    )
    monkeypatch.setattr(
        "src.features.six_index_features._margin_change_metrics",
        lambda: {"margin_change_proxy": 0.12, "quality_status": "info", "degraded_reason": None},
    )
    monkeypatch.setattr(
        "src.features.six_index_features._hotspot_metrics",
        lambda trade_date: {
            "top_hotspots": ["金融科技"],
            "top_hotspot_score": 62.0,
            "snapshot": {"hotspots": []},
            "degraded_reason": None,
        },
    )
    monkeypatch.setattr(
        "src.features.six_index_features.load_kronos_signal",
        lambda index_code, feature_payload=None: {"kronos_available": False, "kronos_score": None, "degraded_reason": None},
    )
    monkeypatch.setattr("src.features.six_index_features._daily_df", lambda symbol, lookback_days=320: df)

    doc = build_feature_snapshot("2026-04-08")

    weights = doc["indices"]["000001"]["weight_sector_changes"]
    assert weights["bank"] == 0.55
    assert weights["non_bank_fin"] == 0.45
    assert round(weights["bank"] + weights["non_bank_fin"], 6) == 1.0
    assert doc["_meta"]["quality_status"] == "info"
