"""
降级波动区间预测模块
当分钟数据不可用时，使用日线数据和实时数据进行波动区间预测
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional, Any, List
import pytz

from src.logger_config import get_module_logger, log_error_with_context
from src.indicator_calculator import (
    calculate_atr, calculate_historical_volatility, calculate_bollinger_bands
)
from src.volatility_range import (
    get_remaining_trading_time, extract_greeks_from_data, calculate_option_volatility_range
)
from src.config_loader import load_system_config

logger = get_module_logger(__name__)


def calculate_volatility_ranges_fallback(
    etf_daily_data: pd.DataFrame,
    index_daily_data: pd.DataFrame,
    etf_current_price: float,
    call_option_price: Optional[float] = None,
    put_option_price: Optional[float] = None,
    call_option_greeks: Optional[pd.DataFrame] = None,
    put_option_greeks: Optional[pd.DataFrame] = None,
    opening_strategy: Optional[Dict] = None,
    previous_volatility_ranges: Optional[Dict] = None,
    config: Optional[Dict] = None,
    call_contract_code: Optional[str] = None,
    put_contract_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    降级方案：基于日线数据的波动区间预测
    
    方法：
    1. 使用日线数据计算历史波动率（20日）
    2. 使用日线数据计算ATR（14日）
    3. 使用实时价格计算当前价格位置
    4. 结合开盘策略的趋势判断
    5. 利用已保存的波动区间数据（如果有）进行校准
    6. 使用期权Greeks数据（IV、Delta）计算期权波动区间
    
    Args:
        etf_daily_data: ETF日线数据
        index_daily_data: 指数日线数据
        etf_current_price: ETF当前价格
        call_option_price: Call期权当前价格
        put_option_price: Put期权当前价格
        call_option_greeks: Call期权Greeks数据
        put_option_greeks: Put期权Greeks数据
        opening_strategy: 开盘策略（包含整体趋势判断）
        previous_volatility_ranges: 已保存的波动区间数据（如果有）
        config: 系统配置
        call_contract_code: Call期权合约代码
        put_contract_code: Put期权合约代码
    
    Returns:
        dict: 波动区间预测结果，格式与正常方案相同
    """
    try:
        logger.info("使用降级方案计算波动区间（基于日线数据）...")
        
        if config is None:
            config = load_system_config()
        
        # 计算剩余交易时间
        remaining_minutes = get_remaining_trading_time(config)
        remaining_ratio = remaining_minutes / 240.0 if remaining_minutes > 0 else 0
        
        # 1. 计算指数波动区间（基于日线数据）
        index_range = calculate_index_volatility_range_fallback(
            index_daily_data,
            remaining_minutes,
            config=config
        )
        
        # 2. 计算ETF波动区间（基于日线数据）
        etf_range = calculate_etf_volatility_range_fallback(
            etf_daily_data,
            etf_current_price,
            remaining_minutes,
            opening_strategy=opening_strategy,
            previous_volatility_ranges=previous_volatility_ranges,
            config=config
        )
        
        # 3. 计算期权波动区间（基于ETF波动区间 + Greeks）
        call_ranges = []
        put_ranges = []
        
        # 获取合约配置
        from src.config_loader import get_contract_codes
        call_contracts_config = get_contract_codes(config, 'call', verify_strike=False) if call_contract_code is None else None
        put_contracts_config = get_contract_codes(config, 'put', verify_strike=False) if put_contract_code is None else None
        
        # 向后兼容：如果使用旧的单个合约参数
        if call_contract_code is not None:
            call_contracts_config = [{'contract_code': call_contract_code, 'strike_price': None, 'expiry_date': None, 'name': call_contract_code}]
        elif not call_contracts_config:
            from src.config_loader import get_contract_code
            old_call_code = get_contract_code(config, 'call', verify_strike=False)
            if old_call_code:
                call_contracts_config = [{'contract_code': old_call_code, 'strike_price': None, 'expiry_date': None, 'name': old_call_code}]
        
        if put_contract_code is not None:
            put_contracts_config = [{'contract_code': put_contract_code, 'strike_price': None, 'expiry_date': None, 'name': put_contract_code}]
        elif not put_contracts_config:
            from src.config_loader import get_contract_code
            old_put_code = get_contract_code(config, 'put', verify_strike=False)
            if old_put_code:
                put_contracts_config = [{'contract_code': old_put_code, 'strike_price': None, 'expiry_date': None, 'name': old_put_code}]
        
        # 计算Call期权波动区间
        if call_contracts_config and call_option_price is not None and call_option_greeks is not None:
            for contract_config in call_contracts_config:
                contract_code = contract_config.get('contract_code')
                strike_price = contract_config.get('strike_price')
                
                # 提取行权价（如果Greeks中有）
                if strike_price is None and call_option_greeks is not None:
                    greeks = extract_greeks_from_data(call_option_greeks)
                    # 尝试从Greeks数据中提取行权价
                    for idx, row in call_option_greeks.iterrows():
                        field = str(row.get('字段', ''))
                        if '行权价' in field or 'strike' in field.lower():
                            try:
                                strike_price = float(row.get('值', 0))
                                break
                            except (ValueError, TypeError):
                                pass
                
                call_range = calculate_option_volatility_range_fallback(
                    'call',
                    call_option_price,
                    etf_range,
                    call_option_greeks,
                    strike_price=strike_price,
                    remaining_minutes=remaining_minutes,
                    config=config,
                    contract_code=contract_code
                )
                if call_range:
                    call_range['contract_code'] = contract_code
                    call_range['name'] = contract_config.get('name', contract_code)
                    if strike_price:
                        call_range['strike_price'] = strike_price
                    call_ranges.append(call_range)
        
        # 计算Put期权波动区间
        if put_contracts_config and put_option_price is not None and put_option_greeks is not None:
            for contract_config in put_contracts_config:
                contract_code = contract_config.get('contract_code')
                strike_price = contract_config.get('strike_price')
                
                # 提取行权价（如果Greeks中有）
                if strike_price is None and put_option_greeks is not None:
                    for idx, row in put_option_greeks.iterrows():
                        field = str(row.get('字段', ''))
                        if '行权价' in field or 'strike' in field.lower():
                            try:
                                strike_price = float(row.get('值', 0))
                                break
                            except (ValueError, TypeError):
                                pass
                
                put_range = calculate_option_volatility_range_fallback(
                    'put',
                    put_option_price,
                    etf_range,
                    put_option_greeks,
                    strike_price=strike_price,
                    remaining_minutes=remaining_minutes,
                    config=config,
                    contract_code=contract_code
                )
                if put_range:
                    put_range['contract_code'] = contract_code
                    put_range['name'] = contract_config.get('name', contract_code)
                    if strike_price:
                        put_range['strike_price'] = strike_price
                    put_ranges.append(put_range)
        
        result = {
            'index_range': index_range,
            'etf_range': etf_range,
            'call_ranges': call_ranges,
            'put_ranges': put_ranges,
            'method': '降级方案（日线数据）',
            'fallback_reason': '分钟数据不可用'
        }
        
        logger.info(f"降级方案波动区间计算完成: ETF区间={etf_range.get('range_pct', 0):.2f}%, "
                   f"Call区间={len(call_ranges)}个, Put区间={len(put_ranges)}个")
        
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_volatility_ranges_fallback'},
            "降级方案波动区间计算失败"
        )
        # 返回默认值
        return {
            'index_range': {'current_price': 4000.0, 'upper': 4080.0, 'lower': 3920.0, 'range_pct': 2.0},
            'etf_range': {'current_price': etf_current_price or 4.8, 'upper': (etf_current_price or 4.8) * 1.02, 
                         'lower': (etf_current_price or 4.8) * 0.98, 'range_pct': 2.0},
            'call_ranges': [],
            'put_ranges': [],
            'method': '降级方案（默认值）',
            'fallback_reason': f'计算失败: {str(e)}'
        }


def calculate_index_volatility_range_fallback(
    index_daily_data: pd.DataFrame,
    remaining_minutes: int,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    基于日线数据计算指数波动区间（降级方案）
    
    Args:
        index_daily_data: 指数日线数据
        remaining_minutes: 剩余交易时间（分钟）
        config: 系统配置
    
    Returns:
        dict: 指数波动区间
    """
    try:
        if index_daily_data is None or index_daily_data.empty:
            logger.warning("指数日线数据为空，使用默认值")
            return {
                'symbol': '000300',
                'current_price': 4000.0,
                'upper': 4080.0,
                'lower': 3920.0,
                'range_pct': 2.0,
                'method': '默认值',
                'confidence': 0.3
            }
        
        # 确定收盘价列名
        close_col = None
        for col in ['收盘', 'close', '收盘价', 'CLOSE']:
            if col in index_daily_data.columns:
                close_col = col
                break
        
        if close_col is None:
            logger.warning("无法找到收盘价列，使用默认值")
            return {
                'symbol': '000300',
                'current_price': 4000.0,
                'upper': 4080.0,
                'lower': 3920.0,
                'range_pct': 2.0,
                'method': '默认值',
                'confidence': 0.3
            }
        
        # 获取当前价格（使用最新收盘价）
        current_price = float(index_daily_data[close_col].iloc[-1])
        
        # 计算历史波动率（20日）
        hist_vol = calculate_historical_volatility(
            index_daily_data,
            period=20,
            close_col=close_col,
            data_period='day'
        )
        hist_vol = hist_vol if hist_vol is not None else 1.5  # 默认1.5%
        
        # 计算ATR（14日）
        high_col = None
        low_col = None
        for col in ['最高', 'high', '最高价', 'HIGH']:
            if col in index_daily_data.columns:
                high_col = col
                break
        for col in ['最低', 'low', '最低价', 'LOW']:
            if col in index_daily_data.columns:
                low_col = col
                break
        
        atr_value = None
        if high_col and low_col:
            atr_series = calculate_atr(
                index_daily_data,
                period=14,
                high_col=high_col,
                low_col=low_col,
                close_col=close_col
            )
            if atr_series is not None and not atr_series.empty:
                atr_value = float(atr_series.iloc[-1])
        
        atr_value = atr_value if atr_value is not None else current_price * 0.01  # 默认1%
        
        # 计算剩余交易时间比例
        remaining_ratio = remaining_minutes / 240.0 if remaining_minutes > 0 else 0
        
        # 基于ATR计算波动区间
        atr_multiplier = 2.0 * np.sqrt(remaining_ratio)  # 根据剩余时间调整
        atr_upper = current_price + atr_value * atr_multiplier
        atr_lower = current_price - atr_value * atr_multiplier
        
        # 基于历史波动率计算波动区间
        hist_vol_range = current_price * (hist_vol / 100) * np.sqrt(remaining_ratio)
        hist_vol_upper = current_price + hist_vol_range
        hist_vol_lower = current_price - hist_vol_range
        
        # 综合计算（加权平均）
        upper = atr_upper * 0.6 + hist_vol_upper * 0.4
        lower = atr_lower * 0.6 + hist_vol_lower * 0.4
        
        range_pct = (upper - lower) / current_price * 100
        
        return {
            'symbol': '000300',
            'current_price': current_price,
            'upper': upper,
            'lower': lower,
            'range_pct': range_pct,
            'method': '降级方案（日线ATR+历史波动率）',
            'confidence': 0.6,  # 降级方案置信度较低
            'atr': atr_value,
            'historical_volatility': hist_vol
        }
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_index_volatility_range_fallback'},
            "计算指数波动区间失败"
        )
        return {
            'symbol': '000300',
            'current_price': 4000.0,
            'upper': 4080.0,
            'lower': 3920.0,
            'range_pct': 2.0,
            'method': '默认值',
            'confidence': 0.3
        }


def calculate_etf_volatility_range_fallback(
    etf_daily_data: pd.DataFrame,
    etf_current_price: float,
    remaining_minutes: int,
    opening_strategy: Optional[Dict] = None,
    previous_volatility_ranges: Optional[Dict] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    基于日线数据计算ETF波动区间（降级方案）
    
    Args:
        etf_daily_data: ETF日线数据
        etf_current_price: ETF当前价格
        remaining_minutes: 剩余交易时间（分钟）
        opening_strategy: 开盘策略（包含整体趋势判断）
        previous_volatility_ranges: 已保存的波动区间数据（如果有）
        config: 系统配置
    
    Returns:
        dict: ETF波动区间
    """
    try:
        if etf_daily_data is None or etf_daily_data.empty:
            logger.warning("ETF日线数据为空，使用默认值")
            return {
                'symbol': '510300',
                'current_price': etf_current_price,
                'upper': etf_current_price * 1.02,
                'lower': etf_current_price * 0.98,
                'range_pct': 2.0,
                'method': '默认值',
                'confidence': 0.3
            }
        
        # 确定收盘价列名
        close_col = None
        for col in ['收盘', 'close', '收盘价', 'CLOSE']:
            if col in etf_daily_data.columns:
                close_col = col
                break
        
        if close_col is None:
            logger.warning("无法找到收盘价列，使用默认值")
            return {
                'symbol': '510300',
                'current_price': etf_current_price,
                'upper': etf_current_price * 1.02,
                'lower': etf_current_price * 0.98,
                'range_pct': 2.0,
                'method': '默认值',
                'confidence': 0.3
            }
        
        # 获取昨日收盘价
        yesterday_close = float(etf_daily_data[close_col].iloc[-1])
        
        # 计算历史波动率（20日）
        hist_vol = calculate_historical_volatility(
            etf_daily_data,
            period=20,
            close_col=close_col,
            data_period='day'
        )
        hist_vol = hist_vol if hist_vol is not None else 1.5  # 默认1.5%
        
        # 计算ATR（14日）
        high_col = None
        low_col = None
        for col in ['最高', 'high', '最高价', 'HIGH']:
            if col in etf_daily_data.columns:
                high_col = col
                break
        for col in ['最低', 'low', '最低价', 'LOW']:
            if col in etf_daily_data.columns:
                low_col = col
                break
        
        atr_value = None
        if high_col and low_col:
            atr_series = calculate_atr(
                etf_daily_data,
                period=14,
                high_col=high_col,
                low_col=low_col,
                close_col=close_col
            )
            if atr_series is not None and not atr_series.empty:
                atr_value = float(atr_series.iloc[-1])
        
        atr_value = atr_value if atr_value is not None else etf_current_price * 0.01  # 默认1%
        
        # 计算剩余交易时间比例
        remaining_ratio = remaining_minutes / 240.0 if remaining_minutes > 0 else 0
        
        # 基于ATR计算波动区间
        atr_multiplier = 2.0 * np.sqrt(remaining_ratio)
        atr_upper = etf_current_price + atr_value * atr_multiplier
        atr_lower = etf_current_price - atr_value * atr_multiplier
        
        # 基于历史波动率计算波动区间
        hist_vol_range = etf_current_price * (hist_vol / 100) * np.sqrt(remaining_ratio)
        hist_vol_upper = etf_current_price + hist_vol_range
        hist_vol_lower = etf_current_price - hist_vol_range
        
        # 结合开盘策略调整（如果有）
        trend_adjustment = 1.0
        if opening_strategy:
            overall_trend = opening_strategy.get('final_trend', '震荡')
            trend_strength = opening_strategy.get('final_strength', 0.5)
            
            # 如果趋势强势，扩大波动区间
            if overall_trend == "强势" and trend_strength >= 0.7:
                trend_adjustment = 1.1  # 扩大10%
            elif overall_trend == "弱势" and trend_strength >= 0.7:
                trend_adjustment = 1.1  # 弱势也可能波动较大
        
        # 利用已保存的波动区间数据进行校准（如果有）
        calibration_factor = 1.0
        if previous_volatility_ranges:
            prev_etf_range = previous_volatility_ranges.get('etf_range', {})
            if prev_etf_range:
                prev_range_pct = prev_etf_range.get('range_pct', 2.0)
                # 如果之前的区间较大，适当扩大当前区间
                if prev_range_pct > 2.5:
                    calibration_factor = 1.05
        
        # 综合计算（加权平均）
        upper = (atr_upper * 0.6 + hist_vol_upper * 0.4) * trend_adjustment * calibration_factor
        lower = (atr_lower * 0.6 + hist_vol_lower * 0.4) * trend_adjustment * calibration_factor
        
        range_pct = (upper - lower) / etf_current_price * 100
        
        return {
            'symbol': '510300',
            'current_price': etf_current_price,
            'upper': upper,
            'lower': lower,
            'range_pct': range_pct,
            'method': '降级方案（日线ATR+历史波动率+趋势调整）',
            'confidence': 0.6,  # 降级方案置信度较低
            'atr': atr_value,
            'historical_volatility': hist_vol,
            'yesterday_close': yesterday_close,
            'price_change_pct': (etf_current_price - yesterday_close) / yesterday_close * 100 if yesterday_close > 0 else 0
        }
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_etf_volatility_range_fallback'},
            "计算ETF波动区间失败"
        )
        return {
            'symbol': '510300',
            'current_price': etf_current_price,
            'upper': etf_current_price * 1.02,
            'lower': etf_current_price * 0.98,
            'range_pct': 2.0,
            'method': '默认值',
            'confidence': 0.3
        }


def calculate_option_volatility_range_fallback(
    option_type: str,
    option_current_price: float,
    etf_range: Dict[str, Any],
    option_greeks: Optional[pd.DataFrame] = None,
    strike_price: Optional[float] = None,
    remaining_minutes: Optional[int] = None,
    config: Optional[Dict] = None,
    contract_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    基于ETF波动区间和期权Greeks计算期权波动区间（降级方案）
    
    Args:
        option_type: "call" 或 "put"
        option_current_price: 期权当前价格
        etf_range: ETF波动区间
        option_greeks: 期权Greeks数据
        strike_price: 行权价
        remaining_minutes: 剩余交易时间（分钟）
        config: 系统配置
        contract_code: 合约代码
    
    Returns:
        dict: 期权波动区间
    """
    try:
        # 使用现有的calculate_option_volatility_range函数，但标记为降级方案
        option_range = calculate_option_volatility_range(
            option_type=option_type,
            option_current_price=option_current_price,
            etf_range=etf_range,
            option_greeks=option_greeks,
            strike_price=strike_price,
            remaining_minutes=remaining_minutes,
            config=config,
            contract_code=contract_code
        )
        
        if option_range:
            option_range['method'] = '降级方案（基于ETF区间+Greeks）'
            option_range['confidence'] = option_range.get('confidence', 0.6) * 0.9  # 降低置信度
        
        return option_range
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_option_volatility_range_fallback', 'option_type': option_type},
            "计算期权波动区间失败"
        )
        # 返回基于ETF区间的简单估算
        etf_current = etf_range.get('current_price', 4.8)
        etf_upper = etf_range.get('upper', etf_current * 1.02)
        etf_lower = etf_range.get('lower', etf_current * 0.98)
        
        # 简单估算：期权波动区间约为ETF波动区间的1.5-2倍（考虑杠杆）
        leverage = 1.8
        option_range_pct = etf_range.get('range_pct', 2.0) * leverage
        
        return {
            'contract_code': contract_code,
            'option_type': option_type,
            'current_price': option_current_price,
            'upper': option_current_price * (1 + option_range_pct / 100),
            'lower': max(0, option_current_price * (1 - option_range_pct / 100)),
            'range_pct': option_range_pct,
            'method': '降级方案（简单估算）',
            'confidence': 0.4
        }
