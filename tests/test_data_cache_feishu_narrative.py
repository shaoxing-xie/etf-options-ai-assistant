"""feishu_notify_title_and_body_for_cache_job 中文叙述。"""

from __future__ import annotations

from src.data_cache_collection_core import feishu_notify_title_and_body_for_cache_job


def test_morning_narrative_success() -> None:
    summary = {
        "phase": "morning_daily",
        "universe": {
            "index_codes": ["000016", "000300"],
            "etf_codes": ["510050", "510300"],
            "stock_codes": ["600519"],
        },
        "steps": [{"tool": "etf_historical", "success": True, "message": "ok"}],
    }
    title, body = feishu_notify_title_and_body_for_cache_job(
        "morning_daily", summary, collection_ok=True
    )
    assert title == "早盘数据采集完成"
    assert "ETF日线已缓存2只基金" in body
    assert "指数日线2个代码" in body
    assert "600519" in body
    assert "全部写入 data/cache/" in body
    assert "状态：成功" in body


def test_title_override_prewarm() -> None:
    summary = {
        "phase": "morning_daily",
        "universe": {"index_codes": ["000300"], "etf_codes": [], "stock_codes": []},
        "steps": [{"tool": "index_historical", "success": True, "message": "ok"}],
    }
    title, body = feishu_notify_title_and_body_for_cache_job(
        "morning_daily",
        summary,
        collection_ok=True,
        title_override="轮动池预热补缓存完成",
    )
    assert title == "轮动池预热补缓存完成"
    assert "指数日线1个代码" in body


def test_morning_narrative_with_failure_step() -> None:
    summary = {
        "phase": "morning_daily",
        "universe": {"index_codes": ["000300"], "etf_codes": [], "stock_codes": []},
        "steps": [{"tool": "index_historical", "success": False, "message": "timeout"}],
    }
    title, body = feishu_notify_title_and_body_for_cache_job(
        "morning_daily", summary, collection_ok=False
    )
    assert title == "早盘数据采集完成"
    assert "状态：失败/降级" in body
    assert "index_historical" in body
    assert "timeout" in body
