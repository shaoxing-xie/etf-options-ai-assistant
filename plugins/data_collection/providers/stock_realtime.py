"""
A 股股票实时行情：Provider 链（与 `stock/fetch_realtime` 同实现，便于单测与文档 import）。

实现本体在 `plugins.data_collection.stock.fetch_realtime`，避免循环依赖。
"""

from plugins.data_collection.stock.fetch_realtime import (
    STOCK_REALTIME_CHAIN_ORDER,
    run_stock_realtime_chain,
)

__all__ = ["STOCK_REALTIME_CHAIN_ORDER", "run_stock_realtime_chain"]
