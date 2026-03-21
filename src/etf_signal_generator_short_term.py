"""
ETF短波段信号生成模块（GROK v2.0优化方案）
独立模块，避免与现有代码冲突
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from datetime import datetime
import pytz

from src.logger_config import get_module_logger
from src.indicator_calculator import calculate_ma, calculate_macd, calculate_volume_ma

logger = get_module_logger(__name__)


def generate_etf_short_term_signal(
    etf_symbol: str,
    etf_daily_data: pd.DataFrame,
    etf_minute_30m: Optional[pd.DataFrame],
    etf_current_price: float,
    volatility_ranges: Optional[Dict] = None,
    config: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    生成ETF短波段信号（GROK v2.0优化方案）
    
    策略框架（DeepSeek策略1 + 3）：
    - 日线定趋势：价格站稳20日MA + MACD金叉 → 中期偏多/偏空
    - 分钟入场：趋势中回调至10日MA + 30min放量反弹 → 买入/卖出
    - 多时间框架：日线方向 + 30min确认
    
    Args:
        etf_symbol: ETF代码（如 "510300"）
        etf_daily_data: ETF日线数据
        etf_minute_30m: ETF 30分钟数据
        etf_current_price: ETF当前价格
        volatility_ranges: 波动区间预测结果（用于止盈目标）
        config: 系统配置
    
    Returns:
        dict: 信号字典，包含：
            - signal_type: "买入" | "卖出" | "持有"
            - signal_strength: 信号强度 (0-1)
            - position_size: 建议仓位 (0-1)
            - stop_loss: 止损价格
            - take_profit: 止盈价格
            - reason: 信号原因
            - etf_symbol: ETF代码
            - timestamp: 信号生成时间
        如果未生成信号，返回None
    """
    try:
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        short_term_config = config.get('etf_trading', {}).get('short_term', {})
        if not short_term_config.get('enabled', True):
            logger.debug(f"ETF短波段信号未启用，跳过生成")
            return None
        
        ma_long = short_term_config.get('ma_long', 20)
        ma_short = short_term_config.get('ma_short', 10)
        volume_multiplier = short_term_config.get('volume_multiplier', 1.2)
        min_strength = short_term_config.get('min_strength', 0.6)
        stop_loss_pct = short_term_config.get('stop_loss_pct', 0.05)
        take_profit_target = short_term_config.get('take_profit_target', 'volatility_upper')
        
        # 检查数据完整性
        if etf_daily_data is None or etf_daily_data.empty:
            logger.warning(f"ETF日线数据缺失，无法生成短波段信号")
            return None
        
        if '收盘' not in etf_daily_data.columns:
            logger.warning(f"ETF日线数据缺少'收盘'列，无法生成短波段信号")
            return None
        
        # 1. 日线定趋势：计算20日MA和10日MA
        ma20 = calculate_ma(etf_daily_data, period=ma_long, close_col='收盘')
        ma10 = calculate_ma(etf_daily_data, period=ma_short, close_col='收盘')
        
        if ma20 is None or ma20.empty or ma10 is None or ma10.empty:
            logger.warning(f"无法计算MA，跳过短波段信号生成")
            return None
        
        current_ma20 = float(ma20.iloc[-1])
        current_ma10 = float(ma10.iloc[-1])
        
        # 2. 计算MACD（用于确认趋势）
        macd_result = calculate_macd(etf_daily_data, close_col='收盘')
        macd_golden_cross = False
        macd_death_cross = False
        
        # calculate_macd 返回字典 {'macd': Series, 'signal': Series, 'histogram': Series}
        if macd_result is not None and 'histogram' in macd_result:
            macd_hist = macd_result['histogram']
            if macd_hist is not None and len(macd_hist) >= 2:
                # MACD金叉：Histogram从负转正
                if macd_hist.iloc[-2] < 0 and macd_hist.iloc[-1] > 0:
                    macd_golden_cross = True
                # MACD死叉：Histogram从正转负
                elif macd_hist.iloc[-2] > 0 and macd_hist.iloc[-1] < 0:
                    macd_death_cross = True
        
        # 3. 判断日线趋势方向
        daily_trend = 'neutral'  # 'bullish', 'bearish', 'neutral'
        if etf_current_price > current_ma20:
            daily_trend = 'bullish'  # 中期偏多
        elif etf_current_price < current_ma20:
            daily_trend = 'bearish'  # 中期偏空
        
        # 4. 30分钟级别入场确认
        minute_confirmed = False
        minute_reason = ""
        signal_strength = 0.0
        volume_ratio = 1.0
        
        if etf_minute_30m is not None and not etf_minute_30m.empty and '收盘' in etf_minute_30m.columns:
            # 计算30分钟MA10（用于回调判断）
            ma10_30m = calculate_ma(etf_minute_30m, period=10, close_col='收盘')
            
            if ma10_30m is not None and not ma10_30m.empty:
                current_price_30m = etf_minute_30m['收盘'].iloc[-1]
                current_ma10_30m = float(ma10_30m.iloc[-1])
                
                # 检查成交量
                volume_amplified = False
                if '成交量' in etf_minute_30m.columns:
                    volume_ma = calculate_volume_ma(etf_minute_30m, period=10, volume_col='成交量')
                    if volume_ma is not None and not volume_ma.empty:
                        current_volume = etf_minute_30m['成交量'].iloc[-1]
                        volume_ma_value = float(volume_ma.iloc[-1])
                        if volume_ma_value > 0:
                            volume_ratio = current_volume / volume_ma_value
                            volume_amplified = volume_ratio >= volume_multiplier
                
                # 买入信号：日线偏多 + 30分钟回调至MA10附近 + 放量反弹
                if daily_trend == 'bullish':
                    # 检查是否回调至MA10附近（价格在MA10下方或接近MA10）
                    price_near_ma10 = abs(current_price_30m - current_ma10_30m) / current_ma10_30m < 0.01  # 1%以内
                    price_below_ma10 = current_price_30m < current_ma10_30m
                    
                    # 检查是否反弹（最近3根K线中，最新价格高于前一根）
                    rebounded = False
                    if len(etf_minute_30m) >= 2:
                        rebounded = etf_minute_30m['收盘'].iloc[-1] > etf_minute_30m['收盘'].iloc[-2]
                    
                    if (price_near_ma10 or price_below_ma10) and rebounded and volume_amplified:
                        minute_confirmed = True
                        signal_strength = 0.6  # 基础强度
                        minute_reason = f"30min回调至MA10附近后放量反弹（成交量{volume_ratio:.2f}倍）"
                        
                        # MACD金叉加分
                        if macd_golden_cross:
                            signal_strength += 0.1
                            minute_reason += "，MACD金叉确认"
                        
                        # 成交量放大倍数加分
                        if volume_ratio > 1.3:
                            signal_strength += 0.05
                        if volume_ratio > 1.5:
                            signal_strength += 0.1
                        
                        signal_strength = min(signal_strength, 0.85)  # 最大0.85
                
                # 卖出信号：日线偏空 + 30分钟反弹至MA10附近 + 反弹回落
                elif daily_trend == 'bearish':
                    price_near_ma10 = abs(current_price_30m - current_ma10_30m) / current_ma10_30m < 0.01
                    price_above_ma10 = current_price_30m > current_ma10_30m
                    
                    # 检查是否回落（最近3根K线中，最新价格低于前一根）
                    declined = False
                    if len(etf_minute_30m) >= 2:
                        declined = etf_minute_30m['收盘'].iloc[-1] < etf_minute_30m['收盘'].iloc[-2]
                    
                    if (price_near_ma10 or price_above_ma10) and declined:
                        minute_confirmed = True
                        signal_strength = 0.6  # 基础强度
                        minute_reason = f"30min反弹至MA10附近后回落"
                        
                        # MACD死叉加分
                        if macd_death_cross:
                            signal_strength += 0.1
                            minute_reason += "，MACD死叉确认"
        
        # 5. 生成信号
        if not minute_confirmed or signal_strength < min_strength:
            logger.debug(f"ETF短波段信号未满足条件: 日线趋势={daily_trend}, 30min确认={minute_confirmed}, 强度={signal_strength:.3f}")
            return None
        
        # 确定信号类型
        if daily_trend == 'bullish' and minute_confirmed:
            signal_type = "买入"
        elif daily_trend == 'bearish' and minute_confirmed:
            signal_type = "卖出"
        else:
            signal_type = "持有"
            return None  # 持有信号不生成
        
        # 6. 计算仓位建议
        if signal_strength >= 0.75:
            position_size_range = [0.5, 0.8]  # 强波段信号
        elif signal_strength >= 0.65:
            position_size_range = [0.3, 0.5]  # 中等波段信号
        else:
            position_size_range = [0.0, 0.2]  # 弱波段信号
        
        position_size = (position_size_range[0] + position_size_range[1]) / 2
        
        # 7. 计算止盈止损
        stop_loss = current_ma20 * (1 - stop_loss_pct)  # 20日MA下方5%
        
        take_profit = None
        if take_profit_target == "volatility_upper" and volatility_ranges:
            etf_range = volatility_ranges.get('etf_range', {})
            if etf_range and 'upper' in etf_range:
                take_profit = etf_range['upper']
        if take_profit is None:
            # 备选：固定止盈（当前价格+3%）
            take_profit = etf_current_price * 1.03
        
        # 8. 构建信号字典
        signal = {
            'signal_type': signal_type,
            'signal_strength': round(signal_strength, 3),
            'position_size': round(position_size, 2),
            'stop_loss': round(stop_loss, 3),
            'take_profit': round(take_profit, 3),
            'reason': f"日线站稳{ma_long}日MA({current_ma20:.3f})，{minute_reason}",
            'etf_symbol': etf_symbol,
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),
            'daily_trend': daily_trend,
            'ma20': round(current_ma20, 3),
            'ma10': round(current_ma10, 3),
            'macd_golden_cross': macd_golden_cross,
            'macd_death_cross': macd_death_cross
        }
        
        logger.info(f"ETF短波段信号生成: {etf_symbol} {signal_type}, 强度={signal_strength:.3f}, "
                   f"仓位={position_size:.2f}, 止损={stop_loss:.3f}, 止盈={take_profit:.3f}")
        
        return signal
        
    except Exception as e:
        logger.error(f"ETF短波段信号生成失败: {e}", exc_info=True)
        return None
