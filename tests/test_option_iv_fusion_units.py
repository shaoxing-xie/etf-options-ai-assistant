import types

import pytest

from src import option_iv_fusion as ivmod


@pytest.mark.parametrize(
    "value,kind,expected,tag",
    [
        (51.67, "iv", 0.5167, "iv_converted_from_percent"),
        (0.5167, "iv", 0.5167, "iv_assumed_decimal"),
        (15.43, "hist_vol", 0.1543, "hist_vol_converted_from_percent"),
        (0.1543, "hist_vol", 0.1543, "hist_vol_assumed_decimal"),
    ],
)
def test_normalize_vol_value_to_decimal(value, kind, expected, tag):
    """确保 IV/HV 在百分数与小数之间的单位归一逻辑稳定。"""
    normalized, status = ivmod._normalize_vol_value_to_decimal(value, kind=kind)
    assert pytest.approx(normalized, rel=1e-4) == expected
    assert status == tag


def test_incorporate_option_iv_fusion_scaling_factor_and_fields():
    """在开启 iv_hv_fusion 时，检查缩放因子与调试字段是否合理写入。"""
    # 构造一个简单的 ETF 预测结果
    etf_prediction = {
        "current_price": 4.5,
        "upper": 4.6,
        "lower": 4.4,
        "hist_vol": 15.43,  # 百分数形式
        "range_pct": 3.55,
    }
    # option_iv_data 使用“百分数形式”的 IV，预期会被转换为小数
    option_iv_data = {"avg_iv": 51.67}
    config = {
        "volatility_engine": {
            "iv_hv_fusion": {
                "enabled": True,
                "weight_iv": 0.5,
                "weight_hv": 0.5,
                "min_scale": 0.7,
                "max_scale": 1.3,
            }
        }
    }

    out = ivmod.incorporate_option_iv(
        etf_prediction=dict(etf_prediction),
        underlying="510300",
        option_iv_data=option_iv_data,
        config=config,
    )

    assert out.get("iv_adjusted") is True
    # option_iv 应为小数形式
    assert 0 < out.get("option_iv", 0) < 2
    # hist_vol_used 应为百分数形式
    assert out.get("hist_vol_used") > 1

    scale = out.get("iv_hv_scaling_factor")
    assert scale is not None
    assert 0.7 <= scale <= 1.3

