"""data_collection：Provider 链（双层降级）入口，供 OpenClaw 与单测。"""

from plugins.data_collection.providers.stock_realtime import (
    STOCK_REALTIME_CHAIN_ORDER,
    run_stock_realtime_chain,
)

__all__ = [
    "STOCK_REALTIME_CHAIN_ORDER",
    "run_stock_realtime_chain",
]
