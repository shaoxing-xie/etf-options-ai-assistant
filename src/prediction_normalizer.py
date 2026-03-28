"""
预测值标准化模块

统一不同预测源的数值单位，确保所有预测值在相同量级上可比较。

核心问题：历史预测存在以下单位混用：
- ETF 价格（正确）：4.7 左右
- 指数点（需转换）：4700 左右，需要除以 1000
- 收益率（需转换）：0.0118 左右，需要转为百分比或价格

解决策略：
1. 根据标的类型设定合理价格区间
2. 自动检测预测值的单位类型
3. 执行标准化转换
"""

from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# 标的价格区间配置（单位：元）
PRICE_RANGES = {
    '510300': {'min': 3.5, 'max': 6.0, 'name': '沪深300ETF'},
    '510050': {'min': 2.0, 'max': 4.0, 'name': '50ETF'},
    '159915': {'min': 0.3, 'max': 1.5, 'name': '创业板ETF'},
    '000300': {'min': 3000, 'max': 6000, 'name': '沪深300指数'},
    '000001': {'min': 2500, 'max': 4500, 'name': '上证指数'},
}

def detect_unit_type(value: float, symbol: str) -> str:
    """
    检测预测值的单位类型
    
    Args:
        value: 预测值
        symbol: 标的代码
        
    Returns:
        str: 单位类型 ('price'|'index_point'|'ratio'|'unknown')
    """
    if symbol not in PRICE_RANGES:
        return 'unknown'
    
    expected_range = PRICE_RANGES[symbol]
    expected_min = expected_range['min']
    expected_max = expected_range['max']
    
    # 情况1：值在预期价格区间内 → 价格单位
    if expected_min <= value <= expected_max:
        return 'price'
    
    # 情况2：值在指数点区间 → 指数点单位
    if value > 1000:
        # 可能是指数点
        converted = value / 1000
        if expected_min <= converted <= expected_max:
            return 'index_point'
    
    # 情况3：值很小 → 可能是收益率/比率
    if value < 0.1:
        return 'ratio'
    
    return 'unknown'

def normalize_prediction(
    value: float, 
    symbol: str,
    strict: bool = True
) -> Tuple[float, str]:
    """
    标准化预测值到统一单位
    
    Args:
        value: 原始预测值
        symbol: 标的代码
        strict: 是否严格模式（拒绝无法确定的值）
        
    Returns:
        Tuple[float, str]: (标准化后的值, 状态消息)
        
    状态消息：
    - 'ok': 标准化成功
    - 'converted_from_index': 从指数点转换
    - 'rejected': 值被拒绝（仅 strict=True）
    - 'unknown_unit': 无法确定单位（仅 strict=False）
    """
    if symbol not in PRICE_RANGES:
        return value, 'unknown_symbol'
    
    expected_range = PRICE_RANGES[symbol]
    unit_type = detect_unit_type(value, symbol)
    
    if unit_type == 'price':
        # 已经是正确单位
        return value, 'ok'
    
    elif unit_type == 'index_point':
        # 从指数点转换为 ETF 价格（除以 1000）
        converted = value / 1000
        logger.info(f"单位转换: {value} (指数点) → {converted} (ETF价格)")
        return converted, 'converted_from_index'
    
    elif unit_type == 'ratio':
        # 比率值无法直接转为价格
        if strict:
            logger.warning(f"拒绝异常预测值: {value} (可能是收益率，无法转为价格)")
            raise ValueError(f"无法将比率值 {value} 转换为价格")
        else:
            return value, 'unknown_unit'
    
    else:
        # 未知单位
        if strict:
            logger.warning(f"拒绝无法识别单位的预测值: {value}")
            raise ValueError(f"无法识别预测值 {value} 的单位")
        else:
            return value, 'unknown_unit'

def normalize_prediction_range(
    upper: float,
    lower: float,
    current_price: float,
    symbol: str
) -> Tuple[float, float, float, str]:
    """
    标准化整个预测区间
    
    Args:
        upper: 预测上轨
        lower: 预测下轨
        current_price: 当前价格
        symbol: 标的代码
        
    Returns:
        Tuple[float, float, float, str]: (标准化后上轨, 标准化后下轨, 标准化后当前价, 状态)
    """
    try:
        norm_upper, status1 = normalize_prediction(upper, symbol, strict=True)
        norm_lower, status2 = normalize_prediction(lower, symbol, strict=True)
        norm_current, status3 = normalize_prediction(current_price, symbol, strict=False)
        
        # 验证标准化后的值
        if norm_upper <= norm_lower:
            raise ValueError(f"标准化后上轨 {norm_upper} <= 下轨 {norm_lower}")
        
        # 检查当前价格是否在合理范围
        if norm_current > 0:
            range_mid = (norm_upper + norm_lower) / 2
            deviation = abs(norm_current - range_mid) / range_mid
            if deviation > 0.5:
                logger.warning(f"当前价格偏离区间中心过远: {norm_current} vs {range_mid}")
        
        status = 'ok' if all(s == 'ok' or s == 'converted_from_index' 
                            for s in [status1, status2, status3]) else 'warning'
        
        return norm_upper, norm_lower, norm_current, status
        
    except ValueError as e:
        logger.error(f"预测区间标准化失败: {e}")
        raise

def validate_prediction_quality(
    upper: float,
    lower: float,
    current_price: float,
    symbol: str
) -> Tuple[bool, str]:
    """
    验证预测质量（质量门禁）
    
    Args:
        upper: 预测上轨
        lower: 预测下轨
        current_price: 当前价格
        symbol: 标的代码
        
    Returns:
        Tuple[bool, str]: (是否通过, 原因)
    """
    # 规则1：上轨必须大于下轨
    if upper <= lower:
        return False, f"上下轨颠倒: upper={upper}, lower={lower}"
    
    # 规则2：区间宽度必须在合理范围 [0.5%, 10%]
    if current_price > 0:
        range_pct = (upper - lower) / current_price * 100
        if range_pct < 0.5:
            return False, f"区间过窄 ({range_pct:.2f}%)，必然突破"
        if range_pct > 10:
            return False, f"区间过宽 ({range_pct:.2f}%)，无参考价值"
    
    # 规则3：价格必须在合理区间
    if symbol in PRICE_RANGES:
        expected_min = PRICE_RANGES[symbol]['min']
        expected_max = PRICE_RANGES[symbol]['max']
        
        if lower < expected_min * 0.8:
            return False, f"下轨过低: {lower} < {expected_min * 0.8}"
        if upper > expected_max * 1.2:
            return False, f"上轨过高: {upper} > {expected_max * 1.2}"
    
    # 规则4：当前价格应在区间内或附近
    if current_price > 0:
        if current_price < lower * 0.95:
            return False, f"当前价格远低于区间: {current_price} < {lower * 0.95}"
        if current_price > upper * 1.05:
            return False, f"当前价格远高于区间: {current_price} > {upper * 1.05}"
    
    return True, "通过质量门禁"

# 便捷函数：标准化并验证
def process_prediction(
    upper: float,
    lower: float,
    current_price: float,
    symbol: str
) -> Tuple[float, float, float, bool, str]:
    """
    处理预测值：标准化 + 质量门禁
    
    Returns:
        Tuple: (标准化上轨, 标准化下轨, 标准化当前价, 是否通过, 消息)
    """
    try:
        # 1. 标准化
        norm_upper, norm_lower, norm_current, norm_status = \
            normalize_prediction_range(upper, lower, current_price, symbol)
        
        # 2. 质量门禁
        passed, msg = validate_prediction_quality(
            norm_upper, norm_lower, norm_current, symbol
        )
        
        return norm_upper, norm_lower, norm_current, passed, msg
        
    except ValueError as e:
        return upper, lower, current_price, False, f"标准化失败: {e}"

if __name__ == "__main__":
    # 测试用例
    test_cases = [
        # (upper, lower, current, symbol, 描述)
        (4.75, 4.65, 4.70, '510300', '正常ETF价格'),
        (4750, 4650, 4700, '510300', '指数点单位'),
        (0.012, 0.011, 0.0115, '510300', '比率值（应被拒绝）'),
        (4800, 4700, 4750, '000300', '指数预测（指数点正确）'),
    ]
    
    print("=== 预测值标准化测试 ===\n")
    
    for upper, lower, current, symbol, desc in test_cases:
        print(f"测试: {desc}")
        print(f"  输入: upper={upper}, lower={lower}, current={current}")
        try:
            norm_u, norm_l, norm_c, passed, msg = process_prediction(
                upper, lower, current, symbol
            )
            print(f"  标准化: upper={norm_u:.4f}, lower={norm_l:.4f}")
            print(f"  质量门禁: {'✅ 通过' if passed else '❌ 拒绝'} - {msg}")
        except Exception as e:
            print(f"  ❌ 错误: {e}")
        print()
