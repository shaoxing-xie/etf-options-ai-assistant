"""
技术指标模型
基于MACD、RSI、MA20、成交量等技术指标生成ETF交易信号
"""

import pandas as pd
from typing import Dict, Any, Optional
from src.logger_config import get_module_logger
from src.indicator_calculator import (
    calculate_macd, calculate_rsi, calculate_ma, calculate_volume_ma
)

logger = get_module_logger(__name__)


def generate_technical_signal(
    etf_daily_data: pd.DataFrame,
    etf_minute_30m: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """
    基于技术指标生成信号
    
    Args:
        etf_daily_data: ETF日线数据（必须包含'收盘'、'成交量'列）
        etf_minute_30m: ETF 30分钟数据（可选，用于实时确认）
    
    Returns:
        dict: {
            'direction': 'up' | 'down' | 'neutral',
            'confidence': float,  # 置信度 (0-1)
            'signals': {
                'macd': str,      # 'golden_cross' | 'death_cross' | 'none'
                'rsi': str,       # 'oversold' | 'overbought' | 'neutral'
                'ma20': str,      # 'above' | 'below' | 'none'
                'volume': str     # 'amplified' | 'normal' | 'shrinking'
            }
        }
    
    信号规则：
    - MACD金叉 + RSI < 40 + 站上MA20 + 成交放大 → 买入信号
    - MACD死叉 + RSI > 60 + 跌破MA20 + 成交放大 → 卖出信号
    - 置信度 = 满足条件的信号数量 / 4
    """
    try:
        if etf_daily_data is None or etf_daily_data.empty:
            logger.warning("ETF日线数据为空，无法生成技术指标信号")
            return _get_neutral_signal("数据为空")
        
        # 检查必要的列
        required_cols = ['收盘']
        if not all(col in etf_daily_data.columns for col in required_cols):
            logger.warning(f"ETF日线数据缺少必要列: {required_cols}")
            return _get_neutral_signal("数据列不完整")
        
        signals = {}
        
        # 1. MACD信号
        macd_result = calculate_macd(etf_daily_data, close_col='收盘')
        if macd_result and not macd_result['macd'].empty and not macd_result['signal'].empty:
            macd_line = macd_result['macd']
            signal_line = macd_result['signal']
            
            # 检查金叉/死叉（最近两个数据点）
            if len(macd_line) >= 2 and len(signal_line) >= 2:
                macd_prev = macd_line.iloc[-2]
                macd_curr = macd_line.iloc[-1]
                signal_prev = signal_line.iloc[-2]
                signal_curr = signal_line.iloc[-1]
                
                # 金叉：MACD从下方穿越信号线
                if macd_prev <= signal_prev and macd_curr > signal_curr:
                    signals['macd'] = 'golden_cross'
                # 死叉：MACD从上方穿越信号线
                elif macd_prev >= signal_prev and macd_curr < signal_curr:
                    signals['macd'] = 'death_cross'
                else:
                    signals['macd'] = 'none'
            else:
                signals['macd'] = 'none'
        else:
            signals['macd'] = 'none'
        
        # 2. RSI信号
        rsi = calculate_rsi(etf_daily_data, close_col='收盘')
        if rsi is not None and not rsi.empty:
            rsi_value = rsi.iloc[-1]
            if rsi_value < 40:
                signals['rsi'] = 'oversold'  # 超卖，买入信号
            elif rsi_value > 60:
                signals['rsi'] = 'overbought'  # 超买，卖出信号
            else:
                signals['rsi'] = 'neutral'
        else:
            signals['rsi'] = 'neutral'
        
        # 3. MA20信号
        ma20 = calculate_ma(etf_daily_data, period=20, close_col='收盘')
        if ma20 is not None and not ma20.empty and '收盘' in etf_daily_data.columns:
            current_price = etf_daily_data['收盘'].iloc[-1]
            ma20_value = ma20.iloc[-1]
            if current_price > ma20_value:
                signals['ma20'] = 'above'  # 站上MA20，买入信号
            else:
                signals['ma20'] = 'below'  # 跌破MA20，卖出信号
        else:
            signals['ma20'] = 'none'
        
        # 4. 成交量信号
        if '成交量' in etf_daily_data.columns:
            volume_ma10 = calculate_volume_ma(etf_daily_data, period=10, volume_col='成交量')
            if volume_ma10 is not None and not volume_ma10.empty:
                current_volume = etf_daily_data['成交量'].iloc[-1]
                volume_ma10_value = volume_ma10.iloc[-1]
                
                # 成交放大：当前成交量 > 10日均量 * 1.2
                if current_volume > volume_ma10_value * 1.2:
                    signals['volume'] = 'amplified'  # 成交放大，买入/卖出信号
                elif current_volume < volume_ma10_value * 0.8:
                    signals['volume'] = 'shrinking'  # 成交萎缩
                else:
                    signals['volume'] = 'normal'
            else:
                signals['volume'] = 'normal'
        else:
            signals['volume'] = 'normal'
        
        # 计算方向（基于信号组合）
        buy_signals = 0
        sell_signals = 0
        
        if signals['macd'] == 'golden_cross':
            buy_signals += 1
        elif signals['macd'] == 'death_cross':
            sell_signals += 1
        
        if signals['rsi'] == 'oversold':
            buy_signals += 1
        elif signals['rsi'] == 'overbought':
            sell_signals += 1
        
        if signals['ma20'] == 'above':
            buy_signals += 1
        elif signals['ma20'] == 'below':
            sell_signals += 1
        
        if signals['volume'] == 'amplified':
            # 成交放大时，根据其他信号判断方向
            if buy_signals > sell_signals:
                buy_signals += 1
            elif sell_signals > buy_signals:
                sell_signals += 1
        
        # 确定方向（优化：改回>=2以提高信号质量，因为>=1导致信号质量差，胜率0%）
        if buy_signals >= 2:
            direction = 'up'
        elif sell_signals >= 2:
            direction = 'down'
        else:
            direction = 'neutral'
        
        # 计算置信度 = 满足条件的信号数量 / 4
        signal_count = sum([
            signals['macd'] != 'none',
            signals['rsi'] != 'neutral',
            signals['ma20'] != 'none',
            signals['volume'] == 'amplified'
        ])
        confidence = signal_count / 4.0
        
        return {
            'direction': direction,
            'confidence': confidence,
            'signals': signals,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals
        }
        
    except Exception as e:
        logger.error(f"生成技术指标信号失败: {e}", exc_info=True)
        return _get_neutral_signal(f"计算失败: {str(e)}")


def _get_neutral_signal(reason: str) -> Dict[str, Any]:
    """返回中性信号"""
    return {
        'direction': 'neutral',
        'confidence': 0.5,
        'signals': {
            'macd': 'none',
            'rsi': 'neutral',
            'ma20': 'none',
            'volume': 'normal'
        },
        'buy_signals': 0,
        'sell_signals': 0,
        'reason': reason
    }
