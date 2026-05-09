from __future__ import annotations

import os
from unittest.mock import patch

from plugins.data_collection.futures.us_mini_index_futures_spot import (
    fetch_us_mini_index_future_spot,
)


def test_fetch_us_mini_es_prefers_em_then_symbol() -> None:
    idx_calls: list[str] = []

    def _fake_idx(**kwargs: object) -> dict:
        idx_calls.append("idx")
        return {"success": True, "data": [{"code": "ES=F", "price": 1.0, "change_pct": 0.1}]}

    with patch.dict(os.environ, {"ENABLE_EM_GLOBAL_FUTURES_SPOT": "1"}, clear=False), patch(
        "plugins.data_collection.futures.fetch_global_futures_spot_em.tool_fetch_global_futures_spot_em",
        return_value={
            "success": True,
            "data": {
                "rows": [
                    {
                        "代码": "ES00Y",
                        "名称": "小型标普当月连续",
                        "最新价": 5000.0,
                        "涨跌幅": 0.33,
                        "昨结": 4983.0,
                    }
                ],
            },
        },
    ), patch(
        "plugins.merged.fetch_index_data.tool_fetch_index_data",
        side_effect=_fake_idx,
    ):
        out = fetch_us_mini_index_future_spot("es", mode="production")

    assert out.get("status") == "ok"
    assert out.get("symbol") == "ES00Y"
    assert out.get("change_pct") == 0.33
    assert idx_calls == []
