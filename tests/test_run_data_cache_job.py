"""tool_run_data_cache_job：notify 分支与飞书 mock。"""

from __future__ import annotations

from unittest.mock import patch


def _summary_ok():
    return {
        "phase": "intraday_minute",
        "universe": {"index_codes": [], "etf_codes": [], "stock_codes": []},
        "steps": [{"tool": "index_minute", "success": True, "message": "ok"}],
    }


@patch("plugins.merged.send_feishu_notification.tool_send_feishu_notification")
@patch("src.data_cache_collection_core.run_data_cache_collection", return_value=_summary_ok())
def test_notify_false_does_not_call_feishu(mock_run, mock_feishu) -> None:
    from plugins.data_collection.run_data_cache_job import tool_run_data_cache_job

    out = tool_run_data_cache_job("intraday_minute", throttle_stock=True, notify=False)
    assert out["collection_success"] is True
    assert out["notify"] is False
    assert out["notify_result"] is None
    mock_feishu.assert_not_called()


@patch("plugins.merged.send_feishu_notification.tool_send_feishu_notification")
@patch("src.data_cache_collection_core.run_data_cache_collection", return_value=_summary_ok())
def test_notify_true_calls_feishu_once(mock_run, mock_feishu) -> None:
    mock_feishu.return_value = {"success": True, "message": "sent"}

    from plugins.data_collection.run_data_cache_job import tool_run_data_cache_job

    out = tool_run_data_cache_job("morning_daily", notify=True)
    assert mock_feishu.call_count == 1
    call_kw = mock_feishu.call_args[1]
    assert call_kw.get("notification_type") == "message"
    assert "早盘数据采集完成" in (call_kw.get("title") or "")
    assert out["success"] is True
    assert out["notify_result"]["success"] is True


@patch("plugins.merged.send_feishu_notification.tool_send_feishu_notification")
@patch("src.data_cache_collection_core.run_data_cache_collection")
def test_collection_fail_still_sends_feishu_degraded(mock_run, mock_feishu) -> None:
    mock_run.return_value = {
        "phase": "morning_daily",
        "universe": {},
        "steps": [{"tool": "index_historical", "success": False, "message": "boom"}],
    }
    mock_feishu.return_value = {"success": True, "message": "sent"}

    from plugins.data_collection.run_data_cache_job import tool_run_data_cache_job

    out = tool_run_data_cache_job("morning_daily", notify=True)
    assert out["collection_success"] is False
    mock_feishu.assert_called_once()
    body = mock_feishu.call_args[1].get("message") or ""
    assert "boom" in body or "降级" in body or "失败" in body
    assert out["success"] is False


@patch("plugins.merged.send_feishu_notification.tool_send_feishu_notification")
@patch("src.data_cache_collection_core.run_data_cache_collection", return_value=_summary_ok())
def test_notify_auto_morning(mock_run, mock_feishu) -> None:
    mock_feishu.return_value = {"success": False, "message": "no webhook"}

    from plugins.data_collection.run_data_cache_job import tool_run_data_cache_job

    out = tool_run_data_cache_job("morning_daily", notify=None)
    assert out["notify"] is True
    mock_feishu.assert_called_once()
    assert out["success"] is False


def test_invalid_job() -> None:
    from plugins.data_collection.run_data_cache_job import tool_run_data_cache_job

    out = tool_run_data_cache_job("bad_phase")
    assert out["success"] is False
    assert "invalid" in (out.get("error") or "").lower()
