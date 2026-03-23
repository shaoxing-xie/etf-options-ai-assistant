"""
信号生成模块
根据技术指标和趋势分析生成交易信号
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List
import pytz
import json
import re
import time

from src.logger_config import get_module_logger, log_error_with_context
from src.indicator_calculator import calculate_rsi, calculate_price_change_rate, calculate_macd, calculate_ma
from src.config_loader import load_system_config
from src.data_collector import fetch_etf_daily_em

logger = get_module_logger(__name__)

# 信号去重缓存（内存中）
_signal_cache: Dict[str, datetime] = {}

# LLM增强信号生成缓存（用于调用频率限制）
_llm_watch_cache: Dict[str, Dict[str, Any]] = {}


def generate_signals(
    index_minute: pd.DataFrame,
    etf_current_price: float,
    call_option_price: Optional[float] = None,
    put_option_price: Optional[float] = None,
    call_option_greeks: Optional[pd.DataFrame] = None,
    put_option_greeks: Optional[pd.DataFrame] = None,
    opening_strategy: Optional[Dict] = None,
    volatility_ranges: Optional[Dict] = None,
    config: Optional[Dict] = None,
    call_option_minute: Optional[pd.DataFrame] = None,  # 兼容参数：本轮排查暂不使用期权分钟技术指标
    put_option_minute: Optional[pd.DataFrame] = None  # 兼容参数：本轮排查暂不使用期权分钟技术指标
) -> List[Dict[str, Any]]:
    """
    生成交易信号（主函数，集成期权分钟数据）
    
    Args:
        index_minute: 指数分钟数据
        etf_current_price: ETF当前价格
        call_option_price: Call期权当前价格
        put_option_price: Put期权当前价格
        call_option_greeks: Call期权Greeks数据
        put_option_greeks: Put期权Greeks数据
        opening_strategy: 开盘策略（包含整体趋势判断）
        volatility_ranges: 波动区间预测结果
        config: 系统配置
        call_option_minute: Call期权分钟K线数据（可选）。为恢复到 20260123 行为，本轮排查默认不使用期权分钟技术指标。
        put_option_minute: Put期权分钟K线数据（可选）。为恢复到 20260123 行为，本轮排查默认不使用期权分钟技术指标。
    
    Returns:
        list: 信号列表
    """
    # 初始化规则条件字典，避免在日志格式化时出现None值错误
    rule1_conditions = {}
    rule2_conditions = {}
    rule1_triggered = False
    rule2_triggered = False
    
    try:
        logger.info("开始生成交易信号...")
        
        if config is None:
            config = load_system_config()
        
        signal_params = config.get('signal_params', {})
        
        # 检查是否启用优化方案v1.0
        use_optimized_v1 = signal_params.get('use_optimized_v1', False)  # 默认False，保持原有逻辑
        
        if use_optimized_v1:
            # 使用优化方案v1.0
            return _generate_signals_optimized_v1(
                index_minute=index_minute,
                etf_current_price=etf_current_price,
                call_option_price=call_option_price,
                put_option_price=put_option_price,
                call_option_greeks=call_option_greeks,
                put_option_greeks=put_option_greeks,
                opening_strategy=opening_strategy,
                volatility_ranges=volatility_ranges,
                config=config
            )
        
        # 原有逻辑（保持不变）
        rsi_oversold = signal_params.get('rsi_oversold', 40)
        rsi_overbought = signal_params.get('rsi_overbought', 60)
        price_change_threshold = signal_params.get('price_change_threshold', 1.5)
        deduplication_time = signal_params.get('signal_deduplication_time', 1800)

        # 从配置中读取高级参数（有默认值，未配置时保持当前行为）
        min_trend_strength = signal_params.get('min_trend_strength_strong', 0.7)
        min_signal_strength = signal_params.get('min_signal_strength', 0.6)

        boundary_price_mult = signal_params.get('boundary_price_mult', 1.2)
        boundary_conf_min = signal_params.get('boundary_confidence_min', 0.6)
        boundary_base_strength = signal_params.get('boundary_base_strength', 0.45)
        
        signals: List[Dict[str, Any]] = []
        
        if index_minute is None or index_minute.empty:
            logger.warning("指数分钟数据为空，无法生成信号")
            return signals
        
        # 1. 计算技术指标（ETF/指数）
        rsi = calculate_rsi(index_minute, close_col='收盘')
        price_change = calculate_price_change_rate(index_minute, close_col='收盘')
        
        if rsi is None or price_change is None:
            logger.warning("技术指标计算失败，无法生成信号")
            return signals
        
        latest_rsi = rsi.iloc[-1]
        latest_price_change = price_change.iloc[-1]
        
        # ========== 恢复到 20260123 行为：本轮排查默认不使用期权分钟技术指标 ==========
        # 为避免“期权分钟RSI/趋势”导致信号过少，本轮直接忽略 call_option_minute / put_option_minute。
        # call_option_minute / put_option_minute 本轮不使用（保留注释即可）
        
        # 2. 获取整体趋势和开盘策略（从开盘策略）
        overall_trend = opening_strategy.get('final_trend', '震荡') if opening_strategy else '震荡'
        trend_strength = opening_strategy.get('final_strength', 0.5) if opening_strategy else 0.5
        opening_strategy_detail = opening_strategy.get('opening_strategy', {}) if opening_strategy else {}
        strategy_direction = opening_strategy_detail.get('direction', '谨慎')  # "偏多"、"偏空"、"谨慎"
        position_size = opening_strategy_detail.get('position_size', '较小')
        # signal_threshold 本轮未使用（保留用于后续规则扩展）
        
        # 调试日志：记录信号生成的关键参数
        logger.info(f"信号生成参数: 趋势={overall_trend}, 强度={trend_strength:.2f}, 方向={strategy_direction}, "
                   f"RSI={latest_rsi:.2f}, 价格变动={latest_price_change:.2f}%, 阈值={price_change_threshold}%")
        
        # 3. 获取多个合约的IV数据（支持多个合约）
        # 统一使用列表格式处理多合约Greeks数据
        call_greeks_list = []
        put_greeks_list = []
        
        if call_option_greeks is not None and not call_option_greeks.empty:
            call_greeks_list = [call_option_greeks]
        
        if put_option_greeks is not None and not put_option_greeks.empty:
            put_greeks_list = [put_option_greeks]
        
        # 4. 分析价格在波动区间中的位置（如果波动区间可用）
        etf_position = None  # 价格在波动区间中的位置（0-1，0为下轨，1为上轨）
        if volatility_ranges and volatility_ranges.get('etf_range'):
            etf_range = volatility_ranges['etf_range']
            etf_upper = etf_range.get('upper')
            etf_lower = etf_range.get('lower')
            if etf_upper is not None and etf_lower is not None and etf_upper > etf_lower:
                etf_position = (etf_current_price - etf_lower) / (etf_upper - etf_lower)
                logger.debug(f"ETF价格在波动区间中的位置: {etf_position:.2f} (0=下轨, 1=上轨)")
        
        # 5. 获取多个合约的波动区间（支持多个合约）
        call_ranges = []
        put_ranges = []
        if volatility_ranges:
            # 使用新格式（多合约格式）
            call_ranges = volatility_ranges.get('call_ranges', [])
            put_ranges = volatility_ranges.get('put_ranges', [])
            # 向后兼容：旧格式 call_range / put_range
            if not call_ranges and volatility_ranges.get('call_range'):
                call_ranges = [volatility_ranges.get('call_range')]
            if not put_ranges and volatility_ranges.get('put_range'):
                put_ranges = [volatility_ranges.get('put_range')]
        
        # 初始化IV变量（用于规则3）
        call_iv = None
        put_iv = None
        # 20260123 行为：rule1/rule2 允许用 iv_ok 替代 price_change_ok
        call_iv_any = extract_iv_from_greeks(call_option_greeks) if call_option_greeks is not None and not call_option_greeks.empty else None
        put_iv_any = extract_iv_from_greeks(put_option_greeks) if put_option_greeks is not None and not put_option_greeks.empty else None
        
        # 6. 根据信号规则生成信号（恢复到 20260123 行为：不考虑期权分钟技术指标）
        # 规则1：上行趋势 + 超卖 + 大波动 + 价格接近下轨 → 买 Call
        rule1_conditions = {
            'trend_ok': overall_trend == "强势",
            'strength_ok': trend_strength >= min_trend_strength,
            'direction_ok': strategy_direction == "偏多",
            'rsi_ok': latest_rsi < rsi_oversold,
            'price_change_ok': abs(latest_price_change) > price_change_threshold,
            'iv_ok': call_iv_any is not None and call_iv_any > 0,
        }
        rule1_triggered = (
            rule1_conditions['trend_ok']
            and rule1_conditions['strength_ok']
            and rule1_conditions['direction_ok']
            and rule1_conditions['rsi_ok']
            and (rule1_conditions['price_change_ok'] or rule1_conditions['iv_ok'])
        )
        
        if rule1_triggered:
            # 为每个Call合约生成信号
            for i, call_range in enumerate(call_ranges):
                # 获取该合约的IV（更新外层变量）
                if i < len(call_greeks_list) and call_greeks_list[i] is not None:
                    call_iv = extract_iv_from_greeks(call_greeks_list[i])
                else:
                    call_iv = None
                
                # 根据价格位置调整信号强度
                adjusted_strength = trend_strength
                signal_type_label = "中等信号"
                
                if etf_position is not None:
                    if etf_position < 0.3:  # 价格在下轨附近（30%区间内）
                        adjusted_strength = trend_strength * 1.2  # 增强20%
                        signal_type_label = "强信号"
                    elif etf_position < 0.5:  # 价格在下半区间
                        adjusted_strength = trend_strength * 1.0  # 正常强度
                        signal_type_label = "中等信号"
                    else:  # 价格在中部或上半区间
                        adjusted_strength = trend_strength * 0.7  # 降低强度
                        signal_type_label = "弱信号"
                
                # 20260123 行为：不做期权分钟技术指标加减分
                
                # 至少达到“中等”强度才生成信号（阈值可在 config.yaml 中配置）
                if adjusted_strength >= min_signal_strength:
                    # 获取该合约的价格
                    contract_price = call_range.get('current_price') or call_option_price
                    contract_code = call_range.get('contract_code')
                    contract_name = call_range.get('name', contract_code or f'Call{i+1}')
                    
                    # 创建该合约的波动区间（单个合约格式）
                    single_contract_volatility = {
                        'etf_range': volatility_ranges.get('etf_range') if volatility_ranges else None,
                        'call_ranges': [call_range],
                        'put_ranges': volatility_ranges.get('put_ranges', []) if volatility_ranges else []
                    }
                    
                    signal = create_signal_with_volatility_range(
                        signal_type='call',
                        reason=f'整体趋势强势，RSI超卖，价格变动大（合约：{contract_name}）',
                        rsi=latest_rsi,
                        price_change=latest_price_change,
                        trend=overall_trend,
                        strength=adjusted_strength,
                        signal_type_label=signal_type_label,
                        volatility_ranges=single_contract_volatility,
                        etf_current_price=etf_current_price,
                        call_option_price=contract_price,
                        deduplication_time=deduplication_time,
                        position_size=position_size
                    )
                    if signal:
                        # 添加合约信息
                        signal['contract_code'] = contract_code
                        signal['contract_name'] = contract_name
                        signals.append(signal)
            else:
                # 没有波动区间数据时，使用简化逻辑
                if abs(latest_price_change) > price_change_threshold:
                    signal = create_signal(
                        signal_type='call',
                        reason='整体趋势上行，RSI超卖，价格变动大（无波动区间数据）',
                        rsi=latest_rsi,
                        price_change=latest_price_change,
                        trend=overall_trend,
                        strength=trend_strength,
                        volatility_ranges=None,
                        deduplication_time=deduplication_time
                    )
                    if signal:
                        signals.append(signal)
        
        # 规则2：下行趋势 + 超买 + 大波动 + 价格接近上轨 → 买 Put
        rule2_conditions = {
            'trend_ok': overall_trend == "弱势",
            'strength_ok': trend_strength >= min_trend_strength,
            'direction_ok': strategy_direction == "偏空",
            'rsi_ok': latest_rsi > rsi_overbought,
            'price_change_ok': abs(latest_price_change) > price_change_threshold,
            'iv_ok': put_iv_any is not None and put_iv_any > 0,
        }
        rule2_triggered = (
            rule2_conditions['trend_ok']
            and rule2_conditions['strength_ok']
            and rule2_conditions['direction_ok']
            and rule2_conditions['rsi_ok']
            and (rule2_conditions['price_change_ok'] or rule2_conditions['iv_ok'])
        )
        
        if rule2_triggered:
            # 为每个Put合约生成信号
            for i, put_range in enumerate(put_ranges):
                # 获取该合约的IV（更新外层变量）
                if i < len(put_greeks_list) and put_greeks_list[i] is not None:
                    put_iv = extract_iv_from_greeks(put_greeks_list[i])
                else:
                    put_iv = None
                
                # 检查波动区间
                if put_range:
                    # 根据价格位置调整信号强度
                    adjusted_strength = trend_strength
                    signal_type_label = "中等信号"
                    
                    if etf_position is not None:
                        if etf_position > 0.7:  # 价格在上轨附近（70%以上）
                            adjusted_strength = trend_strength * 1.2  # 增强20%
                            signal_type_label = "强信号"
                        elif etf_position > 0.5:  # 价格在上半区间
                            adjusted_strength = trend_strength * 1.0  # 正常强度
                            signal_type_label = "中等信号"
                        else:  # 价格在中部或下半区间
                            adjusted_strength = trend_strength * 0.7  # 降低强度
                            signal_type_label = "弱信号"
                    
                    # 20260123 行为：不做期权分钟技术指标加减分
                    
                    # 至少达到“中等”强度才生成信号（阈值可在 config.yaml 中配置）
                    if adjusted_strength >= min_signal_strength:
                        # 获取该合约的价格
                        contract_price = put_range.get('current_price') or put_option_price
                        contract_code = put_range.get('contract_code')
                        contract_name = put_range.get('name', contract_code or f'Put{i+1}')
                        
                        # 创建该合约的波动区间（单个合约格式）
                        single_contract_volatility = {
                            'etf_range': volatility_ranges.get('etf_range') if volatility_ranges else None,
                            'call_ranges': call_ranges if volatility_ranges else [],
                            'put_ranges': [put_range]
                        }
                        
                        signal = create_signal_with_volatility_range(
                            signal_type='put',
                            reason=f'整体趋势弱势，RSI超买，价格变动大（合约：{contract_name}）',
                            rsi=latest_rsi,
                            price_change=latest_price_change,
                            trend=overall_trend,
                            strength=adjusted_strength,
                            signal_type_label=signal_type_label,
                            volatility_ranges=single_contract_volatility,
                            etf_current_price=etf_current_price,
                            put_option_price=contract_price,
                            deduplication_time=deduplication_time,
                            position_size=position_size
                        )
                        if signal:
                            # 添加合约信息
                            signal['contract_code'] = contract_code
                            signal['contract_name'] = contract_name
                            signals.append(signal)
            else:
                # 没有波动区间数据时，使用简化逻辑
                if abs(latest_price_change) > price_change_threshold:
                    signal = create_signal(
                        signal_type='put',
                        reason='整体趋势下行，RSI超买，价格变动大（无波动区间数据）',
                        rsi=latest_rsi,
                        price_change=latest_price_change,
                        trend=overall_trend,
                        strength=trend_strength,
                        volatility_ranges=None,
                        deduplication_time=deduplication_time
                    )
                    if signal:
                        signals.append(signal)
        
        # 规则3：震荡趋势处理（结合波动区间）
        if (overall_trend == "震荡" 
            or trend_strength < 0.7 
            or strategy_direction == "谨慎"):
            
            if volatility_ranges and volatility_ranges.get('etf_range') and etf_position is not None:
                # 策略1：区间交易（价格在区间中部时）
                if 0.3 <= etf_position <= 0.7:
                    logger.debug("价格在波动区间中部，等待突破方向，暂不交易")
                    # 不生成趋势信号
                
                # 策略2：边界反弹（价格接近边界时，但趋势不明确）
                elif etf_position < 0.2 or etf_position > 0.8:
                    # 需要更严格的过滤条件
                    if (abs(latest_price_change) > price_change_threshold * boundary_price_mult
                        or (call_iv is not None and call_iv > 0) 
                        or (put_iv is not None and put_iv > 0)):
                        
                        etf_range = volatility_ranges['etf_range']
                        confidence = etf_range.get('confidence', 0.5)
                        
                        if confidence >= boundary_conf_min:
                            # 生成低权重信号（试探性仓位）
                            signal_strength = boundary_base_strength
                            signal_type_label = "边界反弹信号"
                            
                            # 根据价格位置决定信号类型
                            if etf_position < 0.2:  # 接近下轨，可能反弹向上
                                signal = create_signal_with_volatility_range(
                                    signal_type='call',
                                    reason='震荡市场，价格接近下轨，可能反弹',
                                    rsi=latest_rsi,
                                    price_change=latest_price_change,
                                    trend=overall_trend,
                                    strength=signal_strength,
                                    signal_type_label=signal_type_label,
                                    volatility_ranges=volatility_ranges,
                                    etf_current_price=etf_current_price,
                                    call_option_price=call_option_price,
                                    deduplication_time=deduplication_time,
                                    position_size="较小"  # 降低仓位
                                )
                            elif etf_position > 0.8:  # 接近上轨，可能回调向下
                                signal = create_signal_with_volatility_range(
                                    signal_type='put',
                                    reason='震荡市场，价格接近上轨，可能回调',
                                    rsi=latest_rsi,
                                    price_change=latest_price_change,
                                    trend=overall_trend,
                                    strength=signal_strength,
                                    signal_type_label=signal_type_label,
                                    volatility_ranges=volatility_ranges,
                                    etf_current_price=etf_current_price,
                                    put_option_price=put_option_price,
                                    deduplication_time=deduplication_time,
                                    position_size="较小"  # 降低仓位
                                )
                            else:
                                signal = None
                            
                            if signal:
                                signals.append(signal)
                        else:
                            logger.debug("价格接近边界，但置信度不足，暂不交易")
                    else:
                        logger.debug("价格接近边界，但触发条件不足，暂不交易")
                else:
                    logger.debug("震荡市场，等待趋势明确")
            else:
                # 没有波动区间数据时，降低信号生成频率
                # 提高触发阈值
                if abs(latest_price_change) > price_change_threshold * 1.33:  # 提高到2%
                    logger.debug("震荡市场且无波动区间数据，提高阈值，暂不生成信号")
        
        # 调试日志：记录规则检查结果
        if len(signals) == 0:
            # 安全地格式化条件字典，避免None值导致的格式化错误
            rule1_str = str(rule1_conditions) if rule1_conditions else 'N/A'
            rule2_str = str(rule2_conditions) if rule2_conditions else 'N/A'
            # 安全地格式化ETF位置，避免None值导致的格式化错误
            etf_position_str = f"{etf_position:.2f}" if etf_position is not None else 'N/A'
            logger.debug(f"信号生成规则检查: 规则1={rule1_triggered} {rule1_str}, "
                        f"规则2={rule2_triggered} {rule2_str}, "
                        f"规则3(震荡)={overall_trend == '震荡' or trend_strength < 0.7 or strategy_direction == '谨慎'}, "
                        f"ETF位置={etf_position_str}, "
                        f"波动区间置信度={volatility_ranges.get('etf_range', {}).get('confidence', 'N/A') if volatility_ranges and volatility_ranges.get('etf_range') else 'N/A'}")
        
        logger.info(f"生成 {len(signals)} 个交易信号")
        return signals
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'generate_signals'},
            "生成交易信号失败"
        )
        return []


def extract_iv_from_greeks(greeks_df: pd.DataFrame) -> Optional[float]:
    """
    从Greeks数据中提取隐含波动率（IV）
    
    Args:
        greeks_df: Greeks数据DataFrame
    
    Returns:
        float: IV值（%），如果未找到返回None
    """
    try:
        if greeks_df is None or greeks_df.empty:
            return None
        
        # 查找IV字段
        for idx, row in greeks_df.iterrows():
            field = str(row.get('字段', ''))
            if '波动率' in field or 'IV' in field or 'implied' in field.lower():
                value = row.get('值', '')
                try:
                    iv = float(value)
                    return iv
                except (ValueError, TypeError):
                    continue
        
        return None
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'extract_iv_from_greeks'},
            "提取IV失败"
        )
        return None


def create_signal_with_volatility_range(
    signal_type: str,
    reason: str,
    rsi: float,
    price_change: float,
    trend: str,
    strength: float,
    signal_type_label: str,
    volatility_ranges: Dict,
    etf_current_price: float,
    call_option_price: Optional[float] = None,
    put_option_price: Optional[float] = None,
    deduplication_time: int = 1800,
    position_size: str = "中等"
) -> Optional[Dict[str, Any]]:
    """
    创建交易信号（增强版 - 结合波动区间，包含目标位和止损位）
    
    Args:
        signal_type: "call" 或 "put"
        reason: 信号原因
        rsi: RSI值
        price_change: 价格变动率
        trend: 整体趋势
        strength: 信号强度（已根据价格位置调整）
        signal_type_label: 信号类型标签（"强信号"、"中等信号"、"弱信号"）
        volatility_ranges: 波动区间预测结果
        etf_current_price: ETF当前价格
        call_option_price: Call期权当前价格
        put_option_price: Put期权当前价格
        deduplication_time: 去重时间（秒）
        position_size: 仓位建议
    
    Returns:
        dict: 信号字典，如果重复则返回None
    """
    try:
        # 检查信号去重
        signal_key = f"{signal_type}_{reason[:20]}"
        now = datetime.now(pytz.timezone('Asia/Shanghai'))
        
        if signal_key in _signal_cache:
            last_time = _signal_cache[signal_key]
            time_diff = (now - last_time).total_seconds()
            if time_diff < deduplication_time:
                logger.debug(f"信号去重: {signal_key} (距离上次 {time_diff:.0f}秒)")
                return None
        
        # 从波动区间提取目标位和止损位
        target_price = None
        stop_loss = None
        target_etf_price = None
        expected_return_pct = None
        risk_reward_ratio = None
        
        if signal_type == 'call' and volatility_ranges.get('call_ranges') and call_option_price:
            call_ranges = volatility_ranges.get('call_ranges', [])
            call_range = call_ranges[0] if call_ranges else None
            if call_range:
                target_price = call_range.get('upper')  # Call期权的上轨作为目标位
                stop_loss = call_range.get('lower') * 0.8  # 下轨的80%作为止损位
                
                etf_range = volatility_ranges.get('etf_range', {})
                target_etf_price = etf_range.get('upper')  # ETF的上轨作为目标
                
                # 计算预期收益和风险收益比
                if target_price and call_option_price > 0:
                    expected_return_pct = ((target_price - call_option_price) / call_option_price) * 100
                    if call_option_price > stop_loss:
                        risk_reward_ratio = (target_price - call_option_price) / (call_option_price - stop_loss)
                    else:
                        risk_reward_ratio = 0
        
        elif signal_type == 'put' and volatility_ranges.get('put_ranges') and put_option_price:
            put_ranges = volatility_ranges.get('put_ranges', [])
            put_range = put_ranges[0] if put_ranges else None
            if put_range:
                target_price = put_range.get('upper')  # Put期权的上轨作为目标位
                stop_loss = put_range.get('lower') * 0.8  # 下轨的80%作为止损位
                
                etf_range = volatility_ranges.get('etf_range', {})
                target_etf_price = etf_range.get('lower')  # ETF的下轨作为目标
                
                # 计算预期收益和风险收益比
                if target_price and put_option_price > 0:
                    expected_return_pct = ((target_price - put_option_price) / put_option_price) * 100
                    if put_option_price > stop_loss:
                        risk_reward_ratio = (target_price - put_option_price) / (put_option_price - stop_loss)
                    else:
                        risk_reward_ratio = 0
        
        # 生成信号说明
        etf_price_str = f"{etf_current_price:.3f}" if etf_current_price is not None else "N/A"
        signal_description = f"整体趋势{trend}，ETF价格({etf_price_str})"
        if volatility_ranges and volatility_ranges.get('etf_range'):
            etf_range = volatility_ranges['etf_range']
            lower_bound = etf_range.get('lower')
            upper_bound = etf_range.get('upper')
            if signal_type == 'call':
                lower_str = f"{lower_bound:.3f}" if lower_bound is not None else "N/A"
                signal_description += f"接近下轨({lower_str})，"
            else:
                upper_str = f"{upper_bound:.3f}" if upper_bound is not None else "N/A"
                signal_description += f"接近上轨({upper_str})，"
        
        if target_etf_price:
            target_etf_str = f"{target_etf_price:.3f}" if target_etf_price is not None else "N/A"
            signal_description += f"预期ETF{'上涨' if signal_type == 'call' else '下跌'}至{target_etf_str}，"
        
        if target_price:
            target_str = f"{target_price:.3f}" if target_price is not None else "N/A"
            signal_description += f"{signal_type.upper()}期权目标位{target_str}，"
        
        if expected_return_pct is not None:
            signal_description += f"预期收益{expected_return_pct:.1f}%，"
        
        if risk_reward_ratio is not None:
            signal_description += f"风险收益比{risk_reward_ratio:.2f}"
        
        # 创建信号
        # 从signal_type推断方向：call=看涨，put=看跌
        direction = '看涨' if signal_type == 'call' else '看跌' if signal_type == 'put' else '未知'
        
        # 基础信号字段
        signal = {
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            'signal_type': signal_type,
            'action': f'买入{signal_type.upper()}期权',
            'reason': reason,
            'signal_type_label': signal_type_label,
            'rsi': round(rsi, 2),
            'price_change': round(price_change, 2),
            'trend': trend,
            'trend_strength': round(strength, 2),
            'direction': direction,  # 添加方向字段
            'signal_strength': round(strength, 2),  # 添加信号强度字段（与trend_strength相同）
            'position_size': position_size,
            'description': signal_description
        }
        # 用于日终/回测评估的基础价格与占位字段
        base_option_price = call_option_price if signal_type == 'call' else put_option_price
        signal['base_etf_price'] = etf_current_price
        signal['base_option_price'] = base_option_price
        # 预留评估字段（由日终评估脚本回填）
        signal['future_price_t15m'] = None
        signal['future_price_t2d'] = None
        signal['pnl_pct_t15m'] = None
        signal['pnl_pct_t2d'] = None
        signal['hit_take_profit'] = None
        signal['hit_stop_loss'] = None
        
        # 添加波动区间和目标位、止损位信息
        # 注意：使用实时期权价格，而不是波动区间计算时的价格
        if volatility_ranges:
            if signal_type == 'call' and volatility_ranges.get('call_ranges'):
                call_ranges = volatility_ranges.get('call_ranges', [])
                call_range = call_ranges[0] if call_ranges else None
                if call_range:
                    # 使用实时期权价格，如果获取失败则使用波动区间中的价格
                    current_price = call_option_price if call_option_price and call_option_price > 0 else call_range.get('current_price')
                    signal['volatility_range'] = {
                        'current': current_price,  # 使用实时价格
                        'upper': call_range.get('upper'),
                        'lower': call_range.get('lower'),
                        'range_pct': call_range.get('range_pct')
                    }
                    signal['target_price'] = target_price
                    signal['stop_loss'] = stop_loss
                    signal['target_etf_price'] = target_etf_price
                    signal['expected_return_pct'] = round(expected_return_pct, 2) if expected_return_pct is not None else None
                    signal['risk_reward_ratio'] = round(risk_reward_ratio, 2) if risk_reward_ratio is not None else None
            elif signal_type == 'put' and volatility_ranges.get('put_ranges'):
                put_ranges = volatility_ranges.get('put_ranges', [])
                put_range = put_ranges[0] if put_ranges else None
                if put_range:
                    # 使用实时期权价格，如果获取失败则使用波动区间中的价格
                    current_price = put_option_price if put_option_price and put_option_price > 0 else put_range.get('current_price')
                    signal['volatility_range'] = {
                        'current': current_price,  # 使用实时价格
                        'upper': put_range.get('upper'),
                        'lower': put_range.get('lower'),
                        'range_pct': put_range.get('range_pct')
                    }
                    signal['target_price'] = target_price
                    signal['stop_loss'] = stop_loss
                    signal['target_etf_price'] = target_etf_price
                    signal['expected_return_pct'] = round(expected_return_pct, 2) if expected_return_pct is not None else None
                    signal['risk_reward_ratio'] = round(risk_reward_ratio, 2) if risk_reward_ratio is not None else None
        
        # 更新缓存
        _signal_cache[signal_key] = now
        
        logger.info(f"生成{signal_type_label}: {signal['action']} - {reason}")
        return signal
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'create_signal_with_volatility_range', 'signal_type': signal_type},
            "创建信号失败"
        )
        return None


def create_signal(
    signal_type: str,
    reason: str,
    rsi: float,
    price_change: float,
    trend: str,
    strength: float,
    volatility_ranges: Optional[Dict] = None,
    deduplication_time: int = 1800,
    iv: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    创建交易信号（带去重检查）
    
    Args:
        signal_type: "call" 或 "put"
        reason: 信号原因
        rsi: RSI值
        price_change: 价格变动率
        trend: 整体趋势
        strength: 趋势强度
        volatility_ranges: 波动区间预测结果
        deduplication_time: 去重时间（秒）
        iv: 隐含波动率
    
    Returns:
        dict: 信号字典，如果重复则返回None
    """
    try:
        # 检查信号去重
        signal_key = f"{signal_type}_{reason[:20]}"  # 使用信号类型和原因前20字符作为key
        now = datetime.now(pytz.timezone('Asia/Shanghai'))
        
        if signal_key in _signal_cache:
            last_time = _signal_cache[signal_key]
            time_diff = (now - last_time).total_seconds()
            if time_diff < deduplication_time:
                logger.debug(f"信号去重: {signal_key} (距离上次 {time_diff:.0f}秒)")
                return None
        
        # 创建信号
        # 从signal_type推断方向：call=看涨，put=看跌
        direction = '看涨' if signal_type == 'call' else '看跌' if signal_type == 'put' else '未知'
        
        signal = {
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            'signal_type': signal_type,
            'action': f'买入{signal_type.upper()}期权',
            'reason': reason,
            'rsi': round(rsi, 2),
            'price_change': round(price_change, 2),
            'trend': trend,
            'trend_strength': round(strength, 2),
            'direction': direction,  # 添加方向字段
            'signal_strength': round(strength, 2),  # 添加信号强度字段（与trend_strength相同）
            'iv': round(iv, 2) if iv is not None else None
        }
        # 预留评估字段（简单信号场景下不一定有ETF/期权价格，评估脚本可按需填充）
        signal['base_etf_price'] = None
        signal['base_option_price'] = None
        signal['future_price_t15m'] = None
        signal['future_price_t2d'] = None
        signal['pnl_pct_t15m'] = None
        signal['pnl_pct_t2d'] = None
        signal['hit_take_profit'] = None
        signal['hit_stop_loss'] = None
        
        # 添加波动区间信息（如果可用）
        if volatility_ranges:
            if signal_type == 'call' and volatility_ranges.get('call_ranges'):
                call_ranges = volatility_ranges.get('call_ranges', [])
                call_range = call_ranges[0] if call_ranges else None
                if call_range:
                    signal['volatility_range'] = {
                        'current': call_range.get('current_price'),
                        'upper': call_range.get('upper'),
                        'lower': call_range.get('lower'),
                        'range_pct': call_range.get('range_pct')
                    }
            elif signal_type == 'put' and volatility_ranges.get('put_ranges'):
                put_ranges = volatility_ranges.get('put_ranges', [])
                put_range = put_ranges[0] if put_ranges else None
                if put_range:
                    signal['volatility_range'] = {
                        'current': put_range.get('current_price'),
                        'upper': put_range.get('upper'),
                        'lower': put_range.get('lower'),
                        'range_pct': put_range.get('range_pct')
                    }
        
        # 更新缓存
        _signal_cache[signal_key] = now
        
        logger.info(f"生成信号: {signal['action']} - {reason}")
        return signal
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'create_signal', 'signal_type': signal_type},
            "创建信号失败"
        )
        return None


def clear_signal_cache():
    """
    清除信号缓存（用于测试或重置）
    """
    global _signal_cache
    _signal_cache.clear()
    logger.info("信号缓存已清除")


# ========== 优化方案v1.0：新增辅助函数 ==========

def detect_rsi_divergence(
    index_minute: pd.DataFrame,
    rsi: pd.Series,
    lookback_periods: int = 15,
    threshold: float = 5.0
) -> Dict[str, Any]:
    """
    检测RSI背离
    
    Args:
        index_minute: 指数分钟数据
        rsi: RSI序列
        lookback_periods: 回看周期数（默认15，即最近15分钟）
        threshold: 背离阈值（点数，默认5.0）
    
    Returns:
        dict: {
            'has_divergence': bool,  # 是否有背离
            'divergence_type': str,  # 'bullish'（看涨背离）或 'bearish'（看跌背离）
            'strength': float,  # 背离强度（0-1）
            'details': str  # 详细说明
        }
    """
    try:
        if index_minute is None or index_minute.empty or rsi is None or rsi.empty:
            return {'has_divergence': False, 'divergence_type': None, 'strength': 0.0, 'details': '数据不足'}
        
        if len(index_minute) < lookback_periods or len(rsi) < lookback_periods:
            return {'has_divergence': False, 'divergence_type': None, 'strength': 0.0, 'details': f'数据不足（需要{lookback_periods}条）'}
        
        # 获取最近N个周期的数据
        recent_prices = index_minute['收盘'].tail(lookback_periods).values
        recent_rsi = rsi.tail(lookback_periods).values
        
        # 找到价格和RSI的极值点
        price_min_idx = np.argmin(recent_prices)
        price_max_idx = np.argmax(recent_prices)
        
        # 检测看涨背离：价格新低但RSI更高
        if price_min_idx > 0:  # 价格最低点不在第一个位置
            price_lowest = recent_prices[price_min_idx]
            price_prev_low = np.min(recent_prices[:price_min_idx]) if price_min_idx > 0 else price_lowest
            rsi_at_low = recent_rsi[price_min_idx]
            rsi_prev_low = recent_rsi[np.argmin(recent_prices[:price_min_idx])] if price_min_idx > 0 else rsi_at_low
            
            if price_lowest < price_prev_low and rsi_at_low > rsi_prev_low + threshold:
                divergence_strength = min((rsi_at_low - rsi_prev_low) / 20.0, 1.0)  # 归一化到0-1
                return {
                    'has_divergence': True,
                    'divergence_type': 'bullish',
                    'strength': divergence_strength,
                    'details': f'看涨背离：价格新低({price_lowest:.2f})但RSI更高({rsi_at_low:.2f} vs {rsi_prev_low:.2f})'
                }
        
        # 检测看跌背离：价格新高但RSI更低
        if price_max_idx > 0:  # 价格最高点不在第一个位置
            price_highest = recent_prices[price_max_idx]
            price_prev_high = np.max(recent_prices[:price_max_idx]) if price_max_idx > 0 else price_highest
            rsi_at_high = recent_rsi[price_max_idx]
            rsi_prev_high = recent_rsi[np.argmax(recent_prices[:price_max_idx])] if price_max_idx > 0 else rsi_at_high
            
            if price_highest > price_prev_high and rsi_at_high < rsi_prev_high - threshold:
                divergence_strength = min((rsi_prev_high - rsi_at_high) / 20.0, 1.0)  # 归一化到0-1
                return {
                    'has_divergence': True,
                    'divergence_type': 'bearish',
                    'strength': divergence_strength,
                    'details': f'看跌背离：价格新高({price_highest:.2f})但RSI更低({rsi_at_high:.2f} vs {rsi_prev_high:.2f})'
                }
        
        return {'has_divergence': False, 'divergence_type': None, 'strength': 0.0, 'details': '未检测到背离'}
        
    except Exception as e:
        logger.warning(f"RSI背离检测失败: {e}")
        return {'has_divergence': False, 'divergence_type': None, 'strength': 0.0, 'details': f'检测失败: {e}'}


def detect_macd_histogram_turnover(
    index_minute: pd.DataFrame,
    lookback_periods: int = 15,
    turnover_pct: float = 20.0
) -> Dict[str, Any]:
    """
    检测MACD Histogram转折
    
    Args:
        index_minute: 指数分钟数据
        lookback_periods: 回看周期数（默认15）
        turnover_pct: 转折阈值（%，默认20.0）
    
    Returns:
        dict: {
            'has_turnover': bool,  # 是否有转折
            'turnover_type': str,  # 'bullish'（看涨转折）或 'bearish'（看跌转折）
            'strength': float,  # 转折强度（0-1）
            'details': str  # 详细说明
        }
    """
    try:
        if index_minute is None or index_minute.empty:
            return {'has_turnover': False, 'turnover_type': None, 'strength': 0.0, 'details': '数据不足'}
        
        # 计算MACD
        macd_result = calculate_macd(index_minute, close_col='收盘')
        if macd_result is None:
            return {'has_turnover': False, 'turnover_type': None, 'strength': 0.0, 'details': 'MACD计算失败'}
        
        histogram = macd_result.get('histogram')
        if histogram is None or histogram.empty or len(histogram) < lookback_periods:
            return {'has_turnover': False, 'turnover_type': None, 'strength': 0.0, 'details': 'Histogram数据不足'}
        
        # 获取最近N个周期的Histogram值
        recent_hist = histogram.tail(lookback_periods).values
        
        # 找到最近的极值点
        latest_idx = len(recent_hist) - 1
        latest_hist = recent_hist[latest_idx]
        prev_hist = recent_hist[latest_idx - 1] if latest_idx > 0 else latest_hist
        
        # 检测看涨转折：Histogram从负转正或负值收窄
        if latest_hist > 0 and prev_hist < 0:
            # 从负转正
            turnover_strength = min(abs(latest_hist - prev_hist) / 10.0, 1.0)  # 归一化
            return {
                'has_turnover': True,
                'turnover_type': 'bullish',
                'strength': turnover_strength,
                'details': f'看涨转折：Histogram从负转正({prev_hist:.4f} → {latest_hist:.4f})'
            }
        elif latest_hist < 0 and prev_hist < 0:
            # 负值收窄（绝对值减小）
            if abs(latest_hist) < abs(prev_hist) * (1 - turnover_pct / 100.0):
                turnover_strength = min((abs(prev_hist) - abs(latest_hist)) / abs(prev_hist), 1.0)
                return {
                    'has_turnover': True,
                    'turnover_type': 'bullish',
                    'strength': turnover_strength,
                    'details': f'看涨转折：Histogram负值收窄({prev_hist:.4f} → {latest_hist:.4f})'
                }
        
        # 检测看跌转折：Histogram从正转负或正值收窄
        if latest_hist < 0 and prev_hist > 0:
            # 从正转负
            turnover_strength = min(abs(prev_hist - latest_hist) / 10.0, 1.0)  # 归一化
            return {
                'has_turnover': True,
                'turnover_type': 'bearish',
                'strength': turnover_strength,
                'details': f'看跌转折：Histogram从正转负({prev_hist:.4f} → {latest_hist:.4f})'
            }
        elif latest_hist > 0 and prev_hist > 0:
            # 正值收窄（绝对值减小）
            if abs(latest_hist) < abs(prev_hist) * (1 - turnover_pct / 100.0):
                turnover_strength = min((abs(prev_hist) - abs(latest_hist)) / abs(prev_hist), 1.0)
                return {
                    'has_turnover': True,
                    'turnover_type': 'bearish',
                    'strength': turnover_strength,
                    'details': f'看跌转折：Histogram正值收窄({prev_hist:.4f} → {latest_hist:.4f})'
                }
        
        return {'has_turnover': False, 'turnover_type': None, 'strength': 0.0, 'details': '未检测到转折'}
        
    except Exception as e:
        logger.warning(f"MACD Histogram转折检测失败: {e}")
        return {'has_turnover': False, 'turnover_type': None, 'strength': 0.0, 'details': f'检测失败: {e}'}


def detect_boundary_rebound(
    etf_current_price: float,
    volatility_ranges: Optional[Dict],
    lookback_minutes: int = 15,
    boundary_position_call: float = 0.25,
    boundary_position_put: float = 0.75,
    rebound_pct: float = 0.5
) -> Dict[str, Any]:
    """
    检测价格触边界反弹
    
    Args:
        etf_current_price: ETF当前价格
        volatility_ranges: 波动区间预测结果
        lookback_minutes: 回看分钟数（默认15）
        boundary_position_call: Call信号边界位置阈值（默认0.25）
        boundary_position_put: Put信号边界位置阈值（默认0.75）
        rebound_pct: 反弹幅度阈值（%，默认0.5）
    
    Returns:
        dict: {
            'has_rebound': bool,  # 是否有反弹
            'rebound_type': str,  # 'call'（看涨反弹）或 'put'（看跌反弹）
            'strength': float,  # 反弹强度（0-1）
            'details': str  # 详细说明
        }
    """
    try:
        if volatility_ranges is None or not volatility_ranges.get('etf_range'):
            return {'has_rebound': False, 'rebound_type': None, 'strength': 0.0, 'details': '无波动区间数据'}
        
        etf_range = volatility_ranges['etf_range']
        etf_upper = etf_range.get('upper')
        etf_lower = etf_range.get('lower')
        
        if etf_upper is None or etf_lower is None or etf_upper <= etf_lower:
            return {'has_rebound': False, 'rebound_type': None, 'strength': 0.0, 'details': '波动区间数据无效'}
        
        # 计算价格在区间中的位置（0-1，0为下轨，1为上轨）
        etf_position = (etf_current_price - etf_lower) / (etf_upper - etf_lower)
        
        # 检测看涨反弹：价格在下轨附近且反弹
        if etf_position < boundary_position_call:
            # 这里简化处理：如果价格在下轨附近，认为有反弹潜力
            # 实际应该检查最近N分钟的价格变化
            rebound_strength = (boundary_position_call - etf_position) / boundary_position_call  # 归一化
            return {
                'has_rebound': True,
                'rebound_type': 'call',
                'strength': min(rebound_strength, 1.0),
                'details': f'看涨反弹：价格在下轨附近（位置={etf_position:.2%}，下轨={etf_lower:.3f}）'
            }
        
        # 检测看跌反弹：价格在上轨附近且回落
        if etf_position > boundary_position_put:
            rebound_strength = (etf_position - boundary_position_put) / (1 - boundary_position_put)  # 归一化
            return {
                'has_rebound': True,
                'rebound_type': 'put',
                'strength': min(rebound_strength, 1.0),
                'details': f'看跌反弹：价格在上轨附近（位置={etf_position:.2%}，上轨={etf_upper:.3f}）'
            }
        
        return {'has_rebound': False, 'rebound_type': None, 'strength': 0.0, 'details': '未检测到边界反弹'}
        
    except Exception as e:
        logger.warning(f"边界反弹检测失败: {e}")
        return {'has_rebound': False, 'rebound_type': None, 'strength': 0.0, 'details': f'检测失败: {e}'}


def calculate_daily_trend_score(
    etf_symbol: str,
    etf_current_price: float,
    ma_period: int = 20,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    计算日线趋势分数（GROK v2.0优化方案）
    
    基于20日MA判断日线趋势，作为期权信号的辅助过滤因子（10%权重）
    
    Args:
        etf_symbol: ETF代码（如 "510300"）
        etf_current_price: ETF当前价格
        ma_period: 均线周期（默认20）
        config: 系统配置
    
    Returns:
        dict: {
            'score': float,  # 趋势分数（0-0.10，对应10%权重）
            'direction': str,  # 'bullish'（看涨）或 'bearish'（看跌）或 'neutral'（中性）
            'ma_value': float,  # 20日MA值
            'price_vs_ma_pct': float,  # 价格相对MA的百分比
            'ma_slope': float,  # MA斜率（向上为正，向下为负）
            'details': str  # 详细说明
        }
    """
    try:
        if config is None:
            config = load_system_config()
        
        # 获取ETF日线数据（回看60个交易日，确保有足够数据计算20日MA）
        from datetime import timedelta
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        end_date = now.strftime("%Y%m%d")
        start_date = (now - timedelta(days=90)).strftime("%Y%m%d")  # 90天确保有60个交易日
        
        etf_daily = fetch_etf_daily_em(
            symbol=etf_symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        if etf_daily is None or etf_daily.empty:
            logger.warning(f"无法获取ETF日线数据({etf_symbol})，日线趋势分数为0")
            return {
                'score': 0.0,
                'direction': 'neutral',
                'ma_value': None,
                'price_vs_ma_pct': 0.0,
                'ma_slope': 0.0,
                'details': '日线数据缺失'
            }
        
        # 计算20日MA
        ma20 = calculate_ma(etf_daily, period=ma_period, close_col='收盘')
        
        if ma20 is None or ma20.empty:
            logger.warning(f"无法计算{ma_period}日MA，日线趋势分数为0")
            return {
                'score': 0.0,
                'direction': 'neutral',
                'ma_value': None,
                'price_vs_ma_pct': 0.0,
                'ma_slope': 0.0,
                'details': f'MA{ma_period}计算失败'
            }
        
        # 获取最新的MA值
        current_ma = float(ma20.iloc[-1])
        
        # 计算价格相对MA的百分比
        price_vs_ma_pct = ((etf_current_price - current_ma) / current_ma) * 100 if current_ma > 0 else 0.0
        
        # 计算MA斜率（最近5个交易日的MA变化率）
        if len(ma20) >= 5:
            ma_slope = ((ma20.iloc[-1] - ma20.iloc[-5]) / ma20.iloc[-5]) * 100 if ma20.iloc[-5] > 0 else 0.0
        else:
            ma_slope = 0.0
        
        # 判断趋势方向
        if etf_current_price > current_ma:
            direction = 'bullish'
            # 价格在MA上方，看涨加分
            # 基础分数：价格距离MA越远，分数越高（最高0.10）
            base_score = min(abs(price_vs_ma_pct) / 5.0, 1.0) * 0.05  # 距离5%时达到0.05
            # MA斜率向上，额外加分
            slope_bonus = max(0, ma_slope) / 2.0 * 0.05 if ma_slope > 0 else 0.0  # 斜率每2%加0.05
            score = min(base_score + slope_bonus, 0.10)  # 限制在0.10以内
            details = f"价格({etf_current_price:.3f}) > {ma_period}日MA({current_ma:.3f})，偏多，距离{price_vs_ma_pct:.2f}%，MA斜率{ma_slope:.2f}%"
        elif etf_current_price < current_ma:
            direction = 'bearish'
            # 价格在MA下方，看跌加分
            base_score = min(abs(price_vs_ma_pct) / 5.0, 1.0) * 0.05
            # MA斜率向下，额外加分
            slope_bonus = max(0, -ma_slope) / 2.0 * 0.05 if ma_slope < 0 else 0.0
            score = min(base_score + slope_bonus, 0.10)
            details = f"价格({etf_current_price:.3f}) < {ma_period}日MA({current_ma:.3f})，偏空，距离{abs(price_vs_ma_pct):.2f}%，MA斜率{ma_slope:.2f}%"
        else:
            direction = 'neutral'
            score = 0.0
            details = f"价格({etf_current_price:.3f}) ≈ {ma_period}日MA({current_ma:.3f})，中性"
        
        logger.debug(f"日线趋势分数计算: {details}, 分数={score:.3f}")
        
        return {
            'score': score,
            'direction': direction,
            'ma_value': current_ma,
            'price_vs_ma_pct': price_vs_ma_pct,
            'ma_slope': ma_slope,
            'details': details
        }
        
    except Exception as e:
        logger.warning(f"日线趋势分数计算失败: {e}", exc_info=True)
        return {
            'score': 0.0,
            'direction': 'neutral',
            'ma_value': None,
            'price_vs_ma_pct': 0.0,
            'ma_slope': 0.0,
            'details': f'计算失败: {e}'
        }


def merge_and_analyze_greeks(
    contract_code: str,
    realtime_greeks: Optional[pd.DataFrame],
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    合并实时Greeks数据和缓存数据，计算变化
    
    Args:
        contract_code: 合约代码
        realtime_greeks: 实时Greeks数据（DataFrame，单条记录）
        config: 系统配置
    
    Returns:
        dict: {
            'delta_change': float,  # Delta变化
            'gamma_peak': float,  # Gamma峰值（相对于当天均值）
            'iv_change_pct': float,  # IV变化率（%）
            'data_quality': str,  # 数据质量标记
            'details': str  # 详细说明
        }
    """
    try:
        if config is None:
            config = load_system_config()
        
        # 尝试从缓存加载当天Greeks序列
        greeks_series = None
        try:
            from src.data_cache import get_cached_option_greeks
            from datetime import datetime
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            today_str = now.strftime("%Y%m%d")
            
            # 获取当天缓存的Greeks数据
            cached_greeks = get_cached_option_greeks(contract_code, today_str, config=config)
            if cached_greeks is not None and not cached_greeks.empty:
                greeks_series = cached_greeks.copy()
        except Exception as e:
            logger.debug(f"加载Greeks缓存失败（不影响主流程）: {e}")
        
        # 合并实时数据
        if realtime_greeks is not None and not realtime_greeks.empty:
            if greeks_series is None or greeks_series.empty:
                greeks_series = realtime_greeks.copy()
            else:
                # 追加实时数据
                greeks_series = pd.concat([greeks_series, realtime_greeks], ignore_index=True)
                # 按时间戳排序（如果有时间戳列）
                if 'timestamp' in greeks_series.columns:
                    # 确保时间戳是datetime类型
                    greeks_series['timestamp'] = pd.to_datetime(greeks_series['timestamp'], errors='coerce')
                    greeks_series = greeks_series.sort_values('timestamp')
                    # 设置时间戳为索引，便于后续计算变化率
                    greeks_series = greeks_series.set_index('timestamp')
        
        if greeks_series is None or greeks_series.empty or len(greeks_series) < 2:
            return {
                'delta_change': 0.0,
                'gamma_peak': 1.0,
                'iv_change_pct': 0.0,
                'data_quality': 'insufficient',
                'details': 'Greeks数据不足（<2条），确认强度打折20%'
            }
        
        # 检查数据质量
        if len(greeks_series) < 5:
            data_quality = 'low'
            quality_note = f'数据量少（{len(greeks_series)}条），确认强度打折20%'
        else:
            data_quality = 'good'
            quality_note = '数据充足'
        
        # 提取Delta、Gamma、IV列（兼容不同的列名）
        delta_col = None
        gamma_col = None
        iv_col = None
        
        for col in greeks_series.columns:
            col_lower = col.lower()
            if 'delta' in col_lower and delta_col is None:
                delta_col = col
            if 'gamma' in col_lower and gamma_col is None:
                gamma_col = col
            if ('iv' in col_lower or 'implied' in col_lower) and iv_col is None:
                iv_col = col
        
        if delta_col is None or gamma_col is None or iv_col is None:
            return {
                'delta_change': 0.0,
                'gamma_peak': 1.0,
                'iv_change_pct': 0.0,
                'data_quality': 'invalid',
                'details': f'Greeks数据列缺失（delta={delta_col}, gamma={gamma_col}, iv={iv_col}）'
            }
        
        # 计算Delta变化（使用diff()方法，更安全）
        delta_values = greeks_series[delta_col].dropna()
        if len(delta_values) >= 2:
            # 使用diff()计算变化，取最后一条
            delta_diff = delta_values.diff().iloc[-1]
            delta_change = float(delta_diff) if not pd.isna(delta_diff) else 0.0
            # 如果计算失败，使用直接差值作为备用
            if delta_change == 0.0 and len(delta_values) >= 2:
                delta_change = float(delta_values.iloc[-1] - delta_values.iloc[-2])
        else:
            delta_change = 0.0
        
        # 计算Gamma峰值（当前Gamma / 当天均值）
        gamma_values = greeks_series[gamma_col].dropna()
        if len(gamma_values) > 0:
            gamma_mean = float(gamma_values.mean())
            gamma_current = float(gamma_values.iloc[-1])
            gamma_peak = gamma_current / gamma_mean if gamma_mean > 0 else 1.0
        else:
            gamma_peak = 1.0
        
        # 计算IV变化率（使用pct_change()方法，更安全）
        iv_values = greeks_series[iv_col].dropna()
        if len(iv_values) >= 2:
            # 使用pct_change()计算变化率，取最后一条
            iv_pct_change = iv_values.pct_change().iloc[-1]
            iv_change_pct = float(iv_pct_change * 100) if not pd.isna(iv_pct_change) else 0.0
            # 如果计算失败，使用直接计算作为备用
            if iv_change_pct == 0.0 and len(iv_values) >= 2:
                iv_prev = float(iv_values.iloc[-2])
                iv_current = float(iv_values.iloc[-1])
                iv_change_pct = ((iv_current - iv_prev) / iv_prev * 100) if iv_prev > 0 else 0.0
        else:
            iv_change_pct = 0.0
        
        return {
            'delta_change': delta_change,
            'gamma_peak': gamma_peak,
            'iv_change_pct': iv_change_pct,
            'data_quality': data_quality,
            'details': quality_note
        }
        
    except Exception as e:
        logger.warning(f"Greeks数据合并分析失败: {e}")
        return {
            'delta_change': 0.0,
            'gamma_peak': 1.0,
            'iv_change_pct': 0.0,
            'data_quality': 'error',
            'details': f'分析失败: {e}'
        }


def prepare_llm_input(
    index_minute: pd.DataFrame,
    etf_current_price: float,
    rsi: pd.Series,
    price_change: pd.Series,
    call_option_greeks: Optional[pd.DataFrame],
    put_option_greeks: Optional[pd.DataFrame],
    opening_strategy: Optional[Dict],
    volatility_ranges: Optional[Dict],
    total_strength: float,
    sequence_count: int,
    underlying: str = "510300"
) -> Dict[str, Any]:
    """
    准备LLM输入数据（摘要 + 序列）
    
    Args:
        index_minute: 指数分钟数据
        etf_current_price: ETF当前价格
        rsi: RSI序列
        price_change: 价格变动率序列
        call_option_greeks: Call期权Greeks数据
        put_option_greeks: Put期权Greeks数据
        opening_strategy: 开盘策略
        volatility_ranges: 波动区间预测结果
        total_strength: 规则总强度
        sequence_count: 序列数据条数（0/5/10）
        underlying: 标的物代码
    
    Returns:
        dict: LLM输入数据
    """
    try:
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        
        # 摘要数据
        latest_rsi = float(rsi.iloc[-1]) if not rsi.empty else None
        latest_price_change = float(price_change.iloc[-1]) if not price_change.empty else None
        
        # 计算变化率（最近15分钟）
        if len(price_change) >= 15:
            price_change_15m = float(price_change.tail(15).sum())
        else:
            price_change_15m = latest_price_change if latest_price_change else 0.0
        
        if len(rsi) >= 15:
            rsi_change = float(rsi.iloc[-1] - rsi.iloc[-15])
        else:
            rsi_change = 0.0
        
        # 提取Greeks数据
        delta_change = 0.0
        gamma = 0.0
        iv_change_pct = 0.0
        
        if call_option_greeks is not None and not call_option_greeks.empty:
            # 尝试从Greeks中提取Delta、Gamma、IV
            for idx, row in call_option_greeks.iterrows():
                field = str(row.get('字段', ''))
                value = row.get('值', '')
                try:
                    if 'Delta' in field or 'delta' in field.lower():
                        delta_change = float(value) if value else 0.0
                    elif 'Gamma' in field or 'gamma' in field.lower():
                        gamma = float(value) if value else 0.0
                    elif '波动率' in field or 'IV' in field.lower() or 'implied' in field.lower():
                        iv_change_pct = float(value) if value else 0.0
                except (ValueError, TypeError):
                    continue
        
        # MACD Histogram
        macd_result = calculate_macd(index_minute, close_col='收盘')
        macd_hist = None
        if macd_result and macd_result.get('histogram') is not None:
            hist_series = macd_result['histogram']
            if not hist_series.empty:
                macd_hist = float(hist_series.iloc[-1])
        
        # 波动区间位置
        volatility_position = None
        if volatility_ranges and volatility_ranges.get('etf_range'):
            etf_range = volatility_ranges['etf_range']
            etf_upper = etf_range.get('upper')
            etf_lower = etf_range.get('lower')
            if etf_upper is not None and etf_lower is not None and etf_upper > etf_lower:
                volatility_position = (etf_current_price - etf_lower) / (etf_upper - etf_lower)
        
        # 大盘辅助信息
        overall_trend = opening_strategy.get('final_trend', '震荡') if opening_strategy else '震荡'
        strategy_direction = opening_strategy.get('opening_strategy', {}).get('direction', '谨慎') if opening_strategy else '谨慎'
        trend_strength = opening_strategy.get('final_strength', 0.5) if opening_strategy else 0.5
        
        # 构建输入数据
        input_data = {
            "analysis_type": "signal_watch",
            "timestamp": now.strftime('%Y-%m-%d %H:%M:%S'),
            "etf_symbol": underlying,
            "current_price": round(etf_current_price, 3),
            "volatility_position": round(volatility_position, 3) if volatility_position is not None else None,
            "rsi": round(latest_rsi, 2) if latest_rsi is not None else None,
            "macd_hist": round(macd_hist, 4) if macd_hist is not None else None,
            "delta_change": round(delta_change, 3),
            "gamma": round(gamma, 4),
            "iv_change_pct": round(iv_change_pct, 2),
            "price_change_15m": round(price_change_15m, 2),
            "rsi_change": round(rsi_change, 2),
            "trend": overall_trend,
            "opening_direction": strategy_direction,
            "trend_strength": round(trend_strength, 2),
            "rule_strength": round(total_strength, 3)
        }
        
        # 添加波动区间信息
        if volatility_ranges and volatility_ranges.get('etf_range'):
            etf_range = volatility_ranges['etf_range']
            input_data["volatility_range"] = {
                "upper": round(etf_range.get('upper', 0), 3) if etf_range.get('upper') else None,
                "lower": round(etf_range.get('lower', 0), 3) if etf_range.get('lower') else None,
                "confidence": round(etf_range.get('confidence', 0), 2) if etf_range.get('confidence') else None
            }
        
        # 序列数据（如果sequence_count > 0）
        if sequence_count > 0 and index_minute is not None and not index_minute.empty:
            sequence = []
            # 取最近N条数据
            recent_data = index_minute.tail(min(sequence_count, len(index_minute)))
            
            for idx, row in recent_data.iterrows():
                time_str = str(idx) if isinstance(idx, (datetime, pd.Timestamp)) else str(row.get('时间', ''))
                if isinstance(time_str, str) and len(time_str) > 10:
                    time_str = time_str[-8:]  # 只保留时间部分
                
                seq_item = {
                    "time": time_str,
                    "price": round(float(row.get('收盘', 0)), 3)
                }
                
                # 添加RSI
                if not rsi.empty and idx in rsi.index:
                    seq_item["rsi"] = round(float(rsi.loc[idx]), 2)
                
                # 添加MACD Histogram
                if macd_result and macd_result.get('histogram') is not None:
                    hist_series = macd_result['histogram']
                    if not hist_series.empty and idx in hist_series.index:
                        seq_item["macd_hist"] = round(float(hist_series.loc[idx]), 4)
                
                # 添加Delta（简化处理，使用当前值）
                if delta_change != 0:
                    seq_item["delta"] = round(delta_change, 3)
                
                sequence.append(seq_item)
            
            if sequence:
                input_data["sequence"] = sequence
        
        return input_data
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'prepare_llm_input'},
            "准备LLM输入数据失败"
        )
        return {}


def parse_llm_output(llm_summary: str) -> Optional[Dict[str, Any]]:
    """
    解析LLM输出（优先JSON，失败则尝试正则提取）
    
    Args:
        llm_summary: LLM返回的文本
    
    Returns:
        dict: 解析后的结构化数据，失败返回None
    """
    if not llm_summary or not llm_summary.strip():
        return None
    
    try:
        # 方法1：尝试直接解析JSON
        # 提取JSON部分（可能包含在代码块中）
        json_match = re.search(r'\{[\s\S]*\}', llm_summary)
        if json_match:
            json_str = json_match.group(0)
            try:
                result = json.loads(json_str)
                if isinstance(result, dict) and 'turnover_judgment' in result:
                    logger.debug("LLM输出JSON解析成功")
                    return result
            except json.JSONDecodeError:
                pass
        
        # 方法2：尝试正则提取关键字段
        result = {}
        
        # 提取转折判断
        judgment_match = re.search(r'"turnover_judgment"\s*:\s*"([^"]+)"', llm_summary)
        if not judgment_match:
            judgment_match = re.search(r'转折判断[：:]\s*([^\n]+)', llm_summary)
        if judgment_match:
            result['turnover_judgment'] = judgment_match.group(1).strip()
        
        # 提取转折强度
        strength_match = re.search(r'"turnover_strength"\s*:\s*([0-9.]+)', llm_summary)
        if not strength_match:
            strength_match = re.search(r'转折强度[：:]\s*([0-9.]+)', llm_summary)
        if strength_match:
            try:
                result['turnover_strength'] = float(strength_match.group(1))
            except ValueError:
                pass
        
        # 提取解释（列表）
        explanation_match = re.search(r'"explanation"\s*:\s*\[([^\]]+)\]', llm_summary, re.DOTALL)
        if explanation_match:
            explanation_str = explanation_match.group(1)
            explanations = re.findall(r'"([^"]+)"', explanation_str)
            if explanations:
                result['explanation'] = explanations
        
        # 提取风险警示
        risk_match = re.search(r'"risk_warning"\s*:\s*"([^"]+)"', llm_summary)
        if not risk_match:
            risk_match = re.search(r'风险警示[：:]\s*([^\n]+)', llm_summary)
        if risk_match:
            result['risk_warning'] = risk_match.group(1).strip()
        
        # 提取交易建议
        suggestion_match = re.search(r'"trading_suggestion"\s*:\s*"([^"]+)"', llm_summary)
        if not suggestion_match:
            suggestion_match = re.search(r'交易建议[：:]\s*([^\n]+)', llm_summary)
        if suggestion_match:
            result['trading_suggestion'] = suggestion_match.group(1).strip()
        
        if result and 'turnover_judgment' in result:
            logger.debug("LLM输出正则解析成功")
            return result
        else:
            logger.warning(f"LLM输出解析失败，无法提取关键字段: {llm_summary[:200]}")
            return None
            
    except Exception as e:
        logger.warning(f"LLM输出解析异常: {e}")
        return None


def _generate_signals_optimized_v1(
    index_minute: pd.DataFrame,
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
    优化方案v1.0：基于ETF短期K线转折的信号生成
    
    权重分配：
    - ETF短期K线转折：65%（主驱动）
    - Greeks/IV确认：25%（至少1个因子必须）
    - 大盘趋势/开盘方向：10%（辅助加分，非必须）
    
    Args:
        同 generate_signals
    
    Returns:
        list: 信号列表
    """
    try:
        logger.info("使用优化方案v1.0生成信号...")
        
        if config is None:
            config = load_system_config()
        
        signal_params = config.get('signal_params', {})
        
        # GROK v2.0：ETF-期权联动机制（在信号生成前检查ETF短波段信号）
        filter_by_etf = signal_params.get('filter_by_etf', True)
        etf_filter_threshold = signal_params.get('etf_filter_threshold', 0.6)
        etf_filter_adjustment = signal_params.get('etf_filter_strength_adjustment', 0.1)
        
        etf_short_term_signal = None
        etf_signal_direction = None  # 'bullish', 'bearish', 'neutral'
        
        if filter_by_etf:
            try:
                # 获取ETF短波段信号
                from src.etf_signal_generator_short_term import generate_etf_short_term_signal
                from src.data_collector import fetch_etf_daily_em, fetch_etf_minute_data_with_fallback
                
                # 获取ETF代码
                option_contracts = config.get('option_contracts', {})
                underlyings_list = option_contracts.get('underlyings', [])
                if underlyings_list and isinstance(underlyings_list, list) and len(underlyings_list) > 0:
                    etf_symbol = str(underlyings_list[0].get('underlying', '510300'))
                    
                    # 获取ETF日线数据
                    tz_shanghai = pytz.timezone('Asia/Shanghai')
                    now = datetime.now(tz_shanghai)
                    end_date = now.strftime("%Y%m%d")
                    start_date = (now - timedelta(days=90)).strftime("%Y%m%d")
                    
                    etf_daily = fetch_etf_daily_em(
                        symbol=etf_symbol,
                        start_date=start_date,
                        end_date=end_date
                    )
                    
                    # 获取ETF 30分钟数据
                    # 提高数据周期长度：从5天增加到15天，确保有足够数据计算MACD等指标
                    etf_minute_30m, _ = fetch_etf_minute_data_with_fallback(
                        underlying=etf_symbol,
                        lookback_days=15  # 从5天增加到15天，确保有足够数据计算MACD等指标
                    )
                    
                    if etf_daily is not None and not etf_daily.empty:
                        etf_short_term_signal = generate_etf_short_term_signal(
                            etf_symbol=etf_symbol,
                            etf_daily_data=etf_daily,
                            etf_minute_30m=etf_minute_30m,
                            etf_current_price=etf_current_price,
                            volatility_ranges=volatility_ranges,
                            config=config
                        )
                        
                        if etf_short_term_signal and etf_short_term_signal.get('signal_strength', 0) > etf_filter_threshold:
                            signal_type = etf_short_term_signal.get('signal_type', '持有')
                            if signal_type == '买入':
                                etf_signal_direction = 'bullish'
                            elif signal_type == '卖出':
                                etf_signal_direction = 'bearish'
                            else:
                                etf_signal_direction = 'neutral'
                            
                            logger.info(f"ETF短波段信号检测: {etf_symbol} {signal_type}, 强度={etf_short_term_signal.get('signal_strength', 0):.3f}, "
                                       f"将用于过滤期权方向")
            except Exception as e:
                logger.warning(f"ETF-期权联动检查失败: {e}，继续正常生成期权信号")
        
        # 根据ETF信号方向调整期权信号生成阈值
        # adjusted_min_signal_strength 本轮未使用（保留注释即可）
        
        # 读取优化方案参数（GROK v2.0权重分配）
        # 新权重：边界反弹40% + RSI背离15% + MACD转折15% + Greeks 20% + 日线趋势10% = 100%
        boundary_rebound_weight = signal_params.get('boundary_rebound_weight', 0.40)
        rsi_divergence_weight = signal_params.get('rsi_divergence_weight', 0.15)
        macd_turnover_weight = signal_params.get('macd_turnover_weight', 0.15)
        greeks_iv_weight = signal_params.get('greeks_iv_weight', 0.20)
        daily_trend_weight = signal_params.get('daily_trend_weight', 0.10)
        # 保留旧权重字段以兼容（逐步废弃）：本轮未使用对应变量
        rsi_divergence_threshold = signal_params.get('rsi_divergence_threshold', 5.0)
        macd_hist_turnover_pct = signal_params.get('macd_hist_turnover_pct', 20.0)
        boundary_position_call = signal_params.get('boundary_position_call', 0.25)
        boundary_position_put = signal_params.get('boundary_position_put', 0.75)
        boundary_rebound_pct = signal_params.get('boundary_rebound_pct', 0.5)
        delta_change_threshold = signal_params.get('delta_change_threshold', 0.1)
        gamma_peak_mult = signal_params.get('gamma_peak_mult', 1.5)
        iv_change_threshold = signal_params.get('iv_change_threshold', 5.0)
        base_min_signal_strength = signal_params.get('signal_strength_levels', {}).get('weak', 0.45)
        strong_threshold = signal_params.get('signal_strength_levels', {}).get('strong', 0.75)
        medium_threshold = signal_params.get('signal_strength_levels', {}).get('medium', 0.55)
        enable_weak_notification = signal_params.get('enable_weak_signal_notification', False)
        deduplication_time = signal_params.get('signal_deduplication_time', 1800)
        
        # GROK v2.0：根据ETF信号方向调整阈值
        if filter_by_etf and etf_signal_direction:
            if etf_signal_direction == 'bullish':
                # ETF偏多：Call信号阈值降低，Put信号阈值提高
                min_signal_strength_call = max(0.35, base_min_signal_strength - etf_filter_adjustment)
                min_signal_strength_put = base_min_signal_strength + etf_filter_adjustment
                logger.debug(f"ETF-期权联动: ETF偏多，Call阈值={min_signal_strength_call:.3f}, Put阈值={min_signal_strength_put:.3f}")
            elif etf_signal_direction == 'bearish':
                # ETF偏空：Put信号阈值降低，Call信号阈值提高
                min_signal_strength_call = base_min_signal_strength + etf_filter_adjustment
                min_signal_strength_put = max(0.35, base_min_signal_strength - etf_filter_adjustment)
                logger.debug(f"ETF-期权联动: ETF偏空，Call阈值={min_signal_strength_call:.3f}, Put阈值={min_signal_strength_put:.3f}")
            else:
                # 中性：不调整
                min_signal_strength_call = base_min_signal_strength
                min_signal_strength_put = base_min_signal_strength
        else:
            # 未启用联动或ETF信号不足：使用基础阈值
            min_signal_strength_call = base_min_signal_strength
            min_signal_strength_put = base_min_signal_strength
        
        signals: List[Dict[str, Any]] = []
        
        if index_minute is None or index_minute.empty:
            logger.warning("指数分钟数据为空，无法生成信号")
            return signals
        
        # 1. 计算技术指标
        rsi = calculate_rsi(index_minute, close_col='收盘')
        price_change = calculate_price_change_rate(index_minute, close_col='收盘')
        
        if rsi is None or price_change is None:
            logger.warning("技术指标计算失败，无法生成信号")
            return signals
        
        # 2. 检测ETF短期K线转折（GROK v2.0权重分配：边界反弹40% + RSI 15% + MACD 15% = 70%）
        rsi_divergence = detect_rsi_divergence(index_minute, rsi, threshold=rsi_divergence_threshold)
        macd_turnover = detect_macd_histogram_turnover(index_minute, turnover_pct=macd_hist_turnover_pct)
        boundary_rebound = detect_boundary_rebound(
            etf_current_price, volatility_ranges,
            boundary_position_call=boundary_position_call,
            boundary_position_put=boundary_position_put,
            rebound_pct=boundary_rebound_pct
        )
        
        # 计算ETF转折分数（GROK v2.0：边界反弹40% + RSI背离15% + MACD转折15%）
        # 每个因子独立计算，然后加权求和
        etf_turnover_score = 0.0
        etf_turnover_factors = []
        
        # 边界反弹（40%权重，主逻辑）
        if boundary_rebound['has_rebound']:
            boundary_score = boundary_rebound['strength'] * boundary_rebound_weight
            etf_turnover_score += boundary_score
            etf_turnover_factors.append(f"边界反弹({boundary_rebound['rebound_type']}, 强度={boundary_rebound['strength']:.2f}, 贡献={boundary_score:.3f})")
        
        # RSI背离（15%权重）
        if rsi_divergence['has_divergence']:
            rsi_score = rsi_divergence['strength'] * rsi_divergence_weight
            etf_turnover_score += rsi_score
            etf_turnover_factors.append(f"RSI背离({rsi_divergence['divergence_type']}, 强度={rsi_divergence['strength']:.2f}, 贡献={rsi_score:.3f})")
        
        # MACD转折（15%权重）
        if macd_turnover['has_turnover']:
            macd_score = macd_turnover['strength'] * macd_turnover_weight
            etf_turnover_score += macd_score
            etf_turnover_factors.append(f"MACD转折({macd_turnover['turnover_type']}, 强度={macd_turnover['strength']:.2f}, 贡献={macd_score:.3f})")
        
        # 限制在0-0.70范围内（边界反弹40% + RSI 15% + MACD 15% = 70%）
        max_etf_turnover = boundary_rebound_weight + rsi_divergence_weight + macd_turnover_weight
        etf_turnover_score = min(etf_turnover_score, max_etf_turnover)
        
        logger.debug(f"ETF转折分数计算(GROK v2.0): {', '.join(etf_turnover_factors)}, 总分={etf_turnover_score:.3f}")
        
        # 3. 计算日线趋势分数（10%权重，GROK v2.0新增）
        # 获取ETF代码（从配置中获取）
        etf_symbol = '510300'  # 默认值
        try:
            option_contracts = config.get('option_contracts', {})
            underlyings_list = option_contracts.get('underlyings', [])
            if underlyings_list and isinstance(underlyings_list, list) and len(underlyings_list) > 0:
                # 使用第一个标的物（如果系统支持多标的物，这里可以进一步优化）
                etf_symbol = str(underlyings_list[0].get('underlying', '510300'))
        except Exception as e:
            logger.debug(f"计算日线趋势分数时提取 etf_symbol 失败，使用默认值: {e}", exc_info=True)
        
        daily_trend_result = calculate_daily_trend_score(
            etf_symbol=etf_symbol,
            etf_current_price=etf_current_price,
            ma_period=20,
            config=config
        )
        daily_trend_score_call = 0.0
        daily_trend_score_put = 0.0
        daily_trend_factors = []
        
        if daily_trend_result['score'] > 0:
            if daily_trend_result['direction'] == 'bullish':
                daily_trend_score_call = daily_trend_result['score'] * daily_trend_weight / 0.10  # 归一化到daily_trend_weight
                daily_trend_factors.append(f"日线趋势：{daily_trend_result['details']}")
            elif daily_trend_result['direction'] == 'bearish':
                daily_trend_score_put = daily_trend_result['score'] * daily_trend_weight / 0.10
                daily_trend_factors.append(f"日线趋势：{daily_trend_result['details']}")
        
        logger.debug(f"日线趋势分数计算: Call={daily_trend_score_call:.3f}, Put={daily_trend_score_put:.3f}, {daily_trend_result.get('details', '')}")
        
        # 4. 获取Greeks数据并计算确认分数（20%权重，GROK v2.0从25%降至20%）
        call_greeks_analysis = None
        put_greeks_analysis = None
        
        if call_option_greeks is not None and not call_option_greeks.empty:
            # 从call_option_greeks中提取contract_code（如果有）
            contract_code = None
            if 'contract_code' in call_option_greeks.columns:
                contract_code = str(call_option_greeks['contract_code'].iloc[0])
            elif call_option_price is not None:
                # 如果没有contract_code，尝试从其他来源获取
                # 这里简化处理，使用默认值
                contract_code = 'call_default'
            
            if contract_code:
                call_greeks_analysis = merge_and_analyze_greeks(contract_code, call_option_greeks, config)
        
        if put_option_greeks is not None and not put_option_greeks.empty:
            contract_code = None
            if 'contract_code' in put_option_greeks.columns:
                contract_code = str(put_option_greeks['contract_code'].iloc[0])
            elif put_option_price is not None:
                contract_code = 'put_default'
            
            if contract_code:
                put_greeks_analysis = merge_and_analyze_greeks(contract_code, put_option_greeks, config)
        
        # 计算Greeks/IV确认分数（0-0.25）
        def calculate_greeks_score(greeks_analysis, signal_type):
            if greeks_analysis is None:
                return 0.0, []
            
            score = 0.0
            factors = []
            
            # Delta变化
            if abs(greeks_analysis['delta_change']) >= delta_change_threshold:
                delta_score = min(abs(greeks_analysis['delta_change']) / 0.5, 1.0) * 0.1  # 最多10%
                score += delta_score
                factors.append(f"Delta变化({greeks_analysis['delta_change']:.3f})")
            
            # Gamma峰值
            if greeks_analysis['gamma_peak'] >= gamma_peak_mult:
                gamma_score = min((greeks_analysis['gamma_peak'] - 1.0) / 1.0, 1.0) * 0.1  # 最多10%
                score += gamma_score
                factors.append(f"Gamma峰值({greeks_analysis['gamma_peak']:.2f}x)")
            
            # IV变化率
            if abs(greeks_analysis['iv_change_pct']) >= iv_change_threshold:
                iv_score = min(abs(greeks_analysis['iv_change_pct']) / 20.0, 1.0) * 0.05  # 最多5%
                score += iv_score
                factors.append(f"IV变化({greeks_analysis['iv_change_pct']:.2f}%)")
            
            # 数据质量打折
            if greeks_analysis['data_quality'] == 'low':
                score *= 0.8  # 数据不足时打折20%
                factors.append("数据量少，确认强度打折20%")
            elif greeks_analysis['data_quality'] == 'insufficient':
                score *= 0.6  # 数据严重不足时打折40%
                factors.append("Greeks数据不足，确认强度打折40%")
            
            # 限制在0-0.25范围内
            score = min(score, greeks_iv_weight)
            
            logger.debug(f"Greeks确认分数计算 ({signal_type}): Delta变化={greeks_analysis.get('delta_change', 0):.3f}, "
                        f"Gamma峰值={greeks_analysis.get('gamma_peak', 1.0):.2f}x, "
                        f"IV变化={greeks_analysis.get('iv_change_pct', 0):.2f}%, "
                        f"数据质量={greeks_analysis.get('data_quality', 'unknown')}, 总分={score:.3f}")
            
            return score, factors
        
        call_greeks_score, call_greeks_factors = calculate_greeks_score(call_greeks_analysis, 'call')
        put_greeks_score, put_greeks_factors = calculate_greeks_score(put_greeks_analysis, 'put')
        
        # 5. 计算总强度并生成信号（GROK v2.0：边界反弹40% + RSI 15% + MACD 15% + Greeks 20% + 日线趋势10% = 100%）
        # Call信号
        overall_trend = (
            "强势"
            if daily_trend_result.get("direction") == "bullish"
            else "弱势"
            if daily_trend_result.get("direction") == "bearish"
            else "震荡"
        )
        # 本版未接入额外“大盘辅助”因子；保留接口字段以避免未定义变量报错。
        macro_factors: List[str] = []
        if etf_turnover_score > 0 and (rsi_divergence.get('divergence_type') == 'bullish' or 
                                       macd_turnover.get('turnover_type') == 'bullish' or
                                       boundary_rebound.get('rebound_type') == 'call'):
            total_strength_call = etf_turnover_score + call_greeks_score + daily_trend_score_call
            
            # 详细日志：强度分解（GROK v2.0）
            logger.debug(f"Call信号强度分解(GROK v2.0): ETF转折={etf_turnover_score:.3f}, Greeks确认={call_greeks_score:.3f}, "
                        f"日线趋势={daily_trend_score_call:.3f}, 总强度={total_strength_call:.3f}, "
                        f"阈值={min_signal_strength_call:.3f}, 是否生成={'是' if total_strength_call >= min_signal_strength_call else '否'}")
            
            if total_strength_call >= min_signal_strength_call:
                # 确定信号级别
                if total_strength_call >= strong_threshold:
                    signal_type_label = "强信号"
                elif total_strength_call >= medium_threshold:
                    signal_type_label = "中等信号"
                else:
                    signal_type_label = "弱信号"
                
                # 构建触发因子说明（GROK v2.0）
                trigger_factors = []
                if etf_turnover_factors:
                    trigger_factors.append(f"ETF短期K线：{', '.join(etf_turnover_factors)}")
                if call_greeks_factors:
                    trigger_factors.append(f"Greeks/IV确认：{', '.join(call_greeks_factors)}")
                if daily_trend_factors:
                    trigger_factors.append(f"{', '.join(daily_trend_factors)}")
                
                reason = f"边界转折信号（GROK v2.0优化）: {' | '.join(trigger_factors)}"
                
                # 获取合约信息
                call_ranges = volatility_ranges.get('call_ranges', []) if volatility_ranges else []
                call_range = call_ranges[0] if call_ranges else {}
                contract_code = call_range.get('contract_code')
                contract_name = call_range.get('name', contract_code or 'Call')
                
                signal = create_signal_with_volatility_range(
                    signal_type='call',
                    reason=reason,
                    rsi=float(rsi.iloc[-1]) if not rsi.empty else 50.0,
                    price_change=float(price_change.iloc[-1]) if not price_change.empty else 0.0,
                    trend=overall_trend,
                    strength=total_strength_call,
                    signal_type_label=signal_type_label,
                    volatility_ranges=volatility_ranges or {},
                    etf_current_price=etf_current_price,
                    call_option_price=call_option_price or call_range.get('current_price'),
                    deduplication_time=deduplication_time
                )
                
                if signal:
                    signal['contract_code'] = contract_code
                    signal['contract_name'] = contract_name
                    signal['trigger_factors'] = trigger_factors
                    signal['etf_turnover_score'] = round(etf_turnover_score, 3)
                    signal['greeks_score'] = round(call_greeks_score, 3)
                    signal['daily_trend_score'] = round(daily_trend_score_call, 3)  # GROK v2.0：日线趋势分数
                    
                    # 弱信号默认不推送通知，但会在Web显示
                    if signal_type_label == "弱信号" and not enable_weak_notification:
                        signal['skip_notification'] = True
                        signal['display_in_web'] = True  # 弱信号在Web显示，便于用户手动查看
                    
                    signals.append(signal)
        
        # Put信号（GROK v2.0权重分配）
        if etf_turnover_score > 0 and (rsi_divergence.get('divergence_type') == 'bearish' or 
                                       macd_turnover.get('turnover_type') == 'bearish' or
                                       boundary_rebound.get('rebound_type') == 'put'):
            total_strength_put = etf_turnover_score + put_greeks_score + daily_trend_score_put
            
            # 详细日志：强度分解（GROK v2.0）
            logger.debug(f"Put信号强度分解(GROK v2.0): ETF转折={etf_turnover_score:.3f}, Greeks确认={put_greeks_score:.3f}, "
                        f"日线趋势={daily_trend_score_put:.3f}, 总强度={total_strength_put:.3f}, "
                        f"阈值={min_signal_strength_put:.3f}, 是否生成={'是' if total_strength_put >= min_signal_strength_put else '否'}")
            
            if total_strength_put >= min_signal_strength_put:
                # 确定信号级别
                if total_strength_put >= strong_threshold:
                    signal_type_label = "强信号"
                elif total_strength_put >= medium_threshold:
                    signal_type_label = "中等信号"
                else:
                    signal_type_label = "弱信号"
                
                # 构建触发因子说明
                trigger_factors = []
                if etf_turnover_factors:
                    trigger_factors.append(f"ETF短期K线：{', '.join(etf_turnover_factors)}")
                if put_greeks_factors:
                    trigger_factors.append(f"Greeks/IV确认：{', '.join(put_greeks_factors)}")
                if macro_factors:
                    trigger_factors.append(f"大盘辅助：{', '.join(macro_factors)}")
                
                reason = f"边界转折信号（优化v1.0）: {' | '.join(trigger_factors)}"
                
                # 获取合约信息
                put_ranges = volatility_ranges.get('put_ranges', []) if volatility_ranges else []
                put_range = put_ranges[0] if put_ranges else {}
                contract_code = put_range.get('contract_code')
                contract_name = put_range.get('name', contract_code or 'Put')
                
                signal = create_signal_with_volatility_range(
                    signal_type='put',
                    reason=reason,
                    rsi=float(rsi.iloc[-1]) if not rsi.empty else 50.0,
                    price_change=float(price_change.iloc[-1]) if not price_change.empty else 0.0,
                    trend=overall_trend,
                    strength=total_strength_put,
                    signal_type_label=signal_type_label,
                    volatility_ranges=volatility_ranges or {},
                    etf_current_price=etf_current_price,
                    put_option_price=put_option_price or put_range.get('current_price'),
                    deduplication_time=deduplication_time
                )
                
                if signal:
                    signal['contract_code'] = contract_code
                    signal['contract_name'] = contract_name
                    signal['trigger_factors'] = trigger_factors
                    signal['etf_turnover_score'] = round(etf_turnover_score, 3)
                    signal['greeks_score'] = round(put_greeks_score, 3)
                    signal['daily_trend_score'] = round(daily_trend_score_put, 3)  # GROK v2.0：日线趋势分数
                    
                    # 弱信号默认不推送通知，但会在Web显示
                    if signal_type_label == "弱信号" and not enable_weak_notification:
                        signal['skip_notification'] = True
                        signal['display_in_web'] = True  # 弱信号在Web显示，便于用户手动查看
                    
                    signals.append(signal)
        
        # 输出总结日志
        logger.info(f"优化方案v1.0生成信号: {len(signals)}个")
        if signals:
            strong_count = sum(1 for s in signals if s.get('signal_type_label') == '强信号')
            medium_count = sum(1 for s in signals if s.get('signal_type_label') == '中等信号')
            weak_count = sum(1 for s in signals if s.get('signal_type_label') == '弱信号')
            logger.info(f"信号分级统计: 强信号={strong_count}, 中等信号={medium_count}, 弱信号={weak_count}")
            for signal in signals:
                logger.debug(f"信号详情: {signal.get('signal_type')} {signal.get('signal_type_label')}, "
                           f"强度={signal.get('signal_strength', 0):.3f}, "
                           f"ETF转折={signal.get('etf_turnover_score', 0):.3f}, "
                           f"Greeks确认={signal.get('greeks_score', 0):.3f}, "
                           f"大盘辅助={signal.get('macro_score', 0):.3f}")
        else:
            logger.debug(f"未生成信号原因: ETF转折分数={etf_turnover_score:.3f}, "
                        f"Call Greeks={call_greeks_score:.3f}, Put Greeks={put_greeks_score:.3f}, "
                        f"Call阈值={min_signal_strength_call:.3f}, Put阈值={min_signal_strength_put:.3f}")
        
        # LLM增强信号生成（v1.1优化方案）
        signal_params = config.get('signal_params', {})
        llm_watch_enabled = signal_params.get('llm_watch_enabled', False)
        
        if llm_watch_enabled and signals:
            try:
                from src.llm_enhancer import enhance_with_llm
                
                llm_watch_threshold = signal_params.get('llm_watch_threshold', 0.5)
                llm_watch_cache_minutes = signal_params.get('llm_watch_cache_minutes', 5)
                sequence_threshold_high = signal_params.get('llm_watch_sequence_threshold_high', 0.6)
                sequence_threshold_low = signal_params.get('llm_watch_sequence_threshold_low', 0.5)
                
                # 获取标的物代码（从volatility_ranges或信号中提取，或使用默认值）
                # 注意：由于信号生成时可能没有直接传入underlying，我们从配置中获取
                underlying = '510300'  # 默认值
                try:
                    # 尝试从配置中获取当前标的物
                    option_contracts = config.get('option_contracts', {})
                    underlyings_list = option_contracts.get('underlyings', [])
                    if underlyings_list and isinstance(underlyings_list, list) and len(underlyings_list) > 0:
                        # 使用第一个标的物（如果系统支持多标的物，这里可以进一步优化）
                        underlying = str(underlyings_list[0].get('underlying', '510300'))
                except Exception as e:
                    logger.debug(f"LLM watch 提取 underlying 失败，使用默认值: {e}", exc_info=True)
                
                # 对每个信号进行LLM增强
                enhanced_signals = []
                for signal in signals:
                    total_strength = signal.get('signal_strength', 0.0)
                    
                    # 检查是否达到触发阈值
                    if total_strength < llm_watch_threshold:
                        enhanced_signals.append(signal)
                        continue
                    
                    # 检查调用频率限制（同一标的物N分钟内最多1次）
                    cache_window = int(time.time() / (llm_watch_cache_minutes * 60))
                    cache_key = f"llm_watch_{underlying}_{cache_window}"
                    
                    if cache_key in _llm_watch_cache:
                        # 使用缓存结果
                        cached_result = _llm_watch_cache[cache_key]
                        logger.debug(f"LLM增强使用缓存结果: {cache_key}")
                        if cached_result and cached_result.get('turnover_judgment', '').startswith('是'):
                            signal['llm_confirm'] = cached_result.get('turnover_strength', total_strength)
                            signal['llm_explanation'] = cached_result.get('explanation', [])
                            signal['llm_risk_warning'] = cached_result.get('risk_warning', '')
                            signal['llm_trading_suggestion'] = cached_result.get('trading_suggestion', '')
                        enhanced_signals.append(signal)
                        continue
                    
                    try:
                        # 确定序列数据条数
                        if total_strength >= sequence_threshold_high:
                            sequence_count = 10
                        elif total_strength >= sequence_threshold_low:
                            sequence_count = 5
                        else:
                            sequence_count = 0
                        
                        # 准备输入数据
                        input_data = prepare_llm_input(
                            index_minute=index_minute,
                            etf_current_price=etf_current_price,
                            rsi=rsi,
                            price_change=price_change,
                            call_option_greeks=call_option_greeks,
                            put_option_greeks=put_option_greeks,
                            opening_strategy=opening_strategy,
                            volatility_ranges=volatility_ranges,
                            total_strength=total_strength,
                            sequence_count=sequence_count,
                            underlying=underlying
                        )
                        
                        if not input_data:
                            logger.warning("LLM输入数据准备失败，跳过增强")
                            enhanced_signals.append(signal)
                            continue
                        
                        # 调用LLM
                        llm_summary, llm_meta = enhance_with_llm(input_data, 'signal_watch', config)
                        
                        if not llm_summary:
                            logger.debug("LLM增强返回空，跳过")
                            enhanced_signals.append(signal)
                            continue
                        
                        # 解析LLM输出
                        llm_result = parse_llm_output(llm_summary)
                        
                        # 更新缓存
                        if llm_result:
                            _llm_watch_cache[cache_key] = llm_result
                            
                            # 清理过期缓存（保留最近3个窗口）
                            current_window = cache_window
                            keys_to_remove = [k for k in list(_llm_watch_cache.keys()) 
                                           if int(k.split('_')[-1]) < current_window - 2]
                            for k in keys_to_remove:
                                del _llm_watch_cache[k]
                        
                        if llm_result and llm_result.get('turnover_judgment', '').startswith('是'):
                            signal['llm_confirm'] = llm_result.get('turnover_strength', total_strength)
                            signal['llm_explanation'] = llm_result.get('explanation', [])
                            signal['llm_risk_warning'] = llm_result.get('risk_warning', '')
                            signal['llm_trading_suggestion'] = llm_result.get('trading_suggestion', '')
                            logger.info(f"LLM确认转折信号: {llm_result.get('turnover_judgment')}, "
                                     f"强度={llm_result.get('turnover_strength', 0):.3f}")
                        else:
                            judgment = llm_result.get('turnover_judgment', '解析失败') if llm_result else '解析失败'
                            logger.debug(f"LLM未确认转折: {judgment}")
                            # LLM未确认时，仍然保留信号，但不添加LLM增强信息
                        
                        enhanced_signals.append(signal)
                        
                    except Exception as e:
                        logger.warning(f"LLM增强失败，回退到规则信号: {e}")
                        # 继续使用规则信号，不阻断流程
                        enhanced_signals.append(signal)
                
                signals = enhanced_signals
                logger.info(f"LLM增强完成，最终信号数: {len(signals)}")
                
            except ImportError:
                logger.warning("LLM增强模块未找到，跳过增强")
            except Exception as e:
                log_error_with_context(
                    logger, e,
                    {'function': '_generate_signals_optimized_v1', 'step': 'llm_enhancement'},
                    "LLM增强过程异常"
                )
        
        return signals
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': '_generate_signals_optimized_v1'},
            "优化方案v1.0信号生成失败"
        )
        return []
