"""L4 报告附录：parity 归一化与开关行为（mock 插件调用）。"""

from __future__ import annotations

import os

from plugins.analysis import l4_report_attachment as lr


def test_strip_and_normalize_parity_removes_l4_and_times() -> None:
    core = "## 📊 标题\n\n正文一行。\n"
    l4 = lr.L4_MARKDOWN_HEADING + "\n\n| a | b |\n"
    blob = core + "\n**分析时间：** 2099-01-01 12:00:00\n" + l4 + "\n*分析完成时间：2099-01-01 12:01:00*\n"
    assert lr.L4_MARKDOWN_HEADING not in lr.normalize_core_markdown_for_parity(blob)
    assert "正文一行" in lr.normalize_core_markdown_for_parity(blob)
    assert "分析时间" not in lr.normalize_core_markdown_for_parity(blob)


def test_include_l4_snapshot_env() -> None:
    os.environ.pop("ASSISTANT_INCLUDE_L4_SNAPSHOT", None)
    assert lr.include_l4_snapshot() is True
    os.environ["ASSISTANT_INCLUDE_L4_SNAPSHOT"] = "0"
    assert lr.include_l4_snapshot() is False
    del os.environ["ASSISTANT_INCLUDE_L4_SNAPSHOT"]


def test_attach_respects_flag(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_INCLUDE_L4_SNAPSHOT", "0")
    rd: dict = {"report_type": "daily_market"}
    lr.attach_l4_snapshot_to_report_data(
        rd,
        symbols=["510300"],
        trade_date="2026-05-04",
        task_id="test",
    )
    assert "l4_snapshot" not in rd


def test_build_bundle_mocks(monkeypatch) -> None:
    def _fake_val(*, stock_code: str, trade_date: str = "") -> dict:
        return {"success": True, "data": {"confidence": 0.5}}

    def _fake_pe(*, stock_code: str, trade_date: str = "") -> dict:
        return {"success": True, "data": {"band_label": "mid"}}

    monkeypatch.setattr(
        "plugins.analysis.l4_data_tools.tool_l4_valuation_context",
        _fake_val,
    )
    monkeypatch.setattr(
        "plugins.analysis.l4_data_tools.tool_l4_pe_ttm_percentile",
        _fake_pe,
    )
    b = lr.build_l4_bundle_for_symbols(
        ["510300", "sh600519"],
        trade_date="2026-05-04",
        task_id="unit",
        run_id="rid",
    )
    meta = b.get("_meta") or {}
    assert meta.get("schema_name") == "report_l4_snapshot_attachment_v1"
    assert meta.get("quality_status") == "ok"
    md = lr.format_l4_appendix_markdown(b)
    assert lr.L4_MARKDOWN_HEADING in md
    assert "510300" in md
