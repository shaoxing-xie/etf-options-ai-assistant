"""日报发送层与全球指数合并等本轮优化的单元自测（无长耗时网络/LLM）。"""

from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from plugins.notification.send_daily_report import (
    _build_opening_overnight_outer_lines,
    _build_opening_hot_sector_bullets,
    _build_policy_news_lines,
    _opening_should_emit_hxc_overnight_line,
    _flatten_md_headers_in_embedded_report_text,
    _normalize_daily_report_fields,
    _build_sector_rotation_lines,
    _build_daily_market_etf_universe_lines,
    _build_market_overview_lines,
    _build_northbound_lines,
    _build_a_share_market_flow_lines,
    _build_daily_capital_flow_topic_lines,
    _capital_flow_topic_substantive,
    _capital_flow_exec_summary_fragment,
    _coverage_semantic_present,
    _looks_like_completed_tool_json,
    _merge_extra_report_data_skipping_tool_arg_stubs,
    _normalize_daily_report_fields,
    _build_key_levels_lines,
    _maybe_autofill_cron_daily_market_p0,
    _assess_daily_report_completeness,
    _resolve_trend_fields,
)
from plugins.notification.send_dingtalk_message import _normalize_dingtalk_keyword_fragments
from plugins.data_collection.northbound import _board_net_from_summary_df, _generate_signal, tool_fetch_northbound_flow
from plugins.data_collection.index.fetch_global import fetch_global_index_spot


def test_flatten_md_headers_strips_hashes() -> None:
    s = "## 日频波动\n**标的**\n### 关键\n| a | b |"
    out = _flatten_md_headers_in_embedded_report_text(s)
    assert "##" not in out
    assert "· 日频波动" in out
    assert "· 关键" in out


def test_etf_universe_lines_from_realtime_list_not_top_level_message() -> None:
    """data 为 list 时不得把工具顶层 English message 当作唯一一行正文。"""
    rd = {
        "tool_fetch_etf_realtime": {
            "success": True,
            "message": "Successfully fetched ETF realtime data via stock_realtime (mootdx/TDX)",
            "data": [
                {
                    "code": "510300",
                    "name": "沪深300ETF",
                    "change_percent": 0.12,
                    "current_price": 4.65,
                }
            ],
            "count": 1,
        }
    }
    lines = _build_daily_market_etf_universe_lines(rd, {})
    joined = "\n".join(lines)
    assert "Successfully fetched" not in joined
    assert "510300" in joined
    assert "涨跌" in joined


def test_northbound_generate_signal_zero_is_neutral_not_micro_outflow() -> None:
    sig = _generate_signal({"total_net": 0.0}, None, 0)
    assert sig["strength"] == "neutral"
    assert "微幅流出" not in sig["description"]
    assert "披露口径" in sig["description"] or "沪深港通" in sig["description"]


def test_northbound_generate_signal_nan_is_unknown_not_strong_sell() -> None:
    sig = _generate_signal({"total_net": float("nan")}, None, 0)
    assert sig["strength"] == "unknown"
    assert "大幅流出" not in sig["description"]
    assert "不可用" in sig["description"]


def test_build_northbound_lines_nan_skips_misleading_signal() -> None:
    rd = {
        "northbound": {
            "status": "success",
            "date": "2026-04-10",
            "data": {"total_net": float("nan")},
            "signal": {"description": "大幅流出（>50亿），强烈风险信号"},
        }
    }
    lines = _build_northbound_lines(rd)
    joined = "\n".join(lines)
    assert "大幅流出" not in joined
    assert "暂不可用" in joined


def test_capital_flow_topic_substantive_with_sector_blocks() -> None:
    rd = {
        "a_share_capital_flow_sector_industry": {
            "success": True,
            "query_kind": "sector_rank",
            "records": [{"名称": "银行", "净额": 1.2}],
        }
    }
    assert _capital_flow_topic_substantive(rd) is True


def test_build_daily_capital_flow_topic_with_industry_and_concept() -> None:
    rd = {
        "a_share_capital_flow_market_history": {
            "success": True,
            "query_kind": "market_history",
            "source": "test",
            "records": [{"日期": "2026-04-10", "主力净流入-净额": -46183145472.0}],
        },
        "a_share_capital_flow_sector_industry": {
            "success": True,
            "query_kind": "sector_rank",
            "params_echo": {"em_indicator": "今日"},
            "records": [
                {"名称": "半导体", "今日主力净流入-净额": 120000000.0},
                {"名称": "银行", "今日主力净流入-净额": -50000000.0},
            ],
        },
        "a_share_capital_flow_sector_concept": {
            "success": True,
            "query_kind": "sector_rank",
            "params_echo": {"em_indicator": "今日"},
            "records": [
                {"名称": "人工智能", "今日主力净流入-净额": 80000000.0},
                {"名称": "ST板块", "今日主力净流入-净额": -30000000.0},
            ],
        },
    }
    lines = _build_daily_capital_flow_topic_lines(rd)
    joined = "\n".join(lines)
    assert "全市场大盘" in joined
    assert "-461.83" in joined
    assert "一、行业板块" in joined
    assert "二、概念板块" in joined
    assert "半导体" in joined
    assert "人工智能" in joined


def test_build_northbound_zero_single_paragraph_no_duplicate_signal() -> None:
    rd = {
        "northbound": {
            "status": "success",
            "date": "2026-04-10",
            "data": {"total_net": 0.0},
            "signal": {
                "description": "沪深港通成交净买额汇总为 0（常见为披露口径或当日无净买分量；勿解读为方向性「流出」）"
            },
        }
    }
    lines = _build_northbound_lines(rd)
    assert len(lines) == 1
    assert "见下条" not in lines[0]
    assert "0.00" in lines[0]
    assert "披露口径" not in "\n".join(lines)


def test_build_a_share_market_flow_line_from_tool_block() -> None:
    rd = {
        "tool_fetch_a_share_fund_flow": {
            "success": True,
            "query_kind": "market_history",
            "source": "eastmoney_http.push2his",
            "records": [{"日期": "2026-04-10", "主力净流入-净额": -46183145472.0}],
        }
    }
    lines = _build_a_share_market_flow_lines(rd)
    assert len(lines) == 1
    assert "-461.83" in lines[0]
    assert "主力净流入" in lines[0]


def test_capital_flow_topic_substantive_false_when_no_blocks() -> None:
    assert _capital_flow_topic_substantive({}) is False
    assert _capital_flow_topic_substantive({"a_share_capital_flow_sector_industry": {"success": False}}) is False


def test_capital_flow_topic_substantive_true_market_history_only() -> None:
    rd = {
        "a_share_capital_flow_market_history": {
            "success": True,
            "query_kind": "market_history",
            "records": [{"日期": "2026-04-10", "主力净流入-净额": 1e9}],
        }
    }
    assert _capital_flow_topic_substantive(rd) is True


def test_capital_flow_reads_blocks_from_nested_analysis() -> None:
    rd = {
        "analysis": {
            "a_share_capital_flow_sector_concept": {
                "success": True,
                "query_kind": "sector_rank",
                "params_echo": {"em_indicator": "今日"},
                "records": [{"名称": "芯片概念", "净额": 2.5}],
            }
        }
    }
    assert _capital_flow_topic_substantive(rd) is True
    frag = _capital_flow_exec_summary_fragment(rd)
    assert frag is not None
    assert "概念" in frag or "芯片" in frag


def test_capital_flow_market_history_prefers_dedicated_key_over_tool_fetch() -> None:
    """专用键与 tool_fetch 并存时优先用 a_share_capital_flow_market_history。"""
    rd = {
        "a_share_capital_flow_market_history": {
            "success": True,
            "query_kind": "market_history",
            "source": "primary",
            "records": [{"日期": "2026-04-11", "主力净流入-净额": 0.0}],
        },
        "tool_fetch_a_share_fund_flow": {
            "success": True,
            "query_kind": "market_history",
            "source": "ignored",
            "records": [{"日期": "2026-04-10", "主力净流入-净额": -1e9}],
        },
    }
    lines = _build_a_share_market_flow_lines(rd)
    assert len(lines) == 1
    assert "2026-04-11" in lines[0]
    assert "primary" in lines[0]


def test_build_daily_capital_flow_topic_skips_non_market_tool_fetch() -> None:
    rd = {
        "tool_fetch_a_share_fund_flow": {
            "success": True,
            "query_kind": "sector_rank",
            "records": [{"名称": "x"}],
        }
    }
    lines = _build_daily_capital_flow_topic_lines(rd)
    joined = "\n".join(lines)
    assert "全市场大盘" not in joined
    assert "暂未拉取" in joined or "openclaw-data-china-stock" in joined


def test_build_daily_capital_flow_sector_small_net_treated_as_yi() -> None:
    """同花顺式小数值（已为亿元量级）不再除以 1e8。"""
    rd = {
        "a_share_capital_flow_sector_industry": {
            "success": True,
            "query_kind": "sector_rank",
            "params_echo": {"em_indicator": "今日"},
            "records": [{"名称": "银行", "净额": 1.25}],
        }
    }
    lines = _build_daily_capital_flow_topic_lines(rd)
    joined = "\n".join(lines)
    assert "+1.25亿" in joined or "1.25亿" in joined


def test_build_daily_capital_flow_bottom_three_order() -> None:
    rd = {
        "a_share_capital_flow_sector_industry": {
            "success": True,
            "query_kind": "sector_rank",
            "params_echo": {"em_indicator": "今日"},
            "records": [
                {"名称": "A", "净额": 3.0},
                {"名称": "B", "净额": 2.0},
                {"名称": "C", "净额": 1.0},
                {"名称": "D", "净额": -1.0},
                {"名称": "E", "净额": -2.0},
                {"名称": "F", "净额": -3.0},
            ],
        }
    }
    lines = _build_daily_capital_flow_topic_lines(rd)
    joined = "\n".join(lines)
    assert "净流入居前" in joined
    assert "净流入靠后" in joined
    # 排名表末行应最先出现在「靠后」摘要（F 最差）
    pos_f = joined.find("F")
    pos_e = joined.find("E", pos_f)
    assert pos_f != -1 and pos_e != -1


def test_coverage_semantic_capital_flow_topic() -> None:
    rd = {
        "a_share_capital_flow_market_history": {
            "success": True,
            "query_kind": "market_history",
            "records": [{"日期": "2026-04-10", "主力净流入-净额": 1.0}],
        }
    }
    assert _coverage_semantic_present("capital_flow_topic", rd, {}) is True
    assert _coverage_semantic_present("northbound", rd, {}) is True
    assert _coverage_semantic_present("northbound_flow", rd, {}) is True


def test_assess_daily_completeness_lists_capital_flow_when_absent() -> None:
    """空报告应把资金流向专题列入缺失（与其它维度一起）。"""
    degraded, missing = _assess_daily_report_completeness({}, {})
    assert degraded is True
    assert any("资金流向专题" in m for m in missing)


def test_capital_flow_exec_summary_market_over_sector() -> None:
    rd = {
        "a_share_capital_flow_market_history": {
            "success": True,
            "query_kind": "market_history",
            "source": "m",
            "records": [{"日期": "2026-04-10", "主力净流入-净额": 5e8}],
        },
        "a_share_capital_flow_sector_industry": {
            "success": True,
            "query_kind": "sector_rank",
            "records": [{"名称": "煤炭", "净额": 9.0}],
        },
    }
    frag = _capital_flow_exec_summary_fragment(rd)
    assert frag is not None
    assert "全市场大盘" in frag or "主力净流入" in frag


def test_board_net_from_summary_prefers_northbound_row() -> None:
    df = pd.DataFrame(
        [
            {"板块": "沪股通", "资金方向": "北向", "成交净买额": 1.5},
            {"板块": "沪股通", "资金方向": "其他", "成交净买额": 99.0},
        ]
    )
    assert abs(_board_net_from_summary_df(df, "沪股通") - 1.5) < 1e-9


@patch("plugins.data_collection.northbound.ak")
def test_northbound_hist_fallback_when_summary_zero(mock_ak: MagicMock) -> None:
    mock_ak.stock_hsgt_fund_flow_summary_em.return_value = pd.DataFrame(
        [
            {
                "板块": "沪股通",
                "资金方向": "北向",
                "成交净买额": 0.0,
                "交易日": pd.Timestamp("2026-04-10"),
            },
            {
                "板块": "深股通",
                "资金方向": "北向",
                "成交净买额": 0.0,
                "交易日": pd.Timestamp("2026-04-10"),
            },
        ]
    )
    mock_ak.stock_hsgt_hist_em.side_effect = [
        pd.DataFrame(
            [
                {"日期": "2026-04-09", "当日成交净买额": 10.0},
                {"日期": "2026-04-10", "当日成交净买额": 5.5},
            ]
        ),
        pd.DataFrame(
            [
                {"日期": "2026-04-09", "当日成交净买额": -2.0},
                {"日期": "2026-04-10", "当日成交净买额": 3.2},
            ]
        ),
    ]
    r = tool_fetch_northbound_flow(lookback_days=1)
    assert r.get("status") == "success"
    assert abs(float(r["data"]["total_net"]) - 8.7) < 0.01
    assert "hist_em_fallback" in str(r.get("source") or "")


def test_dingtalk_keyword_orphan_bracket_stripped() -> None:
    assert _normalize_dingtalk_keyword_fragments("监控】") == "【监控】"
    assert _normalize_dingtalk_keyword_fragments("【监控") == "【监控】"
    assert _normalize_dingtalk_keyword_fragments("监控") == "【监控】"
    assert _normalize_dingtalk_keyword_fragments("【监控】") == "【监控】"
    assert _normalize_dingtalk_keyword_fragments(None) is None


@patch("plugins.data_collection.index.fetch_global._fetch_sina")
@patch("plugins.data_collection.index.fetch_global._fetch_yfinance")
def test_fetch_global_sina_fallback_maps_to_yf_symbols(
    mock_yf: MagicMock, mock_sina: MagicMock
) -> None:
    """yf 全败时新浪兜底行应映射为 ^DJI 等 yfinance 符号。"""
    mock_yf.return_value = {"success": False, "data": [], "fetch_failures": []}
    mock_sina.return_value = {
        "success": True,
        "data": [
            {
                "code": "int_dji",
                "name": "道琼斯",
                "price": 40000.0,
                "change": 1.0,
                "change_pct": 0.01,
                "timestamp": "t",
            }
        ],
        "source": "hq.sinajs.cn",
    }
    r = fetch_global_index_spot("^DJI")
    assert r.get("success") is True
    rows = r.get("data") or []
    assert len(rows) >= 1
    assert rows[0].get("code") == "^DJI"


def test_extra_report_data_stub_does_not_overwrite_tool_blob() -> None:
    """Agent 误传 {index_codes:...} 不得覆盖已有 tool_fetch_global_index_spot 完整返回。"""
    good = {
        "success": True,
        "count": 3,
        "data": [
            {"code": "^DJI", "name": "道琼斯", "price": 1.0, "change_pct": 0.1},
        ],
    }
    rd: dict = {"tool_fetch_global_index_spot": good}
    extra = {"tool_fetch_global_index_spot": {"index_codes": "^HSI,^DJI"}}
    skipped = _merge_extra_report_data_skipping_tool_arg_stubs(rd, extra)
    assert "tool_fetch_global_index_spot" in skipped
    assert rd["tool_fetch_global_index_spot"] is good


def test_looks_like_completed_tool_json() -> None:
    assert _looks_like_completed_tool_json("tool_fetch_policy_news", {"max_items": 5}) is False
    assert _looks_like_completed_tool_json("tool_fetch_policy_news", {"success": True, "data": {}}) is True
    assert _looks_like_completed_tool_json("report_meta", {"foo": 1}) is True


@patch("plugins.data_collection.index.fetch_global.fetch_global_index_spot")
def test_p0_syncs_global_index_spot_when_refetch(mock_fetch: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """P0 补拉全球指数后 global_index_spot 应与 tool_fetch 同源，避免与首次 ingest 残留不一致。"""
    monkeypatch.delenv("DAILY_REPORT_DISABLE_CRON_P0_AUTOFILL", raising=False)
    rich = {"success": True, "data": [{"code": "^DJI"}, {"code": "^GSPC"}, {"code": "^IXIC"}]}
    mock_fetch.return_value = rich
    rd = {
        "report_type": "daily_market",
        "tool_fetch_global_index_spot": {"success": True, "data": [{"code": "^HSI"}]},
        "global_index_spot": {"success": True, "data": [{"code": "^HSI"}]},
    }
    _maybe_autofill_cron_daily_market_p0(rd)
    assert rd.get("cron_p0_autofill_global_index") is True
    assert rd.get("global_index_spot") is rich
    assert rd.get("tool_fetch_global_index_spot") is rich


@patch("plugins.analysis.key_levels.tool_compute_index_key_levels")
def test_normalize_autofills_key_levels_when_empty(mock_kl: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """发送层归一化：无关键位时补算 tool_compute_index_key_levels。"""
    monkeypatch.setenv("DAILY_REPORT_DISABLE_VOLATILITY_AUTOFILL", "1")
    monkeypatch.setenv("DAILY_REPORT_DISABLE_ETF_REALTIME_AUTOFILL", "1")
    monkeypatch.setenv("DAILY_REPORT_DISABLE_GLOBAL_TAVILY_LLM", "1")
    mock_kl.return_value = {
        "success": True,
        "data": {
            "index_code": "000300",
            "last_close": 4000.0,
            "support": [3900.0],
            "resistance": [4100.0],
        },
    }
    rd = {"report_type": "daily_market", "overall_trend": "中性", "trend_strength": 0.5}
    out, _ = _normalize_daily_report_fields(rd, {})
    assert out.get("key_levels_fill_source") == "send_layer_autofill"
    assert _build_key_levels_lines(out)


@patch("plugins.data_collection.index.fetch_global._fetch_sina")
@patch("plugins.data_collection.index.fetch_global._fetch_yfinance")
def test_fetch_global_merges_sina_when_yf_partial(
    mock_yf: MagicMock, mock_sina: MagicMock
) -> None:
    """yf 仅命中部分指数时，对缺失映射符号补新浪并合并。"""
    mock_yf.return_value = {
        "success": True,
        "data": [
            {
                "code": "^HSI",
                "name": "恒生指数",
                "price": 26000.0,
                "change": 1.0,
                "change_pct": 0.5,
                "timestamp": "t",
            }
        ],
        "fetch_failures": [{"code": "^DJI", "reason": "fail"}],
    }
    mock_sina.return_value = {
        "success": True,
        "data": [
            {
                "code": "int_dji",
                "name": "道琼斯",
                "price": 39000.0,
                "change": 0.5,
                "change_pct": 0.1,
                "timestamp": "t",
            }
        ],
        "source": "hq.sinajs.cn",
    }
    r = fetch_global_index_spot("^DJI,^HSI")
    assert r.get("success") is True
    codes = {row.get("code") for row in (r.get("data") or []) if isinstance(row, dict)}
    assert "^HSI" in codes
    assert "^DJI" in codes


@patch("plugins.data_collection.index.fetch_global._eastmoney_global_spot_by_em_code")
@patch("plugins.data_collection.index.fetch_global._fetch_sina")
@patch("plugins.data_collection.index.fetch_global._fetch_yfinance")
def test_fetch_global_eastmoney_fills_missing_when_yf_only_hsi(
    mock_yf: MagicMock, mock_sina: MagicMock, mock_em: MagicMock
) -> None:
    """Yahoo 限流常见仅恒生有数：东财一次补全 DJI/SPX/NDX 等无新浪映射符号。"""
    mock_sina.return_value = {"success": False, "data": []}
    mock_yf.return_value = {
        "success": True,
        "data": [
            {
                "code": "^HSI",
                "name": "恒生指数",
                "price": 26000.0,
                "change": 10.0,
                "change_pct": 0.55,
                "timestamp": "t",
            }
        ],
        "source": "yfinance",
        "fetch_failures": [{"code": "^DJI", "reason": "Too Many Requests"}],
    }
    mock_em.return_value = {
        "DJIA": {
            "name": "道琼斯",
            "price": 40000.0,
            "change": 1.0,
            "change_pct": 1.2,
            "prev_close": 39999.0,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
        "SPX": {
            "name": "标普500指数",
            "price": 5000.0,
            "change": 0.5,
            "change_pct": 0.81,
            "prev_close": None,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
        "NDX": {
            "name": "纳斯达克",
            "price": 18000.0,
            "change": -5.0,
            "change_pct": -0.31,
            "prev_close": None,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
        "N225": {
            "name": "日经225",
            "price": 38000.0,
            "change": 100.0,
            "change_pct": 0.25,
            "prev_close": None,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
        "KS11": {
            "name": "韩国KOSPI",
            "price": 2600.0,
            "change": 1.0,
            "change_pct": 0.15,
            "prev_close": None,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
        "GDAXI": {
            "name": "德国DAX",
            "price": 18000.0,
            "change": 20.0,
            "change_pct": 0.4,
            "prev_close": None,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
        "SX5E": {
            "name": "欧洲斯托克50",
            "price": 4800.0,
            "change": 10.0,
            "change_pct": 0.2,
            "prev_close": None,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
        "FTSE": {
            "name": "英国富时100",
            "price": 8000.0,
            "change": 5.0,
            "change_pct": 0.11,
            "prev_close": None,
            "timestamp": "t2",
            "source_detail": "eastmoney_global_spot_em",
        },
    }
    codes = "^DJI,^GSPC,^IXIC,^N225,^HSI,^KS11,^GDAXI,^STOXX50E,^FTSE"
    r = fetch_global_index_spot(codes)
    assert r.get("success") is True
    assert "eastmoney" in str(r.get("source") or "").lower()
    by = {row["code"]: row for row in (r.get("data") or []) if isinstance(row, dict)}
    assert by["^HSI"].get("change_pct") == 0.55
    assert by["^DJI"].get("change_pct") == 1.2
    assert by["^GSPC"].get("change_pct") == 0.81
    assert by["^IXIC"].get("change_pct") == -0.31
    assert by["^KS11"].get("change_pct") == 0.15
    assert by["^GDAXI"].get("change_pct") == 0.4
    assert by["^STOXX50E"].get("change_pct") == 0.2
    assert by["^FTSE"].get("change_pct") == 0.11


def test_market_overview_tavily_summary_replaces_na_grid() -> None:
    """Tavily 摘要-only：用综述覆盖「外盘/指数概览」，不出现 日经 N/A 长串。"""
    rd = {
        "global_market_digest": {
            "summary": "美股三大指数集体收涨，亚欧市场分化。",
            "source": "tavily_llm_prose",
            "replaces_index_overview": True,
        },
        "global_index_spot": {
            "success": True,
            "data": [
                {"code": "^N225", "name": "日经225", "change_pct": None},
                {"code": "^HSI", "name": "恒生指数", "change_pct": 0.55},
            ],
        },
    }
    lines = _build_market_overview_lines(rd)
    joined = "\n".join(lines)
    assert "日经225: N/A" not in joined
    assert "美股三大指数" in joined
    assert "检索摘要归纳" in joined


def test_sector_rotation_skip_hot_sectors_points_to_etf_section() -> None:
    """无 sector_rotation 数据且 skip 时：不重复 dump config/hot_sectors，引导读主要 ETF。"""
    out = _build_sector_rotation_lines({}, skip_hot_sectors_fallback=True)
    assert len(out) == 1
    assert "主要 ETF" in out[0]
    assert "hot_sectors" not in out[0].lower()


def test_normalize_promotes_overlay_sector_heat_to_sector_rotation() -> None:
    """盘后 overlay.sector_heat（与 tool_sector_heat_score 同形）应并入 sector_rotation，板块节可展示。"""
    rd: dict = {}
    an = {
        "daily_report_overlay": {
            "sector_heat": {
                "success": True,
                "date": "20260410",
                "sectors": [{"name": "电池", "score": 60, "limit_up_count": 3, "phase": "启动"}],
            }
        }
    }
    out_rd, _ = _normalize_daily_report_fields(rd, an)
    sr = out_rd.get("sector_rotation")
    assert isinstance(sr, dict)
    assert sr.get("sectors") and sr["sectors"][0].get("name") == "电池"


def test_sector_rotation_prefers_heat_over_config() -> None:
    rd = {
        "sector_rotation": {
            "sectors": [
                {"name": "半导体", "score": 88.0, "limit_up_count": 3, "phase": "主升"},
            ]
        }
    }
    out = _build_sector_rotation_lines(rd, skip_hot_sectors_fallback=True)
    assert any("半导体" in ln for ln in out)


def test_policy_news_opening_prefers_cn_brief_when_tavily_english() -> None:
    rd = {
        "policy_news": {
            "brief_answer": "Based on the most recent data, China's macroeconomic policies have been focused on maintaining economic resilience amid global inflation expectations and regulatory measures.",
            "items": [
                {"title": "【财闻联播】闪迪将跻身纳指100", "url": "http://x"},
                {"title": "5%→10%！A股交易规则拟调整", "url": "http://y"},
            ],
        }
    }
    lines = _build_policy_news_lines(rd, brief_max=220, opening_prefer_cn_brief=True)
    assert lines and lines[0].startswith("提要：综合要点（据下列中文来源标题）")
    assert "闪迪" in lines[0] or "财闻" in lines[0]
    assert "Based on" not in lines[0]


def test_build_opening_overnight_outer_lines_structured() -> None:
    rd = {
        "global_index_spot": {
            "success": True,
            "data": [
                {"code": "^DJI", "name": "道琼斯", "change_pct": 0.1},
                {"code": "^GSPC", "name": "标普500", "change_pct": 0.05},
                {"code": "^N225", "name": "日经225", "change_pct": -0.2},
                {"code": "^KS11", "name": "韩国综合", "change_pct": 0.03},
            ],
        }
    }
    lines = _build_opening_overnight_outer_lines(rd)
    assert any("美股（隔夜）" in ln for ln in lines)
    assert any("日/韩（当日开盘）" in ln for ln in lines)


def test_build_opening_overnight_outer_lines_tavily_summary_override() -> None:
    rd = {
        "global_market_digest": {
            "summary": "美股收涨，亚太早盘偏强。",
            "replaces_index_overview": True,
        }
    }
    lines = _build_opening_overnight_outer_lines(rd)
    assert lines and "美股收涨" in lines[0]
    assert "每日市场分析报告" in lines[1]


def test_opening_hxc_line_hidden_on_hard_failure() -> None:
    assert _opening_should_emit_hxc_overnight_line("获取失败（历史数据为空）") is False
    assert _opening_should_emit_hxc_overnight_line("获取失败") is False
    assert _opening_should_emit_hxc_overnight_line("+0.35%") is True
    assert _opening_should_emit_hxc_overnight_line("检索摘要：金龙隔夜走弱") is True


def test_opening_hot_sector_bullets_no_double_hyphen() -> None:
    rd = {
        "tool_sector_heat_score": {
            "success": True,
            "sectors": [{"name": "汽车零部", "score": 60.0, "limit_up_count": 5, "phase": "发酵"}],
        }
    }
    lines = _build_opening_hot_sector_bullets(rd)
    assert lines[0] == "- **板块热度（涨跌停侧）**"
    assert lines[1].startswith("- 汽车零部")
    assert not any(ln.startswith("- -") for ln in lines)


def test_resolve_trend_fields_opening_from_strong_weak_counts_only() -> None:
    """原系统开盘 summary 无 market_sentiment，仅有 strong_count/weak_count 时也应出结论。"""
    an = {
        "summary": {"strong_count": 2, "weak_count": 1, "neutral_count": 0, "total_count": 3},
        "report_meta": {
            "key_metrics": {
                "summary": {
                    "strong_count": 2,
                    "weak_count": 1,
                    "neutral_count": 0,
                    "total_count": 3,
                }
            }
        },
    }
    ot, ts = _resolve_trend_fields({}, an)
    assert ot == "偏强"
    assert ts is not None and abs(float(ts) - (1 / 3)) < 1e-6
