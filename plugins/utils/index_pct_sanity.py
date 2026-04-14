"""
指数涨跌幅口径修正：行情源偶发把「涨跌额(点)」写入涨跌幅列，或把小数形式(-0.01)当百分比。

在同时有现价/昨收时，优先用 (价 - 昨收) / 昨收 * 100 与原始列比对，显著不一致则采用计算值。
"""

from __future__ import annotations

from typing import Any, Optional


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        if isinstance(v, str) and not v.strip():
            return None
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def reconcile_index_change_pct(
    change_pct: Any,
    price: Any,
    pre_close: Any,
    *,
    max_sane_abs_pct: float = 18.0,
) -> Optional[float]:
    """
    返回「应展示的涨跌幅(%)」：与 A 股主要指数常见波动一致时信任价格重算。

    Args:
        change_pct: 源数据中的涨跌幅字段（可能为点、小数或已是百分比）
        price: 现价 / 今开 / 最新价
        pre_close: 昨收
        max_sane_abs_pct: 超过此阈仍保留原始值（避免极端行情误杀），除非与计算值严重矛盾
    """
    raw = _to_float(change_pct)
    px = _to_float(price)
    pc = _to_float(pre_close)

    if pc is None or pc <= 0 or px is None or px <= 0:
        return raw

    computed = (px - pc) / pc * 100.0

    if raw is None:
        return computed

    # 已一致（0.1 个百分点内）
    if abs(raw - computed) <= 0.1:
        return raw

    # 源为小数形式（如 -0.01 表示 -1%）
    if abs(raw) <= 1.0 and abs(computed) >= 0.8:
        scaled = raw * 100.0
        if abs(scaled - computed) <= max(0.15, 0.05 * abs(computed)):
            return scaled
        if abs(scaled - computed) < abs(raw - computed):
            return scaled

    # 源像「点数」：如 -39 点 vs 计算约 -1%
    if abs(computed) <= max_sane_abs_pct and abs(raw) > max(5.5, 2.5 * max(abs(computed), 0.35)):
        return computed

    # 一般性大幅偏离：计算值在合理区间则采信价格
    if abs(computed) <= max_sane_abs_pct * 1.25 and abs(raw - computed) > max(2.0, 0.4 * abs(raw)):
        return computed

    return raw
