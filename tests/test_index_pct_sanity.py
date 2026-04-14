"""plugins.utils.index_pct_sanity 涨跌幅纠偏"""

from plugins.utils.index_pct_sanity import reconcile_index_change_pct


def test_points_mistaken_as_pct():
    """涨跌额约 -39 点、实际约 -1% 时应采用价格重算。"""
    rp = reconcile_index_change_pct(-39.19, 3841.0, 3880.0)
    assert rp is not None
    assert abs(rp - (3841.0 - 3880.0) / 3880.0 * 100.0) < 0.05


def test_decimal_fraction_form():
    rp = reconcile_index_change_pct(-0.01, 3841.0, 3880.0)
    assert rp is not None
    assert abs(rp + 1.0) < 0.15


def test_agrees_with_source_when_consistent():
    rp = reconcile_index_change_pct(-1.0, 3841.2, 3880.0)
    assert rp is not None
    assert abs(rp + 1.0) < 0.2
