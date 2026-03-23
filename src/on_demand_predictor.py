"""
即时波动区间预测模块
支持通过飞书消息即时预测指数、ETF和期权合约的日内波动区间
"""

import pandas as pd
from typing import Dict, Optional, Any
from datetime import datetime
import pytz

from src.logger_config import get_module_logger
from src.config_loader import load_system_config, get_underlyings
from src.data_collector import (
    fetch_index_minute_data_with_fallback,
    fetch_etf_minute_data_with_fallback,
    get_etf_current_price,
    get_index_current_price,
    get_option_current_price,
    fetch_option_greeks_sina
)
from src.volatility_range import (
    calculate_index_volatility_range_multi_period,
    calculate_etf_volatility_range_multi_period,
    calculate_option_volatility_range,
    get_remaining_trading_time
)
from src.indicator_calculator import calculate_rsi, calculate_macd
from src.prediction_recorder import record_prediction

logger = get_module_logger(__name__)


def _calculate_position_and_trend(
    current_price: float,
    upper: float,
    lower: float,
    minute_data: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    计算当前价格在区间中的位置并分析趋势
    基于综合评分机制预测未来走向：向上、向下、横盘
    
    Args:
        current_price: 当前价格
        upper: 预测上轨
        lower: 预测下轨
        minute_data: 分钟数据（可选，用于计算RSI、MACD等技术指标）
    
    Returns:
        dict: 包含位置、趋势判断、技术指标等信息
    """
    try:
        # 计算位置（0-1，0为下轨，1为上轨）
        range_width = upper - lower
        if range_width > 0:
            position = (current_price - lower) / range_width
            position = max(0.0, min(1.0, position))  # 限制在0-1之间
        else:
            position = 0.5
        
        # 位置描述
        if position >= 0.7:
            position_desc = "接近上轨"
        elif position <= 0.3:
            position_desc = "接近下轨"
        else:
            position_desc = "区间中部"
        
        # 初始化技术指标
        rsi_value = None
        rsi_status = None
        macd_histogram = None
        macd_status = None
        momentum_score = 0.0
        
        # 计算技术指标（如果有分钟数据）
        if minute_data is not None and not minute_data.empty:
            try:
                # 计算RSI
                rsi_series = calculate_rsi(minute_data, close_col='收盘', period=14)
                if rsi_series is not None and not rsi_series.empty:
                    rsi_value = float(rsi_series.iloc[-1])
                    if rsi_value >= 70:
                        rsi_status = "超买"
                    elif rsi_value <= 30:
                        rsi_status = "超卖"
                    else:
                        rsi_status = "正常"
            except Exception as e:
                logger.debug(f"计算RSI失败: {e}")
            
            try:
                # 计算MACD
                macd_result = calculate_macd(minute_data, close_col='收盘')
                if macd_result is not None:
                    histogram_series = macd_result.get('histogram')
                    if histogram_series is not None and not histogram_series.empty:
                        macd_histogram = float(histogram_series.iloc[-1])
            except Exception as e:
                logger.debug(f"计算MACD失败: {e}")
            
            try:
                # 计算价格动量（最近5个周期的平均涨跌幅）
                if len(minute_data) >= 5 and '收盘' in minute_data.columns:
                    close_prices = minute_data['收盘'].tail(5)
                    if len(close_prices) >= 2:
                        # 计算最近5个周期的价格变化率
                        price_changes = close_prices.pct_change().dropna()
                        if len(price_changes) > 0:
                            avg_change = float(price_changes.mean()) * 100  # 转换为百分比
                            # 动量得分：涨跌幅 > 0.3% 为 +0.4，< -0.3% 为 -0.4
                            if avg_change > 0.3:
                                momentum_score = 0.4
                            elif avg_change < -0.3:
                                momentum_score = -0.4
                            else:
                                momentum_score = 0.0
            except Exception as e:
                logger.debug(f"计算价格动量失败: {e}")
        
        # 综合评分机制
        # 1. 位置得分（-0.5 到 0.5）
        if position <= 0.3:
            position_score = 0.5  # 接近下轨，向上倾向
        elif position >= 0.7:
            position_score = -0.5  # 接近上轨，向下倾向
        else:
            position_score = 0.0  # 区间中部，中性
        
        # 2. RSI得分（-0.8 到 0.8）
        rsi_score = 0.0
        if rsi_value is not None:
            if rsi_value <= 30:
                rsi_score = 0.8  # 超卖，向上
            elif rsi_value >= 70:
                rsi_score = -0.8  # 超买，向下
            elif 30 < rsi_value < 50:
                rsi_score = 0.3  # 偏弱，向上
            elif 50 < rsi_value < 70:
                rsi_score = -0.3  # 偏强，向下
        
        # 3. MACD得分（-0.6 到 0.6）
        macd_score = 0.0
        if macd_histogram is not None:
            if macd_histogram > 0:
                macd_score = 0.6  # MACD柱状图为正，向上
                macd_status = "零轴上方（多头）"
            elif macd_histogram < 0:
                macd_score = -0.6  # MACD柱状图为负，向下
                macd_status = "零轴下方（空头）"
            else:
                macd_status = "零轴附近（中性）"
        
        # 4. 动量得分（已在上面计算，-0.4 到 0.4）
        
        # 计算综合得分（正数表示向上倾向，负数表示向下倾向）
        total_score = position_score + rsi_score + macd_score + momentum_score
        
        # 判断阈值
        threshold = 0.3
        
        # 最终趋势判断
        if total_score > threshold:
            trend_direction = "向上"
        elif total_score < -threshold:
            trend_direction = "向下"
        else:
            trend_direction = "横盘"

        # 简单风险场景与提示（B/C 方案）
        if position <= 0.3:
            scenario = "弱势回调"
            scenario_hint = "靠近下轨，关注支撑是否有效，可考虑逢低布局或保护性看跌策略"
            risk_level = "high"
        elif position >= 0.7:
            scenario = "强势突破"
            scenario_hint = "靠近上轨，关注阻力突破与否，可考虑看涨价差或分批止盈"
            risk_level = "high"
        else:
            scenario = "震荡区间"
            scenario_hint = "区间中部，震荡概率较高，适合铁秃鹰/蝶式等中性策略或等待突破确认"
            risk_level = "medium"

        return {
            "position": round(position, 4),
            "position_desc": position_desc,
            "trend_direction": trend_direction,
            "rsi_value": rsi_value,
            "rsi_status": rsi_status,
            "macd_status": macd_status,
            "scenario": scenario,
            "scenario_hint": scenario_hint,
            "risk_level": risk_level,
        }
    except Exception as e:
        logger.error(f"计算位置和趋势失败: {e}")
        return {
            "position": 0.5,
            "position_desc": "区间中部",
            "trend_direction": "横盘",
            "rsi_value": None,
            "rsi_status": None,
            "macd_status": None,
            "scenario": "震荡区间",
            "scenario_hint": "区间中部，震荡概率较高，适合中性策略或观望",
            "risk_level": "medium",
        }


def predict_index_volatility_range_on_demand(
    symbol: str = "000300",
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    即时预测指定指数的日内波动区间
    
    Args:
        symbol: 指数代码（如"000300"）
        config: 系统配置，如果为None则自动加载
    
    Returns:
        dict: 预测结果，包含波动区间、位置、趋势等信息
    """
    try:
        if config is None:
            config = load_system_config()
        
        logger.info(f"开始即时预测指数波动区间: {symbol}")
        
        # 获取指数分钟数据（30分钟和15分钟）
        index_minute_30m, index_minute_15m = fetch_index_minute_data_with_fallback(
            lookback_days=5,
            max_retries=2,
            retry_delay=1.0
        )
        
        if index_minute_30m is None or index_minute_30m.empty:
            return {
                'success': False,
                'error': '指数分钟数据获取失败',
                'symbol': symbol
            }
        
        # 获取当前价格：优先使用实时指数现货价格，失败则回退到分钟K线最后收盘价
        spot_price = get_index_current_price(symbol)
        if spot_price is not None and spot_price > 0:
            current_price = float(spot_price)
        else:
            current_price = float(index_minute_30m['收盘'].iloc[-1])
        
        # 计算剩余交易时间
        remaining_minutes = get_remaining_trading_time(config)
        
        # 计算波动区间
        volatility_range = calculate_index_volatility_range_multi_period(
            index_minute_30m=index_minute_30m,
            index_minute_15m=index_minute_15m if index_minute_15m is not None and not index_minute_15m.empty else index_minute_30m,
            current_price=current_price,
            remaining_minutes=remaining_minutes,
            is_etf_data=False,
            price_ratio=1.0
        )
        
        # 计算位置和趋势
        position_trend = _calculate_position_and_trend(
            current_price=current_price,
            upper=volatility_range.get('upper', current_price * 1.02),
            lower=volatility_range.get('lower', current_price * 0.98),
            minute_data=index_minute_30m,
        )
        
        # 指数名称映射
        index_names = {
            "000300": "沪深300",
            "000001": "上证指数",
            "000016": "上证50",
            "000905": "中证500",
            "399001": "深证成指",
            "399006": "创业板指"
        }
        
        result = {
            'success': True,
            'type': 'index',
            'symbol': symbol,
            'symbol_name': index_names.get(symbol, symbol),
            'current_price': round(current_price, 2),
            'upper': volatility_range.get('upper', current_price * 1.02),
            'lower': volatility_range.get('lower', current_price * 0.98),
            'range_pct': volatility_range.get('range_pct', 2.0),
            'confidence': volatility_range.get('confidence', 0.5),
            'method': volatility_range.get('method', '综合方法'),
            'remaining_minutes': remaining_minutes,
            'position': position_trend['position'],
            'position_desc': position_trend['position_desc'],
            'trend_direction': position_trend['trend_direction'],
            'rsi_value': position_trend['rsi_value'],
            'rsi_status': position_trend['rsi_status'],
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # GROK优化：添加突破概率（如果volatility_range中有）
        if 'breakthrough_probability' in volatility_range:
            result['breakthrough_probability'] = volatility_range['breakthrough_probability']
        
        # ========== LLM增强：波动预测（指数使用标的物Prompt） ==========
        try:
            from src.llm_enhancer import enhance_with_llm
            llm_config = config.get('llm_enhancer', {}) if config else {}
            if llm_config.get('enabled', False) and 'volatility_prediction' in llm_config.get('analysis_types', []):
                # 添加当前日期时间信息，帮助LLM正确理解时间上下文
                tz_shanghai = pytz.timezone('Asia/Shanghai')
                now = datetime.now(tz_shanghai)
                result['current_date'] = now.strftime('%Y-%m-%d')
                result['current_datetime'] = now.strftime('%Y-%m-%d %H:%M:%S')
                logger.info("开始调用LLM增强指数波动预测...")
                llm_summary, llm_meta = enhance_with_llm(result, 'volatility_prediction_underlying', config)
                if llm_summary:
                    result['llm_summary'] = llm_summary
                    if llm_meta:
                        result['llm_meta'] = llm_meta
                    logger.info("波动预测LLM增强完成（指数）")
                else:
                    logger.warning("波动预测LLM增强返回空结果（指数），可能调用失败")
            else:
                logger.debug("LLM增强未启用或volatility_prediction不在analysis_types中，跳过（指数）")
        except Exception as e:
            logger.warning(f"波动预测LLM增强失败（指数），已忽略: {e}", exc_info=True)
        # ========== LLM增强结束 ==========
        
        # 记录预测
        try:
            record_prediction(
                prediction_type='index',
                symbol=symbol,
                prediction={
                    'upper': result['upper'],
                    'lower': result['lower'],
                    'current_price': result['current_price'],
                    'method': result['method'],
                    'confidence': result['confidence'],
                    'range_pct': result['range_pct'],
                    'timestamp': result['timestamp']
                },
                source='on_demand',
                config=config
            )
        except Exception as e:
            logger.warning(f"记录指数预测失败: {e}")
        
        return result
    except Exception as e:
        logger.error(f"预测指数波动区间失败: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'symbol': symbol
        }


def predict_etf_volatility_range_on_demand(
    symbol: str = "510300",
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    即时预测指定ETF的日内波动区间
    
    Args:
        symbol: ETF代码（如"510300"）
        config: 系统配置，如果为None则自动加载
    
    Returns:
        dict: 预测结果，包含波动区间、位置、趋势等信息
    """
    try:
        if config is None:
            config = load_system_config()
        
        logger.info(f"开始即时预测ETF波动区间: {symbol}")
        
        # 获取ETF当前价格
        etf_price = get_etf_current_price(symbol)
        if etf_price is None:
            return {
                'success': False,
                'error': f'无法获取ETF {symbol} 的当前价格',
                'symbol': symbol
            }
        
        # 获取ETF分钟数据（30分钟和15分钟）
        # 提高数据周期长度：从5天增加到15天，确保有足够数据计算技术指标
        # MACD需要至少35个数据点（slow=26 + signal=9），30分钟数据需要约9天（35/4≈9）
        # 历史波动率和布林带需要至少20期，30分钟数据需要约5天（20/4=5）
        # 设置为15天，确保所有指标都能正常计算，并留有缓冲
        etf_minute_30m, etf_minute_15m = fetch_etf_minute_data_with_fallback(
            underlying=symbol,
            lookback_days=15,  # 从5天增加到15天，确保有足够数据计算MACD等指标
            max_retries=2,
            retry_delay=1.0
        )
        
        if etf_minute_30m is None or etf_minute_30m.empty:
            return {
                'success': False,
                'error': f'ETF {symbol} 分钟数据获取失败',
                'symbol': symbol
            }
        
        # 计算剩余交易时间
        remaining_minutes = get_remaining_trading_time(config)
        
        # 计算波动区间
        volatility_range = calculate_etf_volatility_range_multi_period(
            etf_minute_30m=etf_minute_30m,
            etf_minute_15m=etf_minute_15m if etf_minute_15m is not None and not etf_minute_15m.empty else etf_minute_30m,
            etf_current_price=etf_price,
            remaining_minutes=remaining_minutes,
            underlying=symbol,  # 传入ETF代码用于IV融合
            config=config
        )
        
        # 计算位置和趋势
        position_trend = _calculate_position_and_trend(
            current_price=etf_price,
            upper=volatility_range.get('upper', etf_price * 1.02),
            lower=volatility_range.get('lower', etf_price * 0.98),
            minute_data=etf_minute_30m,
        )
        
        # ETF名称映射
        etf_names = {
            "510300": "沪深300ETF",
            "510050": "上证50ETF",
            "510500": "中证500ETF",
            "159919": "沪深300ETF（深市）"
        }
        
        result = {
            'success': True,
            'type': 'etf',
            'symbol': symbol,
            'symbol_name': etf_names.get(symbol, symbol),
            'current_price': round(etf_price, 4),
            'upper': volatility_range.get('upper', etf_price * 1.02),
            'lower': volatility_range.get('lower', etf_price * 0.98),
            'range_pct': volatility_range.get('range_pct', 2.0),
            'confidence': volatility_range.get('confidence', 0.5),
            'method': volatility_range.get('method', '综合方法'),
            'remaining_minutes': remaining_minutes,
            'position': position_trend['position'],
            'position_desc': position_trend['position_desc'],
            'trend_direction': position_trend['trend_direction'],
            'rsi_value': position_trend['rsi_value'],
            'rsi_status': position_trend['rsi_status'],
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # GROK优化：添加突破概率（如果volatility_range中有）
        if 'breakthrough_probability' in volatility_range:
            result['breakthrough_probability'] = volatility_range['breakthrough_probability']
        
        # ========== LLM增强：波动预测（ETF使用标的物Prompt） ==========
        try:
            from src.llm_enhancer import enhance_with_llm
            llm_config = config.get('llm_enhancer', {}) if config else {}
            if llm_config.get('enabled', False) and 'volatility_prediction' in llm_config.get('analysis_types', []):
                # 添加当前日期时间信息，帮助LLM正确理解时间上下文
                tz_shanghai = pytz.timezone('Asia/Shanghai')
                now = datetime.now(tz_shanghai)
                result['current_date'] = now.strftime('%Y-%m-%d')
                result['current_datetime'] = now.strftime('%Y-%m-%d %H:%M:%S')
                logger.info("开始调用LLM增强ETF波动预测...")
                llm_summary, llm_meta = enhance_with_llm(result, 'volatility_prediction_underlying', config)
                if llm_summary:
                    result['llm_summary'] = llm_summary
                    if llm_meta:
                        result['llm_meta'] = llm_meta
                    logger.info("波动预测LLM增强完成（ETF）")
                else:
                    logger.warning("波动预测LLM增强返回空结果（ETF），可能调用失败")
            else:
                logger.debug("LLM增强未启用或volatility_prediction不在analysis_types中，跳过（ETF）")
        except Exception as e:
            logger.warning(f"波动预测LLM增强失败（ETF），已忽略: {e}", exc_info=True)
        # ========== LLM增强结束 ==========
        
        # 记录预测
        try:
            record_prediction(
                prediction_type='etf',
                symbol=symbol,
                prediction={
                    'upper': result['upper'],
                    'lower': result['lower'],
                    'current_price': result['current_price'],
                    'method': result['method'],
                    'confidence': result['confidence'],
                    'range_pct': result['range_pct'],
                    'timestamp': result['timestamp']
                },
                source='on_demand',
                config=config
            )
        except Exception as e:
            logger.warning(f"记录ETF预测失败: {e}")
        
        return result
    except Exception as e:
        logger.error(f"预测ETF波动区间失败: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'symbol': symbol
        }


def predict_option_volatility_range_on_demand(
    contract_code: str,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    即时预测指定期权合约的日内波动区间
    
    Args:
        contract_code: 期权合约代码（如"10010474"）
        config: 系统配置，如果为None则自动加载
    
    Returns:
        dict: 预测结果，包含波动区间、位置、趋势等信息
    """
    try:
        if config is None:
            config = load_system_config()
        
        logger.info(f"开始即时预测期权波动区间: {contract_code}")
        
        # 获取期权当前价格和Greeks
        option_price = get_option_current_price(contract_code)
        if option_price is None:
            return {
                'success': False,
                'error': f'无法获取期权合约 {contract_code} 的当前价格',
                'contract_code': contract_code
            }
        
        option_greeks = fetch_option_greeks_sina(contract_code, config=config)
        
        # 从配置中查找合约对应的ETF代码
        option_contracts = config.get('option_contracts', {})
        underlyings_list = get_underlyings(option_contracts)
        underlying = None
        option_type = None
        strike_price = None
        
        # 统一合约代码类型（转换为字符串进行比较，因为配置中可能是整数）
        contract_code_str = str(contract_code)
        contract_code_int = None
        try:
            contract_code_int = int(contract_code)
        except (ValueError, TypeError):
            pass
        
        logger.debug(f"查找合约配置: contract_code={contract_code} (str={contract_code_str}, int={contract_code_int})")
        logger.debug(f"配置中的标的物数量: {len(underlyings_list)}")
        
        # 遍历配置查找对应的ETF代码和期权类型
        for underlying_config in underlyings_list:
            call_contracts = underlying_config.get('call_contracts', [])
            put_contracts = underlying_config.get('put_contracts', [])
            
            logger.debug(f"标的物: {underlying_config.get('underlying')}, Call合约数: {len(call_contracts)}, Put合约数: {len(put_contracts)}")
            
            # 检查Call合约（支持字符串和整数类型匹配）
            for contract in call_contracts:
                config_contract_code = contract.get('contract_code')
                # 支持多种类型匹配：字符串、整数
                if (config_contract_code == contract_code or 
                    str(config_contract_code) == contract_code_str or
                    (contract_code_int is not None and config_contract_code == contract_code_int)):
                    underlying = underlying_config.get('underlying', '510300')
                    option_type = 'call'
                    strike_price = contract.get('strike_price')
                    logger.info(f"找到Call合约: {contract_code} -> ETF {underlying}, 行权价 {strike_price}")
                    break
            
            # 检查Put合约（支持字符串和整数类型匹配）
            if not underlying:
                for contract in put_contracts:
                    config_contract_code = contract.get('contract_code')
                    # 支持多种类型匹配：字符串、整数
                    if (config_contract_code == contract_code or 
                        str(config_contract_code) == contract_code_str or
                        (contract_code_int is not None and config_contract_code == contract_code_int)):
                        underlying = underlying_config.get('underlying', '510300')
                        option_type = 'put'
                        strike_price = contract.get('strike_price')
                        logger.info(f"找到Put合约: {contract_code} -> ETF {underlying}, 行权价 {strike_price}")
                        break
            
            if underlying:
                break
        
        if not underlying:
            # 输出详细的调试信息
            logger.warning(f"未找到合约 {contract_code} 的配置")
            logger.warning("配置中的合约列表:")
            for underlying_config in underlyings_list:
                logger.warning(f"  标的物: {underlying_config.get('underlying')}")
                for contract in underlying_config.get('call_contracts', []):
                    logger.warning(f"    Call: {contract.get('contract_code')} (type: {type(contract.get('contract_code'))})")
                for contract in underlying_config.get('put_contracts', []):
                    logger.warning(f"    Put: {contract.get('contract_code')} (type: {type(contract.get('contract_code'))})")
            
            return {
                'success': False,
                'error': f'无法从配置中找到合约 {contract_code} 对应的ETF代码，请先配置该合约',
                'contract_code': contract_code
            }
        
        if not option_type:
            option_type = 'call'  # 默认值
        
        # 获取ETF波动区间（用于计算期权波动区间）
        # 提高数据周期长度：从5天增加到15天，确保有足够数据计算技术指标
        etf_minute_30m, etf_minute_15m = fetch_etf_minute_data_with_fallback(
            underlying=underlying,
            lookback_days=15,  # 从5天增加到15天，确保有足够数据计算MACD等指标
            max_retries=2,
            retry_delay=1.0
        )
        
        if etf_minute_30m is None or etf_minute_30m.empty:
            return {
                'success': False,
                'error': f'无法获取ETF {underlying} 的分钟数据',
                'contract_code': contract_code
            }
        
        etf_price = get_etf_current_price(underlying)
        if etf_price is None:
            return {
                'success': False,
                'error': f'无法获取ETF {underlying} 的当前价格',
                'contract_code': contract_code
            }
        
        # 计算ETF波动区间
        remaining_minutes = get_remaining_trading_time(config)
        etf_range = calculate_etf_volatility_range_multi_period(
            etf_minute_30m=etf_minute_30m,
            etf_minute_15m=etf_minute_15m if etf_minute_15m is not None and not etf_minute_15m.empty else etf_minute_30m,
            etf_current_price=etf_price,
            remaining_minutes=remaining_minutes,
            underlying=underlying,  # 传入ETF代码用于IV融合
            config=config
        )
        
        # 从Greeks中提取信息
        delta = None
        iv = None
        if option_greeks is not None:
            if isinstance(option_greeks, pd.DataFrame):
                if not option_greeks.empty:
                    delta = option_greeks.get('delta', [None]).iloc[0] if 'delta' in option_greeks.columns else None
                    iv = option_greeks.get('iv', [None]).iloc[0] if 'iv' in option_greeks.columns else None
            elif isinstance(option_greeks, dict):
                delta = option_greeks.get('delta')
                iv = option_greeks.get('iv')
        
        # 计算期权波动区间
        volatility_range = calculate_option_volatility_range(
            option_type=option_type,
            option_current_price=option_price,
            etf_range=etf_range,
            option_greeks=option_greeks,
            strike_price=strike_price,
            remaining_minutes=remaining_minutes,
            config=config,
            contract_code=contract_code
        )
        
        # 计算位置和趋势（期权趋势主要跟随ETF）
        position_trend = _calculate_position_and_trend(
            current_price=option_price,
            upper=volatility_range.get('upper', option_price * 1.1),
            lower=volatility_range.get('lower', option_price * 0.9),
            minute_data=None,  # 期权分钟数据获取较复杂，暂时不计算RSI
        )
        
        # 获取到期日信息（如果配置中有）
        expiry_date = None
        days_to_expiry = None
        if strike_price and option_type:
            for underlying_config in underlyings_list:
                contracts_list = underlying_config.get('call_contracts', []) if option_type == 'call' else underlying_config.get('put_contracts', [])
                for contract in contracts_list:
                    config_contract_code = contract.get('contract_code')
                    if (config_contract_code == contract_code or 
                        str(config_contract_code) == contract_code_str or
                        (contract_code_int is not None and config_contract_code == contract_code_int)):
                        expiry_date = contract.get('expiry_date')
                        if expiry_date:
                            # 计算剩余天数
                            try:
                                from datetime import datetime as dt
                                tz_shanghai = pytz.timezone('Asia/Shanghai')
                                now = datetime.now(tz_shanghai)
                                expiry_dt = dt.strptime(expiry_date, '%Y-%m-%d')
                                days_to_expiry = (expiry_dt.date() - now.date()).days
                                days_to_expiry = max(0, days_to_expiry)
                            except Exception as e:
                                logger.debug(f"计算剩余天数失败: expiry_date={expiry_date}, 错误: {e}", exc_info=True)
                        break
                if expiry_date:
                    break
        
        result = {
            'success': True,
            'type': 'option',
            'contract_code': contract_code,
            'underlying': underlying,
            'current_price': round(option_price, 4),
            'upper': volatility_range.get('upper', option_price * 1.1),
            'lower': volatility_range.get('lower', option_price * 0.9),
            'range_pct': volatility_range.get('range_pct', 10.0),
            'confidence': volatility_range.get('confidence', 0.5),
            'method': volatility_range.get('method', '基于ETF区间和Greeks'),
            'remaining_minutes': remaining_minutes,
            'position': position_trend['position'],
            'position_desc': position_trend['position_desc'],
            'trend_direction': position_trend['trend_direction'],
            'delta': delta,
            'iv': iv,
            'rsi_value': None,  # 期权暂时不计算RSI
            'rsi_status': None,
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 添加到期日信息（如果存在）
        if expiry_date:
            result['expiry_date'] = expiry_date
        if days_to_expiry is not None:
            result['days_to_expiry'] = days_to_expiry
        
        # GROK优化：添加突破概率、IV Percentile上下文、Greeks贡献（如果volatility_range中有）
        if 'breakthrough_probability' in volatility_range:
            result['breakthrough_probability'] = volatility_range['breakthrough_probability']
        if 'iv_percentile_context' in volatility_range:
            result['iv_percentile_context'] = volatility_range['iv_percentile_context']
        if 'greeks_contribution' in volatility_range:
            result['greeks_contribution'] = volatility_range['greeks_contribution']
        
        # ========== LLM增强：波动预测（期权使用期权专用Prompt） ==========
        try:
            from src.llm_enhancer import enhance_with_llm
            llm_config = config.get('llm_enhancer', {}) if config else {}
            if llm_config.get('enabled', False) and 'volatility_prediction' in llm_config.get('analysis_types', []):
                # 添加当前日期时间信息，帮助LLM正确理解时间上下文
                tz_shanghai = pytz.timezone('Asia/Shanghai')
                now = datetime.now(tz_shanghai)
                result['current_date'] = now.strftime('%Y-%m-%d')
                result['current_datetime'] = now.strftime('%Y-%m-%d %H:%M:%S')
                logger.info("开始调用LLM增强期权波动预测...")
                llm_summary, llm_meta = enhance_with_llm(result, 'volatility_prediction_option', config)
                if llm_summary:
                    result['llm_summary'] = llm_summary
                    if llm_meta:
                        result['llm_meta'] = llm_meta
                    logger.info("波动预测LLM增强完成（期权）")
                else:
                    logger.warning("波动预测LLM增强返回空结果（期权），可能调用失败")
            else:
                logger.debug("LLM增强未启用或volatility_prediction不在analysis_types中，跳过（期权）")
        except Exception as e:
            logger.warning(f"波动预测LLM增强失败（期权），已忽略: {e}", exc_info=True)
        # ========== LLM增强结束 ==========
        
        # 记录预测
        try:
            record_prediction(
                prediction_type='option',
                symbol=contract_code,
                prediction={
                    'upper': result['upper'],
                    'lower': result['lower'],
                    'current_price': result['current_price'],
                    'method': result['method'],
                    'confidence': result['confidence'],
                    'range_pct': result['range_pct'],
                    'timestamp': result['timestamp']
                },
                source='on_demand',
                config=config
            )
        except Exception as e:
            logger.warning(f"记录期权预测失败: {e}")
        
        return result
    except Exception as e:
        logger.error(f"预测期权波动区间失败: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'contract_code': contract_code
        }
