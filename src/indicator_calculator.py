"""
技术指标计算模块
使用pandas_ta计算MACD、RSI、ATR、移动平均线等技术指标
"""

import pandas as pd
import pandas_ta_classic as ta
import numpy as np
from typing import Optional, Dict

from src.logger_config import get_module_logger, log_error_with_context, log_function_call, log_function_result

logger = get_module_logger(__name__)


def calculate_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    close_col: str = '收盘'
) -> Optional[Dict[str, pd.Series]]:
    """
    计算MACD指标
    
    Args:
        df: 价格数据DataFrame
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期
        close_col: 收盘价列名
    
    Returns:
        dict: {
            'macd': MACD线,
            'signal': 信号线,
            'histogram': 柱状图
        }，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_macd", fast=fast, slow=slow, signal=signal)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算MACD")
            return None
        
        if close_col not in df.columns:
            logger.warning(f"未找到收盘价列: {close_col}")
            return None
        
        # 确保收盘价数据有效（去除NaN和None值）
        close_series = df[close_col].dropna()
        if len(close_series) < slow + signal:  # 需要足够的数据点
            logger.warning(f"数据点不足，无法计算MACD（需要至少{slow + signal}个数据点，当前{len(close_series)}个）")
            return None
        
        # 确保数据是数值类型
        if not pd.api.types.is_numeric_dtype(close_series):
            logger.warning("收盘价数据不是数值类型，无法计算MACD")
            return None
        
        # 计算MACD（使用原始DataFrame的索引，但只传入有效的收盘价数据）
        try:
            # 创建一个临时的DataFrame，只包含收盘价列
            temp_df = pd.DataFrame({close_col: close_series})
            macd_result = ta.macd(temp_df[close_col], fast=fast, slow=slow, signal=signal)
        except Exception as macd_error:
            logger.warning(f"MACD计算失败: {macd_error}")
            return None
        
        if macd_result is None or (isinstance(macd_result, pd.DataFrame) and macd_result.empty):
            logger.warning("MACD计算结果为空")
            return None
        
        # 检查必要的列是否存在
        macd_col = f'MACD_{fast}_{slow}_{signal}'
        signal_col = f'MACDs_{fast}_{slow}_{signal}'
        histogram_col = f'MACDh_{fast}_{slow}_{signal}'
        
        if macd_col not in macd_result.columns:
            logger.warning(f"MACD结果中缺少列: {macd_col}")
            return None
        
        # 验证数据有效性
        macd_series = macd_result[macd_col]
        
        # 检查signal列是否存在且有效
        if signal_col not in macd_result.columns:
            logger.warning(f"MACD结果中缺少signal列: {signal_col}，无法计算完整的MACD指标")
            return None
        
        signal_series = macd_result[signal_col]
        
        # 检查signal列是否全为NaN
        if signal_series.isna().all():
            logger.warning("MACD signal列全为NaN，无法计算完整的MACD指标")
            return None
        
        # 检查是否有None值（使用isnull()更安全）
        if signal_series.isnull().any():
            logger.debug("MACD signal列包含NaN值，尝试填充")
            # 尝试填充NaN：先向前填充，再向后填充，最后用0填充
            signal_series = signal_series.ffill().bfill().fillna(0)
        
        # 确保signal_series中没有None值（转换为NaN）
        signal_series = signal_series.replace([None], np.nan).fillna(0)
        
        # 计算histogram（如果列存在）
        if histogram_col in macd_result.columns:
            histogram_series = macd_result[histogram_col]
        else:
            # 手动计算histogram: MACD - Signal
            try:
                # 确保两个Series都没有None值
                macd_clean = macd_series.replace([None], np.nan).fillna(0)
                signal_clean = signal_series.replace([None], np.nan).fillna(0)
                histogram_series = macd_clean - signal_clean
            except Exception as e:
                logger.warning(f"无法计算histogram: {e}")
                histogram_series = pd.Series(index=macd_result.index, dtype=float).fillna(0)
        
        if len(macd_series.dropna()) == 0:
            logger.warning("MACD计算结果无效（全为NaN）")
            return None
        
        # 构建结果，确保所有Series都有相同的索引且没有None值
        result = {
            'macd': macd_series.replace([None], np.nan).fillna(0),
            'signal': signal_series,
            'histogram': histogram_series.replace([None], np.nan).fillna(0)
        }
        
        log_function_result(logger, "calculate_macd", "计算成功")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_macd', 'fast': fast, 'slow': slow, 'signal': signal},
            "计算MACD失败"
        )
        return None


def calculate_rsi(
    df: pd.DataFrame,
    period: int = 14,
    close_col: str = '收盘'
) -> Optional[pd.Series]:
    """
    计算RSI指标
    
    Args:
        df: 价格数据DataFrame
        period: RSI周期
        close_col: 收盘价列名
    
    Returns:
        pd.Series: RSI值，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_rsi", period=period)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算RSI")
            return None
        
        if close_col not in df.columns:
            logger.warning(f"未找到收盘价列: {close_col}")
            return None
        
        # 计算RSI
        rsi = ta.rsi(df[close_col], length=period)
        
        if rsi is None or rsi.empty:
            logger.warning("RSI计算结果为空")
            return None
        
        log_function_result(logger, "calculate_rsi", f"计算成功，最新RSI={rsi.iloc[-1]:.2f}")
        return rsi
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_rsi', 'period': period},
            "计算RSI失败"
        )
        return None


def calculate_atr(
    df: pd.DataFrame,
    period: int = 14,
    high_col: str = '最高',
    low_col: str = '最低',
    close_col: str = '收盘'
) -> Optional[pd.Series]:
    """
    计算ATR（平均真实波幅）指标
    
    Args:
        df: 价格数据DataFrame
        period: ATR周期
        high_col: 最高价列名
        low_col: 最低价列名
        close_col: 收盘价列名
    
    Returns:
        pd.Series: ATR值，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_atr", period=period)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算ATR")
            return None
        
        required_cols = [high_col, low_col, close_col]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"缺少必要的列: {missing_cols}")
            return None
        
        # 计算ATR
        atr = ta.atr(df[high_col], df[low_col], df[close_col], length=period)
        
        if atr is None or atr.empty:
            logger.warning("ATR计算结果为空")
            return None
        
        log_function_result(logger, "calculate_atr", f"计算成功，最新ATR={atr.iloc[-1]:.4f}")
        return atr
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_atr', 'period': period},
            "计算ATR失败"
        )
        return None


def calculate_ma(
    df: pd.DataFrame,
    period: int = 20,
    close_col: str = '收盘'
) -> Optional[pd.Series]:
    """
    计算移动平均线（MA）
    
    Args:
        df: 价格数据DataFrame
        period: 移动平均周期
        close_col: 收盘价列名
    
    Returns:
        pd.Series: MA值，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_ma", period=period)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算MA")
            return None
        
        if close_col not in df.columns:
            logger.warning(f"未找到收盘价列: {close_col}，可用列: {df.columns.tolist()}")
            return None
        
        # 检查数据长度是否足够
        if len(df) < period:
            logger.warning(f"数据长度({len(df)})不足，无法计算MA{period}，需要至少{period}条数据")
            return None
        
        # 计算MA
        ma = ta.sma(df[close_col], length=period)
        
        if ma is None or ma.empty:
            logger.warning(f"MA计算结果为空，数据长度: {len(df)}, 周期: {period}")
            return None
        
        log_function_result(logger, "calculate_ma", f"计算成功，最新MA{period}={ma.iloc[-1]:.4f}")
        return ma
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_ma', 'period': period},
            "计算MA失败"
        )
        return None


def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std: float = 2.0,
    close_col: str = '收盘'
) -> Optional[Dict[str, pd.Series]]:
    """
    计算布林带指标
    
    Args:
        df: 价格数据DataFrame
        period: 周期
        std: 标准差倍数
        close_col: 收盘价列名
    
    Returns:
        dict: {
            'upper': 上轨,
            'middle': 中轨（MA）,
            'lower': 下轨
        }，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_bollinger_bands", period=period, std=std)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算布林带")
            return None
        
        if close_col not in df.columns:
            logger.warning(f"未找到收盘价列: {close_col}")
            return None
        
        # 计算布林带
        bb = ta.bbands(df[close_col], length=period, std=std)
        
        if bb is None or bb.empty:
            logger.warning("布林带计算结果为空")
            return None
        
        result = {
            'upper': bb[f'BBU_{period}_{std}'],
            'middle': bb[f'BBM_{period}_{std}'],
            'lower': bb[f'BBL_{period}_{std}']
        }
        
        log_function_result(logger, "calculate_bollinger_bands", "计算成功")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_bollinger_bands', 'period': period, 'std': std},
            "计算布林带失败"
        )
        return None


def calculate_price_change_rate(
    df: pd.DataFrame,
    period: int = 1,
    close_col: str = '收盘'
) -> Optional[pd.Series]:
    """
    计算价格变动率（百分比）
    
    Args:
        df: 价格数据DataFrame
        period: 计算周期（向前看多少期）
        close_col: 收盘价列名
    
    Returns:
        pd.Series: 价格变动率（%），如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_price_change_rate", period=period)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算价格变动率")
            return None
        
        if close_col not in df.columns:
            logger.warning(f"未找到收盘价列: {close_col}")
            return None
        
        # 计算价格变动率
        price_change = df[close_col].pct_change(periods=period) * 100
        
        log_function_result(logger, "calculate_price_change_rate", 
                          f"计算成功，最新变动率={price_change.iloc[-1]:.2f}%")
        return price_change
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_price_change_rate', 'period': period},
            "计算价格变动率失败"
        )
        return None


def calculate_volume_ma(
    df: pd.DataFrame,
    period: int = 20,
    volume_col: str = '成交量'
) -> Optional[pd.Series]:
    """
    计算成交量移动平均
    
    Args:
        df: 价格数据DataFrame
        period: 移动平均周期
        volume_col: 成交量列名
    
    Returns:
        pd.Series: 成交量MA，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_volume_ma", period=period)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算成交量MA")
            return None
        
        if volume_col not in df.columns:
            logger.warning(f"未找到成交量列: {volume_col}")
            return None
        
        # 计算成交量MA
        volume_ma = ta.sma(df[volume_col], length=period)
        
        if volume_ma is None or volume_ma.empty:
            logger.warning("成交量MA计算结果为空")
            return None
        
        log_function_result(logger, "calculate_volume_ma", "计算成功")
        return volume_ma
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_volume_ma', 'period': period},
            "计算成交量MA失败"
        )
        return None


def calculate_historical_volatility(
    df: pd.DataFrame,
    period: int = 20,
    close_col: str = '收盘',
    data_period: str = 'day'  # 新增：数据周期类型，'day'或'minute'
) -> Optional[float]:
    """
    计算历史波动率（标准差）
    
    Args:
        df: 价格数据DataFrame
        period: 计算周期
        close_col: 收盘价列名
        data_period: 数据周期类型，'day'（日线）或'minute'（分钟线），默认'day'
    
    Returns:
        float: 历史波动率（%），如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_historical_volatility", period=period, data_period=data_period)
        
        if df is None or df.empty:
            logger.warning("数据为空，无法计算历史波动率")
            return None
        
        if close_col not in df.columns:
            logger.warning(f"未找到收盘价列: {close_col}")
            return None
        
        # 计算收益率
        returns = df[close_col].pct_change().dropna()
        
        if len(returns) < period:
            logger.warning(f"数据不足，需要至少{period}期数据，实际只有{len(returns)}期")
            return None
        
        # 计算最近period期的标准差
        recent_returns = returns.tail(period)
        std = recent_returns.std()
        
        # 根据数据周期类型年化波动率
        if data_period == 'minute':
            # 分钟数据：假设240分钟/天，252个交易日/年
            # 年化系数 = sqrt(240 * 252)
            annualized_vol = std * np.sqrt(240 * 252) * 100
        else:
            # 日线数据：假设252个交易日/年
            annualized_vol = std * np.sqrt(252) * 100
        
        # 添加合理性检查：限制波动率的最大值
        # 期权价格波动较大，但年化波动率超过500%通常不合理
        MAX_VOLATILITY_THRESHOLD = 500.0
        if annualized_vol > MAX_VOLATILITY_THRESHOLD:
            logger.warning(
                f"历史波动率异常高: {annualized_vol:.2f}%，限制为{MAX_VOLATILITY_THRESHOLD:.2f}% "
                f"(数据周期={data_period}, 标准差={std:.6f})"
            )
            annualized_vol = MAX_VOLATILITY_THRESHOLD
        
        # 检查最小值：波动率不应该为负或过小
        if annualized_vol < 0:
            logger.warning(f"历史波动率为负: {annualized_vol:.2f}%，设为0%")
            annualized_vol = 0.0
        
        log_function_result(logger, "calculate_historical_volatility", 
                          f"计算成功，历史波动率={annualized_vol:.2f}% (数据周期={data_period})")
        return annualized_vol
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_historical_volatility', 'period': period, 'data_period': data_period},
            "计算历史波动率失败"
        )
        return None


def calculate_option_rsi(
    option_minute_data: pd.DataFrame,
    period: int = 14,
    price_col: str = '收盘'
) -> Optional[float]:
    """
    计算期权RSI（相对强弱指标）
    
    Args:
        option_minute_data: 期权分钟K线数据
        period: RSI周期，默认14
        price_col: 价格列名，默认'收盘'
    
    Returns:
        float: 最新RSI值，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_option_rsi", period=period)
        
        if option_minute_data is None or option_minute_data.empty:
            logger.debug("期权分钟数据为空，无法计算RSI")
            return None
        
        # 确定价格列名
        if price_col not in option_minute_data.columns:
            # 尝试其他可能的列名
            for col in ['收盘', 'close', '收盘价', '价格']:
                if col in option_minute_data.columns:
                    price_col = col
                    break
            else:
                logger.debug(f"未找到价格列，可用列: {option_minute_data.columns.tolist()}")
                return None
        
        # 使用通用RSI函数
        rsi_result = calculate_rsi(option_minute_data, period=period, close_col=price_col)
        
        if rsi_result is not None and not rsi_result.empty:
            latest_rsi = rsi_result.iloc[-1]
            log_function_result(logger, "calculate_option_rsi", f"计算成功，RSI={latest_rsi:.2f}")
            return float(latest_rsi)
        else:
            logger.debug("期权RSI计算结果为空")
            return None
            
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_option_rsi', 'period': period},
            "计算期权RSI失败"
        )
        return None


def calculate_option_macd(
    option_minute_data: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    price_col: str = '收盘'
) -> Optional[Dict[str, float]]:
    """
    计算期权MACD指标
    
    Args:
        option_minute_data: 期权分钟K线数据
        fast: 快线周期，默认12
        slow: 慢线周期，默认26
        signal: 信号线周期，默认9
        price_col: 价格列名，默认'收盘'
    
    Returns:
        dict: {
            'macd': MACD值,
            'signal': 信号线值,
            'histogram': 柱状图值
        }，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_option_macd", fast=fast, slow=slow, signal=signal)
        
        if option_minute_data is None or option_minute_data.empty:
            logger.debug("期权分钟数据为空，无法计算MACD")
            return None
        
        # 确定价格列名
        if price_col not in option_minute_data.columns:
            # 尝试其他可能的列名
            for col in ['收盘', 'close', '收盘价', '价格']:
                if col in option_minute_data.columns:
                    price_col = col
                    break
            else:
                logger.debug(f"未找到价格列，可用列: {option_minute_data.columns.tolist()}")
                return None
        
        # 使用通用MACD函数
        macd_result = calculate_macd(option_minute_data, fast=fast, slow=slow, signal=signal, close_col=price_col)
        
        if macd_result is not None:
            macd_series = macd_result.get('macd')
            signal_series = macd_result.get('signal')
            histogram_series = macd_result.get('histogram')
            
            if macd_series is not None and not macd_series.empty:
                macd_val: Optional[float] = (
                    float(macd_series.iloc[-1])
                    if not pd.isna(macd_series.iloc[-1])
                    else None
                )
                signal_val: Optional[float] = (
                    float(signal_series.iloc[-1])
                    if signal_series is not None
                    and not signal_series.empty
                    and not pd.isna(signal_series.iloc[-1])
                    else None
                )
                histogram_val: Optional[float] = (
                    float(histogram_series.iloc[-1])
                    if histogram_series is not None
                    and not histogram_series.empty
                    and not pd.isna(histogram_series.iloc[-1])
                    else None
                )
                if macd_val is None or signal_val is None or histogram_val is None:
                    logger.debug("期权MACD计算结果存在NaN/缺失，返回None")
                    return None

                result: Dict[str, float] = {
                    'macd': macd_val,
                    'signal': signal_val,
                    'histogram': histogram_val,
                }
                log_function_result(logger, "calculate_option_macd", 
                                  f"计算成功，MACD={result['macd']:.4f}, Signal={result['signal']:.4f}")
                return result
            else:
                logger.debug("期权MACD计算结果为空")
                return None
        else:
            logger.debug("期权MACD计算结果为空")
            return None
            
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_option_macd', 'fast': fast, 'slow': slow, 'signal': signal},
            "计算期权MACD失败"
        )
        return None


def analyze_option_trend(
    option_minute_data: pd.DataFrame,
    price_col: str = '收盘',
    lookback_periods: int = 5
) -> Optional[str]:
    """
    分析期权价格趋势
    
    Args:
        option_minute_data: 期权分钟K线数据
        price_col: 价格列名，默认'收盘'
        lookback_periods: 回看周期数，默认5
    
    Returns:
        str: 趋势方向（'上升'、'下降'、'震荡'），如果失败返回None
    """
    try:
        log_function_call(logger, "analyze_option_trend", lookback_periods=lookback_periods)
        
        if option_minute_data is None or option_minute_data.empty:
            logger.debug("期权分钟数据为空，无法分析趋势")
            return None
        
        # 确定价格列名
        if price_col not in option_minute_data.columns:
            # 尝试其他可能的列名
            for col in ['收盘', 'close', '收盘价', '价格']:
                if col in option_minute_data.columns:
                    price_col = col
                    break
            else:
                logger.debug(f"未找到价格列，可用列: {option_minute_data.columns.tolist()}")
                return None
        
        if len(option_minute_data) < lookback_periods:
            logger.debug(f"数据不足，需要至少{lookback_periods}条数据，实际只有{len(option_minute_data)}条")
            return None
        
        # 计算最近N个周期的价格变化
        recent_prices = option_minute_data[price_col].tail(lookback_periods)
        price_change_pct = (recent_prices.iloc[-1] - recent_prices.iloc[0]) / recent_prices.iloc[0] * 100
        
        # 判断趋势
        if price_change_pct > 1.0:
            trend = '上升'
        elif price_change_pct < -1.0:
            trend = '下降'
        else:
            trend = '震荡'
        
        log_function_result(logger, "analyze_option_trend", 
                          f"分析成功，价格变化={price_change_pct:.2f}%, 趋势={trend}")
        return trend
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'analyze_option_trend', 'lookback_periods': lookback_periods},
            "分析期权趋势失败"
        )
        return None


def calculate_option_atr(
    option_minute_data: pd.DataFrame,
    period: int = 14,
    price_col: str = '价格'
) -> Optional[pd.Series]:
    """
    计算期权ATR（平均真实波幅）- 适配期权分钟数据格式
    
    期权分钟数据通常只有价格列，没有OHLC（开高低收）数据。
    本函数使用价格序列的变化幅度来估算ATR。
    
    Args:
        option_minute_data: 期权分钟数据DataFrame，包含价格列
        period: ATR周期，默认14
        price_col: 价格列名，默认'价格'，会自动尝试其他可能的列名
    
    Returns:
        pd.Series: ATR值序列，如果失败返回None
    """
    try:
        log_function_call(logger, "calculate_option_atr", period=period)
        
        if option_minute_data is None or option_minute_data.empty:
            logger.debug("期权分钟数据为空，无法计算ATR")
            return None
        
        # 确定价格列名（兼容不同的数据格式）
        if price_col not in option_minute_data.columns:
            # 尝试其他可能的列名
            for col in ['收盘', 'close', '收盘价', '价格', '均价']:
                if col in option_minute_data.columns:
                    price_col = col
                    break
            else:
                logger.debug(f"未找到价格列，可用列: {option_minute_data.columns.tolist()}")
                return None
        
        if len(option_minute_data) < period + 1:
            logger.debug(f"数据不足，需要至少{period + 1}期数据，实际只有{len(option_minute_data)}期")
            return None
        
        # 方法：使用价格变化幅度的滚动平均作为ATR的近似值
        # ATR本质上是价格波动的度量，可以用价格变化的标准差或平均绝对变化来近似
        
        prices = option_minute_data[price_col].astype(float)
        
        # 计算价格变化（绝对值）
        price_changes = prices.diff().abs()
        
        # 计算滚动平均（ATR的近似值）
        # 使用简单移动平均（SMA）而不是指数移动平均（EMA），因为数据可能不连续
        atr = price_changes.rolling(window=period, min_periods=period).mean()
        
        if atr is None or atr.empty or atr.isna().all():
            logger.debug("ATR计算结果为空")
            return None
        
        # 过滤掉NaN值
        atr = atr.dropna()
        
        if len(atr) == 0:
            logger.debug("ATR计算结果为空（过滤后）")
            return None
        
        log_function_result(logger, "calculate_option_atr", 
                          f"计算成功，最新ATR={atr.iloc[-1]:.4f}")
        return atr
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_option_atr', 'period': period, 'price_col': price_col},
            "计算期权ATR失败"
        )
        return None
