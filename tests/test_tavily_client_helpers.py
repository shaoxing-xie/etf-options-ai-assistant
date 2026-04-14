"""tavily_client 通用辅助（无网络）。"""

from plugins.utils.tavily_client import (
    DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS,
    parse_include_domains,
    tavily_pack_search_result_for_llm,
)


def test_parse_include_domains_list_and_default() -> None:
    d = parse_include_domains([], default=DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS)
    assert d == list(DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS)
    d2 = parse_include_domains(["ft.com", "wsj.com"], default=DEFAULT_FINANCE_NEWS_INCLUDE_DOMAINS)
    assert d2 == ["ft.com", "wsj.com"]


def test_parse_include_domains_csv() -> None:
    d = parse_include_domains("reuters.com, ft.com ,", default=None)
    assert d == ["reuters.com", "ft.com"]


def test_pack_search_result_for_llm_empty() -> None:
    assert tavily_pack_search_result_for_llm({}) == ""
    assert tavily_pack_search_result_for_llm({"success": False}) == ""


def test_pack_search_result_for_llm_merges_answer_and_results() -> None:
    r = {
        "success": True,
        "answer": "Summary line.",
        "raw": {
            "results": [
                {"title": "T1", "url": "https://a", "content": "Body one"},
            ]
        },
    }
    s = tavily_pack_search_result_for_llm(r, max_chars=5000)
    assert "Summary line" in s
    assert "T1" in s
    assert "https://a" in s
    assert "Body one" in s
