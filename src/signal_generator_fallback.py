"""
降级信号生成模块
当分钟数据不可用时，使用日线数据和实时数据进行信号生成
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, Any, List
import pytz

from src.logger_config import get_module_logger, log_error_with_context
from src.indicator_calculator import calculate_rsi, calculate_macd, calculate_price_change_rate
from src.signal_generator import create_signal_with_volatility_range
from src.config_loader import load_system_config

logger = get_module_logger(__name__)


def generate_signals_fallback(
    etf_daily_data: pd.DataFrame,
    index_daily_data: pd.DataFrame,
    etf_current_price: float,
    call_option_price: Optional[float] = None,
    put_option_price: Optional[float] = None,
    call_option_greeks: Optional[pd.DataFrame] = None,
    put_option_greeks: Optional[pd.DataFrame] = None,
    opening_strategy: Optional[Dict] = None,
    volatility_ranges: Optional[Dict] = None,
    config: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    """
    降级方案：基于日线数据的信号生成
    
    方法：
    1. 使用日线数据计算RSI、MACD（日线级别）
    2. 使用实时价格计算价格变化率（相对于昨日收盘价）
    3. 结合开盘策略的整体趋势判断
    4. 使用已保存的波动区间数据（如果有）
    5. 使用期权Greeks数据（IV、Delta）评估期权价值
    6. 生成交易信号
    
    Args:
        etf_daily_data: ETF日线数据
        index_daily_data: 指数日线数据
        etf_current_price: ETF当前价格
        call_option_price: Call期权当前价格
        put_option_price: Put期权当前价格
        call_option_greeks: Call期权Greeks数据
        put_option_greeks: Put期权Greeks数据
        opening_strategy: 开盘策略（包含整体趋势判断）
        volatility_ranges: 波动区间预测结果
        config: 系统配置
    
    Returns:
        list: 信号列表
    """
    try:
        logger.info("使用降级方案生成交易信号（基于日线数据）...")
        
        if config is None:
            config = load_system_config()
        
        signal_params = config.get('signal_params', {})
        rsi_oversold = signal_params.get('rsi_oversold', 40)
        rsi_overbought = signal_params.get('rsi_overbought', 60)
        price_change_threshold = signal_params.get('price_change_threshold', 1.5)
        deduplication_time = signal_params.get('signal_deduplication_time', 1800)
        
        signals = []
        
        # 1. 计算日线级别的技术指标
        daily_indicators = calculate_daily_indicators(
            index_daily_data,
            etf_daily_data,
            etf_current_price
        )
        
        if not daily_indicators:
            logger.warning("日线技术指标计算失败，无法生成信号")
            return signals
        
        latest_rsi = daily_indicators.get('rsi')
        latest_macd = daily_indicators.get('macd')
        latest_price_change = daily_indicators.get('price_change_pct')
        yesterday_close = daily_indicators.get('yesterday_close')
        
        # 2. 获取开盘策略信息
        overall_trend = "震荡"
        trend_strength = 0.5
        strategy_direction = "中性"
        
        if opening_strategy:
            overall_trend = opening_strategy.get('final_trend', '震荡')
            trend_strength = opening_strategy.get('final_strength', 0.5)
            strategy_direction = opening_strategy.get('final_direction', '中性')
        
        # 3. 提取期权Greeks数据
        call_iv = None
        put_iv = None
        call_delta = None
        put_delta = None
        
        if call_option_greeks is not None:
            from src.volatility_range import extract_greeks_from_data
            call_greeks = extract_greeks_from_data(call_option_greeks)
            call_iv = call_greeks.get('iv')
            call_delta = call_greeks.get('delta')
        
        if put_option_greeks is not None:
            from src.volatility_range import extract_greeks_from_data
            put_greeks = extract_greeks_from_data(put_option_greeks)
            put_iv = put_greeks.get('iv')
            put_delta = put_greeks.get('delta')
        
        # 4. 根据简化规则生成信号
        # 规则1：买入Call信号
        # 条件：日线RSI < 40（超卖）+ 实时价格变化 > 0.5%（上涨）+ 开盘策略趋势 = 强势
        rule1_conditions = {
            'trend_ok': overall_trend == "强势",
            'strength_ok': trend_strength >= 0.7,
            'direction_ok': strategy_direction == "偏多",
            'rsi_ok': latest_rsi is not None and latest_rsi < rsi_oversold,
            'price_change_ok': latest_price_change is not None and latest_price_change > 0.5,
            'iv_ok': call_iv is None or call_iv < 50  # IV不太高
        }
        
        rule1_triggered = (rule1_conditions['trend_ok'] 
                          and rule1_conditions['strength_ok']
                          and rule1_conditions['direction_ok']
                          and rule1_conditions['rsi_ok']
                          and rule1_conditions['price_change_ok']
                          and rule1_conditions['iv_ok'])
        
        if rule1_triggered and call_option_price is not None:
            # 计算信号强度
            strength = 0.5
            if latest_rsi < 30:
                strength += 0.2
            if latest_price_change > 1.0:
                strength += 0.2
            if trend_strength >= 0.8:
                strength += 0.1
            
            signal = create_signal_with_volatility_range(
                signal_type='call',
                reason='降级方案：日线超卖+价格上涨+强势趋势',
                rsi=latest_rsi or 50,
                price_change=latest_price_change or 0,
                trend=overall_trend,
                strength=min(1.0, strength),
                signal_type_label='中等信号',
                volatility_ranges=volatility_ranges or {},
                etf_current_price=etf_current_price,
                call_option_price=call_option_price,
                deduplication_time=deduplication_time,
                position_size='中等'
            )
            if signal:
                signals.append(signal)
        
        # 规则2：买入Put信号
        # 条件：日线RSI > 60（超买）+ 实时价格变化 < -0.5%（下跌）+ 开盘策略趋势 = 弱势
        rule2_conditions = {
            'trend_ok': overall_trend == "弱势",
            'strength_ok': trend_strength >= 0.7,
            'direction_ok': strategy_direction == "偏空",
            'rsi_ok': latest_rsi is not None and latest_rsi > rsi_overbought,
            'price_change_ok': latest_price_change is not None and latest_price_change < -0.5,
            'iv_ok': put_iv is None or put_iv < 50  # IV不太高
        }
        
        rule2_triggered = (rule2_conditions['trend_ok']
                          and rule2_conditions['strength_ok']
                          and rule2_conditions['direction_ok']
                          and rule2_conditions['rsi_ok']
                          and rule2_conditions['price_change_ok']
                          and rule2_conditions['iv_ok'])
        
        if rule2_triggered and put_option_price is not None:
            # 计算信号强度
            strength = 0.5
            if latest_rsi > 70:
                strength += 0.2
            if latest_price_change < -1.0:
                strength += 0.2
            if trend_strength >= 0.8:
                strength += 0.1
            
            signal = create_signal_with_volatility_range(
                signal_type='put',
                reason='降级方案：日线超买+价格下跌+弱势趋势',
                rsi=latest_rsi or 50,
                price_change=latest_price_change or 0,
                trend=overall_trend,
                strength=min(1.0, strength),
                signal_type_label='中等信号',
                volatility_ranges=volatility_ranges or {},
                etf_current_price=etf_current_price,
                put_option_price=put_option_price,
                deduplication_time=deduplication_time,
                position_size='中等'
            )
            if signal:
                signals.append(signal)
        
        logger.info(f"降级方案信号生成完成，共生成 {len(signals)} 个信号")
        return signals
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'generate_signals_fallback'},
            "降级方案信号生成失败"
        )
        return []


def calculate_daily_indicators(
    index_daily_data: pd.DataFrame,
    etf_daily_data: pd.DataFrame,
    etf_current_price: float
) -> Optional[Dict[str, Any]]:
    """
    计算日线级别的技术指标
    
    Args:
        index_daily_data: 指数日线数据
        etf_daily_data: ETF日线数据
        etf_current_price: ETF当前价格
    
    Returns:
        dict: 包含RSI、MACD、价格变化率等技术指标
    """
    try:
        result = {}
        
        # 确定收盘价列名
        index_close_col = None
        etf_close_col = None
        
        for col in ['收盘', 'close', '收盘价', 'CLOSE']:
            if index_close_col is None and col in index_daily_data.columns:
                index_close_col = col
            if etf_close_col is None and col in etf_daily_data.columns:
                etf_close_col = col
        
        if index_close_col is None or etf_close_col is None:
            logger.warning("无法找到收盘价列")
            return None
        
        # 计算RSI（基于指数日线数据，14日）
        rsi_series = calculate_rsi(
            index_daily_data,
            period=14,
            close_col=index_close_col
        )
        if rsi_series is not None and not rsi_series.empty:
            result['rsi'] = float(rsi_series.iloc[-1])
        else:
            result['rsi'] = None
        
        # 计算MACD（基于指数日线数据）
        macd_result = calculate_macd(
            index_daily_data,
            fast=12,
            slow=26,
            signal=9,
            close_col=index_close_col
        )
        if macd_result is not None:
            macd_line = macd_result.get('macd')
            signal_line = macd_result.get('signal')
            histogram = macd_result.get('histogram')
            
            if macd_line is not None and not macd_line.empty:
                result['macd'] = float(macd_line.iloc[-1])
            if signal_line is not None and not signal_line.empty:
                result['macd_signal'] = float(signal_line.iloc[-1])
            if histogram is not None and not histogram.empty:
                result['macd_histogram'] = float(histogram.iloc[-1])
        else:
            result['macd'] = None
            result['macd_signal'] = None
            result['macd_histogram'] = None
        
        # 获取昨日收盘价
        yesterday_close = float(etf_daily_data[etf_close_col].iloc[-1])
        result['yesterday_close'] = yesterday_close
        
        # 计算实时价格变化率（相对于昨日收盘价）
        if yesterday_close > 0:
            price_change_pct = (etf_current_price - yesterday_close) / yesterday_close * 100
            result['price_change_pct'] = price_change_pct
        else:
            result['price_change_pct'] = 0.0
        
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_daily_indicators'},
            "计算日线技术指标失败"
        )
        return None


def calculate_realtime_price_change(
    etf_current_price: float,
    yesterday_close: float
) -> float:
    """
    计算实时价格变化率（相对于昨日收盘价）
    
    Args:
        etf_current_price: ETF当前价格
        yesterday_close: 昨日收盘价
    
    Returns:
        float: 价格变化率（%）
    """
    try:
        if yesterday_close > 0:
            return (etf_current_price - yesterday_close) / yesterday_close * 100
        else:
            return 0.0
    except Exception as e:
        logger.warning(f"计算实时价格变化率失败: {e}")
        return 0.0
