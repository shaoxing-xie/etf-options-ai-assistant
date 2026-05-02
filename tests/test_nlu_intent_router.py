from __future__ import annotations

from plugins.nlu.intent_router import tool_nlu_query


def test_nlu_routes_hotspot(monkeypatch) -> None:
    monkeypatch.setattr(
        "plugins.nlu.intent_router.call_data_plugin_tool",
        lambda tool_name, args: {"success": True, "hotspots": [{"name": "半导体"}]},
    )
    out = tool_nlu_query("今天什么板块最热")
    assert out["intent"] == "hotspot"
    assert out["success"] is True


def test_nlu_routes_index_prediction(monkeypatch) -> None:
    monkeypatch.setattr("plugins.nlu.intent_router.build_feature_snapshot", lambda: {"trade_date": "2026-04-29"})
    monkeypatch.setattr(
        "plugins.nlu.intent_router.predict_all",
        lambda doc: {"trade_date": "2026-04-29", "predictions": [{"index_code": "000300.SH", "direction": "up"}]},
    )
    out = tool_nlu_query("沪深300明天怎么看")
    assert out["intent"] == "index_prediction"
    assert out["success"] is True
    assert out["result"]["prediction"]["index_code"] == "000300.SH"


def test_nlu_unknown_intent() -> None:
    out = tool_nlu_query("今天天气怎么样")
    assert out["intent"] == "unknown"
    assert out["success"] is False
    assert isinstance(out.get("examples"), list)
