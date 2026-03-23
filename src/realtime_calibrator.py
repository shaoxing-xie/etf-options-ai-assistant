"""
实时校准模块
根据盘中实际走势实时调整预测区间
"""

import pandas as pd
from typing import Dict, Optional, Any

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


def real_time_calibration(
    prediction: Dict[str, Any],
    current_price: float,
    intraday_data: pd.DataFrame,
    time_of_day: Optional[str] = None,  # 'morning'/'afternoon'/'near_close'
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    根据盘中实际走势实时调整预测区间
    
    Args:
        prediction: 原始预测结果
        current_price: 当前价格
        intraday_data: 当日分钟数据
        time_of_day: 交易时段
        config: 系统配置
    
    Returns:
        dict: 校准后的预测结果
    """
    try:
        if intraday_data is None or intraday_data.empty or len(intraday_data) < 2:
            return prediction
        
        # 计算当日已实现波动
        if '收盘' not in intraday_data.columns:
            return prediction
        
        price_changes = intraday_data['收盘'].pct_change().dropna()
        if len(price_changes) == 0:
            return prediction
        
        realized_vol = price_changes.std() * 100  # 转换为百分比
        
        # 预测的波动范围
        predicted_range_pct = prediction.get('range_pct', 2.0)
        
        # 如果已实现波动显著大于预测波动，扩大区间
        vol_ratio = realized_vol / predicted_range_pct if predicted_range_pct > 0 else 1.0
        
        calibration_applied = False
        calibration_reason = None
        
        if vol_ratio > 1.2:  # 已实现波动比预测大20%以上
            # 扩大区间（但不超过50%）
            adjustment_factor = min(1.5, 1.0 + (vol_ratio - 1.2) * 0.5)
            
            center = (prediction['upper'] + prediction['lower']) / 2
            half_range = (prediction['upper'] - prediction['lower']) / 2
            
            adjusted_upper = center + half_range * adjustment_factor
            adjusted_lower = center - half_range * adjustment_factor
            
            calibration_applied = True
            calibration_reason = f'已实现波动({realized_vol:.2f}%) > 预测波动({predicted_range_pct:.2f}%)'
            
            prediction['upper'] = adjusted_upper
            prediction['lower'] = adjusted_lower
            prediction['range_pct'] = (adjusted_upper - adjusted_lower) / current_price * 100
        
        # 如果价格快速接近边界，也需要调整
        upper = prediction.get('upper', current_price * 1.02)
        lower = prediction.get('lower', current_price * 0.98)
        
        if upper > lower:
            position = (current_price - lower) / (upper - lower)
            
            if position > 0.85:  # 接近上轨
                # 如果价格还在上涨，扩大上轨
                if len(intraday_data) >= 3:
                    recent_trend = (intraday_data['收盘'].iloc[-1] - intraday_data['收盘'].iloc[-3]) / intraday_data['收盘'].iloc[-3]
                    if recent_trend > 0.001:  # 最近3个周期上涨超过0.1%
                        expansion = (upper - lower) * 0.1
                        prediction['upper'] = upper + expansion
                        prediction['range_pct'] = (upper + expansion - lower) / current_price * 100
                        calibration_applied = True
                        calibration_reason = '价格接近上轨且继续上涨'
            
            elif position < 0.15:  # 接近下轨
                # 如果价格还在下跌，扩大下轨
                if len(intraday_data) >= 3:
                    recent_trend = (intraday_data['收盘'].iloc[-1] - intraday_data['收盘'].iloc[-3]) / intraday_data['收盘'].iloc[-3]
                    if recent_trend < -0.001:  # 最近3个周期下跌超过0.1%
                        expansion = (upper - lower) * 0.1
                        prediction['lower'] = lower - expansion
                        prediction['range_pct'] = (upper - (lower - expansion)) / current_price * 100
                        calibration_applied = True
                        calibration_reason = '价格接近下轨且继续下跌'
        
        if calibration_applied:
            prediction['calibration_applied'] = True
            prediction['calibration_reason'] = calibration_reason
            logger.debug(f"实时校准已应用: {calibration_reason}")
        
        return prediction
        
    except Exception as e:
        logger.warning(f"实时校准失败: {e}，返回原始预测")
        return prediction


def should_trigger_calibration(
    prediction: Dict[str, Any],
    current_price: float,
    intraday_data: pd.DataFrame
) -> bool:
    """
    判断是否应该触发实时校准
    
    Args:
        prediction: 预测结果
        current_price: 当前价格
        intraday_data: 当日分钟数据
    
    Returns:
        bool: 是否应该触发校准
    """
    try:
        if intraday_data is None or intraday_data.empty or len(intraday_data) < 2:
            return False
        
        # 条件1：价格突破预测区间的80%
        upper = prediction.get('upper', current_price * 1.02)
        lower = prediction.get('lower', current_price * 0.98)
        
        if upper > lower:
            position = (current_price - lower) / (upper - lower)
            if position > 0.8 or position < 0.2:
                return True
        
        # 条件2：已实现波动显著大于预测波动
        if '收盘' in intraday_data.columns:
            price_changes = intraday_data['收盘'].pct_change().dropna()
            if len(price_changes) > 0:
                realized_vol = price_changes.std() * 100
                predicted_range_pct = prediction.get('range_pct', 2.0)
                if predicted_range_pct > 0 and realized_vol / predicted_range_pct > 1.2:
                    return True
        
        return False
        
    except Exception as e:
        logger.debug(f"判断校准触发条件失败: {e}")
        return False
