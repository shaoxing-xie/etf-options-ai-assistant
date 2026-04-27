from __future__ import annotations

import pandas as pd
from unittest.mock import patch

from plugins.analysis.key_levels import tool_compute_index_key_levels


@patch("src.data_collector.fetch_index_daily_em")
def test_key_levels_filters_far_levels_prioritizes_near(mock_fetch) -> None:
    """
    关键位应优先输出近邻位，避免把远端历史极值直接当日内关键位。
    """
    closes = [4639.3721] * 59 + [4418.0]
    df = pd.DataFrame({"收盘": closes})
    mock_fetch.return_value = df

    out = tool_compute_index_key_levels(index_code="000300", max_gap_pct=0.03)
    assert out.get("success") is True
    data = out.get("data") or {}
    supports = data.get("support") or []

    # 4418 距离昨收约 4.8%，在 3% 门槛外，不应优先进入结果
    assert 4418.0 not in supports
    assert supports
