from __future__ import annotations

from apps.chart_console.api.market_snapshot_build import (
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


def test_qdii_snapshot_structure(monkeypatch):
    def fake_yf(*_a, **_k):
        return (100.0, 1.0, 1.0, "yfinance")

    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *a, **k: fake_yf(),
    )

    doc = build_qdii_futures_snapshot("2026-04-25")
    assert doc.get("trade_date") == "2026-04-25"
    assert isinstance(doc.get("groups"), list)
    assert doc["_meta"]["schema_name"] == "qdii_futures_snapshot_v1"


def test_persist_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *a, **k: (1.0, 0.1, 1.0, "yfinance"),
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
            return None, None, None, "yfinance_empty"
        if sym == "^IDX":
            return 100.0, 1.0, 1.0, "yfinance"
        return None, None, None, "yfinance_empty"

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


def test_yf_hist_metrics_nan_is_treated_as_missing(monkeypatch):
    import math

    class _FakeHist:
        empty = False

        def __init__(self, closes):
            self._closes = closes
            self.index = [1] * len(closes)

        def __getitem__(self, _k):
            class _Series:
                def __init__(self, closes):
                    self._c = closes

                @property
                def iloc(self):
                    class _ILoc:
                        def __init__(self, closes):
                            self._c = closes

                        def __getitem__(self, idx):
                            return self._c[idx]

                    return _ILoc(self._c)

            return _Series(self._closes)

    class _FakeTicker:
        def __init__(self, _s):
            pass

        def history(self, **_k):
            return _FakeHist([1.0, math.nan])

    class _FakeYF:
        Ticker = _FakeTicker

    monkeypatch.setitem(__import__("sys").modules, "yfinance", _FakeYF())
    monkeypatch.setattr(
        "plugins.utils.proxy_env.proxy_env_for_source",
        lambda *_a, **_k: __import__("contextlib").nullcontext(),
    )
    from apps.chart_console.api.market_snapshot_build import _yf_hist_metrics

    last, ca, cp, tag = _yf_hist_metrics("X", {})
    assert last is None
    assert tag == "yfinance_nan"


def test_persist_l3_jsonl_append(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(
        "apps.chart_console.api.market_snapshot_build._yf_hist_metrics",
        lambda *a, **k: (1.0, 0.1, 1.0, "yfinance"),
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
