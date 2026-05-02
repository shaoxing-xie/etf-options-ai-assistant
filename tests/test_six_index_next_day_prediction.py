from __future__ import annotations

from scripts.six_index_next_day_prediction import _notify_if_configured


def test_notify_if_configured_uses_openclaw_dingtalk_env(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK", raising=False)
    monkeypatch.delenv("DINGTALK_SECRET", raising=False)
    monkeypatch.setenv("OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL", "https://example.test/webhook")
    monkeypatch.setenv("OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET", "sec-example")

    captured = {}

    def _fake_send(**kwargs):
        captured.update(kwargs)
        return {"success": True, "message": "ok"}

    monkeypatch.setattr(
        "scripts.six_index_next_day_prediction.tool_send_dingtalk_message",
        _fake_send,
    )

    result = _notify_if_configured("hello")

    assert result["success"] is True
    assert captured["webhook_url"] == "https://example.test/webhook"
    assert captured["secret"] == "sec-example"
    assert captured["message"] == "hello"
