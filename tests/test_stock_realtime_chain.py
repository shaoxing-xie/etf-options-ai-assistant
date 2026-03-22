"""单测：A 股实时 Provider 链顺序与降级（不访问外网）。"""

from __future__ import annotations

import unittest
from unittest.mock import patch


class TestStockRealtimeChain(unittest.TestCase):
    @patch("plugins.data_collection.stock.fetch_realtime._fetch_realtime_akshare")
    @patch("plugins.data_collection.stock.fetch_realtime._fetch_realtime_tencent")
    @patch("plugins.data_collection.stock.fetch_realtime._fetch_bid_ask_em_single")
    @patch("plugins.data_collection.stock.fetch_realtime._fetch_realtime_mootdx")
    def test_prefers_mootdx(
        self,
        mock_mootdx,
        mock_bid,
        mock_tencent,
        mock_ak,
    ):
        from plugins.data_collection.stock.fetch_realtime import run_stock_realtime_chain

        mock_mootdx.return_value = [{"stock_code": "600000", "current_price": 1.0}]
        rows, src, _ = run_stock_realtime_chain(["600000"], include_depth=True)
        self.assertIsNotNone(rows)
        self.assertEqual(src, "mootdx")
        mock_bid.assert_not_called()
        mock_tencent.assert_not_called()
        mock_ak.assert_not_called()

    @patch("plugins.data_collection.stock.fetch_realtime._fetch_realtime_akshare")
    @patch("plugins.data_collection.stock.fetch_realtime._fetch_realtime_tencent")
    @patch("plugins.data_collection.stock.fetch_realtime._fetch_bid_ask_em_single")
    @patch("plugins.data_collection.stock.fetch_realtime._fetch_realtime_mootdx")
    def test_tencent_after_mootdx_fail(
        self,
        mock_mootdx,
        mock_bid,
        mock_tencent,
        mock_ak,
    ):
        from plugins.data_collection.stock.fetch_realtime import run_stock_realtime_chain

        mock_mootdx.return_value = None
        mock_bid.return_value = None
        mock_tencent.return_value = [{"stock_code": "600000", "current_price": 2.0}]
        rows, src, dbg = run_stock_realtime_chain(
            ["600000", "600519"], include_depth=True
        )
        self.assertIsNotNone(rows)
        self.assertEqual(src, "qt.gtimg.cn")
        mock_bid.assert_not_called()
        mock_ak.assert_not_called()
        self.assertIn("qt.gtimg.cn", dbg.get("attempted", []))


if __name__ == "__main__":
    unittest.main()
