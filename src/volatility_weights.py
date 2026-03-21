"""
波动预测权重优化模块
实现市场状态自适应权重、动态权重优化等功能
"""

from typing import Dict, Optional, Any
import numpy as np
from datetime import datetime, timedelta
import pytz

from src.logger_config import get_module_logger
from src.prediction_recorder import get_method_performance

logger = get_module_logger(__name__)


def get_market_state_weights(market_state: str) -> Dict[str, float]:
    """
    根据市场状态返回对应的权重配置
    
    Args:
        market_state: 'trend'（趋势）/ 'range'（震荡）/ 'high_volatility'（高波动）
    
    Returns:
        dict: 各方法的权重
    """
    # 趋势市场：ATR和历史波动率更有效（能捕捉趋势延续）
    if market_state == 'trend':
        return {
            'atr': 0.4,
            'hist_vol': 0.35,
            'bb': 0.15,
            'intraday_vol': 0.1
        }
    
    # 震荡市场：布林带更有效（能捕捉区间震荡）
    elif market_state == 'range':
        return {
            'atr': 0.2,
            'hist_vol': 0.2,
            'bb': 0.4,
            'intraday_vol': 0.2
        }
    
    # 高波动市场：日内波动率权重增加（能快速响应市场变化）
    else:  # high_volatility
        return {
            'atr': 0.25,
            'hist_vol': 0.25,
            'bb': 0.2,
            'intraday_vol': 0.3
        }


def determine_market_state(
    daily_df=None,
    minute_data=None,
    trend_analysis=None
) -> str:
    """
    判断市场状态
    
    Args:
        daily_df: 日线数据（可选）
        minute_data: 分钟数据（可选）
        trend_analysis: 趋势分析结果（可选）
    
    Returns:
        str: 'trend'/'range'/'high_volatility'
    """
    try:
        # 方法1：基于趋势分析结果
        if trend_analysis:
            trend_direction, trend_strength = trend_analysis
            if trend_strength > 0.7:
                return 'trend'
            elif trend_strength < 0.3:
                return 'trend'
            else:
                return 'range'
        
        # 方法2：基于分钟数据的波动率
        if minute_data is not None and not minute_data.empty and len(minute_data) >= 20:
            price_changes = minute_data['收盘'].pct_change().dropna()
            volatility = price_changes.std() * 100  # 转换为百分比
            
            # 高波动：波动率 > 1.5%
            if volatility > 1.5:
                return 'high_volatility'
            # 趋势：波动率适中且价格有明显方向
            elif volatility > 0.8:
                # 检查价格趋势
                if len(minute_data) >= 10:
                    price_trend = (minute_data['收盘'].iloc[-1] - minute_data['收盘'].iloc[-10]) / minute_data['收盘'].iloc[-10]
                    if abs(price_trend) > 0.01:  # 价格变化超过1%
                        return 'trend'
            
            return 'range'
        
        # 方法3：基于日线数据
        if daily_df is not None and not daily_df.empty and len(daily_df) >= 20:
            price_changes = daily_df['收盘'].pct_change().dropna()
            volatility = price_changes.std() * 100
            
            if volatility > 2.0:
                return 'high_volatility'
            elif volatility > 1.0:
                return 'trend'
            else:
                return 'range'
        
        # 默认：震荡市场
        return 'range'
        
    except Exception as e:
        logger.warning(f"判断市场状态失败: {e}，使用默认值（震荡）")
        return 'range'


def calculate_dynamic_weights(
    method_performances: Dict[str, Dict[str, Any]],
    lookback_days: int = 30,
    min_predictions: int = 10
) -> Dict[str, float]:
    """
    根据历史表现计算动态权重
    - 表现好的方法权重增加
    - 表现差的方法权重减少
    
    Args:
        method_performances: {
            'atr': {'hit_rate': 0.85, 'avg_width': 2.5, 'score': 0.8},
            'hist_vol': {'hit_rate': 0.75, 'avg_width': 2.8, 'score': 0.7},
            'bb': {'hit_rate': 0.70, 'avg_width': 2.2, 'score': 0.65},
            'intraday_vol': {'hit_rate': 0.80, 'avg_width': 2.6, 'score': 0.75}
        }
        lookback_days: 回看天数
        min_predictions: 最少预测次数（低于此值的方法使用默认权重）
    
    Returns:
        dict: 动态权重 {'atr': 0.35, 'hist_vol': 0.30, 'bb': 0.15, 'intraday_vol': 0.20}
    """
    try:
        # 如果没有提供方法表现，从数据库获取
        if not method_performances:
            method_performances = get_method_performance(lookback_days=lookback_days)
        
        # 如果仍然为空，返回默认权重
        if not method_performances:
            logger.debug("无法获取方法表现，使用默认权重")
            return {'atr': 0.3, 'hist_vol': 0.3, 'bb': 0.2, 'intraday_vol': 0.2}
        
        # 计算综合得分（命中率 * 0.6 + 宽度得分 * 0.4）
        scores = {}
        for method, perf in method_performances.items():
            # 检查是否有足够的预测次数
            total_predictions = perf.get('total_predictions', 0)
            if total_predictions < min_predictions:
                logger.debug(f"方法 {method} 预测次数不足 ({total_predictions} < {min_predictions})，使用默认权重")
                continue
            
            hit_rate = perf.get('hit_rate', 0.5)
            avg_width = perf.get('avg_width', 3.0)
            
            # 宽度得分：2%为基准，越小越好
            width_score = 1.0 - (avg_width - 2.0) / 2.0
            width_score = max(0.0, min(1.0, width_score))
            
            # 综合得分
            scores[method] = hit_rate * 0.6 + width_score * 0.4
        
        # 如果没有有效的方法，返回默认权重
        if not scores:
            return {'atr': 0.3, 'hist_vol': 0.3, 'bb': 0.2, 'intraday_vol': 0.2}
        
        # 归一化权重
        total_score = sum(scores.values())
        if total_score > 0:
            weights = {method: score / total_score for method, score in scores.items()}
        else:
            # 默认权重
            weights = {'atr': 0.3, 'hist_vol': 0.3, 'bb': 0.2, 'intraday_vol': 0.2}
        
        # 限制权重范围（避免极端值）
        min_weight = 0.1
        max_weight = 0.5
        weights = {
            method: max(min_weight, min(max_weight, w))
            for method, w in weights.items()
        }
        
        # 确保所有方法都有权重（缺失的方法使用默认值）
        default_weights = {'atr': 0.3, 'hist_vol': 0.3, 'bb': 0.2, 'intraday_vol': 0.2}
        for method in default_weights:
            if method not in weights:
                weights[method] = default_weights[method]
        
        # 重新归一化
        total = sum(weights.values())
        weights = {method: w / total for method, w in weights.items()}
        
        logger.debug(f"动态权重计算完成: {weights}")
        return weights
        
    except Exception as e:
        logger.error(f"计算动态权重失败: {e}", exc_info=True)
        return {'atr': 0.3, 'hist_vol': 0.3, 'bb': 0.2, 'intraday_vol': 0.2}


def time_decay_adjustment(
    base_range: float,
    remaining_minutes: int,
    time_decay_factor: float = 0.5,
    config: Optional[Dict] = None
) -> float:
    """
    剩余时间越少，波动范围应该越小（因为时间有限）
    使用指数衰减：range_adjusted = range_base * (remaining_ratio ^ time_decay_factor)
    
    Args:
        base_range: 基础波动范围（百分比）
        remaining_minutes: 剩余交易时间（分钟）
        time_decay_factor: 时间衰减因子（0-1，越大衰减越快）
        config: 系统配置
    
    Returns:
        float: 调整后的波动范围（百分比）
    """
    try:
        if remaining_minutes <= 0:
            return base_range * 0.1  # 收盘后几乎无波动
        
        if remaining_minutes >= 240:
            return base_range  # 开盘前，使用完整范围
        
        remaining_ratio = remaining_minutes / 240.0
        
        # 分段调整策略（基于剩余时间，不依赖当前时间）
        # 上午时段（剩余180-240分钟）：使用完整范围
        if remaining_minutes >= 180:
            return base_range
        
        # 午休时段（剩余120-180分钟）：保持上午的预测
        if remaining_minutes >= 120:
            return base_range
        
        # 下午时段（剩余30-120分钟）：根据剩余时间逐步缩小
        if remaining_minutes >= 30:
            # 正常衰减
            adjusted_ratio = remaining_ratio ** time_decay_factor
            return base_range * adjusted_ratio
        
        # 临近收盘（剩余0-30分钟）：使用更温和的衰减，避免过度缩小
        if remaining_minutes > 0:
            adjusted_ratio = remaining_ratio ** (time_decay_factor * 0.7)
            return base_range * adjusted_ratio
        
        # 默认：指数衰减（如果剩余时间不在上述范围）
        adjusted_ratio = remaining_ratio ** time_decay_factor
        return base_range * adjusted_ratio
        
    except Exception as e:
        logger.warning(f"时间衰减调整失败: {e}，使用原始范围")
        return base_range
