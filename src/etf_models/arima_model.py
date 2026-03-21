"""
ARIMA模型适配器
复用现有的ARIMA模型函数，适配ETF数据格式
"""

import pandas as pd
from typing import Dict, Any, Optional
from src.logger_config import get_module_logger
from src.trend_analyzer_arima import predict_index_trend_arima

logger = get_module_logger(__name__)


def predict_etf_trend_arima(
    etf_daily_data: pd.DataFrame,
    forecast_days: int = 3,
    auto_select_order: bool = True,
    data_window_days: int = 200
) -> Dict[str, Any]:
    """
    使用ARIMA预测ETF趋势（复用现有函数）
    
    Args:
        etf_daily_data: ETF日线数据DataFrame（必须包含'收盘'列）
        forecast_days: 预测天数（默认3天）
        auto_select_order: 是否自动选择最优阶数（默认True）
        data_window_days: 数据窗口大小（默认200天）
    
    Returns:
        dict: {
            'direction': 'up' | 'down' | 'neutral',
            'forecast_prices': 预测价格列表,
            'confidence': 置信度 (0-1),
            'trend_strength': 趋势强度 (0-1),
            'method': 'ARIMA',
            ...
        }
    
    注意：
    - 直接调用 predict_index_trend_arima()，适配ETF数据格式
    - 确保数据格式一致（列名：'收盘'）
    - 将返回的'direction'转换为ETF信号格式：'上行'→'up', '下行'→'down', '震荡'→'neutral'
    """
    try:
        if etf_daily_data is None or etf_daily_data.empty:
            logger.warning("ETF日线数据为空，无法进行ARIMA预测")
            return {
                'direction': 'neutral',
                'confidence': 0.5,
                'trend_strength': 0.5,
                'forecast_prices': [],
                'method': 'ARIMA',
                'error': '数据为空'
            }
        
        # 确保数据格式一致（列名：'收盘'）
        if '收盘' not in etf_daily_data.columns:
            logger.warning("ETF日线数据缺少'收盘'列，无法进行ARIMA预测")
            return {
                'direction': 'neutral',
                'confidence': 0.5,
                'trend_strength': 0.5,
                'forecast_prices': [],
                'method': 'ARIMA',
                'error': '缺少收盘价列'
            }
        
        # 调用现有的ARIMA预测函数
        result = predict_index_trend_arima(
            daily_df=etf_daily_data,
            forecast_days=forecast_days,
            auto_select_order=auto_select_order,
            data_window_days=data_window_days
        )
        
        # 转换方向格式：'上行'→'up', '下行'→'down', '震荡'→'neutral'
        direction_map = {
            '上行': 'up',
            '下行': 'down',
            '震荡': 'neutral'
        }
        
        original_direction = result.get('direction', '震荡')
        etf_direction = direction_map.get(original_direction, 'neutral')
        
        # 返回适配后的结果
        return {
            'direction': etf_direction,
            'confidence': result.get('confidence', 0.5),
            'trend_strength': result.get('trend_strength', 0.5),
            'forecast_prices': result.get('forecast_prices', []),
            'method': 'ARIMA',
            'arima_order': result.get('arima_order'),
            'aic': result.get('aic'),
            'bic': result.get('bic'),
            'original_direction': original_direction  # 保留原始方向
        }
        
    except Exception as e:
        logger.error(f"ARIMA预测ETF趋势失败: {e}", exc_info=True)
        return {
            'direction': 'neutral',
            'confidence': 0.5,
            'trend_strength': 0.5,
            'forecast_prices': [],
            'method': 'ARIMA',
            'error': str(e)
        }
