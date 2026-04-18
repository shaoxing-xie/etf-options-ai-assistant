"""Tavily 多 Key：429/432 时自动换下一枚。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_collect_tavily_api_keys_prefers_tavily_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEYS", "alpha,beta")
    for k in ("TAVILY_API_KEY", "ETF_TAVILY_API_KEY", "OPENCLAW_TAVILY_API_KEY", "TAVILY_KEY"):
        monkeypatch.delenv(k, raising=False)

    from plugins.utils.tavily_client import collect_tavily_api_keys

    assert collect_tavily_api_keys() == ["alpha", "beta"]


@patch("requests.post")
@patch("plugins.utils.tavily_client.collect_tavily_api_keys")
def test_tavily_post_search_retries_on_432(mock_keys: MagicMock, mock_post: MagicMock) -> None:
    mock_keys.return_value = ["bad", "good"]

    r432 = MagicMock()
    r432.ok = False
    r432.status_code = 432
    r432.json.return_value = {"detail": {"error": "quota"}}

    r200 = MagicMock()
    r200.ok = True
    r200.status_code = 200
    r200.json.return_value = {"answer": "ok", "results": []}

    mock_post.side_effect = [r432, r200]

    from plugins.utils.tavily_client import tavily_post_search

    out = tavily_post_search({"query": "x", "topic": "news", "max_results": 1}, timeout=5)
    assert out["success"] is True
    assert out["data"]["answer"] == "ok"
    assert mock_post.call_count == 2
