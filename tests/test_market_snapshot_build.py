from __future__ import annotations

import pytest

from apps.chart_console.api.market_snapshot_build import (
    _build_cn_index_items,
    build_global_market_snapshot,
    build_qdii_futures_snapshot,
    persist_qdii_futures_l3_events,
    persist_snapshot,
    _future_item,
    _meta_block,
)


def test_meta_block_has_required_keys():
    m = _meta_block(
        schema_name="global_market_snapshot_v1",
        task_id="global-market-snapshot",
        trade_date="2026-04-25",
        quality="ok",
        source_tools=["x"],
        lineage_refs=["y"],
    )
    for k in (
        "schema_name",
        "schema_version",
        "task_id",
        "run_id",
        "data_layer",
        "generated_at",
        "trade_date",
        "quality_status",
        "source_tools",
        "lineage_refs",
    ):
        assert k in m


def _patch_qdii_offline(monkeypatch, *, hist_return):
    """Mock 日线 + 日内，PR 门禁零外网。"""
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *a, **k: hist_return,
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_intraday_metrics",
        lambda *_a, **_k: (hist_return[0], hist_return[1], hist_return[2], "global_spot_intraday"),
    )


def test_qdii_snapshot_structure(monkeypatch):
    _patch_qdii_offline(monkeypatch, hist_return=(100.0, 1.0, 1.0, "global_hist_sina"))
    doc = build_qdii_futures_snapshot("2026-04-25")
    assert doc.get("trade_date") == "2026-04-25"
    assert isinstance(doc.get("groups"), list)
    assert doc["_meta"]["schema_name"] == "qdii_futures_snapshot_v1"


@pytest.mark.network
def test_qdii_snapshot_structure_network(monkeypatch):
    """走真实 global_spot（yfinance→FMP→sina）；仅 mock 日线以控口径。仅 ``-m network`` / 联网 job 跑。"""
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *a, **k: (100.0, 1.0, 1.0, "global_hist_sina"),
    )
    doc = build_qdii_futures_snapshot("2026-04-25")
    assert doc.get("trade_date") == "2026-04-25"
    assert isinstance(doc.get("groups"), list)
    assert doc["_meta"]["schema_name"] == "qdii_futures_snapshot_v1"


def test_persist_writes_file(tmp_path, monkeypatch):
    _patch_qdii_offline(monkeypatch, hist_return=(1.0, 0.1, 1.0, "global_hist_sina"))
    doc = build_qdii_futures_snapshot("2026-04-25")
    p = persist_snapshot(tmp_path, "qdii_futures_snapshot", "2026-04-25", doc)
    assert p.is_file()
    assert "groups" in p.read_text(encoding="utf-8")


@pytest.mark.network
def test_persist_writes_file_network(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *a, **k: (1.0, 0.1, 1.0, "global_hist_sina"),
    )
    doc = build_qdii_futures_snapshot("2026-04-25")
    p = persist_snapshot(tmp_path, "qdii_futures_snapshot", "2026-04-25", doc)
    assert p.is_file()
    assert "groups" in p.read_text(encoding="utf-8")


def test_future_item_does_not_use_index_fallback(monkeypatch):
    hist_calls = []
    intraday_calls = []

    def fake_yf(sym, _cfg, **_kwargs):
        hist_calls.append(sym)
        if sym == "NOFUT":
            return None, None, None, "global_hist_empty"
        if sym == "^IDX":
            return 100.0, 1.0, 1.0, "global_hist_sina"
        return None, None, None, "global_hist_empty"

    def fake_intraday(sym, _cfg, **_kwargs):
        intraday_calls.append(sym)
        return None, None, None, "yfinance_intraday_empty"

    monkeypatch.setattr("apps.chart_console.api.market_snapshot_build._yf_hist_metrics", fake_yf)
    monkeypatch.setattr("apps.chart_console.api.market_snapshot_build._yf_intraday_metrics", fake_intraday)
    it = _future_item(
        instrument_id="x",
        display_name="T",
        subtitle="s",
        symbols_try=["NOFUT"],
        cfg={},
        index_fallback=("^IDX", "idx"),
    )
    assert it["quality_status"] == "error"
    assert it["display_price_role"] == "future"
    assert it["instrument_code"] == "NOFUT"
    assert intraday_calls == ["NOFUT"]
    assert hist_calls == ["NOFUT"]


def test_future_item_global_spot_intraday_marked_minute_bar(monkeypatch):
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_intraday_metrics",
        lambda *_a, **_k: (100.0, 1.0, 1.0, "global_spot_intraday"),
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *_a, **_k: (None, None, None, "global_hist_empty"),
    )
    it = _future_item(
        instrument_id="future.nq",
        display_name="迷你纳指",
        subtitle="期指连续",
        symbols_try=["NQ=F"],
        cfg={},
    )
    assert it["last_price"] == 100.0
    assert it["data_semantics"] == "minute_bar"
    assert it["quality_status"] == "ok"
    assert it["source_id"] == "openclaw"


def test_cn_index_proxy_fallback_for_kc50_and_chinext50(monkeypatch):
    monkeypatch.setattr(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        lambda **_kwargs: {"success": True, "data": []},
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._cn_hist_metrics",
        lambda *_a, **_k: (None, None, None, "cn_hist_empty"),
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *_a, **_k: (None, None, None, "global_hist_empty"),
    )

    def fake_proxy(etf_code):
        if etf_code == "588080":
            return 1.23, 0.01, 0.82, "cn_proxy_etf"
        if etf_code == "159915":
            return 2.34, -0.02, -0.85, "cn_proxy_etf"
        return None, None, None, "cn_proxy_empty"

    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._cn_proxy_etf_metrics",
        fake_proxy,
    )

    items, _, _ = _build_cn_index_items("2026-04-30")
    by_code = {str(x.get("instrument_code")): x for x in items}
    kc50 = by_code["000688"]
    cyb50 = by_code["399673"]
    assert kc50["last_price"] == 1.23
    assert cyb50["last_price"] == 2.34
    assert kc50["quality_status"] == "degraded"
    assert cyb50["quality_status"] == "degraded"
    assert kc50["source_raw"].endswith("cn_proxy_etf:588080")
    assert cyb50["source_raw"].endswith("cn_proxy_etf:159915")


def test_yf_hist_metrics_plugin_hist_empty(monkeypatch):
    def fake_hist(*_a, **_k):
        return {"success": True, "data": []}

    monkeypatch.setattr(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        fake_hist,
    )
    from apps.chart_console.api.market_snapshot_build import _yf_hist_metrics

    last, ca, cp, tag = _yf_hist_metrics("^DJI", {})
    assert last is None
    assert tag == "global_hist_empty"


def test_yf_hist_metrics_plugin_hist_ok(monkeypatch):
    def fake_hist(*_a, **_k):
        return {"success": True, "data": [{"close": 100.0}, {"close": 101.0}]}

    monkeypatch.setattr(
        "plugins.data_collection.index.fetch_global_hist_sina.tool_fetch_global_index_hist_sina",
        fake_hist,
    )
    from apps.chart_console.api.market_snapshot_build import _yf_hist_metrics

    last, ca, cp, tag = _yf_hist_metrics("^DJI", {})
    assert last == 101.0
    assert ca is not None
    assert tag == "global_hist_sina"


def test_persist_l3_jsonl_append(tmp_path, monkeypatch):
    import json

    _patch_qdii_offline(monkeypatch, hist_return=(1.0, 0.1, 1.0, "global_hist_sina"))
    doc = build_qdii_futures_snapshot("2026-04-25")
    p1 = persist_qdii_futures_l3_events(tmp_path, "2026-04-25", doc)
    assert p1.is_file()
    lines1 = [ln for ln in p1.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines1) == 7
    row = json.loads(lines1[0])
    assert row["_meta"]["schema_name"] == "qdii_futures_quote_event_v1"
    assert row["_meta"]["data_layer"] == "L3"
    assert row["event_id"].endswith(":" + row["instrument_id"])
    assert isinstance(row["payload"], dict)
    persist_qdii_futures_l3_events(tmp_path, "2026-04-25", doc)
    lines2 = [ln for ln in p1.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines2) == 14


@pytest.mark.network
def test_persist_l3_jsonl_append_network(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *a, **k: (1.0, 0.1, 1.0, "global_hist_sina"),
    )
    doc = build_qdii_futures_snapshot("2026-04-25")
    p1 = persist_qdii_futures_l3_events(tmp_path, "2026-04-25", doc)
    assert p1.is_file()
    lines1 = [ln for ln in p1.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines1) == 7
    row = json.loads(lines1[0])
    assert row["_meta"]["schema_name"] == "qdii_futures_quote_event_v1"
    assert row["_meta"]["data_layer"] == "L3"
    assert row["event_id"].endswith(":" + row["instrument_id"])
    assert isinstance(row["payload"], dict)
    persist_qdii_futures_l3_events(tmp_path, "2026-04-25", doc)
    lines2 = [ln for ln in p1.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines2) == 14


def test_global_snapshot_includes_catalog_debug_when_env(monkeypatch):
    monkeypatch.setenv("OPTION_TRADING_ASSISTANT_DEBUG_PLUGIN_CATALOG", "1")
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._build_cn_index_items",
        lambda *_a, **_k: ([], "ok", []),
    )

    def fake_spot(symbols, retry_rounds=1):
        data = {
            "^HSI": {"code": "^HSI", "price": 1.0, "change": 0.0, "change_pct": 0.0, "source_id": "yfinance", "timestamp": "t"},
        }
        dbg = [
            {"catalog_merge": {"dataset_id": "global_index_spot"}, "active_priority": ["yfinance"], "index_codes": ",".join(symbols)}
        ]
        return ({k: v for k, v in data.items() if k in symbols}, ["tool_fetch_global_index_spot"], "ok", dbg)

    monkeypatch.setattr("apps.chart_console.api.market_snapshot_build._global_spot_map_with_retry", fake_spot)
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._build_future_item_from_spec",
        lambda spec, _cfg: {
            "instrument_id": spec["id"],
            "instrument_code": spec["try"][0],
            "display_name": spec["title"],
            "subtitle": spec["sub"],
            "category": "index_future",
            "last_price": 1.0,
            "change_abs": 0.0,
            "change_pct": 0.0,
            "display_price_role": "future",
            "quality_status": "ok",
            "degraded_reason": "",
            "source_id": "akshare",
            "source_raw": "akshare.futures_global_spot_em",
            "as_of": "2026-04-29T00:00:00Z",
            "data_semantics": "realtime_quote",
            "fetched_at": "2026-04-29T00:00:00Z",
            "freshness_age_sec": 0,
        },
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._future_item_a50_plugin_then_yf",
        lambda _cfg: {
            "instrument_id": "future.a50",
            "instrument_code": "CN=F",
            "display_name": "富时A50",
            "subtitle": "期指连续",
            "category": "index_future",
            "last_price": 1.0,
            "change_abs": 0.0,
            "change_pct": 0.0,
            "display_price_role": "future",
            "quality_status": "ok",
            "degraded_reason": "",
            "source_id": "openclaw",
            "source_raw": "futures_global_spot_em",
            "as_of": "2026-04-29T00:00:00Z",
            "data_semantics": "realtime_quote",
            "fetched_at": "2026-04-29T00:00:00Z",
            "freshness_age_sec": 0,
        },
    )

    doc = build_global_market_snapshot("2026-04-29")
    dbg = doc.get("_debug", {}).get("plugin_catalog", {}).get("global_index_spot", {})
    assert "apac_batches" in dbg and "us_eu_batches" in dbg
    assert dbg["apac_batches"] and dbg["apac_batches"][0].get("catalog_merge")


def test_global_snapshot_hscei_alias_mapping_without_cross_substitute(monkeypatch):
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._build_cn_index_items",
        lambda *_a, **_k: ([], "ok", []),
    )

    def fake_spot(symbols, retry_rounds=1):
        data = {
            "^HSI": {"code": "^HSI", "price": 25000.0, "change": 10.0, "change_pct": 0.04, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^HSCE": {"code": "^HSCE", "price": 9300.0, "change": 20.0, "change_pct": 0.2, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^N225": {"code": "^N225", "price": 39000.0, "change": 30.0, "change_pct": 0.08, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^KS11": {"code": "^KS11", "price": 2700.0, "change": 5.0, "change_pct": 0.18, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^AXJO": {"code": "^AXJO", "price": 7800.0, "change": 4.0, "change_pct": 0.05, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^STI": {"code": "^STI", "price": 3200.0, "change": 3.0, "change_pct": 0.09, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^BSESN": {"code": "^BSESN", "price": 74000.0, "change": 40.0, "change_pct": 0.05, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^TWII": {"code": "^TWII", "price": 21000.0, "change": 10.0, "change_pct": 0.05, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^DJI": {"code": "^DJI", "price": 40000.0, "change": 10.0, "change_pct": 0.03, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^IXIC": {"code": "^IXIC", "price": 16000.0, "change": 8.0, "change_pct": 0.05, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^GSPC": {"code": "^GSPC", "price": 5200.0, "change": 6.0, "change_pct": 0.06, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^FTSE": {"code": "^FTSE", "price": 8200.0, "change": 7.0, "change_pct": 0.08, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^GDAXI": {"code": "^GDAXI", "price": 18000.0, "change": 9.0, "change_pct": 0.05, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^FCHI": {"code": "^FCHI", "price": 7900.0, "change": 4.0, "change_pct": 0.05, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
            "^STOXX50E": {"code": "^STOXX50E", "price": 5000.0, "change": 5.0, "change_pct": 0.1, "source_id": "yfinance", "timestamp": "2026-04-29 08:00:00"},
        }
        return ({k: v for k, v in data.items() if k in symbols}, ["tool_fetch_global_index_spot"], "ok", [])

    monkeypatch.setattr("apps.chart_console.api.market_snapshot_build._global_spot_map_with_retry", fake_spot)
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._build_future_item_from_spec",
        lambda spec, _cfg: {
            "instrument_id": spec["id"],
            "instrument_code": spec["try"][0],
            "display_name": spec["title"],
            "subtitle": spec["sub"],
            "category": "index_future",
            "last_price": 1.0,
            "change_abs": 0.0,
            "change_pct": 0.0,
            "display_price_role": "future",
            "quality_status": "ok",
            "degraded_reason": "",
            "source_id": "akshare",
            "source_raw": "akshare.futures_global_spot_em",
            "as_of": "2026-04-29T00:00:00Z",
            "data_semantics": "realtime_quote",
            "fetched_at": "2026-04-29T00:00:00Z",
            "freshness_age_sec": 0,
        },
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._future_item_a50_plugin_then_yf",
        lambda _cfg: {
            "instrument_id": "future.a50",
            "instrument_code": "CN=F",
            "display_name": "富时A50",
            "subtitle": "期指连续",
            "category": "index_future",
            "last_price": 1.0,
            "change_abs": 0.0,
            "change_pct": 0.0,
            "display_price_role": "future",
            "quality_status": "ok",
            "degraded_reason": "",
            "source_id": "openclaw",
            "source_raw": "futures_global_spot_em",
            "as_of": "2026-04-29T00:00:00Z",
            "data_semantics": "realtime_quote",
            "fetched_at": "2026-04-29T00:00:00Z",
            "freshness_age_sec": 0,
        },
    )

    doc = build_global_market_snapshot("2026-04-29")
    apac = next(g for g in doc["groups"] if g["group_id"] == "global_index")["subgroups"][0]["items"]
    hscei = next(x for x in apac if x["instrument_id"] == "global.apac.HSCEI")
    assert hscei["last_price"] == 9300.0
    assert hscei["instrument_code"] == "^HSCE"
    assert hscei["source_id"] == "yfinance"


def test_global_snapshot_missing_keeps_error_no_snapshot_fallback(monkeypatch):
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._build_cn_index_items",
        lambda *_a, **_k: ([], "ok", []),
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._global_spot_map_with_retry",
        lambda symbols, retry_rounds=1: ({}, ["tool_fetch_global_index_spot"], "ok", []),
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._build_future_item_from_spec",
        lambda spec, _cfg: {
            "instrument_id": spec["id"],
            "instrument_code": spec["try"][0],
            "display_name": spec["title"],
            "subtitle": spec["sub"],
            "category": "index_future",
            "last_price": 1.0,
            "change_abs": 0.0,
            "change_pct": 0.0,
            "display_price_role": "future",
            "quality_status": "ok",
            "degraded_reason": "",
            "source_id": "akshare",
            "source_raw": "akshare.futures_global_spot_em",
            "as_of": "2026-04-29T00:00:00Z",
            "data_semantics": "realtime_quote",
            "fetched_at": "2026-04-29T00:00:00Z",
            "freshness_age_sec": 0,
        },
    )
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._future_item_a50_plugin_then_yf",
        lambda _cfg: {
            "instrument_id": "future.a50",
            "instrument_code": "CN=F",
            "display_name": "富时A50",
            "subtitle": "期指连续",
            "category": "index_future",
            "last_price": 1.0,
            "change_abs": 0.0,
            "change_pct": 0.0,
            "display_price_role": "future",
            "quality_status": "ok",
            "degraded_reason": "",
            "source_id": "openclaw",
            "source_raw": "futures_global_spot_em",
            "as_of": "2026-04-29T00:00:00Z",
            "data_semantics": "realtime_quote",
            "fetched_at": "2026-04-29T00:00:00Z",
            "freshness_age_sec": 0,
        },
    )

    doc = build_global_market_snapshot("2026-04-29")
    apac = next(g for g in doc["groups"] if g["group_id"] == "global_index")["subgroups"][0]["items"]
    hscei = next(x for x in apac if x["instrument_id"] == "global.apac.HSCEI")
    assert hscei["last_price"] is None
    assert hscei["quality_status"] == "error"
    assert "global_spot_missing:^HSCE|2828.HK" == hscei["degraded_reason"]
