"""
数据采集模块
从AKShare获取市场数据（指数、ETF、期权）
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, cast
import time
import pytz
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from src.logger_config import get_module_logger, log_function_call, log_function_result, log_error_with_context
from src.config_loader import load_system_config

logger = get_module_logger(__name__)

# =========================
# 数据源熔断与健康状态管理
# =========================

_data_source_health: Dict[str, Dict[str, Any]] = {}


def _get_circuit_breaker_config(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    获取数据源熔断配置
    """
    if config is None:
        config = load_system_config()
    data_sources_cfg = config.get("data_sources", {})
    cb_cfg = data_sources_cfg.get("circuit_breaker", {})
    return {
        "enabled": cb_cfg.get("enabled", True),
        "error_threshold": cb_cfg.get("error_threshold", 3),
        "cooldown_seconds": cb_cfg.get("cooldown_seconds", 300),
    }


def _is_data_source_available(source_key: str, config: Optional[Dict] = None) -> bool:
    """
    判断数据源当前是否可用（未处于熔断期）
    """
    cb_cfg = _get_circuit_breaker_config(config)
    if not cb_cfg.get("enabled", True):
        return True

    state = _data_source_health.get(source_key)
    if not state:
        return True

    open_until = state.get("circuit_open_until")
    if open_until is None:
        return True

    now = datetime.now(pytz.timezone("Asia/Shanghai"))
    if now >= open_until:
        # 熔断期已结束，视为可用
        state["circuit_open_until"] = None
        state["error_count"] = 0
        return True

    return False


def _record_data_source_success(source_key: str) -> None:
    """
    记录数据源一次成功调用，重置错误计数与熔断状态
    """
    state = _data_source_health.get(source_key)
    if not state:
        _data_source_health[source_key] = {
            "error_count": 0,
            "last_error_time": None,
            "circuit_open_until": None,
        }
        return

    state["error_count"] = 0
    state["circuit_open_until"] = None


def _record_data_source_failure(source_key: str, config: Optional[Dict] = None) -> None:
    """
    记录数据源一次失败调用，并在达到阈值时进入熔断期
    """
    cb_cfg = _get_circuit_breaker_config(config)
    if not cb_cfg.get("enabled", True):
        return

    now = datetime.now(pytz.timezone("Asia/Shanghai"))
    state = _data_source_health.setdefault(
        source_key,
        {"error_count": 0, "last_error_time": None, "circuit_open_until": None},
    )

    state["error_count"] += 1
    state["last_error_time"] = now

    if (
        state["error_count"] >= cb_cfg.get("error_threshold", 3)
        and state.get("circuit_open_until") is None
    ):
        cooldown_seconds = cb_cfg.get("cooldown_seconds", 300)
        state["circuit_open_until"] = now + timedelta(seconds=cooldown_seconds)
        logger.warning(
            f"数据源 {source_key} 进入熔断状态 {cooldown_seconds} 秒（连续失败 {state['error_count']} 次）"
        )

# 缓存配置（从config.yaml读取）
_cache_enabled = None
_cache_config = None

def _get_cache_config(config: Optional[Dict] = None) -> Dict[str, Any]:
    """获取缓存配置"""
    global _cache_config
    if _cache_config is None or config is not None:
        if config is None:
            config = load_system_config()
        _cache_config = config.get('data_cache', {})
    return _cache_config

def _is_cache_enabled(config: Optional[Dict] = None) -> bool:
    """检查缓存是否启用"""
    global _cache_enabled
    if _cache_enabled is None or config is not None:
        cache_config = _get_cache_config(config)
        _cache_enabled = cache_config.get('enabled', True)
    return _cache_enabled


def fetch_index_minute_em(
    symbol: str = "000300",
    period: str = "5",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    max_retries: int = 5,  # 增加重试次数：3 -> 5
    retry_delay: float = 3.0,  # 增加基础延迟：2.0 -> 3.0秒
    fast_fail: bool = False,  # 快速失败模式：如果有缓存数据，减少重试次数
    force_realtime: bool = False  # 强制实时获取：交易时间内不使用当天缓存数据
) -> Optional[pd.DataFrame]:
    """
    获取指数分钟数据（东方财富接口）
    支持重试机制和SSL错误处理
    
    Args:
        symbol: 指数代码（如 "000300" 表示沪深300）
        period: 周期（"1", "5", "15", "30", "60"）
        start_date: 开始日期（格式："YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYYMMDD"），如果为None则使用当前日期
        lookback_days: 回看天数（默认5天，确保有足够数据计算技术指标）
        max_retries: 最大重试次数（默认3次）
        retry_delay: 重试延迟（秒，默认2.0秒）
    
    Returns:
        pd.DataFrame: 指数分钟数据，如果失败返回None
    """
    # 确保symbol是字符串类型（防止配置文件中是整数）
    symbol = str(symbol) if symbol else "000300"
    
    log_function_call(logger, "fetch_index_minute_em", 
                     symbol=symbol, period=period, lookback_days=lookback_days)
    
    # ========== 自动识别 symbol 类型：如果是 ETF 代码，自动调用 fetch_etf_minute_em ==========
    # ETF代码通常以5或1开头（如510300, 159915），指数代码通常以000或399开头（如000300, 399001）
    if symbol.startswith("5") or symbol.startswith("1"):
        # 这是 ETF 代码，自动调用 fetch_etf_minute_em
        logger.info(f"检测到 ETF 代码 {symbol}，自动调用 fetch_etf_minute_em")
        return fetch_etf_minute_em(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            lookback_days=lookback_days,
            max_retries=max_retries,
            retry_delay=retry_delay,
            fast_fail=fast_fail,
            force_realtime=force_realtime
        )
    # ========== symbol 类型检测结束 ==========
    
    # ========== 缓存逻辑：先检查缓存 ==========
    config_for_cache = load_system_config(use_cache=True)
    cached_partial_minute_df = None  # 用于存储部分缓存的数据
    missing_dates = None  # 用于存储缺失的日期列表
    
    if _is_cache_enabled(config_for_cache):
        try:
            from src.data_cache import (
                get_cached_index_minute, save_index_minute_cache,
                merge_cached_and_fetched_data
            )
            
            # 先计算日期范围（用于缓存检查）
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            
            cache_start_date = start_date
            cache_end_date = end_date
            
            if cache_end_date is None:
                cache_end_date = now.strftime("%Y%m%d")
            
            if cache_start_date is None:
                start = now - timedelta(days=lookback_days * 2)
                cache_start_date = start.strftime("%Y%m%d")
            
            # 检查缓存
            cached_df, missing_dates = get_cached_index_minute(
                symbol, period, cache_start_date, cache_end_date, config=config_for_cache
            )
            
            # 如果启用快速失败模式且有部分缓存数据，减少重试次数
            if fast_fail and cached_df is not None and not cached_df.empty:
                original_max_retries = max_retries
                max_retries = min(max_retries, 2)  # 快速失败模式最多重试2次
                retry_delay = min(retry_delay, 1.0)  # 减少延迟时间
                logger.info(f"快速失败模式启用: {symbol} {period}分钟, 有缓存数据, 重试次数: {original_max_retries} -> {max_retries}, 延迟: {retry_delay:.1f}秒")
            
            # 检查 end_date 是否是今天
            is_today = (cache_end_date == now.strftime("%Y%m%d"))
            
            # 检查是否在交易时间内（用于force_realtime判断）
            from src.system_status import get_current_market_status
            market_status = get_current_market_status(config_for_cache)
            is_trading_time = market_status.get('is_trading_time', False)
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中
                if is_today:
                    # 如果 end_date 是今天，需要实时获取当天的数据（因为当天数据会实时更新）
                    # 如果force_realtime=True且在交易时间内，强制实时获取，不使用当天缓存
                    if force_realtime and is_trading_time:
                        logger.info(f"强制实时获取模式: {symbol}, {period}分钟, 交易时间内不使用当天缓存数据")
                        # 保存历史缓存数据（排除今天），用于后续合并
                        # 过滤掉今天的数据
                        date_col = None
                        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                            if col in cached_df.columns:
                                date_col = col
                                break
                        if date_col:
                            if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                                cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
                            today_str = now.strftime("%Y%m%d")
                            historical_data = cached_df[cached_df[date_col].dt.strftime('%Y%m%d') != today_str]
                            if not historical_data.empty:
                                cached_partial_minute_df = historical_data
                                logger.info(f"保留历史缓存数据: {symbol}, {period}分钟, {len(historical_data)} 条")
                            else:
                                cached_partial_minute_df = None
                        else:
                            cached_partial_minute_df = None
                        # 调整日期范围，只获取当天的数据
                        start_date = cache_end_date
                        end_date = cache_end_date
                    else:
                        # 正常情况：保存历史缓存数据，用于后续合并
                        logger.info(f"指数分钟数据缓存命中（历史部分）: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条，但需要实时获取当天数据")
                        cached_partial_minute_df = cached_df
                        # 调整日期范围，只获取当天的数据
                        start_date = cache_end_date
                        end_date = cache_end_date
                else:
                    # 如果 end_date 是历史日期，可以使用全部缓存
                    logger.info(f"指数分钟数据全部从缓存加载: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条")
                    return cached_df
            
            # 计算总日期数
            total_days = (datetime.strptime(cache_end_date, "%Y%m%d") - datetime.strptime(cache_start_date, "%Y%m%d")).days + 1
            
            if cached_df is not None and not cached_df.empty and missing_dates and len(missing_dates) < total_days:
                # 部分缓存命中，需要获取缺失部分并合并
                logger.info(f"指数分钟数据部分缓存命中: {symbol}, {period}分钟, 缺失 {len(missing_dates)} 个日期")
                # 保存已缓存的数据，用于后续合并
                cached_partial_minute_df = cached_df
                # 调整日期范围，只获取缺失部分
                if missing_dates:
                    start_date = min(missing_dates)
                    end_date = max(missing_dates)
        except Exception as e:
            logger.debug(f"缓存检查失败，继续从接口获取: {e}")
    # ========== 缓存逻辑结束 ==========
    
    # 计算日期范围
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date = now.strftime("%Y%m%d")
    
    if start_date is None:
        # 计算回看日期（包括非交易日，确保有足够数据）
        start = now - timedelta(days=lookback_days * 2)  # 乘以2以确保包含非交易日
        start_date = start.strftime("%Y%m%d")
    
    # 重试机制（指数退避策略）
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                # 指数退避：延迟时间 = 基础延迟 * (2 ^ (attempt-1))，最大30秒
                delay = min(retry_delay * (2 ** (attempt - 1)), 30.0)
                logger.debug(f"重试获取指数分钟数据: symbol={symbol}, period={period}, 第{attempt+1}次尝试, 等待{delay:.1f}秒")
                time.sleep(delay)
            
            logger.debug(f"获取指数分钟数据: symbol={symbol}, period={period}, "
                        f"start_date={start_date}, end_date={end_date}")
            
            start_time = time.time()
            minute_df = ak.index_zh_a_hist_min_em(
                symbol=symbol,
                period=period,
                start_date=start_date,
                end_date=end_date
            )
            duration = time.time() - start_time
            
            if minute_df is not None and not minute_df.empty:
                # 转换日期格式为 "YYYY-MM-DD HH:MM:SS"
                if '时间' in minute_df.columns:
                    minute_df['时间'] = pd.to_datetime(minute_df['时间']).dt.strftime('%Y-%m-%d %H:%M:%S')
                elif '日期' in minute_df.columns:
                    minute_df['日期'] = pd.to_datetime(minute_df['日期']).dt.strftime('%Y-%m-%d %H:%M:%S')
                
                log_function_result(logger, "fetch_index_minute_em", 
                                  f"获取到{len(minute_df)}条数据", duration)
                
                # ========== 合并部分缓存数据 ==========
                if _is_cache_enabled(config_for_cache) and cached_partial_minute_df is not None:
                    try:
                        from src.data_cache import merge_cached_and_fetched_data
                        # 找到日期/时间列
                        date_col = None
                        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                            if col in minute_df.columns:
                                date_col = col
                                break
                        cached_count = len(cached_partial_minute_df)
                        # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                        minute_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_minute_df, minute_df, date_col))
                        logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(minute_df) - cached_count} 条 = 总计 {len(minute_df)} 条")
                    except Exception as e:
                        logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
                
                # ========== 保存到缓存 ==========
                if _is_cache_enabled(config_for_cache):
                    try:
                        from src.data_cache import save_index_minute_cache
                        save_index_minute_cache(symbol, period, minute_df, config=config_for_cache)
                    except Exception as e:
                        logger.debug(f"保存缓存失败（不影响主流程）: {e}")
                # ========== 缓存保存结束 ==========
                
                return minute_df
            else:
                logger.warning(f"未获取到指数分钟数据: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "API返回空数据"
                
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, 
                requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
            # SSL错误、连接错误、超时或代理错误，需要重试
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"网络连接错误: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                # 对于连接错误，额外等待一段时间再重试
                extra_wait = min(2.0 * attempt, 10.0)  # 额外等待，最多10秒
                if extra_wait > 0:
                    logger.debug(f"连接错误，额外等待{extra_wait:.1f}秒后重试...")
                    time.sleep(extra_wait)
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_index_minute_em',
                        'symbol': symbol,
                        'period': period,
                        'start_date': start_date,
                        'end_date': end_date,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取指数分钟数据失败（SSL/连接错误，已重试{max_retries}次）"
                )
        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"获取指数分钟数据失败: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_index_minute_em',
                        'symbol': symbol,
                        'period': period,
                        'start_date': start_date,
                        'end_date': end_date,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取指数分钟数据失败（已重试{max_retries}次）"
                )
    
    # 先检查是否有缓存数据，区分降级处理和完全失败
    if cached_partial_minute_df is not None and not cached_partial_minute_df.empty:
        # 有缓存数据：降级处理，记录WARNING
        cache_count = len(cached_partial_minute_df)
        
        # 计算数据完整性信息
        try:
            # 尝试从缓存数据中提取日期范围
            date_col = None
            for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                if col in cached_partial_minute_df.columns:
                    date_col = col
                    break
            
            if date_col:
                # 提取日期信息
                if pd.api.types.is_datetime64_any_dtype(cached_partial_minute_df[date_col]):
                    dates = cached_partial_minute_df[date_col].dt.date.unique()
                else:
                    dates = pd.to_datetime(cached_partial_minute_df[date_col], errors='coerce').dt.date.unique()
                    dates = dates[~pd.isna(dates)]
                
                date_range_str = f"{min(dates)} ~ {max(dates)}" if len(dates) > 0 else "未知"
                missing_count = len(missing_dates) if missing_dates else 0
            else:
                date_range_str = "未知"
                missing_count = len(missing_dates) if missing_dates else 0
        except Exception:
            date_range_str = "未知"
            missing_count = len(missing_dates) if missing_dates else 0
        
        logger.warning(
            f"指数分钟数据API获取失败（已降级使用缓存）: symbol={symbol}, period={period}分钟, "
            f"缓存数据: {cache_count} 条, 日期范围: {date_range_str}, "
            f"缺失日期: {missing_count} 个, 原因: {last_error[:100] if last_error else '未知'}"
        )
        return cached_partial_minute_df
    else:
        # 没有缓存数据：完全失败，记录ERROR
        if "SSL" in str(last_error) or "SSLError" in str(last_error):
            logger.error(f"获取指数分钟数据完全失败: symbol={symbol}, period={period}分钟, "
                        f"可能原因: SSL连接问题或网络不稳定，建议检查网络连接或稍后重试, 无缓存数据可用")
        elif "Connection" in str(last_error) or "连接" in str(last_error):
            logger.error(f"获取指数分钟数据完全失败: symbol={symbol}, period={period}分钟, "
                        f"可能原因: 网络连接问题，建议检查网络连接, 无缓存数据可用")
        else:
            logger.error(f"获取指数分钟数据完全失败: symbol={symbol}, period={period}分钟, "
                        f"原因: {last_error}, 无缓存数据可用")
        return None


def fetch_index_minute_data_with_fallback(
    lookback_days: int = 5,
    max_retries: int = 2,
    retry_delay: float = 1.0,
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    获取指数分钟数据（000300）- 独立获取，不依赖ETF数据
    
    支持多数据源优先级配置（通过config.yaml中的data_sources.index_minute.priority配置）
    默认优先级：["eastmoney", "sina"]
    - eastmoney: 东方财富指数接口（index_zh_a_hist_min_em）
    - sina: 新浪财经接口（CN_MarketData.getKLineData）
    
    Args:
        lookback_days: 回看天数（默认5天）
        max_retries: 最大重试次数（默认2次，每个数据源独立重试）
        retry_delay: 重试延迟（秒，默认1.0秒）
    
    Returns:
        tuple: (30分钟数据, 15分钟数据)
    """
    logger.info("开始获取指数分钟数据（000300）：多数据源优先级")
    
    # 检查是否在交易时间内（用于force_realtime判断）
    from src.system_status import get_current_market_status
    from src.config_loader import load_system_config
    config = load_system_config()
    market_status = get_current_market_status(config)
    is_trading_time = market_status.get('is_trading_time', False)
    force_realtime = is_trading_time  # 交易时间内强制实时获取
    
    # 熔断配置和数据源优先级
    cb_cfg = _get_circuit_breaker_config(config)
    data_sources_config = config.get("data_sources", {})
    index_minute_config = data_sources_config.get("index_minute", {})

    # 默认优先级：["eastmoney", "sina"]
    priority = index_minute_config.get("priority", ["eastmoney", "sina"])

    # 获取各数据源的配置
    eastmoney_config = index_minute_config.get("eastmoney", {})
    sina_config = index_minute_config.get("sina", {})

    # 检查各数据源是否启用
    eastmoney_enabled = eastmoney_config.get("enabled", True)
    sina_enabled = sina_config.get("enabled", True)

    # 过滤掉未启用的数据源
    available_sources = [
        src
        for src in priority
        if (src == "eastmoney" and eastmoney_enabled) or (src == "sina" and sina_enabled)
    ]

    if not available_sources:
        logger.warning("所有指数分钟数据源均未启用，使用默认配置")
        available_sources = ["eastmoney"]  # 默认使用东方财富

    logger.debug(f"指数分钟数据源优先级: {available_sources}")
    
    # ========== 按优先级尝试获取30分钟数据 ==========
    index_30m = None
    for source in available_sources:
        source_key = f"index_minute_{source}"
        if cb_cfg.get("enabled", True) and not _is_data_source_available(source_key, config):
            logger.warning(f"数据源 {source_key} 当前处于熔断期，跳过30分钟数据获取")
            continue
        try:
            if source == 'eastmoney':
                source_max_retries = eastmoney_config.get('max_retries', max_retries)
                source_retry_delay = eastmoney_config.get('retry_delay', retry_delay)
                logger.debug("尝试从东方财富获取30分钟数据: 000300")
                index_30m = fetch_index_minute_em(
                    symbol="000300",
                    period="30",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            elif source == 'sina':
                source_max_retries = sina_config.get('max_retries', max_retries)
                source_retry_delay = sina_config.get('retry_delay', retry_delay)
                logger.debug("尝试从新浪财经获取30分钟数据: 000300")
                index_30m = fetch_index_minute_sina(
                    symbol="000300",
                    period="30",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            else:
                logger.warning(f"未知的数据源: {source}，跳过")
                continue
            
            if index_30m is not None and not index_30m.empty:
                logger.info(f"30分钟数据获取成功（数据源: {source}）")
                _record_data_source_success(source_key)
                break
            else:
                logger.debug(f"数据源 {source} 返回空数据，尝试下一个数据源")
                _record_data_source_failure(source_key, config)
        except Exception as e:
            logger.warning(f"从数据源 {source} 获取30分钟数据失败: {e}，尝试下一个数据源")
            _record_data_source_failure(source_key, config)
            continue
    
    # ========== 按优先级尝试获取15分钟数据 ==========
    index_15m = None
    for source in available_sources:
        source_key = f"index_minute_{source}"
        if cb_cfg.get("enabled", True) and not _is_data_source_available(source_key, config):
            logger.warning(f"数据源 {source_key} 当前处于熔断期，跳过15分钟数据获取")
            continue
        try:
            if source == 'eastmoney':
                source_max_retries = eastmoney_config.get('max_retries', max_retries)
                source_retry_delay = eastmoney_config.get('retry_delay', retry_delay)
                logger.debug("尝试从东方财富获取15分钟数据: 000300")
                index_15m = fetch_index_minute_em(
                    symbol="000300",
                    period="15",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            elif source == 'sina':
                source_max_retries = sina_config.get('max_retries', max_retries)
                source_retry_delay = sina_config.get('retry_delay', retry_delay)
                logger.debug("尝试从新浪财经获取15分钟数据: 000300")
                index_15m = fetch_index_minute_sina(
                    symbol="000300",
                    period="15",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            else:
                logger.warning(f"未知的数据源: {source}，跳过")
                continue
            
            if index_15m is not None and not index_15m.empty:
                logger.info(f"15分钟数据获取成功（数据源: {source}）")
                _record_data_source_success(source_key)
                break
            else:
                logger.debug(f"数据源 {source} 返回空数据，尝试下一个数据源")
                _record_data_source_failure(source_key, config)
        except Exception as e:
            logger.warning(f"从数据源 {source} 获取15分钟数据失败: {e}，尝试下一个数据源")
            _record_data_source_failure(source_key, config)
            continue
    
    # ========== 返回结果 ==========
    if index_30m is not None and not index_30m.empty and index_15m is not None and not index_15m.empty:
        logger.info("指数分钟数据获取成功（30分钟和15分钟数据均获取成功）")
        return index_30m, index_15m
    else:
        # 记录失败信息
        failed_periods = []
        if index_30m is None or index_30m.empty:
            failed_periods.append("30分钟")
        if index_15m is None or index_15m.empty:
            failed_periods.append("15分钟")
        logger.warning(f"指数分钟数据获取部分失败: {', '.join(failed_periods)}数据未获取成功（已尝试所有配置的数据源，缓存数据已在各函数中处理）")
        return index_30m, index_15m


def fetch_etf_minute_data_with_fallback(
    underlying: str = "510300",
    lookback_days: int = 5,
    max_retries: int = 2,
    retry_delay: float = 1.0
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    获取ETF分钟数据（支持多标的物）- 独立获取，不依赖指数数据
    
    支持多数据源优先级配置（通过config.yaml中的data_sources.etf_minute.priority配置）
    默认优先级：["eastmoney", "sina"]
    - eastmoney: 东方财富ETF接口（fund_etf_hist_min_em）
    - sina: 新浪财经接口（CN_MarketData.getKLineData）
    
    Args:
        underlying: ETF代码（如 "510300"）
        lookback_days: 回看天数（默认5天）
        max_retries: 最大重试次数（默认2次，每个数据源独立重试）
        retry_delay: 重试延迟（秒，默认1.0秒）
    
    Returns:
        tuple: (30分钟数据, 15分钟数据)
    """
    logger.info(f"开始获取ETF分钟数据（{underlying}）：多数据源优先级")
    
    # 检查是否在交易时间内（用于force_realtime判断）
    from src.system_status import get_current_market_status
    from src.config_loader import load_system_config
    config = load_system_config()
    market_status = get_current_market_status(config)
    is_trading_time = market_status.get('is_trading_time', False)
    force_realtime = is_trading_time  # 交易时间内强制实时获取
    
    # 熔断配置
    cb_cfg = _get_circuit_breaker_config(config)
    
    # ========== 读取数据源优先级配置 ==========
    data_sources_config = config.get('data_sources', {})
    etf_minute_config = data_sources_config.get('etf_minute', {})
    
    # 默认优先级：["eastmoney", "sina"]
    priority = etf_minute_config.get('priority', ['eastmoney', 'sina'])
    
    # 获取各数据源的配置
    eastmoney_config = etf_minute_config.get('eastmoney', {})
    sina_config = etf_minute_config.get('sina', {})
    
    # 检查各数据源是否启用
    eastmoney_enabled = eastmoney_config.get('enabled', True)
    sina_enabled = sina_config.get('enabled', True)
    
    # 过滤掉未启用的数据源
    available_sources = [src for src in priority if (src == 'eastmoney' and eastmoney_enabled) or (src == 'sina' and sina_enabled)]
    
    if not available_sources:
        logger.warning("所有ETF分钟数据源均未启用，使用默认配置")
        available_sources = ['eastmoney']  # 默认使用东方财富
    
    logger.debug(f"ETF分钟数据源优先级: {available_sources}")
    
    # ========== 按优先级尝试获取30分钟数据 ==========
    etf_30m = None
    for source in available_sources:
        source_key = f"etf_minute_{source}"
        if cb_cfg.get("enabled", True) and not _is_data_source_available(source_key, config):
            logger.warning(f"数据源 {source_key} 当前处于熔断期，跳过30分钟数据获取")
            continue
        try:
            if source == 'eastmoney':
                source_max_retries = eastmoney_config.get('max_retries', max_retries)
                source_retry_delay = eastmoney_config.get('retry_delay', retry_delay)
                logger.debug(f"尝试从东方财富获取30分钟数据: {underlying}")
                etf_30m = fetch_etf_minute_em(
                    symbol=underlying,
                    period="30",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            elif source == 'sina':
                source_max_retries = sina_config.get('max_retries', max_retries)
                source_retry_delay = sina_config.get('retry_delay', retry_delay)
                logger.debug(f"尝试从新浪财经获取30分钟数据: {underlying}")
                etf_30m = fetch_etf_minute_sina(
                    symbol=underlying,
                    period="30",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            else:
                logger.warning(f"未知的数据源: {source}，跳过")
                continue
            
            if etf_30m is not None and not etf_30m.empty:
                logger.info(f"30分钟数据获取成功（数据源: {source}）")
                _record_data_source_success(source_key)
                break
            else:
                logger.debug(f"数据源 {source} 返回空数据，尝试下一个数据源")
                _record_data_source_failure(source_key, config)
        except Exception as e:
            logger.warning(f"从数据源 {source} 获取30分钟数据失败: {e}，尝试下一个数据源")
            _record_data_source_failure(source_key, config)
            continue
    
    # ========== 按优先级尝试获取15分钟数据 ==========
    etf_15m = None
    for source in available_sources:
        source_key = f"etf_minute_{source}"
        if cb_cfg.get("enabled", True) and not _is_data_source_available(source_key, config):
            logger.warning(f"数据源 {source_key} 当前处于熔断期，跳过15分钟数据获取")
            continue
        try:
            if source == 'eastmoney':
                source_max_retries = eastmoney_config.get('max_retries', max_retries)
                source_retry_delay = eastmoney_config.get('retry_delay', retry_delay)
                logger.debug(f"尝试从东方财富获取15分钟数据: {underlying}")
                etf_15m = fetch_etf_minute_em(
                    symbol=underlying,
                    period="15",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            elif source == 'sina':
                source_max_retries = sina_config.get('max_retries', max_retries)
                source_retry_delay = sina_config.get('retry_delay', retry_delay)
                logger.debug(f"尝试从新浪财经获取15分钟数据: {underlying}")
                etf_15m = fetch_etf_minute_sina(
                    symbol=underlying,
                    period="15",
                    lookback_days=lookback_days,
                    max_retries=source_max_retries,
                    retry_delay=source_retry_delay,
                    fast_fail=True,
                    force_realtime=force_realtime
                )
            else:
                logger.warning(f"未知的数据源: {source}，跳过")
                continue
            
            if etf_15m is not None and not etf_15m.empty:
                logger.info(f"15分钟数据获取成功（数据源: {source}）")
                _record_data_source_success(source_key)
                break
            else:
                logger.debug(f"数据源 {source} 返回空数据，尝试下一个数据源")
                _record_data_source_failure(source_key, config)
        except Exception as e:
            logger.warning(f"从数据源 {source} 获取15分钟数据失败: {e}，尝试下一个数据源")
            _record_data_source_failure(source_key, config)
            continue
    
    # ========== 返回结果 ==========
    if etf_30m is not None and not etf_30m.empty and etf_15m is not None and not etf_15m.empty:
        logger.info("ETF分钟数据获取成功（30分钟和15分钟数据均获取成功）")
        return etf_30m, etf_15m
    else:
        # 记录失败信息
        failed_periods = []
        if etf_30m is None or etf_30m.empty:
            failed_periods.append("30分钟")
        if etf_15m is None or etf_15m.empty:
            failed_periods.append("15分钟")
        logger.warning(f"ETF分钟数据获取部分失败: {', '.join(failed_periods)}数据未获取成功（已尝试所有配置的数据源，缓存数据已在各函数中处理）")
        return etf_30m, etf_15m


# 保留旧函数以保持向后兼容（标记为废弃）
def fetch_minute_data_with_fallback(
    lookback_days: int = 5,
    primary_max_retries: int = 2,
    fallback_max_retries: int = 2,
    retry_delay: float = 1.0
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], bool, float]:
    """
    [已废弃] 请使用 fetch_index_minute_data_with_fallback 和 fetch_etf_minute_data_with_fallback
    此函数保留仅用于向后兼容
    """
    logger.warning("fetch_minute_data_with_fallback 已废弃，请使用独立的 fetch_index_minute_data_with_fallback 和 fetch_etf_minute_data_with_fallback")
    # 默认返回ETF数据（保持旧行为）
    etf_30m, etf_15m = fetch_etf_minute_data_with_fallback(
        lookback_days=lookback_days,
        max_retries=primary_max_retries,
        retry_delay=retry_delay,
    )
    if etf_30m is not None and etf_15m is not None:
        # 计算价格转换比率（用于兼容）
        from src.data_collector import get_etf_current_price, fetch_index_daily_em
        from datetime import timedelta
        etf_price = get_etf_current_price()
        price_ratio = 1000.0
        if etf_price and etf_price > 0:
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            end_date = now.strftime("%Y%m%d")
            start_date = (now - timedelta(days=1)).strftime("%Y%m%d")
            index_daily = fetch_index_daily_em(symbol="000300", start_date=start_date, end_date=end_date)
            if index_daily is not None and not index_daily.empty:
                index_current_price = index_daily['收盘'].iloc[-1]
                price_ratio = index_current_price / etf_price
        return etf_30m, etf_15m, True, price_ratio
    else:
        index_30m, index_15m = fetch_index_minute_data_with_fallback(lookback_days, fallback_max_retries, retry_delay)
        return index_30m, index_15m, False, 1.0


def fetch_etf_minute_em(
    symbol: str = "510300",
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    max_retries: int = 5,
    retry_delay: float = 3.0,
    fast_fail: bool = False,
    force_realtime: bool = False  # 强制实时获取：交易时间内不使用当天缓存数据
) -> Optional[pd.DataFrame]:
    """
    获取ETF分钟数据（东方财富接口）- 替代指数分钟数据，更稳定
    使用 fund_etf_hist_min_em 接口，比指数接口更稳定
    
    Args:
        symbol: ETF代码（如 "510300" 表示沪深300ETF）
        period: 周期（"1", "5", "15", "30", "60"）
        start_date: 开始日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则使用当前日期
        lookback_days: 回看天数（默认5天）
        max_retries: 最大重试次数（默认5次）
        retry_delay: 重试延迟（秒，默认3.0秒）
        fast_fail: 快速失败模式（默认False）
    
    Returns:
        pd.DataFrame: ETF分钟数据，如果失败返回None
    """
    # 确保symbol是字符串类型（防止配置文件中是整数）
    symbol = str(symbol) if symbol else "510300"
    
    log_function_call(logger, "fetch_etf_minute_em", 
                     symbol=symbol, period=period, lookback_days=lookback_days)

    # ========== 缓存逻辑：先检查缓存（使用独立的ETF分钟数据缓存） ==========
    config_for_cache = load_system_config(use_cache=True)
    cached_partial_minute_df = None  # 用于存储部分缓存的数据
    missing_dates = None  # 用于存储缺失的日期列表
    
    if _is_cache_enabled(config_for_cache):
        try:
            from src.data_cache import (
                get_cached_etf_minute, save_etf_minute_cache,
                merge_cached_and_fetched_data
            )
            
            # 先计算日期范围（用于缓存检查）
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            
            cache_start_date = start_date
            cache_end_date = end_date
            
            if cache_end_date is None:
                cache_end_date = now.strftime("%Y%m%d")
            elif len(cache_end_date) > 8:  # 如果是 "YYYY-MM-DD HH:MM:SS" 格式
                cache_end_date = cache_end_date[:10].replace("-", "")
            
            if cache_start_date is None:
                start = now - timedelta(days=lookback_days * 2)
                cache_start_date = start.strftime("%Y%m%d")
            elif len(cache_start_date) > 8:  # 如果是 "YYYY-MM-DD HH:MM:SS" 格式
                cache_start_date = cache_start_date[:10].replace("-", "")
            
            # 检查缓存（使用独立的ETF分钟数据缓存函数）
            cached_df, missing_dates = get_cached_etf_minute(
                symbol, period, cache_start_date, cache_end_date, config=config_for_cache
            )
            
            # 如果启用快速失败模式且有部分缓存数据，减少重试次数
            if fast_fail and cached_df is not None and not cached_df.empty:
                original_max_retries = max_retries
                max_retries = min(max_retries, 2)  # 快速失败模式最多重试2次
                retry_delay = min(retry_delay, 1.0)  # 减少延迟时间
                logger.info(f"快速失败模式启用: {symbol} {period}分钟, 有缓存数据, 重试次数: {original_max_retries} -> {max_retries}, 延迟: {retry_delay:.1f}秒")
            
            # 检查 end_date 是否是今天
            is_today = (cache_end_date == now.strftime("%Y%m%d"))
            
            # 检查是否在交易时间内（用于force_realtime判断）
            from src.system_status import get_current_market_status
            market_status = get_current_market_status(config_for_cache)
            is_trading_time = market_status.get('is_trading_time', False)
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中
                if is_today:
                    # 如果 end_date 是今天，需要实时获取当天的数据（因为当天数据会实时更新）
                    # 如果force_realtime=True且在交易时间内，强制实时获取，不使用当天缓存
                    if force_realtime and is_trading_time:
                        logger.info(f"强制实时获取模式: {symbol}, {period}分钟, 交易时间内不使用当天缓存数据")
                        # 保存历史缓存数据（排除今天），用于后续合并
                        # 过滤掉今天的数据
                        date_col = None
                        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                            if col in cached_df.columns:
                                date_col = col
                                break
                        if date_col:
                            if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                                cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
                            today_str = now.strftime("%Y%m%d")
                            historical_data = cached_df[cached_df[date_col].dt.strftime('%Y%m%d') != today_str]
                            if not historical_data.empty:
                                cached_partial_minute_df = historical_data
                                logger.info(f"保留历史缓存数据: {symbol}, {period}分钟, {len(historical_data)} 条")
                            else:
                                cached_partial_minute_df = None
                        else:
                            cached_partial_minute_df = None
                        # 调整日期范围，只获取当天的数据
                        min_date = cache_end_date
                        max_date = cache_end_date
                        start_date = f"{min_date[:4]}-{min_date[4:6]}-{min_date[6:8]} 09:30:00"
                        end_date = f"{max_date[:4]}-{max_date[4:6]}-{max_date[6:8]} 17:40:00"
                    else:
                        # 正常情况：保存历史缓存数据，用于后续合并
                        logger.info(f"ETF分钟数据缓存命中（历史部分）: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条，但需要实时获取当天数据")
                        cached_partial_minute_df = cached_df
                        # 调整日期范围，只获取当天的数据
                        min_date = cache_end_date
                        max_date = cache_end_date
                        start_date = f"{min_date[:4]}-{min_date[4:6]}-{min_date[6:8]} 09:30:00"
                        end_date = f"{max_date[:4]}-{max_date[4:6]}-{max_date[6:8]} 17:40:00"
                else:
                    # 如果 end_date 是历史日期，可以使用全部缓存
                    logger.info(f"ETF分钟数据全部从缓存加载: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条")
                    return cached_df
            
            # 计算总日期数
            total_days = (datetime.strptime(cache_end_date, "%Y%m%d") - datetime.strptime(cache_start_date, "%Y%m%d")).days + 1
            
            if cached_df is not None and not cached_df.empty and missing_dates and len(missing_dates) < total_days:
                # 部分缓存命中，需要获取缺失部分并合并
                logger.info(f"ETF分钟数据部分缓存命中: {symbol}, {period}分钟, 缺失 {len(missing_dates)} 个日期")
                # 保存已缓存的数据，用于后续合并
                cached_partial_minute_df = cached_df
                # 调整日期范围，只获取缺失部分（转换为API需要的格式）
                if missing_dates:
                    min_date = min(missing_dates)
                    max_date = max(missing_dates)
                    start_date = f"{min_date[:4]}-{min_date[4:6]}-{min_date[6:8]} 09:30:00"
                    end_date = f"{max_date[:4]}-{max_date[4:6]}-{max_date[6:8]} 17:40:00"
        except Exception as e:
            logger.debug(f"缓存检查失败，继续从接口获取: {e}")
    # ========== 缓存逻辑结束 ==========
    
    # ========== Tushare 优先逻辑 ==========
    config = load_system_config()
    tushare_config = config.get('tushare', {})
    prefer_tushare_minute = tushare_config.get('prefer_minute', False)
    
    if prefer_tushare_minute:
        try:
            from src.tushare_fallback import fetch_etf_minute_tushare
            
            # 获取 prefer_token，如果为空则使用默认 token
            prefer_token = tushare_config.get('prefer_token', '').strip()
            
            # 计算日期范围（用于 Tushare 调用）
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            
            # 处理日期格式，转换为 Tushare 需要的格式：YYYY-MM-DD HH:MM:SS
            if end_date is None:
                tushare_end_date = now.strftime("%Y-%m-%d 19:00:00")
            else:
                # 转换为 YYYY-MM-DD HH:MM:SS 格式
                if len(end_date) == 8 and end_date.isdigit():
                    tushare_end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]} 19:00:00"
                elif len(end_date) > 8:
                    # 如果是 "YYYY-MM-DD HH:MM:SS" 格式，直接使用；否则转换
                    if '-' in end_date and ':' in end_date:
                        tushare_end_date = end_date
                    else:
                        # 转换为标准格式
                        end_date_clean = end_date.replace("-", "").replace(":", "").replace(" ", "")
                        if len(end_date_clean) >= 8:
                            date_part = f"{end_date_clean[:4]}-{end_date_clean[4:6]}-{end_date_clean[6:8]}"
                            if len(end_date_clean) >= 14:
                                time_part = f"{end_date_clean[8:10]}:{end_date_clean[10:12]}:{end_date_clean[12:14]}"
                            else:
                                time_part = "19:00:00"
                            tushare_end_date = f"{date_part} {time_part}"
                        else:
                            tushare_end_date = f"{end_date_clean} 19:00:00"
                else:
                    tushare_end_date = end_date
            
            if start_date is None:
                start = now - timedelta(days=lookback_days * 2)
                tushare_start_date = start.strftime("%Y-%m-%d 09:30:00")
            else:
                # 转换为 YYYY-MM-DD HH:MM:SS 格式
                if len(start_date) == 8 and start_date.isdigit():
                    tushare_start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 09:30:00"
                elif len(start_date) > 8:
                    # 如果是 "YYYY-MM-DD HH:MM:SS" 格式，直接使用；否则转换
                    if '-' in start_date and ':' in start_date:
                        tushare_start_date = start_date
                    else:
                        # 转换为标准格式
                        start_date_clean = start_date.replace("-", "").replace(":", "").replace(" ", "")
                        if len(start_date_clean) >= 8:
                            date_part = f"{start_date_clean[:4]}-{start_date_clean[4:6]}-{start_date_clean[6:8]}"
                            if len(start_date_clean) >= 14:
                                time_part = f"{start_date_clean[8:10]}:{start_date_clean[10:12]}:{start_date_clean[12:14]}"
                            else:
                                time_part = "09:30:00"
                            tushare_start_date = f"{date_part} {time_part}"
                        else:
                            tushare_start_date = f"{start_date_clean} 09:30:00"
                else:
                    tushare_start_date = start_date
            
            logger.info(f"【方法1】使用 Tushare 获取 ETF 分钟数据（主数据源）: {symbol}, {period}分钟")
            minute_df = fetch_etf_minute_tushare(
                symbol=symbol,
                period=period,
                start_date=tushare_start_date,
                end_date=tushare_end_date,
                token=prefer_token if prefer_token else None,
                config=config_for_cache
            )
            
            if minute_df is not None and not minute_df.empty:
                logger.info(f"Tushare ETF分钟数据获取成功: {symbol}, {period}分钟, {len(minute_df)} 条数据")
                
                # ========== 合并部分缓存数据 ==========
                if _is_cache_enabled(config_for_cache) and cached_partial_minute_df is not None:
                    try:
                        from src.data_cache import merge_cached_and_fetched_data
                        # 找到日期/时间列
                        date_col = None
                        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                            if col in minute_df.columns:
                                date_col = col
                                break
                        cached_count = len(cached_partial_minute_df)
                        # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                        minute_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_minute_df, minute_df, date_col))
                        logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(minute_df) - cached_count} 条 = 总计 {len(minute_df)} 条")
                    except Exception as e:
                        logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
                
                # ========== 保存到缓存 ==========
                # 注意：如果使用 Tushare 数据源，分批获取时已经立即保存了缓存
                # 这里的保存作为兜底（双重保险），确保数据不会丢失
                if _is_cache_enabled(config_for_cache):
                    try:
                        from src.data_cache import save_etf_minute_cache
                        save_etf_minute_cache(symbol, period, minute_df, config=config_for_cache)
                    except Exception as e:
                        logger.debug(f"保存缓存失败（不影响主流程）: {e}")
                # ========== 缓存保存结束 ==========
                
                return minute_df
            else:
                logger.warning(f"Tushare主数据源返回空数据，将尝试备用方案: {symbol}, {period}分钟")
        except Exception as e:
            logger.warning(f"Tushare ETF分钟数据获取失败，将尝试备用方案: {symbol}, {period}分钟, 错误: {e}")
    # ========== Tushare 优先逻辑结束 ==========
    
    # 计算日期范围
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    # 处理日期格式
    if end_date is None:
        end_date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 如果格式是YYYYMMDD，转换为YYYY-MM-DD HH:MM:SS
        if len(end_date) == 8 and end_date.isdigit():
            end_date_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]} 17:40:00"
        else:
            end_date_str = end_date
    
    if start_date is None:
        # 计算回看日期
        start = now - timedelta(days=lookback_days * 2)
        start_date_str = start.strftime("%Y-%m-%d 09:30:00")
    else:
        # 如果格式是YYYYMMDD，转换为YYYY-MM-DD HH:MM:SS
        if len(start_date) == 8 and start_date.isdigit():
            start_date_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 09:30:00"
        else:
            start_date_str = start_date
    
    # 重试机制（指数退避策略）
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = min(retry_delay * (2 ** (attempt - 1)), 30.0)
                logger.debug(f"重试获取ETF分钟数据: symbol={symbol}, period={period}, 第{attempt+1}次尝试, 等待{delay:.1f}秒")
                time.sleep(delay)
            
            logger.debug(f"获取ETF分钟数据: symbol={symbol}, period={period}, "
                        f"start_date={start_date_str}, end_date={end_date_str}")
            
            start_time = time.time()
            minute_df = ak.fund_etf_hist_min_em(
                symbol=symbol,
                period=period,
                adjust="",  # 不复权
                start_date=start_date_str,
                end_date=end_date_str
            )
            duration = time.time() - start_time
            
            if minute_df is not None and not minute_df.empty:
                # 确保时间列为字符串格式
                if '时间' in minute_df.columns:
                    minute_df['时间'] = pd.to_datetime(minute_df['时间']).dt.strftime('%Y-%m-%d %H:%M:%S')
                
                log_function_result(logger, "fetch_etf_minute_em", 
                                  f"获取到{len(minute_df)}条数据", duration)
                
                # ========== 合并部分缓存数据 ==========
                if _is_cache_enabled(config_for_cache) and cached_partial_minute_df is not None:
                    try:
                        from src.data_cache import merge_cached_and_fetched_data
                        # 找到日期/时间列
                        date_col = None
                        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                            if col in minute_df.columns:
                                date_col = col
                                break
                        cached_count = len(cached_partial_minute_df)
                        # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                        minute_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_minute_df, minute_df, date_col))
                        logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(minute_df) - cached_count} 条 = 总计 {len(minute_df)} 条")
                    except Exception as e:
                        logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
                
                # ========== 保存到缓存 ==========
                if _is_cache_enabled(config_for_cache):
                    try:
                        from src.data_cache import save_etf_minute_cache
                        # 使用独立的ETF分钟数据缓存函数
                        save_etf_minute_cache(symbol, period, minute_df, config=config_for_cache)
                    except Exception as e:
                        logger.debug(f"保存缓存失败（不影响主流程）: {e}")
                # ========== 缓存保存结束 ==========
                
                return minute_df
            else:
                logger.warning(f"未获取到ETF分钟数据: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "API返回空数据"
                
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, 
                requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"网络连接错误: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                extra_wait = min(2.0 * attempt, 10.0)
                if extra_wait > 0:
                    logger.debug(f"连接错误，额外等待{extra_wait:.1f}秒后重试...")
                    time.sleep(extra_wait)
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_etf_minute_em',
                        'symbol': symbol,
                        'period': period,
                        'start_date': start_date_str,
                        'end_date': end_date_str,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取ETF分钟数据失败（SSL/连接错误，已重试{max_retries}次）"
                )
        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"获取ETF分钟数据失败: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_etf_minute_em',
                        'symbol': symbol,
                        'period': period,
                        'start_date': start_date_str,
                        'end_date': end_date_str,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取ETF分钟数据失败（已重试{max_retries}次）"
                )
    
    # 先检查是否有缓存数据，区分降级处理和完全失败
    if cached_partial_minute_df is not None and not cached_partial_minute_df.empty:
        # 有缓存数据：降级处理，记录WARNING
        cache_count = len(cached_partial_minute_df)
        
        # 计算数据完整性信息
        try:
            # 尝试从缓存数据中提取日期范围
            date_col = None
            for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                if col in cached_partial_minute_df.columns:
                    date_col = col
                    break
            
            if date_col:
                # 提取日期信息
                if pd.api.types.is_datetime64_any_dtype(cached_partial_minute_df[date_col]):
                    dates = cached_partial_minute_df[date_col].dt.date.unique()
                else:
                    dates = pd.to_datetime(cached_partial_minute_df[date_col], errors='coerce').dt.date.unique()
                    dates = dates[~pd.isna(dates)]
                
                date_range_str = f"{min(dates)} ~ {max(dates)}" if len(dates) > 0 else "未知"
                missing_count = len(missing_dates) if missing_dates else 0
            else:
                date_range_str = "未知"
                missing_count = len(missing_dates) if missing_dates else 0
        except Exception:
            date_range_str = "未知"
            missing_count = len(missing_dates) if missing_dates else 0
        
        logger.warning(
            f"ETF分钟数据API获取失败（已降级使用缓存）: symbol={symbol}, period={period}分钟, "
            f"缓存数据: {cache_count} 条, 日期范围: {date_range_str}, "
            f"缺失日期: {missing_count} 个, 原因: {last_error[:100] if last_error else '未知'}"
        )
        return cached_partial_minute_df
    else:
        # 没有缓存数据：完全失败，记录ERROR
        logger.error(
            f"获取ETF分钟数据完全失败: symbol={symbol}, period={period}分钟, "
            f"原因: {last_error}, 无缓存数据可用"
        )
        return None


def fetch_etf_minute_sina(
    symbol: str = "510300",
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    fast_fail: bool = False,
    force_realtime: bool = False
) -> Optional[pd.DataFrame]:
    """
    获取ETF分钟数据（新浪财经接口）- 独立实现，不依赖 akshare
    
    使用新浪财经的 CN_MarketData.getKLineData 接口获取ETF分钟数据
    
    Args:
        symbol: ETF代码（如 "510300" 表示沪深300ETF）
        period: 周期（"5", "15", "30", "60"），注意：新浪不支持1分钟数据
        start_date: 开始日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则使用当前日期
        lookback_days: 回看天数（默认5天）
        max_retries: 最大重试次数（默认3次）
        retry_delay: 重试延迟（秒，默认1.0秒）
        fast_fail: 快速失败模式（默认False）
        force_realtime: 强制实时获取（交易时间内不使用当天缓存数据）
    
    Returns:
        pd.DataFrame: ETF分钟数据，如果失败返回None
        数据格式：时间、开盘、收盘、最高、最低、成交量、成交额
    """
    # 确保symbol是字符串类型（防止配置文件中是整数）
    symbol = str(symbol) if symbol else "510300"
    
    log_function_call(logger, "fetch_etf_minute_sina", 
                     symbol=symbol, period=period, lookback_days=lookback_days)
    
    # ========== 缓存逻辑：先检查缓存（使用独立的ETF分钟数据缓存） ==========
    config_for_cache = load_system_config(use_cache=True)
    cached_partial_minute_df = None  # 用于存储部分缓存的数据
    missing_dates = None  # 用于存储缺失的日期列表
    
    if _is_cache_enabled(config_for_cache):
        try:
            from src.data_cache import (
                get_cached_etf_minute, save_etf_minute_cache,
                merge_cached_and_fetched_data
            )
            
            # 先计算日期范围（用于缓存检查）
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            
            cache_start_date = start_date
            cache_end_date = end_date
            
            if cache_end_date is None:
                cache_end_date = now.strftime("%Y%m%d")
            elif len(cache_end_date) > 8:  # 如果是 "YYYY-MM-DD HH:MM:SS" 格式
                cache_end_date = cache_end_date[:10].replace("-", "")
            
            if cache_start_date is None:
                start = now - timedelta(days=lookback_days * 2)
                cache_start_date = start.strftime("%Y%m%d")
            elif len(cache_start_date) > 8:  # 如果是 "YYYY-MM-DD HH:MM:SS" 格式
                cache_start_date = cache_start_date[:10].replace("-", "")
            
            # 检查缓存（使用独立的ETF分钟数据缓存函数）
            cached_df, missing_dates = get_cached_etf_minute(
                symbol, period, cache_start_date, cache_end_date, config=config_for_cache
            )
            
            # 如果启用快速失败模式且有部分缓存数据，减少重试次数
            if fast_fail and cached_df is not None and not cached_df.empty:
                original_max_retries = max_retries
                max_retries = min(max_retries, 2)  # 快速失败模式最多重试2次
                retry_delay = min(retry_delay, 1.0)  # 减少延迟时间
                logger.info(f"快速失败模式启用: {symbol} {period}分钟, 有缓存数据, 重试次数: {original_max_retries} -> {max_retries}, 延迟: {retry_delay:.1f}秒")
            
            # 检查 end_date 是否是今天
            is_today = (cache_end_date == now.strftime("%Y%m%d"))
            
            # 检查是否在交易时间内（用于force_realtime判断）
            from src.system_status import get_current_market_status
            market_status = get_current_market_status(config_for_cache)
            is_trading_time = market_status.get('is_trading_time', False)
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中
                if is_today:
                    # 如果 end_date 是今天，需要实时获取当天的数据（因为当天数据会实时更新）
                    # 如果force_realtime=True且在交易时间内，强制实时获取，不使用当天缓存
                    if force_realtime and is_trading_time:
                        logger.info(f"强制实时获取模式: {symbol}, {period}分钟, 交易时间内不使用当天缓存数据")
                        # 保存历史缓存数据（排除今天），用于后续合并
                        date_col = None
                        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                            if col in cached_df.columns:
                                date_col = col
                                break
                        if date_col:
                            if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                                cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
                            today_str = now.strftime("%Y%m%d")
                            historical_data = cached_df[cached_df[date_col].dt.strftime('%Y%m%d') != today_str]
                            if not historical_data.empty:
                                cached_partial_minute_df = historical_data
                                logger.info(f"保留历史缓存数据: {symbol}, {period}分钟, {len(historical_data)} 条")
                            else:
                                cached_partial_minute_df = None
                        else:
                            cached_partial_minute_df = None
                    else:
                        # 正常情况：保存历史缓存数据，用于后续合并
                        logger.info(f"ETF分钟数据缓存命中（历史部分）: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条，但需要实时获取当天数据")
                        cached_partial_minute_df = cached_df
                else:
                    # 如果 end_date 是历史日期，可以使用全部缓存
                    logger.info(f"ETF分钟数据全部从缓存加载: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条")
                    return cached_df
            
            # 计算总日期数
            total_days = (datetime.strptime(cache_end_date, "%Y%m%d") - datetime.strptime(cache_start_date, "%Y%m%d")).days + 1
            
            if cached_df is not None and not cached_df.empty and missing_dates and len(missing_dates) < total_days:
                # 部分缓存命中，需要获取缺失部分并合并
                logger.info(f"ETF分钟数据部分缓存命中: {symbol}, {period}分钟, 缺失 {len(missing_dates)} 个日期")
                # 保存已缓存的数据，用于后续合并
                cached_partial_minute_df = cached_df
        except Exception as e:
            logger.debug(f"缓存检查失败，继续从接口获取: {e}")
    # ========== 缓存逻辑结束 ==========
    
    # ========== ETF代码转换：转换为新浪财经格式 ==========
    # 新浪财经ETF代码格式：sh510300（上海）或 sz159919（深圳）
    if symbol.startswith('51'):  # 上海ETF（如510300）
        sina_symbol = f"sh{symbol}"
    elif symbol.startswith('15'):  # 深圳ETF（如159919）
        sina_symbol = f"sz{symbol}"
    else:
        # 默认假设是上海ETF
        sina_symbol = f"sh{symbol}"
        logger.debug(f"ETF代码格式未知，默认使用上海格式: {symbol} -> {sina_symbol}")
    
    # ========== 周期映射：转换为新浪财经的scale参数 ==========
    # 新浪财经支持的周期：5, 15, 30, 60分钟（注意：不支持1分钟）
    period_to_scale = {
        "1": 1,   # 注意：新浪可能不支持1分钟，但先保留
        "5": 5,
        "15": 15,
        "30": 30,
        "60": 60
    }
    scale = period_to_scale.get(period)
    if scale is None:
        logger.warning(f"不支持的周期: {period}，使用默认30分钟")
        scale = 30
    
    # ========== 日期处理 ==========
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 统一转换为 "YYYY-MM-DD HH:MM:SS" 格式
        if len(end_date) == 8 and end_date.isdigit():
            end_date_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]} 15:00:00"
        else:
            end_date_str = end_date
    
    if start_date is None:
        # 计算回看天数
        start = now - timedelta(days=lookback_days)
        start_date_str = start.strftime("%Y-%m-%d 09:30:00")
    else:
        # 统一转换为 "YYYY-MM-DD HH:MM:SS" 格式
        if len(start_date) == 8 and start_date.isdigit():
            start_date_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 09:30:00"
        else:
            start_date_str = start_date
    
    # ========== 计算datalen参数 ==========
    # 新浪财经接口限制：datalen最大1023
    # 根据日期范围和周期估算需要的数据点数
    try:
        start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days + 1
        
        # 估算：每个交易日约4小时 = 240分钟，按周期计算数据点数
        # 保守估计：每个交易日约240/scale个数据点
        estimated_points = int(days_diff * (240 / scale) * 1.2)  # 1.2倍缓冲
        datalen = min(estimated_points, 1023)  # 新浪限制最大1023
    except Exception as e:
        logger.debug(f"计算datalen失败，使用默认值1023: {e}")
        datalen = 1023
    
    # ========== 构建请求URL和参数 ==========
    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": sina_symbol,
        "scale": scale,
        "ma": "no",  # 不计算均线，减少数据量
        "datalen": datalen
    }
    
    # ========== 请求头设置 ==========
    config = load_system_config()
    data_sources_config = config.get('data_sources', {})
    sina_config = data_sources_config.get('etf_minute', {}).get('sina', {})
    
    headers = {
        "Referer": sina_config.get('referer', 'http://finance.sina.com.cn'),
        "User-Agent": sina_config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    }
    
    # ========== 重试机制 ==========
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = min(retry_delay * (2 ** (attempt - 1)), 30.0)
                logger.debug(f"重试获取ETF分钟数据（新浪）: symbol={symbol}, period={period}, 第{attempt+1}次尝试, 等待{delay:.1f}秒")
                time.sleep(delay)
            
            logger.debug(f"获取ETF分钟数据（新浪）: symbol={symbol}, period={period}, "
                        f"sina_symbol={sina_symbol}, scale={scale}, datalen={datalen}")
            
            start_time = time.time()
            response = requests.get(url, params=params, headers=headers, timeout=10)
            duration = time.time() - start_time
            
            # 检查HTTP状态码
            if response.status_code != 200:
                raise requests.exceptions.HTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
            
            # 解析JSON响应
            try:
                data = response.json()
            except ValueError:
                raise ValueError(f"JSON解析失败: {response.text[:200]}")
            
            # 检查返回数据
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"新浪接口返回空数据: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "API返回空数据"
                continue
            
            # ========== 转换为DataFrame并统一格式 ==========
            # 新浪返回格式：{"day": "2023-01-01 15:00:00", "open": 1.234, "high": 1.235, "low": 1.233, "close": 1.234, "volume": 123456}
            # 需要转换为：时间、开盘、收盘、最高、最低、成交量、成交额
            
            df = pd.DataFrame(data)
            
            # 重命名列名（统一格式）
            column_mapping = {
                "day": "时间",
                "open": "开盘",
                "close": "收盘",
                "high": "最高",
                "low": "最低",
                "volume": "成交量"
            }
            
            # 只保留需要的列
            available_columns = [col for col in column_mapping.keys() if col in df.columns]
            df = df[available_columns].copy()
            
            # 重命名
            df = df.rename(columns=column_mapping)
            
            # 添加成交额列（新浪接口不提供，设为0或根据成交量估算）
            if "成交额" not in df.columns:
                df["成交额"] = 0.0  # 新浪接口不提供成交额，设为0
            
            # 确保时间列为datetime类型，然后转换为字符串格式（与东方财富接口一致）
            if "时间" in df.columns:
                df["时间"] = pd.to_datetime(df["时间"], errors='coerce')
                # 过滤掉无效的时间数据
                df = df[df["时间"].notna()].copy()
                # 转换为字符串格式（与fetch_etf_minute_em一致）
                df["时间"] = df["时间"].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # 确保数值列为float类型
            numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 按时间排序（从早到晚）
            if "时间" in df.columns:
                df = df.sort_values("时间").reset_index(drop=True)
            
            # 日期范围过滤（如果指定了start_date和end_date）
            if start_date_str and end_date_str:
                try:
                    start_dt = datetime.strptime(start_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    end_dt = datetime.strptime(end_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    
                    # 将时间列转换为datetime进行比较
                    df_time = pd.to_datetime(df["时间"], errors='coerce')
                    mask = (df_time >= start_dt) & (df_time <= end_dt)
                    df = df[mask].copy()
                except Exception as e:
                    logger.debug(f"日期范围过滤失败，返回全部数据: {e}")
            
            if df.empty:
                logger.warning(f"过滤后数据为空: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "过滤后数据为空"
                continue
            
            log_function_result(logger, "fetch_etf_minute_sina", 
                              f"获取到{len(df)}条数据", duration)
            
            # ========== 合并部分缓存数据 ==========
            if _is_cache_enabled(config_for_cache) and cached_partial_minute_df is not None:
                try:
                    from src.data_cache import merge_cached_and_fetched_data
                    # 找到日期/时间列
                    date_col = None
                    for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                        if col in df.columns:
                            date_col = col
                            break
                    cached_count = len(cached_partial_minute_df)
                    # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                    df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_minute_df, df, date_col))
                    logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(df) - cached_count} 条 = 总计 {len(df)} 条")
                except Exception as e:
                    logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
            
            # ========== 保存到缓存 ==========
            if _is_cache_enabled(config_for_cache):
                try:
                    from src.data_cache import save_etf_minute_cache
                    save_etf_minute_cache(symbol, period, df, config=config_for_cache)
                except Exception as e:
                    logger.debug(f"保存缓存失败（不影响主流程）: {e}")
            
            return df
            
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, 
                requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"网络连接错误（新浪）: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                extra_wait = min(2.0 * attempt, 10.0)
                if extra_wait > 0:
                    logger.debug(f"连接错误，额外等待{extra_wait:.1f}秒后重试...")
                    time.sleep(extra_wait)
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_etf_minute_sina',
                        'symbol': symbol,
                        'period': period,
                        'sina_symbol': sina_symbol,
                        'scale': scale,
                        'start_date': start_date_str,
                        'end_date': end_date_str,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取ETF分钟数据失败（新浪，SSL/连接错误，已重试{max_retries}次）"
                )
        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"获取ETF分钟数据失败（新浪）: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_etf_minute_sina',
                        'symbol': symbol,
                        'period': period,
                        'sina_symbol': sina_symbol,
                        'scale': scale,
                        'start_date': start_date_str,
                        'end_date': end_date_str,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取ETF分钟数据失败（新浪，已重试{max_retries}次）"
                )
    
    # ========== 所有重试失败后的处理 ==========
    # ===== 新浪兜底：分时 stock_zh_a_minute =====
    # 当 CN_MarketData.getKLineData 返回空（或过滤后为空）且重试失败时，
    # 使用 stock_zh_a_minute 拉取同周期的分钟数据并映射到“ETF分钟数据”统一列格式。
    def _try_stock_zh_a_minute_fallback() -> Optional[pd.DataFrame]:
        try:
            minute_df = ak.stock_zh_a_minute(
                symbol=sina_symbol,
                period=str(period),
                adjust="qfq",
            )
            if minute_df is None or getattr(minute_df, "empty", True):
                return None

            df = minute_df.copy()
            # stock_zh_a_minute 输出列：
            # day, open, high, low, close, volume
            column_mapping = {
                "day": "时间",
                "open": "开盘",
                "high": "最高",
                "low": "最低",
                "close": "收盘",
                "volume": "成交量",
            }
            # 只映射存在的列，避免接口返回字段名变化
            for src_col, dst_col in list(column_mapping.items()):
                if src_col not in df.columns:
                    df[dst_col] = 0.0

            df = df.rename(columns=column_mapping)

            # 确保必需列存在
            required_cols = ["时间", "开盘", "最高", "最低", "收盘", "成交量"]
            for c in required_cols:
                if c not in df.columns:
                    df[c] = 0.0

            # 添加成交额（新浪 stock_zh_a_minute 不提供）
            if "成交额" not in df.columns:
                df["成交额"] = 0.0

            # 类型转换 + 时间字符串化
            df["时间"] = pd.to_datetime(df["时间"], errors="coerce")
            df = df[df["时间"].notna()].copy()
            df["时间"] = df["时间"].dt.strftime("%Y-%m-%d %H:%M:%S")

            for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            # 排序
            df = df.sort_values("时间").reset_index(drop=True)

            # 日期范围过滤（尽量对齐 CN_MarketData 的 start/end）
            if start_date_str and end_date_str:
                try:
                    sdt = datetime.strptime(start_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    edt = datetime.strptime(end_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    df_time = pd.to_datetime(df["时间"], errors="coerce")
                    df = df[(df_time >= sdt) & (df_time <= edt)].copy()
                except Exception:
                    pass

            if df.empty:
                return None
            return df
        except Exception:
            return None

    stock_fallback_df = _try_stock_zh_a_minute_fallback()

    if stock_fallback_df is not None and not stock_fallback_df.empty:
        # 如果缓存部分存在，做合并与落缓存
        try:
            if _is_cache_enabled(config_for_cache) and cached_partial_minute_df is not None:
                try:
                    from src.data_cache import merge_cached_and_fetched_data
                    date_col = None
                    for col in ["时间", "日期", "date", "日期时间", "datetime"]:
                        if col in stock_fallback_df.columns:
                            date_col = col
                            break
                    if date_col is not None:
                        stock_fallback_df = cast(
                            pd.DataFrame,
                            merge_cached_and_fetched_data(cached_partial_minute_df, stock_fallback_df, date_col),
                        )
                except Exception:
                    pass

            if _is_cache_enabled(config_for_cache):
                from src.data_cache import save_etf_minute_cache

                save_etf_minute_cache(symbol, period, stock_fallback_df, config=config_for_cache)
        except Exception:
            pass

        return stock_fallback_df

    # 先检查是否有缓存数据，区分降级处理和完全失败
    if cached_partial_minute_df is not None and not cached_partial_minute_df.empty:
        # 有缓存数据：降级处理，记录WARNING
        cache_count = len(cached_partial_minute_df)
        
        # 计算数据完整性信息
        try:
            date_col = None
            for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                if col in cached_partial_minute_df.columns:
                    date_col = col
                    break
            
            if date_col:
                if pd.api.types.is_datetime64_any_dtype(cached_partial_minute_df[date_col]):
                    dates = cached_partial_minute_df[date_col].dt.date.unique()
                else:
                    dates = pd.to_datetime(cached_partial_minute_df[date_col], errors='coerce').dt.date.unique()
                    dates = dates[~pd.isna(dates)]
                
                date_range_str = f"{min(dates)} ~ {max(dates)}" if len(dates) > 0 else "未知"
                missing_count = len(missing_dates) if missing_dates else 0
            else:
                date_range_str = "未知"
                missing_count = len(missing_dates) if missing_dates else 0
        except Exception:
            date_range_str = "未知"
            missing_count = len(missing_dates) if missing_dates else 0
        
        logger.warning(
            f"ETF分钟数据API获取失败（新浪，已降级使用缓存）: symbol={symbol}, period={period}分钟, "
            f"缓存数据: {cache_count} 条, 日期范围: {date_range_str}, "
            f"缺失日期: {missing_count} 个, 原因: {last_error[:100] if last_error else '未知'}"
        )
        return cached_partial_minute_df
    else:
        # 没有缓存数据：完全失败，记录ERROR
        logger.error(
            f"获取ETF分钟数据完全失败（新浪）: symbol={symbol}, period={period}分钟, "
            f"原因: {last_error}, 无缓存数据可用"
        )
        return None


def fetch_index_minute_sina(
    symbol: str = "000300",
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    fast_fail: bool = False,
    force_realtime: bool = False
) -> Optional[pd.DataFrame]:
    """
    获取指数分钟数据（新浪财经接口）- 独立实现，不依赖 akshare
    
    使用新浪财经的 CN_MarketData.getKLineData 接口获取指数分钟数据
    
    Args:
        symbol: 指数代码（如 "000300" 表示沪深300）
        period: 周期（"5", "15", "30", "60"），注意：新浪不支持1分钟数据
        start_date: 开始日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则使用当前日期
        lookback_days: 回看天数（默认5天）
        max_retries: 最大重试次数（默认3次）
        retry_delay: 重试延迟（秒，默认1.0秒）
        fast_fail: 快速失败模式（默认False）
        force_realtime: 强制实时获取（交易时间内不使用当天缓存数据）
    
    Returns:
        pd.DataFrame: 指数分钟数据，如果失败返回None
        数据格式：时间、开盘、收盘、最高、最低、成交量、成交额
    """
    log_function_call(logger, "fetch_index_minute_sina", 
                     symbol=symbol, period=period, lookback_days=lookback_days)
    
    # ========== 缓存逻辑：先检查缓存（使用独立的指数分钟数据缓存） ==========
    config_for_cache = load_system_config(use_cache=True)
    cached_partial_minute_df = None  # 用于存储部分缓存的数据
    missing_dates = None  # 用于存储缺失的日期列表
    
    if _is_cache_enabled(config_for_cache):
        try:
            from src.data_cache import (
                get_cached_index_minute, save_index_minute_cache,
                merge_cached_and_fetched_data
            )
            
            # 先计算日期范围（用于缓存检查）
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            
            cache_start_date = start_date
            cache_end_date = end_date
            
            if cache_end_date is None:
                cache_end_date = now.strftime("%Y%m%d")
            elif len(cache_end_date) > 8:  # 如果是 "YYYY-MM-DD HH:MM:SS" 格式
                cache_end_date = cache_end_date[:10].replace("-", "")
            
            if cache_start_date is None:
                start = now - timedelta(days=lookback_days * 2)
                cache_start_date = start.strftime("%Y%m%d")
            elif len(cache_start_date) > 8:  # 如果是 "YYYY-MM-DD HH:MM:SS" 格式
                cache_start_date = cache_start_date[:10].replace("-", "")
            
            # 检查缓存（使用独立的指数分钟数据缓存函数）
            cached_df, missing_dates = get_cached_index_minute(
                symbol, period, cache_start_date, cache_end_date, config=config_for_cache
            )
            
            # 如果启用快速失败模式且有部分缓存数据，减少重试次数
            if fast_fail and cached_df is not None and not cached_df.empty:
                original_max_retries = max_retries
                max_retries = min(max_retries, 2)  # 快速失败模式最多重试2次
                retry_delay = min(retry_delay, 1.0)  # 减少延迟时间
                logger.info(f"快速失败模式启用: {symbol} {period}分钟, 有缓存数据, 重试次数: {original_max_retries} -> {max_retries}, 延迟: {retry_delay:.1f}秒")
            
            # 检查 end_date 是否是今天
            is_today = (cache_end_date == now.strftime("%Y%m%d"))
            
            # 检查是否在交易时间内（用于force_realtime判断）
            from src.system_status import get_current_market_status
            market_status = get_current_market_status(config_for_cache)
            is_trading_time = market_status.get('is_trading_time', False)
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中
                if is_today:
                    # 如果 end_date 是今天，需要实时获取当天的数据（因为当天数据会实时更新）
                    # 如果force_realtime=True且在交易时间内，强制实时获取，不使用当天缓存
                    if force_realtime and is_trading_time:
                        logger.info(f"强制实时获取模式: {symbol}, {period}分钟, 交易时间内不使用当天缓存数据")
                        # 保存历史缓存数据（排除今天），用于后续合并
                        date_col = None
                        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                            if col in cached_df.columns:
                                date_col = col
                                break
                        if date_col:
                            if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                                cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
                            today_str = now.strftime("%Y%m%d")
                            historical_data = cached_df[cached_df[date_col].dt.strftime('%Y%m%d') != today_str]
                            if not historical_data.empty:
                                cached_partial_minute_df = historical_data
                                logger.info(f"保留历史缓存数据: {symbol}, {period}分钟, {len(historical_data)} 条")
                            else:
                                cached_partial_minute_df = None
                        else:
                            cached_partial_minute_df = None
                    else:
                        # 正常情况：保存历史缓存数据，用于后续合并
                        logger.info(f"指数分钟数据缓存命中（历史部分）: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条，但需要实时获取当天数据")
                        cached_partial_minute_df = cached_df
                else:
                    # 如果 end_date 是历史日期，可以使用全部缓存
                    logger.info(f"指数分钟数据全部从缓存加载: {symbol}, {period}分钟, {cache_start_date}~{cache_end_date}, {len(cached_df)} 条")
                    return cached_df
            
            # 计算总日期数
            total_days = (datetime.strptime(cache_end_date, "%Y%m%d") - datetime.strptime(cache_start_date, "%Y%m%d")).days + 1
            
            if cached_df is not None and not cached_df.empty and missing_dates and len(missing_dates) < total_days:
                # 部分缓存命中，需要获取缺失部分并合并
                logger.info(f"指数分钟数据部分缓存命中: {symbol}, {period}分钟, 缺失 {len(missing_dates)} 个日期")
                # 保存已缓存的数据，用于后续合并
                cached_partial_minute_df = cached_df
        except Exception as e:
            logger.debug(f"缓存检查失败，继续从接口获取: {e}")
    # ========== 缓存逻辑结束 ==========
    
    # ========== 自动识别 symbol 类型并转换代码 ==========
    # ETF代码通常以5或1开头（如510300, 159915），指数代码通常以000或399开头（如000300, 399001）
    if symbol.startswith("5") or symbol.startswith("1"):
        # 这是 ETF 代码，自动调用 fetch_etf_minute_sina
        logger.info(f"检测到 ETF 代码 {symbol}，自动调用 fetch_etf_minute_sina")
        return fetch_etf_minute_sina(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            lookback_days=lookback_days,
            max_retries=max_retries,
            retry_delay=retry_delay,
            fast_fail=fast_fail,
            force_realtime=force_realtime
        )
    
    # 指数代码转换：转换为新浪财经格式
    # 指数代码映射表
    index_code_mapping = {
        "000300": "sz399300",  # 沪深300（特殊处理）
        "000001": "sh000001",  # 上证指数
        "000016": "sh000016",  # 上证50
        "000905": "sh000905",  # 中证500
        "399001": "sz399001",  # 深证成指
        "399006": "sz399006",  # 创业板指
    }
    
    sina_symbol = index_code_mapping.get(symbol)
    if sina_symbol is None:
        # 自动转换：000xxx -> sh000xxx, 399xxx -> sz399xxx
        if symbol.startswith("000"):
            sina_symbol = f"sh{symbol}"
        elif symbol.startswith("399"):
            sina_symbol = f"sz{symbol}"
        else:
            logger.warning(f"无法识别的指数代码格式: {symbol}")
            return None
    
    # ========== 周期映射：转换为新浪财经的scale参数 ==========
    # 新浪财经支持的周期：5, 15, 30, 60分钟（注意：不支持1分钟）
    period_to_scale = {
        "1": 1,   # 注意：新浪可能不支持1分钟，但先保留
        "5": 5,
        "15": 15,
        "30": 30,
        "60": 60
    }
    scale = period_to_scale.get(period)
    if scale is None:
        logger.warning(f"不支持的周期: {period}，使用默认30分钟")
        scale = 30
    
    # ========== 日期处理 ==========
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 统一转换为 "YYYY-MM-DD HH:MM:SS" 格式
        if len(end_date) == 8 and end_date.isdigit():
            end_date_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]} 15:00:00"
        else:
            end_date_str = end_date
    
    if start_date is None:
        # 计算回看天数
        start = now - timedelta(days=lookback_days)
        start_date_str = start.strftime("%Y-%m-%d 09:30:00")
    else:
        # 统一转换为 "YYYY-MM-DD HH:MM:SS" 格式
        if len(start_date) == 8 and start_date.isdigit():
            start_date_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 09:30:00"
        else:
            start_date_str = start_date
    
    # ========== 计算datalen参数 ==========
    # 新浪财经接口限制：datalen最大1023
    # 根据日期范围和周期估算需要的数据点数
    try:
        start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days + 1
        
        # 估算：每个交易日约4小时 = 240分钟，按周期计算数据点数
        # 保守估计：每个交易日约240/scale个数据点
        estimated_points = int(days_diff * (240 / scale) * 1.2)  # 1.2倍缓冲
        datalen = min(estimated_points, 1023)  # 新浪限制最大1023
    except Exception as e:
        logger.debug(f"计算datalen失败，使用默认值1023: {e}")
        datalen = 1023
    
    # ========== 构建请求URL和参数 ==========
    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": sina_symbol,
        "scale": scale,
        "ma": "no",  # 不计算均线，减少数据量
        "datalen": datalen
    }
    
    # ========== 请求头设置 ==========
    config = load_system_config()
    data_sources_config = config.get('data_sources', {})
    # 优先使用 index_minute.sina 配置，如果没有则复用 etf_minute.sina 配置
    sina_config = data_sources_config.get('index_minute', {}).get('sina', {})
    if not sina_config:
        sina_config = data_sources_config.get('etf_minute', {}).get('sina', {})
    
    headers = {
        "Referer": sina_config.get('referer', 'http://finance.sina.com.cn'),
        "User-Agent": sina_config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    }
    
    # ========== 重试机制 ==========
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = min(retry_delay * (2 ** (attempt - 1)), 30.0)
                logger.debug(f"重试获取指数分钟数据（新浪）: symbol={symbol}, period={period}, 第{attempt+1}次尝试, 等待{delay:.1f}秒")
                time.sleep(delay)
            
            logger.debug(f"获取指数分钟数据（新浪）: symbol={symbol}, period={period}, "
                        f"sina_symbol={sina_symbol}, scale={scale}, datalen={datalen}")
            
            start_time = time.time()
            response = requests.get(url, params=params, headers=headers, timeout=10)
            duration = time.time() - start_time
            
            # 检查HTTP状态码
            if response.status_code != 200:
                raise requests.exceptions.HTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
            
            # 解析JSON响应
            try:
                data = response.json()
            except ValueError:
                raise ValueError(f"JSON解析失败: {response.text[:200]}")
            
            # 检查返回数据
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"新浪接口返回空数据: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "API返回空数据"
                continue
            
            # ========== 转换为DataFrame并统一格式 ==========
            # 新浪返回格式：{"day": "2023-01-01 15:00:00", "open": 1.234, "high": 1.235, "low": 1.233, "close": 1.234, "volume": 123456}
            # 需要转换为：时间、开盘、收盘、最高、最低、成交量、成交额
            
            df = pd.DataFrame(data)
            
            # 重命名列名（统一格式）
            column_mapping = {
                "day": "时间",
                "open": "开盘",
                "close": "收盘",
                "high": "最高",
                "low": "最低",
                "volume": "成交量"
            }
            
            # 只保留需要的列
            available_columns = [col for col in column_mapping.keys() if col in df.columns]
            df = df[available_columns].copy()
            
            # 重命名
            df = df.rename(columns=column_mapping)
            
            # 添加成交额列（新浪接口不提供，设为0或根据成交量估算）
            if "成交额" not in df.columns:
                df["成交额"] = 0.0  # 新浪接口不提供成交额，设为0
            
            # 确保时间列为datetime类型，然后转换为字符串格式（与东方财富接口一致）
            if "时间" in df.columns:
                df["时间"] = pd.to_datetime(df["时间"], errors='coerce')
                # 过滤掉无效的时间数据
                df = df[df["时间"].notna()].copy()
                # 转换为字符串格式（与fetch_index_minute_em一致）
                df["时间"] = df["时间"].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # 确保数值列为float类型
            numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 按时间排序（从早到晚）
            if "时间" in df.columns:
                df = df.sort_values("时间").reset_index(drop=True)
            
            # 日期范围过滤（如果指定了start_date和end_date）
            if start_date_str and end_date_str:
                try:
                    start_dt = datetime.strptime(start_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    end_dt = datetime.strptime(end_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    
                    # 将时间列转换为datetime进行比较
                    df_time = pd.to_datetime(df["时间"], errors='coerce')
                    mask = (df_time >= start_dt) & (df_time <= end_dt)
                    df = df[mask].copy()
                except Exception as e:
                    logger.debug(f"日期范围过滤失败，返回全部数据: {e}")
            
            if df.empty:
                logger.warning(f"过滤后数据为空: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "过滤后数据为空"
                continue
            
            log_function_result(logger, "fetch_index_minute_sina", 
                              f"获取到{len(df)}条数据", duration)
            
            # ========== 合并部分缓存数据 ==========
            if _is_cache_enabled(config_for_cache) and cached_partial_minute_df is not None:
                try:
                    from src.data_cache import merge_cached_and_fetched_data
                    # 找到日期/时间列
                    date_col = None
                    for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                        if col in df.columns:
                            date_col = col
                            break
                    cached_count = len(cached_partial_minute_df)
                    # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                    df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_minute_df, df, date_col))
                    logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(df) - cached_count} 条 = 总计 {len(df)} 条")
                except Exception as e:
                    logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
            
            # ========== 保存到缓存 ==========
            if _is_cache_enabled(config_for_cache):
                try:
                    from src.data_cache import save_index_minute_cache
                    save_index_minute_cache(symbol, period, df, config=config_for_cache)
                except Exception as e:
                    logger.debug(f"保存缓存失败（不影响主流程）: {e}")
            
            return df
            
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, 
                requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"网络连接错误（新浪）: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                extra_wait = min(2.0 * attempt, 10.0)
                if extra_wait > 0:
                    logger.debug(f"连接错误，额外等待{extra_wait:.1f}秒后重试...")
                    time.sleep(extra_wait)
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_index_minute_sina',
                        'symbol': symbol,
                        'period': period,
                        'sina_symbol': sina_symbol,
                        'scale': scale,
                        'start_date': start_date_str,
                        'end_date': end_date_str,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取指数分钟数据失败（新浪，SSL/连接错误，已重试{max_retries}次）"
                )
        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"获取指数分钟数据失败（新浪）: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                         f"错误类型: {error_type}, 错误: {last_error[:100]}")
            if attempt < max_retries - 1:
                continue
            else:
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_index_minute_sina',
                        'symbol': symbol,
                        'period': period,
                        'sina_symbol': sina_symbol,
                        'scale': scale,
                        'start_date': start_date_str,
                        'end_date': end_date_str,
                        'attempts': max_retries,
                        'error_type': error_type
                    },
                    f"获取指数分钟数据失败（新浪，已重试{max_retries}次）"
                )
    
    # ========== 所有重试失败后的处理 ==========
    # 先检查是否有缓存数据，区分降级处理和完全失败
    if cached_partial_minute_df is not None and not cached_partial_minute_df.empty:
        # 有缓存数据：降级处理，记录WARNING
        cache_count = len(cached_partial_minute_df)
        
        # 计算数据完整性信息
        try:
            date_col = None
            for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                if col in cached_partial_minute_df.columns:
                    date_col = col
                    break
            
            if date_col:
                if pd.api.types.is_datetime64_any_dtype(cached_partial_minute_df[date_col]):
                    dates = cached_partial_minute_df[date_col].dt.date.unique()
                else:
                    dates = pd.to_datetime(cached_partial_minute_df[date_col], errors='coerce').dt.date.unique()
                    dates = dates[~pd.isna(dates)]
                
                date_range_str = f"{min(dates)} ~ {max(dates)}" if len(dates) > 0 else "未知"
                missing_count = len(missing_dates) if missing_dates else 0
            else:
                date_range_str = "未知"
                missing_count = len(missing_dates) if missing_dates else 0
        except Exception:
            date_range_str = "未知"
            missing_count = len(missing_dates) if missing_dates else 0
        
        logger.warning(
            f"指数分钟数据API获取失败（新浪，已降级使用缓存）: symbol={symbol}, period={period}分钟, "
            f"缓存数据: {cache_count} 条, 日期范围: {date_range_str}, "
            f"缺失日期: {missing_count} 个, 原因: {last_error[:100] if last_error else '未知'}"
        )
        return cached_partial_minute_df
    else:
        # 没有缓存数据：完全失败，记录ERROR
        logger.error(
            f"获取指数分钟数据完全失败（新浪）: symbol={symbol}, period={period}分钟, "
            f"原因: {last_error}, 无缓存数据可用"
        )
        return None


def fetch_option_spot_sina(symbol: str) -> Optional[pd.DataFrame]:
    """
    获取期权实时数据（新浪接口）
    
    注意：此接口仅支持上交所（SSE）期权，不支持深交所（SZSE）期权。
    深交所期权需要使用其他数据源（如Tushare）。
    
    Args:
        symbol: 期权合约代码（如 "10002273"，上交所期权）
    
    Returns:
        pd.DataFrame: 期权实时数据，如果失败返回None
    """
    try:
        log_function_call(logger, "fetch_option_spot_sina", symbol=symbol)
        
        start_time = time.time()
        spot_df = ak.option_sse_spot_price_sina(symbol=symbol)
        duration = time.time() - start_time
        
        if spot_df is None or spot_df.empty:
            logger.warning(f"未获取到期权实时数据: symbol={symbol}")
            return None
        
        log_function_result(logger, "fetch_option_spot_sina", 
                          f"获取到{len(spot_df)}条数据", duration)
        return spot_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'fetch_option_spot_sina', 'symbol': symbol},
            "获取期权实时数据失败"
        )
        return None


def fetch_option_greeks_sina(
    symbol: str,
    use_cache: bool = True,
    include_previous_day: bool = False,
        date: Optional[str] = None,
        config: Optional[Dict] = None
    ) -> Optional[pd.DataFrame]:
    """
    获取期权希腊字母信息（包含隐含波动率IV）（新浪接口）
    支持缓存和前一交易日数据
    
    注意：此接口仅支持上交所（SSE）期权，不支持深交所（SZSE）期权。
    深交所期权需要使用其他数据源（如Tushare）。
    
    重要：Greeks数据在交易时间内会实时变化，因此当天数据不使用缓存，每次都实时调用API。
    历史数据（非当天）使用对应日期时间的缓存，不会调用API（因为历史数据不会变化）。
    实时调用后，数据会保存为历史数据（供以后使用，如历史分析、GARCH模型训练等）。
    
    Args:
        symbol: 期权合约代码（上交所期权）
        use_cache: 是否使用缓存（默认True）
        include_previous_day: 是否包含前一交易日数据（默认False，仅对当天数据有效）
        date: 日期时间字符串（格式：YYYYMMDD hh:mm:ss 或 YYYYMMDD），如果为None则查询当天数据
              如果指定历史日期时间，则从缓存中查找最接近该时间点的数据
        config: 系统配置
    
    Returns:
        pd.DataFrame: 希腊字母信息（Delta、Gamma、Theta、Vega、IV），如果失败返回None
    """
    try:
        log_function_call(logger, "fetch_option_greeks_sina", symbol=symbol,
                         use_cache=use_cache, include_previous_day=include_previous_day, date=date)
        
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        today = datetime.now().strftime("%Y%m%d")
        
        # 解析日期时间参数
        # 默认走“当天”逻辑，避免 target_date 被 mypy 推断成 Optional
        target_date: str = today
        target_datetime: Optional[datetime] = None
        if date is not None:
            # 支持两种格式：YYYYMMDD hh:mm:ss 或 YYYYMMDD
            if len(date) == 8 and date.isdigit():
                # YYYYMMDD 格式
                target_date = date
            elif len(date) >= 8:
                # YYYYMMDD hh:mm:ss 格式
                try:
                    # 尝试解析完整日期时间
                    if ' ' in date:
                        date_part, time_part = date.split(' ', 1)
                        target_date = date_part
                        target_datetime = datetime.strptime(date, '%Y%m%d %H:%M:%S')
                    else:
                        target_date = date[:8]
                        target_datetime = datetime.strptime(date, '%Y%m%d%H%M%S')
                except ValueError:
                    # 如果解析失败，只使用日期部分
                    target_date = date[:8] if len(date) >= 8 else date
        # else: 使用上面的默认 target_date=today
        
        # ========== 历史数据查询：使用对应日期时间的缓存（或最接近的缓存）==========
        if target_date != today:
            # 查询历史日期，使用缓存（历史数据不会变化，不需要调用API）
            if use_cache:
                try:
                    from src.data_cache import get_cached_option_greeks
                    if _is_cache_enabled(config):
                        # 尝试获取精确日期的缓存，如果不存在则查找最接近的缓存
                        cached_df = get_cached_option_greeks(symbol, target_date, use_closest=True, config=config)
                        if cached_df is not None and not cached_df.empty:
                            # 如果指定了具体时间，从缓存数据中筛选最接近的时间点
                            if target_datetime is not None:
                                # 查找缓存数据中的时间列
                                time_col = None
                                for col in ['采集时间', 'timestamp', '时间', '日期时间', 'datetime']:
                                    if col in cached_df.columns:
                                        time_col = col
                                        break
                                
                                if time_col:
                                    try:
                                        # 将时间列转换为datetime类型
                                        cached_df = cached_df.copy()
                                        if not pd.api.types.is_datetime64_any_dtype(cached_df[time_col]):
                                            cached_df[time_col] = pd.to_datetime(cached_df[time_col], errors='coerce')
                                        
                                        # 计算与目标时间的差值，找到最接近的时间点
                                        cached_df['_time_diff'] = (cached_df[time_col] - target_datetime).abs()
                                        closest_idx = cached_df['_time_diff'].idxmin()
                                        closest_time = cached_df.loc[closest_idx, time_col]
                                        closest_diff = cached_df.loc[closest_idx, '_time_diff']
                                        
                                        # 选择最接近时间点的数据
                                        result_df = cached_df.loc[[closest_idx]].copy()
                                        result_df = result_df.drop(columns=['_time_diff'])
                                        
                                        logger.info(f"使用最接近时间点的缓存数据: {symbol}, "
                                                  f"目标时间: {target_datetime.strftime('%Y-%m-%d %H:%M:%S')}, "
                                                  f"实际时间: {closest_time.strftime('%Y-%m-%d %H:%M:%S')}, "
                                                  f"时间差: {closest_diff.total_seconds():.0f}秒")
                                        
                                        log_function_result(logger, "fetch_option_greeks_sina", 
                                                          f"获取到{len(result_df)}条历史数据（来自缓存，最接近时间点）", 0)
                                        return result_df
                                    except Exception as e:
                                        logger.debug(f"筛选最接近时间点失败，返回全部缓存数据: {e}")
                                        # 如果筛选失败，返回全部缓存数据
                            
                            # 检查实际使用的日期（通过检查缓存文件是否存在）
                            from src.data_cache import get_cache_file_path
                            cache_path = get_cache_file_path('option_greeks', str(symbol), target_date, config=config)
                            if cache_path.exists():
                                logger.debug(f"使用历史日期的精确缓存数据: {symbol}, {target_date}")
                            else:
                                logger.info(f"使用历史日期的最接近缓存数据: {symbol}, 目标日期: {target_date}")
                            log_function_result(logger, "fetch_option_greeks_sina", 
                                              f"获取到{len(cached_df)}条历史数据（来自缓存）", 0)
                            return cached_df
                except Exception as e:
                    logger.debug(f"获取历史缓存失败: {e}")
            
            # 历史日期缓存不存在，返回None（历史数据无法通过API获取）
            logger.warning(f"历史日期 {target_date} 的缓存数据不存在（包括最接近的缓存）: {symbol}")
            return None
        
        # ========== 当天数据查询：实时调用API（不使用缓存）==========
        # Greeks数据在交易时间内会实时变化（Delta、Gamma、Theta、Vega、IV都会变化）
        # 使用缓存会导致使用过时的数据，影响信号生成和波动区间预测的准确性
        # 因此：当天数据每次都实时调用API，不使用缓存
        
        start_time = time.time()
        greeks_df = ak.option_sse_greeks_sina(symbol=symbol)
        duration = time.time() - start_time
        
        if greeks_df is None or greeks_df.empty:
            logger.warning(f"未获取到期权希腊字母数据: symbol={symbol}")
            # 如果API调用失败，尝试使用缓存作为fallback（仅限当天数据）
            if use_cache:
                try:
                    from src.data_cache import get_cached_option_greeks
                    if _is_cache_enabled(config):
                        cached_df = get_cached_option_greeks(symbol, today, config=config)
                        if cached_df is not None and not cached_df.empty:
                            logger.warning(f"API调用失败，使用缓存的当天数据作为fallback: {symbol}, {today}")
                            return cached_df
                except Exception as e:
                    logger.debug(f"缓存fallback失败: {e}")
            return None
        
        # ========== 保存到缓存（作为历史数据，供以后使用）==========
        # 即使当天数据不使用缓存读取，也要保存为历史数据
        # 这样以后查询历史数据时可以使用，也可以用于GARCH模型训练等
        if use_cache:
            try:
                from src.data_cache import save_option_greeks_cache
                if _is_cache_enabled(config):
                    save_result = save_option_greeks_cache(symbol, greeks_df, today, config=config)
                    if save_result:
                        logger.info(f"期权Greeks数据已保存为历史数据: {symbol}, {today}, {len(greeks_df)} 条")
                    else:
                        logger.warning(f"期权Greeks数据保存失败: {symbol}, {today}（返回False）")
            except Exception as e:
                logger.warning(f"保存缓存失败（不影响主流程）: {symbol}, {today}, 错误: {e}", exc_info=True)
        
        # ========== 如果需要包含前一交易日数据 ==========
        if include_previous_day:
            try:
                from src.data_cache import get_previous_trading_day_option_data
                _, prev_greeks = get_previous_trading_day_option_data(symbol, config=config)
                if prev_greeks is not None and not prev_greeks.empty:
                    # 合并前一交易日和当天数据
                    combined_df = pd.concat([prev_greeks, greeks_df], ignore_index=True)
                    logger.info(f"合并前一交易日和当天期权Greeks数据: {symbol}, "
                              f"前一交易日 {len(prev_greeks)} 条, 当天 {len(greeks_df)} 条")
                    log_function_result(logger, "fetch_option_greeks_sina", 
                                      f"获取到{len(combined_df)}条数据（含前一交易日）", duration)
                    return combined_df
            except Exception as e:
                logger.debug(f"获取前一交易日数据失败（不影响主流程）: {e}")
        
        log_function_result(logger, "fetch_option_greeks_sina", 
                          f"获取到{len(greeks_df)}条数据（实时调用，已保存为历史数据）", duration)
        return greeks_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'fetch_option_greeks_sina', 'symbol': symbol, 'date': date},
            "获取期权希腊字母数据失败"
        )
        return None


def fetch_option_expiry_date(contract_code: str) -> Optional[datetime]:
    """
    从期权合约数据中提取到期日期
    
    Args:
        contract_code: 期权合约代码
    
    Returns:
        datetime: 到期日期，如果无法获取返回None
    """
    try:
        # 方法1：从spot数据中查找到期日期字段
        spot_data = fetch_option_spot_sina(contract_code)
        if spot_data is not None and not spot_data.empty:
            for idx, row in spot_data.iterrows():
                field = str(row.get('字段', '')).strip()
                value = str(row.get('值', '')).strip()
                
                # 查找到期日期相关字段
                if any(keyword in field for keyword in ['到期', 'expiry', 'expire', '到期日', '到期日期', '行权日']):
                    try:
                        # 尝试解析日期
                        if len(value) == 8 and value.isdigit():
                            # YYYYMMDD格式
                            expiry_date = datetime.strptime(value, '%Y%m%d')
                            logger.debug(f"从spot数据获取到期日期: {contract_code} -> {expiry_date.strftime('%Y-%m-%d')}")
                            return expiry_date
                        elif len(value) == 10:
                            # YYYY-MM-DD格式
                            expiry_date = datetime.strptime(value, '%Y-%m-%d')
                            logger.debug(f"从spot数据获取到期日期: {contract_code} -> {expiry_date.strftime('%Y-%m-%d')}")
                            return expiry_date
                    except (ValueError, TypeError):
                        continue
        
        # 方法2：从合约代码推断（如果合约代码包含月份信息）
        # 上交所期权合约代码格式：通常是数字，可能包含月份信息
        # 这里简化处理：如果无法从数据获取，返回None，让调用方使用其他方法
        
        # 方法3：从Greeks数据中查找（某些接口可能包含到期日期）
        greeks_data = fetch_option_greeks_sina(contract_code)
        if greeks_data is not None and not greeks_data.empty:
            for idx, row in greeks_data.iterrows():
                field = str(row.get('字段', '')).strip()
                value = str(row.get('值', '')).strip()
                
                if any(keyword in field for keyword in ['到期', 'expiry', 'expire', '到期日', '到期日期', '行权日']):
                    try:
                        if len(value) == 8 and value.isdigit():
                            expiry_date = datetime.strptime(value, '%Y%m%d')
                            logger.debug(f"从Greeks数据获取到期日期: {contract_code} -> {expiry_date.strftime('%Y-%m-%d')}")
                            return expiry_date
                        elif len(value) == 10:
                            expiry_date = datetime.strptime(value, '%Y-%m-%d')
                            logger.debug(f"从Greeks数据获取到期日期: {contract_code} -> {expiry_date.strftime('%Y-%m-%d')}")
                            return expiry_date
                    except (ValueError, TypeError):
                        continue
        
        logger.debug(f"无法从合约数据中获取到期日期: {contract_code}")
        return None
        
    except Exception as e:
        logger.warning(f"获取期权到期日期失败: {contract_code}, 错误: {e}")
        return None


def fetch_option_minute_sina(
    symbol: str,
    use_cache: bool = True,
    include_previous_day: bool = False,
    period: Optional[str] = None,
    date: Optional[str] = None,
    config: Optional[Dict] = None
) -> Optional[pd.DataFrame]:
    """
    获取期权分钟数据（新浪接口，只能返回当天数据）
    支持缓存和前一交易日数据
    
    注意：此接口仅支持上交所（SSE）期权，不支持深交所（SZSE）期权。
    深交所期权需要使用其他数据源（如Tushare）。
    
    重要：期权分钟数据在交易时间内会实时更新，因此当天数据不使用缓存，每次都实时调用API。
    历史数据（非当天）使用对应日期的缓存，不会调用API（因为历史数据不会变化）。
    
    Args:
        symbol: 期权合约代码（上交所期权）
        use_cache: 是否使用缓存（默认True）
        include_previous_day: 是否包含前一交易日数据（默认False，仅对当天数据有效）
        period: 周期（可选，用于缓存，如 '15', '30'）
        date: 日期字符串（格式：YYYYMMDD 或 YYYYMMDD hh:mm:ss），如果为None则查询当天数据
        config: 系统配置
    
    Returns:
        pd.DataFrame: 期权分钟数据，如果失败返回None
    """
    try:
        log_function_call(logger, "fetch_option_minute_sina", symbol=symbol, 
                         use_cache=use_cache, include_previous_day=include_previous_day, date=date)
        
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        today = datetime.now().strftime("%Y%m%d")
        
        # 解析日期参数
        # 默认使用今天，避免 target_date 在 mypy 中被推断为 Optional[str]
        target_date: str = today
        if date is not None:
            # 支持两种格式：YYYYMMDD hh:mm:ss 或 YYYYMMDD
            if len(date) >= 8:
                target_date = date[:8]
        
        # ========== 历史数据查询：使用对应日期的缓存 ==========
        if target_date != today:
            # 查询历史日期，使用缓存（历史数据不会变化，不需要调用API）
            if use_cache:
                try:
                    from src.data_cache import get_cached_option_minute
                    if _is_cache_enabled(config):
                        cached_df = get_cached_option_minute(symbol, target_date, period=period, config=config)
                        if cached_df is not None and not cached_df.empty:
                            logger.debug(f"使用历史日期的缓存数据: {symbol}, {target_date}")
                            log_function_result(logger, "fetch_option_minute_sina", 
                                              f"获取到{len(cached_df)}条历史数据（来自缓存）", 0)
                            return cached_df
                except Exception as e:
                    logger.debug(f"获取历史缓存失败: {e}")
            
            # 历史日期缓存不存在，返回None（历史数据无法通过API获取）
            logger.warning(f"历史日期 {target_date} 的缓存数据不存在: {symbol}")
            return None
        
        # ========== 当天数据查询：实时调用API（不使用缓存）==========
        # 期权分钟数据在交易时间内会实时更新，使用缓存会导致使用过时的数据
        
        # ========== 从API获取数据 ==========
        start_time = time.time()
        minute_df = ak.option_sse_minute_sina(symbol=symbol)
        duration = time.time() - start_time
        
        if minute_df is None or minute_df.empty:
            logger.warning(f"未获取到期权分钟数据: symbol={symbol}")
            return None
        
        # ========== 保存到缓存 ==========
        if use_cache:
            try:
                from src.data_cache import save_option_minute_cache
                if _is_cache_enabled(config):
                    save_option_minute_cache(symbol, minute_df, period=period, config=config)
            except Exception as e:
                logger.debug(f"保存缓存失败（不影响主流程）: {e}")
        
        # ========== 如果需要包含前一交易日数据 ==========
        if include_previous_day:
            try:
                from src.data_cache import get_previous_trading_day_option_data
                prev_minute, _ = get_previous_trading_day_option_data(symbol, period=period, config=config)
                if prev_minute is not None and not prev_minute.empty:
                    # 合并前一交易日和当天数据
                    combined_df = pd.concat([prev_minute, minute_df], ignore_index=True)
                    # 按时间排序
                    time_col = None
                    for col in ['时间', '日期', 'date', '日期时间', 'datetime', '时间戳']:
                        if col in combined_df.columns:
                            time_col = col
                            break
                    if time_col:
                        combined_df = combined_df.sort_values(by=time_col)
                    logger.info(f"合并前一交易日和当天期权分钟K数据: {symbol}, "
                              f"前一交易日 {len(prev_minute)} 条, 当天 {len(minute_df)} 条")
                    log_function_result(logger, "fetch_option_minute_sina", 
                                      f"获取到{len(combined_df)}条数据（含前一交易日）", duration)
                    return combined_df
            except Exception as e:
                logger.debug(f"获取前一交易日数据失败（不影响主流程）: {e}")
        
        log_function_result(logger, "fetch_option_minute_sina", 
                          f"获取到{len(minute_df)}条数据", duration)
        return minute_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'fetch_option_minute_sina', 'symbol': symbol},
            "获取期权分钟数据失败"
        )
        return None


def fetch_etf_spot_sina(symbol: str = "510300") -> Optional[pd.DataFrame]:
    """
    获取ETF实时数据（新浪接口）
    
    Args:
        symbol: ETF代码（如 "510300"）
    
    Returns:
        pd.DataFrame: ETF实时数据，如果失败返回None
    """
    try:
        # 确保symbol是字符串类型（防止配置文件中是整数）
        symbol = str(symbol) if symbol else "510300"
        
        log_function_call(logger, "fetch_etf_spot_sina", symbol=symbol)
        
        start_time = time.time()
        # 新浪接口需要 "sh" 或 "sz" 前缀
        etf_symbol = f"sh{symbol}" if symbol.startswith('51') else f"sz{symbol}"
        spot_df = ak.option_sse_underlying_spot_price_sina(symbol=etf_symbol)
        duration = time.time() - start_time
        
        if spot_df is None or spot_df.empty:
            logger.warning(f"未获取到ETF实时数据: symbol={symbol}")
            return None
        
        log_function_result(logger, "fetch_etf_spot_sina", 
                          f"获取到{len(spot_df)}条数据", duration)
        return spot_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'fetch_etf_spot_sina', 'symbol': symbol},
            "获取ETF实时数据失败"
        )
        return None


def fetch_index_daily_em(
    symbol: str = "000300",
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> Optional[pd.DataFrame]:
    """
    获取指数日线数据（Tushare优先，akshare三个接口轮流作为备用）
    
    数据源优先级：
    1. Tushare（主数据源）- 优先使用
    2. stock_zh_index_daily（备用方案1）- 新浪财经接口
    3. index_zh_a_hist（备用方案2）- 东方财富接口
    4. stock_zh_index_daily_em（备用方案3）- 东方财富备用接口
    
    注意：akshare的三个备用数据源如果接口错误，轮流调用，不再重试。
    
    Args:
        symbol: 指数代码（如 "000300" 表示沪深300，"000001" 表示上证综指）
        period: 周期（"daily", "weekly", "monthly"）
        start_date: 开始日期（格式："YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYYMMDD"），如果为None则使用当前日期
        max_retries: 最大重试次数（默认3次，仅用于向后兼容，akshare接口不再重试）
        retry_delay: 重试延迟（秒，默认1.0秒，仅用于向后兼容）
    
    Returns:
        pd.DataFrame: 指数日线数据，如果失败返回None
    """
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date = now.strftime("%Y%m%d")
    
    if start_date is None:
        # 默认回看90天，确保有足够的交易日数据（60个交易日 ≈ 90个日历日）
        start = now - timedelta(days=90)
        start_date = start.strftime("%Y%m%d")
    
    log_function_call(logger, "fetch_index_daily_em", 
                     symbol=symbol, period=period, start_date=start_date, end_date=end_date)
    
    # ========== 自动识别 symbol 类型：如果是 ETF 代码，自动调用 fetch_etf_daily_em ==========
    # ETF代码通常以5或1开头（如510300, 159915），指数代码通常以000或399开头（如000300, 399001）
    if symbol.startswith("5") or symbol.startswith("1"):
        # 这是 ETF 代码，自动调用 fetch_etf_daily_em
        logger.info(f"检测到 ETF 代码 {symbol}，自动调用 fetch_etf_daily_em")
        return fetch_etf_daily_em(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            max_retries=max_retries,
            retry_delay=retry_delay
        )
    # ========== symbol 类型检测结束 ==========
    
    # ========== 缓存逻辑：先检查缓存 ==========
    config_for_cache = load_system_config(use_cache=True)
    cached_partial_df = None  # 用于存储部分缓存的数据
    
    if _is_cache_enabled(config_for_cache) and period == "daily":
        try:
            from src.data_cache import (
                get_cached_index_daily, save_index_daily_cache, 
                merge_cached_and_fetched_data
            )
            
            # 检查缓存
            cached_df, missing_dates = get_cached_index_daily(
                symbol, start_date, end_date, config=config_for_cache
            )
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中，直接返回
                logger.info(f"指数日线数据全部从缓存加载: {symbol}, {start_date}~{end_date}, {len(cached_df)} 条")
                return cached_df
            
            # 计算总日期数
            from datetime import datetime as dt
            start_dt = dt.strptime(start_date, "%Y%m%d")
            end_dt = dt.strptime(end_date, "%Y%m%d")
            total_days = (end_dt - start_dt).days + 1
            
            if cached_df is not None and not cached_df.empty and missing_dates and len(missing_dates) < total_days:
                # 部分缓存命中，需要获取缺失部分并合并
                logger.info(f"指数日线数据部分缓存命中: {symbol}, 缺失 {len(missing_dates)} 个日期")
                # 保存已缓存的数据，用于后续合并
                cached_partial_df = cached_df
                # 调整日期范围，只获取缺失部分
                if missing_dates:
                    start_date = min(missing_dates)
                    end_date = max(missing_dates)
        except Exception as e:
            logger.debug(f"缓存检查失败，继续从接口获取: {e}")
    # ========== 缓存逻辑结束 ==========
    
    # 方法1：优先使用 Tushare（主数据源）
    last_error = None
    try:
        from src.tushare_fallback import fetch_index_daily_tushare, fetch_etf_daily_tushare
        # 自动识别：如果是 ETF 代码，使用 ETF 接口；否则使用指数接口
        if symbol.startswith("5") or symbol.startswith("1"):
            logger.info(f"【方法1】使用 Tushare 获取ETF日线（主数据源）: {symbol}")
            tushare_df = fetch_etf_daily_tushare(symbol, start_date, end_date)
        else:
            logger.info(f"【方法1】使用 Tushare 获取指数日线（主数据源）: {symbol}")
            tushare_df = fetch_index_daily_tushare(symbol, start_date, end_date)
        if tushare_df is not None and not tushare_df.empty:
            log_function_result(logger, "fetch_index_daily_em", 
                              f"Tushare主数据源成功，获取到{len(tushare_df)}条数据", 0)
            
            # ========== 合并部分缓存数据 ==========
            if _is_cache_enabled(config_for_cache) and period == "daily" and cached_partial_df is not None:
                try:
                    from src.data_cache import merge_cached_and_fetched_data
                    date_col = None
                    for col in ['日期', 'date', '日期时间', 'datetime']:
                        if col in tushare_df.columns:
                            date_col = col
                            break
                    cached_count = len(cached_partial_df)
                    # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                    tushare_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_df, tushare_df, date_col))
                    logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(tushare_df) - cached_count} 条 = 总计 {len(tushare_df)} 条")
                except Exception as e:
                    logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
            
            # ========== 保存到缓存 ==========
            if _is_cache_enabled(config_for_cache) and period == "daily":
                try:
                    from src.data_cache import save_index_daily_cache
                    save_index_daily_cache(symbol, tushare_df, config=config_for_cache)
                except Exception as e:
                    logger.debug(f"保存缓存失败（不影响主流程）: {e}")
            # ========== 缓存保存结束 ==========
            
            return tushare_df
        else:
            logger.warning(f"Tushare主数据源返回空数据，将尝试备用方案: {symbol}")
            last_error = "Tushare返回空数据"
    except Exception as e:
        last_error = str(e)
        logger.warning(f"Tushare主数据源失败: {symbol}, 错误: {last_error}, 将尝试备用方案")
    
    # 方法2：尝试使用 stock_zh_index_daily（备用方案1，新浪财经）或 fund_etf_hist_sina（ETF）
    try:
        sina_symbol: Optional[str] = None
        # 如果是 ETF 代码，使用新浪 ETF 接口
        if symbol.startswith("5") or symbol.startswith("1"):
            # ETF 代码：使用 fund_etf_hist_sina
            sina_symbol = f"sh{symbol}" if symbol.startswith("51") else f"sz{symbol}"
            logger.warning(f"【方法2】使用备用方案 fund_etf_hist_sina（新浪财经ETF）: {symbol} -> {sina_symbol}")
            start_time = time.time()
            daily_df = ak.fund_etf_hist_sina(symbol=sina_symbol)
            duration = time.time() - start_time
        else:
            # 指数代码：使用 stock_zh_index_daily
            # 指数代码映射表（与 stock_zh_index_daily_em 相同）
            index_code_mapping = {
                "000300": "sz399300",  # 沪深300
                "000001": "sh000001",  # 上证指数
                "000016": "sh000016",  # 上证50
                "000905": "sh000905",  # 中证500
                "399001": "sz399001",  # 深证成指
                "399006": "sz399006",  # 创业板指
            }
            
            # 转换指数代码
            sina_symbol = index_code_mapping.get(symbol)
            if sina_symbol is None:
                # 自动转换：000xxx -> sh000xxx, 399xxx -> sz399xxx
                if symbol.startswith("000"):
                    sina_symbol = f"sh{symbol}"
                elif symbol.startswith("399"):
                    sina_symbol = f"sz{symbol}"
                else:
                    logger.debug(f"无法转换指数代码用于新浪接口: {symbol}，代码格式不支持（仅支持以000或399开头的指数代码），将尝试下一个备用方案")
                    sina_symbol = None
            
            if sina_symbol:
                logger.warning(f"【方法2】使用备用方案 stock_zh_index_daily（新浪财经）: {symbol} -> {sina_symbol}")
                start_time = time.time()
                daily_df = ak.stock_zh_index_daily(symbol=sina_symbol)
                duration = time.time() - start_time
            else:
                daily_df = None
        
        if daily_df is not None and not daily_df.empty:
            # 格式转换：新浪返回 date, open, high, low, close, volume
            column_mapping = {
                'date': '日期',
                'open': '开盘',
                'close': '收盘',
                'high': '最高',
                'low': '最低',
                'volume': '成交量'
            }
            
            # 重命名列
            for old_col, new_col in column_mapping.items():
                if old_col in daily_df.columns:
                    daily_df = daily_df.rename(columns={old_col: new_col})
            
            # 添加成交额列（如果没有，设为0或计算）
            if '成交额' not in daily_df.columns:
                if '成交量' in daily_df.columns and '收盘' in daily_df.columns:
                    # 成交量单位是"手"，需要乘以100转换为股数，再乘以价格得到成交额
                    daily_df['成交额'] = daily_df['成交量'] * daily_df['收盘'] * 100
                else:
                    daily_df['成交额'] = 0
            
            # 添加涨跌额和涨跌幅列（如果没有，计算）
            if '涨跌额' not in daily_df.columns:
                if '收盘' in daily_df.columns:
                    daily_df['涨跌额'] = daily_df['收盘'].diff()
                else:
                    daily_df['涨跌额'] = 0
            
            if '涨跌幅' not in daily_df.columns:
                if '收盘' in daily_df.columns:
                    daily_df['涨跌幅'] = daily_df['收盘'].pct_change() * 100
                else:
                    daily_df['涨跌幅'] = 0
            
            # 转换日期格式并筛选日期范围
            if '日期' in daily_df.columns:
                daily_df['日期'] = pd.to_datetime(daily_df['日期'])
                start_dt = datetime.strptime(start_date, "%Y%m%d")
                end_dt = datetime.strptime(end_date, "%Y%m%d")
                daily_df = daily_df[(daily_df['日期'] >= start_dt) & (daily_df['日期'] <= end_dt)]
                daily_df['日期'] = daily_df['日期'].dt.strftime('%Y%m%d')
                
                if not daily_df.empty:
                    log_function_result(logger, "fetch_index_daily_em", 
                                      f"获取到{len(daily_df)}条数据（新浪接口）", duration)
                    
                    # ========== 合并部分缓存数据 ==========
                    if _is_cache_enabled(config_for_cache) and period == "daily" and cached_partial_df is not None:
                        try:
                            from src.data_cache import merge_cached_and_fetched_data
                            date_col = None
                            for col in ['日期', 'date', '日期时间', 'datetime']:
                                if col in daily_df.columns:
                                    date_col = col
                                    break
                            cached_count = len(cached_partial_df)
                            # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                            daily_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_df, daily_df, date_col))
                            logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(daily_df) - cached_count} 条 = 总计 {len(daily_df)} 条")
                        except Exception as e:
                            logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
                    
                    # ========== 保存到缓存 ==========
                    if _is_cache_enabled(config_for_cache) and period == "daily":
                        try:
                            from src.data_cache import save_index_daily_cache
                            save_index_daily_cache(symbol, daily_df, config=config_for_cache)
                        except Exception as e:
                            logger.debug(f"保存缓存失败（不影响主流程）: {e}")
                    # ========== 缓存保存结束 ==========
                    
                    return daily_df
        else:
            if not (symbol.startswith("5") or symbol.startswith("1")):
                logger.warning(f"无法转换指数代码用于新浪接口: {symbol}, 将尝试下一个备用方案")
    except Exception as e:
        logger.warning(f"stock_zh_index_daily 失败: {symbol}, 错误: {str(e)}, 将尝试下一个备用方案")
    
    # 方法3：尝试使用 index_zh_a_hist（备用方案2）
    try:
        logger.warning(f"【方法3】使用备用方案 index_zh_a_hist: {symbol}")
        logger.debug(f"获取指数日线数据: symbol={symbol}, period={period}, "
                    f"start_date={start_date}, end_date={end_date}")
        
        start_time = time.time()
        daily_df = ak.index_zh_a_hist(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date
        )
        duration = time.time() - start_time
        
        if daily_df is not None and not daily_df.empty:
            log_function_result(logger, "fetch_index_daily_em", 
                              f"获取到{len(daily_df)}条数据", duration)
            
            # ========== 合并部分缓存数据 ==========
            if _is_cache_enabled(config_for_cache) and period == "daily" and cached_partial_df is not None:
                try:
                    from src.data_cache import merge_cached_and_fetched_data
                    # 找到日期列
                    date_col = None
                    for col in ['日期', 'date', '日期时间', 'datetime']:
                        if col in daily_df.columns:
                            date_col = col
                            break
                    cached_count = len(cached_partial_df)
                    # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                    daily_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_df, daily_df, date_col))
                    logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(daily_df) - cached_count} 条 = 总计 {len(daily_df)} 条")
                except Exception as e:
                    logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
            
            # ========== 保存到缓存 ==========
            if _is_cache_enabled(config_for_cache) and period == "daily":
                try:
                    from src.data_cache import save_index_daily_cache
                    save_index_daily_cache(symbol, daily_df, config=config_for_cache)
                except Exception as e:
                    logger.debug(f"保存缓存失败（不影响主流程）: {e}")
            # ========== 缓存保存结束 ==========
            
            return daily_df
        else:
            logger.warning(f"index_zh_a_hist 返回空数据: {symbol}, 将尝试下一个备用方案")
    except Exception as e:
        logger.warning(f"index_zh_a_hist 失败: {symbol}, 错误: {str(e)}, 将尝试下一个备用方案")
    
    # 方法4：使用 stock_zh_index_daily_em（备用方案3）
    try:
        # 指数代码映射表
        index_code_mapping = {
            "000300": "sz399300",  # 沪深300
            "000001": "sh000001",  # 上证指数
            "000016": "sh000016",  # 上证50
            "000905": "sh000905",  # 中证500
            "399001": "sz399001",  # 深证成指
            "399006": "sz399006",  # 创业板指
        }
        
        # 转换指数代码
        converted_symbol = index_code_mapping.get(symbol)
        if converted_symbol is None:
            # 自动转换：000xxx -> sh000xxx, 399xxx -> sz399xxx
            if symbol.startswith("000"):
                converted_symbol = f"sh{symbol}"
            elif symbol.startswith("399"):
                converted_symbol = f"sz{symbol}"
            else:
                # 检查是否是ETF代码（通常以5或1开头）
                if symbol.startswith("5") or symbol.startswith("1"):
                    logger.warning(f"无法转换代码: {symbol} 是ETF代码，stock_zh_index_daily_em接口不支持ETF代码。所有指数数据源均失败，请使用 fetch_etf_daily_em 获取ETF数据")
                else:
                    logger.warning(f"无法转换指数代码，所有数据源均失败: {symbol}，代码格式不支持（仅支持以000或399开头的指数代码）")
                log_error_with_context(
                    logger, Exception(last_error),
                    {
                        'function': 'fetch_index_daily_em',
                        'symbol': symbol,
                        'period': period,
                        'start_date': start_date,
                        'end_date': end_date,
                        'attempts': max_retries
                    },
                    "获取指数日线数据失败（所有数据源均失败：Tushare主数据源、stock_zh_index_daily备用1、index_zh_a_hist备用2、stock_zh_index_daily_em备用3）"
                )
                return None
        
        logger.warning(f"【方法4】使用备用方案 stock_zh_index_daily_em: {symbol} -> {converted_symbol}")
        
        # 调用备用接口
        start_time = time.time()
        daily_df = ak.stock_zh_index_daily_em(symbol=converted_symbol)
        duration = time.time() - start_time
        
        if daily_df is not None and not daily_df.empty:
            # 转换数据格式以匹配 index_zh_a_hist 的格式
            # stock_zh_index_daily_em 返回: date, open, close, high, low, volume, amount
            # index_zh_a_hist 返回格式可能不同，需要统一
            
            # 统一列名为中文（如果原数据是英文列名）
            column_mapping = {
                'date': '日期',
                'open': '开盘',
                'close': '收盘',
                'high': '最高',
                'low': '最低',
                'volume': '成交量',
                'amount': '成交额'
            }
            
            # 重命名列
            for old_col, new_col in column_mapping.items():
                if old_col in daily_df.columns:
                    daily_df = daily_df.rename(columns={old_col: new_col})
            
            # 筛选日期范围
            if '日期' in daily_df.columns:
                # 转换日期格式
                daily_df['日期'] = pd.to_datetime(daily_df['日期'])
                start_dt = datetime.strptime(start_date, "%Y%m%d")
                end_dt = datetime.strptime(end_date, "%Y%m%d")
                
                # 筛选日期范围
                daily_df = daily_df[(daily_df['日期'] >= start_dt) & (daily_df['日期'] <= end_dt)]
                
                # 转换日期为字符串格式（YYYYMMDD）
                daily_df['日期'] = daily_df['日期'].dt.strftime('%Y%m%d')
            
            if not daily_df.empty:
                log_function_result(logger, "fetch_index_daily_em", 
                                  f"使用备用方案获取到{len(daily_df)}条数据", duration)
                logger.info(f"备用方案成功: stock_zh_index_daily_em({converted_symbol})")
                
                # ========== 合并部分缓存数据 ==========
                if _is_cache_enabled(config_for_cache) and period == "daily" and cached_partial_df is not None:
                    try:
                        from src.data_cache import merge_cached_and_fetched_data
                        date_col = None
                        for col in ['日期', 'date', '日期时间', 'datetime']:
                            if col in daily_df.columns:
                                date_col = col
                                break
                        cached_count = len(cached_partial_df)
                        # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                        daily_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_df, daily_df, date_col))
                        logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(daily_df) - cached_count} 条 = 总计 {len(daily_df)} 条")
                    except Exception as e:
                        logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
                
                # ========== 保存到缓存 ==========
                if _is_cache_enabled(config_for_cache) and period == "daily":
                    try:
                        from src.data_cache import save_index_daily_cache
                        save_index_daily_cache(symbol, daily_df, config=config_for_cache)
                    except Exception as e:
                        logger.debug(f"保存缓存失败（不影响主流程）: {e}")
                # ========== 缓存保存结束 ==========
                
                return daily_df
            else:
                logger.warning(f"备用方案返回的数据在日期范围内为空: {symbol} ({converted_symbol})")
        else:
            logger.warning(f"备用方案返回空数据: {symbol} ({converted_symbol})")
            
    except Exception as e:
        logger.warning(f"备用方案3 stock_zh_index_daily_em 也失败: {symbol}, 错误: {e}")
    
    # 所有方法都失败
    # 提供更友好的错误信息
    if "NoneType" in str(last_error) or "subscriptable" in str(last_error):
        logger.error(f"获取指数日线数据失败: symbol={symbol}, 可能原因: API返回数据格式异常或网络问题")
    elif "Proxy" in str(last_error) or "proxy" in str(last_error).lower():
        logger.error(f"获取指数日线数据失败: symbol={symbol}, 可能原因: 代理连接问题")
    else:
        logger.error(f"获取指数日线数据最终失败: symbol={symbol}, 原因: {last_error}")
    
    # 如果部分缓存命中，即使API失败也返回缓存数据
    if cached_partial_df is not None and not cached_partial_df.empty:
        logger.warning(f"API获取失败，但存在部分缓存数据，返回缓存数据: {symbol}, {len(cached_partial_df)} 条")
        return cached_partial_df
    
    return None


def fetch_global_index_spot_em(
    symbol: str,
    max_retries: int = 2,
    retry_delay: float = 2.0
) -> Optional[pd.DataFrame]:
    """
    获取全球指数实时数据（东方财富接口）
    
    Args:
        symbol: 指数名称（如 "A50期指", "纳斯达克中国金龙指数"）
        max_retries: 最大重试次数（默认2次，因为外盘数据获取较慢）
        retry_delay: 重试延迟（秒，默认2.0秒）
    
    Returns:
        pd.DataFrame: 全球指数实时数据，如果失败返回None
    """
    log_function_call(logger, "fetch_global_index_spot_em", symbol=symbol)
    
    # 重试机制
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.debug(f"重试获取全球指数实时数据: symbol={symbol}, 第{attempt+1}次尝试")
                time.sleep(retry_delay)
            
            start_time = time.time()
            # 获取全球期货实时数据
            spot_df = ak.futures_global_spot_em()
            duration = time.time() - start_time
            
            if spot_df is not None and not spot_df.empty:
                # 如果是A50期指，筛选A50期指数据
                if symbol == "A50期指":
                    # 查找A50期指代码
                    a50_code = _find_a50_futures_code()
                    if a50_code:
                        # 查找代码列
                        code_col = None
                        for col in spot_df.columns:
                            col_lower = str(col).lower()
                            if 'code' in col_lower or '代码' in col_lower or 'symbol' in col_lower:
                                code_col = col
                                break
                        if code_col is None and len(spot_df.columns) > 0:
                            code_col = spot_df.columns[0]
                        
                        if code_col:
                            a50_data = spot_df[spot_df[code_col].astype(str) == str(a50_code)]
                            if not a50_data.empty:
                                log_function_result(logger, "fetch_global_index_spot_em", 
                                                  "获取到A50期指实时数据", duration)
                                return a50_data
                            else:
                                logger.warning(f"未找到A50期指实时数据: code={a50_code}")
                
                # 其他情况返回整个DataFrame（向后兼容）
                log_function_result(logger, "fetch_global_index_spot_em", 
                                  f"获取到{len(spot_df)}条数据", duration)
                return spot_df
            else:
                logger.warning(f"API返回空数据: symbol={symbol}, 尝试{attempt+1}/{max_retries}")
                last_error = "API返回空数据"
                
        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            
            # 如果是代理错误，只重试一次
            if 'Proxy' in error_type or 'proxy' in str(e).lower():
                logger.warning(f"代理连接失败: symbol={symbol}, 错误: {last_error}")
                if attempt < max_retries - 1:
                    continue
                else:
                    logger.warning(f"全球指数实时数据获取失败（代理问题）: symbol={symbol}，这是可选数据，不影响核心功能")
                    return None
            else:
                logger.warning(f"获取全球指数实时数据失败: symbol={symbol}, 尝试{attempt+1}/{max_retries}, 错误: {last_error}")
                if attempt < max_retries - 1:
                    continue
                else:
                    # 最后一次尝试失败，记录详细错误
                    log_error_with_context(
                        logger, e,
                        {
                            'function': 'fetch_global_index_spot_em',
                            'symbol': symbol,
                            'attempts': max_retries
                        },
                        f"获取全球指数实时数据失败（已重试{max_retries}次）"
                    )
    
    logger.warning(f"获取全球指数实时数据最终失败: symbol={symbol}, 原因: {last_error}（这是可选数据，不影响核心功能）")
    return None


def _find_a50_futures_code() -> Optional[str]:
    """
    查找A50期指在新浪财经/东方财富中的代码（优先选择主力合约）
    
    Returns:
        str: A50期指代码，如果未找到返回None
    """
    try:
        logger.debug("查找A50期指代码...")
        spot_df = ak.futures_global_spot_em()
        
        if spot_df is None or spot_df.empty:
            logger.warning("futures_global_spot_em返回空数据，无法查找A50期指代码")
            return None
        
        # 查找包含A50相关关键词的合约
        # 可能的列名：代码、名称、symbol、name等
        search_keywords = ["A50", "CHINA50", "XIN9", "富时", "FTSE"]
        
        # 尝试不同的列名组合
        code_col = None
        name_col = None
        
        for col in spot_df.columns:
            col_lower = str(col).lower()
            if 'code' in col_lower or '代码' in col_lower or 'symbol' in col_lower:
                code_col = col
            if 'name' in col_lower or '名称' in col_lower or '品种' in col_lower:
                name_col = col
        
        if code_col is None or name_col is None:
            logger.debug(f"无法找到代码或名称列，可用列: {spot_df.columns.tolist()}")
            # 尝试使用第一列作为代码，第二列作为名称
            if len(spot_df.columns) >= 2:
                code_col = spot_df.columns[0]
                name_col = spot_df.columns[1]
            else:
                return None
        
        # 先找到所有A50相关的合约
        a50_all = pd.DataFrame()
        for keyword in search_keywords:
            mask = spot_df[name_col].astype(str).str.contains(keyword, case=False, na=False)
            matches = spot_df[mask]
            if not matches.empty:
                a50_all = pd.concat([a50_all, matches], ignore_index=True)
        
        # 去重（如果有重复）
        if not a50_all.empty:
            a50_all = a50_all.drop_duplicates(subset=[code_col], keep='first')
            logger.debug(f"找到 {len(a50_all)} 个A50相关合约")
            
            # 筛选策略：优先选择有价格数据且成交量最大的（主力合约）
            # 查找价格列和成交量列
            price_col = None
            volume_col = None
            for col in a50_all.columns:
                col_lower = str(col).lower()
                if 'price' in col_lower or '最新价' in col_lower or '现价' in col_lower:
                    price_col = col
                if 'volume' in col_lower or '成交量' in col_lower or 'vol' in col_lower:
                    volume_col = col
            
            if price_col and volume_col:
                # 优先选择有价格数据且成交量最大的
                a50_with_price = a50_all[
                    (a50_all[price_col].notna()) & 
                    (pd.to_numeric(a50_all[volume_col], errors='coerce') > 0)
                ]
                
                if not a50_with_price.empty:
                    # 按成交量降序排序，选择主力合约
                    a50_with_price = a50_with_price.sort_values(volume_col, ascending=False)
                    row = a50_with_price.iloc[0]
                    code = str(row[code_col])
                    logger.info(f"找到A50期指主力合约代码: {code} ({row[name_col]}), 成交量={row[volume_col]}")
                    logger.debug(f"匹配的合约信息: {row.to_dict()}")
                    return code
                else:
                    # 如果没有有价格的合约，至少选择有成交量的
                    a50_with_volume = a50_all[pd.to_numeric(a50_all[volume_col], errors='coerce') > 0]
                    if not a50_with_volume.empty:
                        row = a50_with_volume.sort_values(volume_col, ascending=False).iloc[0]
                        code = str(row[code_col])
                        logger.info(f"找到A50期指合约代码（有成交量但无价格）: {code} ({row[name_col]})")
                        return code
            
            # 如果无法通过价格和成交量筛选，选择第一个匹配的
            row = a50_all.iloc[0]
            code = str(row[code_col])
            logger.info(f"找到A50期指代码: {code} ({row[name_col]})")
            logger.warning("该合约可能暂无交易数据")
            return code
        
        logger.warning(f"未找到A50期指代码，搜索关键词: {search_keywords}")
        logger.debug(f"可用合约示例（前10个）: {spot_df[[code_col, name_col]].head(10).to_dict('records')}")
        return None
        
    except Exception as e:
        logger.warning(f"查找A50期指代码失败: {e}")
        return None


def fetch_global_index_hist_em(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    获取全球指数历史数据（东方财富接口）
    
    对于A50期指，使用fetch_a50_daily_sina_hist接口（通过AKShare的futures_foreign_hist接口）
    
    Args:
        symbol: 指数名称（如 "A50期指", "纳斯达克中国金龙指数"）
        start_date: 开始日期（格式："YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYYMMDD"），如果为None则使用当前日期
    
    Returns:
        pd.DataFrame: 全球指数历史数据，如果失败返回None
    """
    try:
        log_function_call(logger, "fetch_global_index_hist_em", 
                         symbol=symbol, start_date=start_date, end_date=end_date)
        
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        
        if end_date is None:
            end_date = now.strftime("%Y%m%d")
        
        if start_date is None:
            # 默认回看30天
            start = now - timedelta(days=30)
            start_date = start.strftime("%Y%m%d")
        
        # 如果是A50期指，使用fetch_a50_daily_sina_hist接口（直接使用CHA50CFD代码）
        if symbol == "A50期指":
            logger.info("使用fetch_a50_daily_sina_hist获取A50期指历史数据（通过AKShare的futures_foreign_hist接口）")
            # 直接调用fetch_a50_daily_sina_hist，该函数使用固定的CHA50CFD代码，无需查找代码
            return fetch_a50_daily_sina_hist(start_date=start_date, end_date=end_date)
        
        # 纳斯达克中国金龙指数：使用 yfinance 的 HXC 指数数据（可配置开关）
        if symbol == "纳斯达克中国金龙指数":
            try:
                cfg = load_system_config()
                ds_cfg = cfg.get("data_sources", {}) if isinstance(cfg, dict) else {}
                gl_cfg = ds_cfg.get("global_index", {})
                hxc_cfg = gl_cfg.get("hxc", {})
                enabled = bool(hxc_cfg.get("enabled", False))
            except Exception:
                enabled = False

            if not enabled:
                logger.warning(
                    "fetch_global_index_hist_em: 已跳过纳斯达克中国金龙指数（HXC）yfinance 请求，"
                    "可在 config.yaml 的 data_sources.global_index.hxc.enabled 开启后再使用该数据源"
                )
                return None

            try:
                import yfinance as yf  # type: ignore
            except ImportError as e:
                logger.warning(f"fetch_global_index_hist_em: 需要 yfinance 支持纳斯达克中国金龙指数历史数据，但未安装 yfinance: {e}")
                return None

            try:
                # yfinance 符号：^HXC
                yf_symbol = "^HXC"
                # 将 YYYYMMDD 转为 YYYY-MM-DD，并注意 end 为开区间，需要 +1 天以包含 end_date
                start_dt = datetime.strptime(start_date, "%Y%m%d")
                end_dt = datetime.strptime(end_date, "%Y%m%d") + timedelta(days=1)
                hist = yf.download(
                    yf_symbol,
                    start=start_dt.strftime("%Y-%m-%d"),
                    end=end_dt.strftime("%Y-%m-%d"),
                    progress=False,
                )
                if hist is None or hist.empty:
                    logger.warning("fetch_global_index_hist_em: yfinance 未返回纳指金龙指数历史数据")
                    return None

                # 统一列名为与 A 股日线类似的中文列名，便于后续使用 '收盘'
                df = hist.rename(
                    columns={
                        "Open": "开盘",
                        "Close": "收盘",
                        "High": "最高",
                        "Low": "最低",
                        "Volume": "成交量",
                    }
                ).reset_index()

                # 将日期列命名为 '日期'
                if "Date" in df.columns:
                    df = df.rename(columns={"Date": "日期"})

                # 只保留必要列
                keep_cols = [c for c in ["日期", "开盘", "收盘", "最高", "最低", "成交量"] if c in df.columns]
                df = df[keep_cols]

                logger.info(
                    "fetch_global_index_hist_em: 使用 yfinance 获取纳斯达克中国金龙指数历史数据成功 "
                    f"(rows={len(df)}, symbol={yf_symbol})"
                )
                return df
            except Exception as e:
                log_error_with_context(
                    logger,
                    e,
                    {
                        "function": "fetch_global_index_hist_em",
                        "symbol": symbol,
                        "start_date": start_date,
                        "end_date": end_date,
                        "source": "yfinance_^HXC",
                    },
                    "获取纳斯达克中国金龙指数历史数据失败（yfinance）",
                )
                return None

        # 其他指数暂不支持
        logger.warning(f"fetch_global_index_hist_em: 暂不支持 {symbol}，功能待实现")
        return None
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'fetch_global_index_hist_em',
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date
            },
            "获取全球指数历史数据失败"
        )
        return None


def fetch_a50_daily_sina(
    symbol: str = "CHA50CFD",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> Optional[pd.DataFrame]:
    """
    获取A50期指日线数据（新浪财经接口）- ⚠️ 已确认不可用
    
    ⚠️ 警告：新浪财经的 CN_MarketData.getKLineData 接口不支持A50期货数据，
    对 CHA50CFD 代码返回 null。此函数保留仅用于测试目的。
    
    实际使用请使用 fetch_a50_daily_sina_hist() 函数（通过AKShare获取新浪财经数据）。
    
    Args:
        symbol: A50期指代码（默认 "CHA50CFD"）
        start_date: 开始日期（格式："YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYYMMDD"），如果为None则使用当前日期
        max_retries: 最大重试次数（默认3次）
        retry_delay: 重试延迟（秒，默认1.0秒）
    
    Returns:
        pd.DataFrame: A50期指日线数据，如果失败返回None（通常返回None，因为接口不支持）
        数据格式：日期、开盘、收盘、最高、最低、成交量、成交额
    """
    log_function_call(logger, "fetch_a50_daily_sina", 
                     symbol=symbol, start_date=start_date, end_date=end_date)
    
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date = now.strftime("%Y%m%d")
    
    if start_date is None:
        # 默认回看30天
        start = now - timedelta(days=30)
        start_date = start.strftime("%Y%m%d")
    
    # ========== 构建请求URL和参数 ==========
    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    
    # 日线数据使用 scale=1200
    scale = 1200
    
    # 计算datalen参数（日线数据，每个交易日1条数据）
    try:
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        days_diff = (end_dt - start_dt).days + 1
        # 保守估计：每个交易日1条数据，加上缓冲
        estimated_points = int(days_diff * 1.2)
        datalen = min(estimated_points, 1023)  # 新浪限制最大1023
    except Exception as e:
        logger.debug(f"计算datalen失败，使用默认值1023: {e}")
        datalen = 1023
    
    params = {
        "symbol": symbol,
        "scale": scale,
        "ma": "no",  # 不计算均线，减少数据量
        "datalen": datalen
    }
    
    # ========== 请求头设置 ==========
    config = load_system_config()
    data_sources_config = config.get('data_sources', {})
    # 优先使用 a50_futures.sina 配置，如果没有则复用 etf_minute.sina 配置
    sina_config = data_sources_config.get('a50_futures', {}).get('sina', {})
    if not sina_config:
        sina_config = data_sources_config.get('etf_minute', {}).get('sina', {})
    
    headers = {
        "Referer": sina_config.get('referer', 'http://finance.sina.com.cn'),
        "User-Agent": sina_config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    }
    
    # ========== 重试机制 ==========
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = min(retry_delay * (2 ** (attempt - 1)), 30.0)
                logger.debug(f"重试获取A50期指日线数据（新浪）: symbol={symbol}, 第{attempt+1}次尝试, 等待{delay:.1f}秒")
                time.sleep(delay)
            
            logger.debug(f"获取A50期指日线数据（新浪）: symbol={symbol}, scale={scale}, datalen={datalen}")
            
            start_time = time.time()
            response = requests.get(url, params=params, headers=headers, timeout=10)
            duration = time.time() - start_time
            
            # 检查HTTP状态码
            if response.status_code != 200:
                raise requests.exceptions.HTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
            
            # 解析JSON响应
            try:
                data = response.json()
            except ValueError:
                logger.debug(f"JSON解析失败，原始响应: {response.text[:500]}")
                raise ValueError(f"JSON解析失败: {response.text[:200]}")
            
            # 调试日志：记录实际响应内容
            logger.debug(f"新浪接口响应: symbol={symbol}, 响应类型={type(data)}, 响应长度={len(data) if isinstance(data, list) else 'N/A'}")
            if isinstance(data, list) and len(data) == 0:
                logger.debug(f"空数据响应，完整响应文本: {response.text[:500]}")
            elif isinstance(data, list) and len(data) > 0:
                logger.debug(f"响应数据示例（前3条）: {data[:3]}")
            else:
                logger.debug(f"非列表响应，完整响应: {response.text[:500]}")
            
            # 检查返回数据
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"新浪接口返回空数据: symbol={symbol}, 尝试{attempt+1}/{max_retries}, 响应文本: {response.text[:200]}")
                last_error = "API返回空数据"
                continue
            
            # ========== 转换为DataFrame并统一格式 ==========
            # 新浪返回格式：{"day": "2023-01-01", "open": 1234.5, "high": 1235.0, "low": 1233.0, "close": 1234.5, "volume": 123456}
            # 需要转换为：日期、开盘、收盘、最高、最低、成交量、成交额
            
            df = pd.DataFrame(data)
            
            # 重命名列名（统一格式）
            column_mapping = {
                "day": "日期",
                "open": "开盘",
                "close": "收盘",
                "high": "最高",
                "low": "最低",
                "volume": "成交量"
            }
            
            # 只保留需要的列
            available_columns = [col for col in column_mapping.keys() if col in df.columns]
            df = df[available_columns].copy()
            
            # 重命名
            df = df.rename(columns=column_mapping)
            
            # 添加成交额列（新浪接口不提供，设为0或根据成交量估算）
            if "成交额" not in df.columns:
                df["成交额"] = 0.0  # 新浪接口不提供成交额，设为0
            
            # 确保日期列为datetime类型，然后转换为字符串格式
            if "日期" in df.columns:
                df["日期"] = pd.to_datetime(df["日期"], errors='coerce')
                # 过滤掉无效的日期数据
                df = df[df["日期"].notna()].copy()
                # 转换为字符串格式（YYYYMMDD）
                df["日期"] = df["日期"].dt.strftime('%Y%m%d')
            
            # 确保数值列为float类型
            numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 按日期排序（从早到晚）
            if "日期" in df.columns:
                df = df.sort_values("日期").reset_index(drop=True)
            
            # 日期范围过滤
            if start_date and end_date:
                try:
                    mask = (df["日期"] >= start_date) & (df["日期"] <= end_date)
                    df = df[mask].copy()
                except Exception as e:
                    logger.debug(f"日期范围过滤失败，返回全部数据: {e}")
            
            if df.empty:
                logger.warning(f"过滤后数据为空: symbol={symbol}, 尝试{attempt+1}/{max_retries}")
                last_error = "过滤后数据为空"
                continue
            
            log_function_result(logger, "fetch_a50_daily_sina", 
                              f"获取到{len(df)}条数据", duration)
            
            return df
            
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, 
                requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"网络连接错误（新浪）: symbol={symbol}, 尝试{attempt+1}/{max_retries}, "
                          f"错误类型: {error_type}, 错误: {last_error}")
            if attempt < max_retries - 1:
                continue
        except requests.exceptions.HTTPError as e:
            last_error = str(e)
            logger.warning(f"HTTP错误（新浪）: symbol={symbol}, 尝试{attempt+1}/{max_retries}, 错误: {last_error}")
            if attempt < max_retries - 1:
                continue
        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            log_error_with_context(
                logger, e,
                {
                    'function': 'fetch_a50_daily_sina',
                    'symbol': symbol,
                    'attempt': attempt + 1,
                    'max_retries': max_retries
                },
                "获取A50期指日线数据失败（新浪）"
            )
            if attempt < max_retries - 1:
                continue
    
    logger.warning(f"获取A50期指日线数据最终失败（新浪）: symbol={symbol}, 原因: {last_error}")
    return None


def fetch_a50_minute_sina(
    symbol: str = "CHA50CFD",
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    fast_fail: bool = False,
    force_realtime: bool = False
) -> Optional[pd.DataFrame]:
    """
    获取A50期指分钟数据（新浪财经接口）- ⚠️ 已确认不可用
    
    ⚠️ 警告：新浪财经的 CN_MarketData.getKLineData 接口不支持A50期货数据，
    对 CHA50CFD 代码返回 null。此函数保留仅用于测试目的。
    
    实际使用请使用其他数据源（目前暂无可用的A50分钟数据接口）。
    
    Args:
        symbol: A50期指代码（默认 "CHA50CFD"）
        period: 周期（"5", "15", "30", "60"），注意：新浪不支持1分钟数据
        start_date: 开始日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYY-MM-DD HH:MM:SS" 或 "YYYYMMDD"），如果为None则使用当前日期
        lookback_days: 回看天数（默认5天）
        max_retries: 最大重试次数（默认3次）
        retry_delay: 重试延迟（秒，默认1.0秒）
        fast_fail: 快速失败模式（默认False）
        force_realtime: 强制实时获取（交易时间内不使用当天缓存数据）
    
    Returns:
        pd.DataFrame: A50期指分钟数据，如果失败返回None（通常返回None，因为接口不支持）
        数据格式：时间、开盘、收盘、最高、最低、成交量、成交额
    """
    log_function_call(logger, "fetch_a50_minute_sina", 
                     symbol=symbol, period=period, lookback_days=lookback_days)
    
    # ========== 周期映射：转换为新浪财经的scale参数 ==========
    # 新浪财经支持的周期：5, 15, 30, 60分钟（注意：不支持1分钟）
    period_to_scale = {
        "1": 1,   # 注意：新浪可能不支持1分钟，但先保留
        "5": 5,
        "15": 15,
        "30": 30,
        "60": 60
    }
    scale = period_to_scale.get(period)
    if scale is None:
        logger.warning(f"不支持的周期: {period}，使用默认30分钟")
        scale = 30
    
    # ========== 日期处理 ==========
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # 统一转换为 "YYYY-MM-DD HH:MM:SS" 格式
        if len(end_date) == 8 and end_date.isdigit():
            end_date_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]} 15:00:00"
        else:
            end_date_str = end_date
    
    if start_date is None:
        # 计算回看天数
        start = now - timedelta(days=lookback_days)
        start_date_str = start.strftime("%Y-%m-%d 09:30:00")
    else:
        # 统一转换为 "YYYY-MM-DD HH:MM:SS" 格式
        if len(start_date) == 8 and start_date.isdigit():
            start_date_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 09:30:00"
        else:
            start_date_str = start_date
    
    # ========== 计算datalen参数 ==========
    # 新浪财经接口限制：datalen最大1023
    # 根据日期范围和周期估算需要的数据点数
    try:
        start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days + 1
        
        # 估算：A50期指交易时间较长（T时段9:00-16:29；T+1时段17:40-4:45），按周期计算数据点数
        # 保守估计：每个交易日约240/scale个数据点（假设4小时交易时间）
        estimated_points = int(days_diff * (240 / scale) * 1.2)  # 1.2倍缓冲
        datalen = min(estimated_points, 1023)  # 新浪限制最大1023
    except Exception as e:
        logger.debug(f"计算datalen失败，使用默认值1023: {e}")
        datalen = 1023
    
    # ========== 构建请求URL和参数 ==========
    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": symbol,
        "scale": scale,
        "ma": "no",  # 不计算均线，减少数据量
        "datalen": datalen
    }
    
    # ========== 请求头设置 ==========
    config = load_system_config()
    data_sources_config = config.get('data_sources', {})
    # 优先使用 a50_futures.sina 配置，如果没有则复用 etf_minute.sina 配置
    sina_config = data_sources_config.get('a50_futures', {}).get('sina', {})
    if not sina_config:
        sina_config = data_sources_config.get('etf_minute', {}).get('sina', {})
    
    headers = {
        "Referer": sina_config.get('referer', 'http://finance.sina.com.cn'),
        "User-Agent": sina_config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    }
    
    # ========== 重试机制 ==========
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = min(retry_delay * (2 ** (attempt - 1)), 30.0)
                logger.debug(f"重试获取A50期指分钟数据（新浪）: symbol={symbol}, period={period}, 第{attempt+1}次尝试, 等待{delay:.1f}秒")
                time.sleep(delay)
            
            logger.debug(f"获取A50期指分钟数据（新浪）: symbol={symbol}, period={period}, "
                        f"scale={scale}, datalen={datalen}")
            
            start_time = time.time()
            response = requests.get(url, params=params, headers=headers, timeout=10)
            duration = time.time() - start_time
            
            # 检查HTTP状态码
            if response.status_code != 200:
                raise requests.exceptions.HTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
            
            # 解析JSON响应
            try:
                data = response.json()
            except ValueError:
                logger.debug(f"JSON解析失败，原始响应: {response.text[:500]}")
                raise ValueError(f"JSON解析失败: {response.text[:200]}")
            
            # 调试日志：记录实际响应内容
            logger.debug(f"新浪接口响应: symbol={symbol}, period={period}, 响应类型={type(data)}, 响应长度={len(data) if isinstance(data, list) else 'N/A'}")
            if isinstance(data, list) and len(data) == 0:
                logger.debug(f"空数据响应，完整响应文本: {response.text[:500]}")
            elif isinstance(data, list) and len(data) > 0:
                logger.debug(f"响应数据示例（前3条）: {data[:3]}")
            else:
                logger.debug(f"非列表响应，完整响应: {response.text[:500]}")
            
            # 检查返回数据
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"新浪接口返回空数据: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, 响应文本: {response.text[:200]}")
                last_error = "API返回空数据"
                continue
            
            # ========== 转换为DataFrame并统一格式 ==========
            # 新浪返回格式：{"day": "2023-01-01 15:00:00", "open": 1234.5, "high": 1235.0, "low": 1233.0, "close": 1234.5, "volume": 123456}
            # 需要转换为：时间、开盘、收盘、最高、最低、成交量、成交额
            
            df = pd.DataFrame(data)
            
            # 重命名列名（统一格式）
            column_mapping = {
                "day": "时间",
                "open": "开盘",
                "close": "收盘",
                "high": "最高",
                "low": "最低",
                "volume": "成交量"
            }
            
            # 只保留需要的列
            available_columns = [col for col in column_mapping.keys() if col in df.columns]
            df = df[available_columns].copy()
            
            # 重命名
            df = df.rename(columns=column_mapping)
            
            # 添加成交额列（新浪接口不提供，设为0或根据成交量估算）
            if "成交额" not in df.columns:
                df["成交额"] = 0.0  # 新浪接口不提供成交额，设为0
            
            # 确保时间列为datetime类型，然后转换为字符串格式
            if "时间" in df.columns:
                df["时间"] = pd.to_datetime(df["时间"], errors='coerce')
                # 过滤掉无效的时间数据
                df = df[df["时间"].notna()].copy()
                # 转换为字符串格式（与fetch_index_minute_em一致）
                df["时间"] = df["时间"].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # 确保数值列为float类型
            numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 按时间排序（从早到晚）
            if "时间" in df.columns:
                df = df.sort_values("时间").reset_index(drop=True)
            
            # 日期范围过滤（如果指定了start_date和end_date）
            if start_date_str and end_date_str:
                try:
                    start_dt = datetime.strptime(start_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    end_dt = datetime.strptime(end_date_str[:19], "%Y-%m-%d %H:%M:%S")
                    
                    # 将时间列转换为datetime进行比较
                    df_time = pd.to_datetime(df["时间"], errors='coerce')
                    mask = (df_time >= start_dt) & (df_time <= end_dt)
                    df = df[mask].copy()
                except Exception as e:
                    logger.debug(f"日期范围过滤失败，返回全部数据: {e}")
            
            if df.empty:
                logger.warning(f"过滤后数据为空: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "过滤后数据为空"
                continue
            
            log_function_result(logger, "fetch_a50_minute_sina", 
                              f"获取到{len(df)}条数据", duration)
            
            return df
            
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, 
                requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
            last_error = str(e)
            error_type = type(e).__name__
            logger.warning(f"网络连接错误（新浪）: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, "
                          f"错误类型: {error_type}, 错误: {last_error}")
            if attempt < max_retries - 1:
                continue
        except requests.exceptions.HTTPError as e:
            last_error = str(e)
            logger.warning(f"HTTP错误（新浪）: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}, 错误: {last_error}")
            if attempt < max_retries - 1:
                continue
        except Exception as e:
            last_error = str(e)
            error_type = type(e).__name__
            log_error_with_context(
                logger, e,
                {
                    'function': 'fetch_a50_minute_sina',
                    'symbol': symbol,
                    'period': period,
                    'attempt': attempt + 1,
                    'max_retries': max_retries
                },
                "获取A50期指分钟数据失败（新浪）"
            )
            if attempt < max_retries - 1:
                continue
    
    logger.warning(f"获取A50期指分钟数据最终失败（新浪）: symbol={symbol}, period={period}, 原因: {last_error}")
    return None


def fetch_a50_daily_sina_hist(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> Optional[pd.DataFrame]:
    """
    获取A50期指日线数据（新浪财经数据源，通过AKShare接口）
    
    使用AKShare的futures_foreign_hist接口获取A50期指日线数据
    数据源：新浪财经（https://finance.sina.com.cn/futuremarket/）
    直接使用固定代码 "CHA50CFD"，无需查找代码
    
    Args:
        start_date: 开始日期（格式："YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYYMMDD"），如果为None则使用当前日期
        max_retries: 最大重试次数（默认3次，未使用，保留用于兼容）
        retry_delay: 重试延迟（秒，默认1.0秒，未使用，保留用于兼容）
    
    Returns:
        pd.DataFrame: A50期指日线数据，如果失败返回None
        数据格式：日期、开盘、收盘、最高、最低、成交量、成交额
    """
    log_function_call(logger, "fetch_a50_daily_sina_hist", 
                     start_date=start_date, end_date=end_date)
    
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date = now.strftime("%Y%m%d")
    
    if start_date is None:
        # 默认回看30天
        start = now - timedelta(days=30)
        start_date = start.strftime("%Y%m%d")
    
    try:
        logger.info("使用AKShare接口获取A50期指历史数据: symbol=CHA50CFD")
        start_time = time.time()
        
        # 使用线程池执行器添加超时机制（30秒超时），防止AKShare调用卡住
        def _fetch_data():
            try:
                logger.debug("开始调用ak.futures_foreign_hist...")
                result = ak.futures_foreign_hist(symbol="CHA50CFD")
                logger.debug(f"ak.futures_foreign_hist调用完成，返回数据形状: {result.shape if result is not None else None}")
                return result
            except Exception as e:
                logger.error(f"ak.futures_foreign_hist内部异常: {e}")
                raise
        
        timeout_seconds = 30  # 30秒超时（减少超时时间，避免长时间卡住）
        hist_df = None
        try:
            logger.debug(f"使用ThreadPoolExecutor执行AKShare调用，超时时间: {timeout_seconds}秒")
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_fetch_data)
                hist_df = future.result(timeout=timeout_seconds)
                logger.debug("ThreadPoolExecutor执行完成")
        except FutureTimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"获取A50期指历史数据超时（超过{timeout_seconds}秒，实际耗时{elapsed:.2f}秒），请检查网络连接或AKShare接口状态")
            logger.error("建议：1) 检查网络连接 2) 检查AKShare接口是否正常 3) 考虑使用缓存数据")
            return None
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"AKShare接口调用异常（耗时{elapsed:.2f}秒）: {e}", exc_info=True)
            raise
        
        duration = time.time() - start_time
        logger.debug(f"AKShare调用总耗时: {duration:.2f}秒")
        
        if hist_df is None or hist_df.empty:
            logger.warning("A50期指历史数据为空")
            return None
        
        logger.debug(f"AKShare返回数据形状: {hist_df.shape}, 列: {hist_df.columns.tolist()}")
        
        # 统一数据格式
        # AKShare返回格式：date, open, high, low, close, volume, position, s
        # 需要转换为：日期、开盘、收盘、最高、最低、成交量、成交额
        
        result_df = pd.DataFrame()
        
        # 日期列：date -> 日期（转换为YYYYMMDD格式）
        if 'date' in hist_df.columns:
            result_df['日期'] = pd.to_datetime(hist_df['date'], errors='coerce')
            result_df['日期'] = result_df['日期'].dt.strftime('%Y%m%d')
        else:
            logger.warning("未找到date列，尝试使用第一列作为日期")
            if len(hist_df.columns) > 0:
                result_df['日期'] = pd.to_datetime(hist_df.iloc[:, 0], errors='coerce')
                result_df['日期'] = result_df['日期'].dt.strftime('%Y%m%d')
            else:
                logger.error("数据列为空")
                return None
        
        # 价格列
        if 'open' in hist_df.columns:
            result_df['开盘'] = pd.to_numeric(hist_df['open'], errors='coerce')
        else:
            logger.warning("未找到open列")
            result_df['开盘'] = 0.0
        
        if 'close' in hist_df.columns:
            result_df['收盘'] = pd.to_numeric(hist_df['close'], errors='coerce')
        else:
            logger.warning("未找到close列")
            result_df['收盘'] = 0.0
        
        if 'high' in hist_df.columns:
            result_df['最高'] = pd.to_numeric(hist_df['high'], errors='coerce')
        else:
            logger.warning("未找到high列")
            result_df['最高'] = 0.0
        
        if 'low' in hist_df.columns:
            result_df['最低'] = pd.to_numeric(hist_df['low'], errors='coerce')
        else:
            logger.warning("未找到low列")
            result_df['最低'] = 0.0
        
        # 成交量列
        if 'volume' in hist_df.columns:
            result_df['成交量'] = pd.to_numeric(hist_df['volume'], errors='coerce')
        else:
            logger.warning("未找到volume列")
            result_df['成交量'] = 0.0
        
        # 成交额列（futures_foreign_hist不提供成交额，设为0）
        result_df['成交额'] = 0.0
        
        # 过滤无效日期
        result_df = result_df[result_df['日期'].notna()].copy()
        
        # 日期范围筛选
        if start_date and end_date:
            mask = (result_df['日期'] >= start_date) & (result_df['日期'] <= end_date)
            result_df = result_df[mask].copy()
        
        # 按日期排序
        if '日期' in result_df.columns:
            result_df = result_df.sort_values('日期').reset_index(drop=True)
        
        if result_df.empty:
            logger.warning(f"日期范围筛选后数据为空: start_date={start_date}, end_date={end_date}")
            return None
        
        log_function_result(logger, "fetch_a50_daily_sina_hist", 
                          f"获取到{len(result_df)}条A50期指历史数据", duration)
        
        return result_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'fetch_a50_daily_sina_hist',
                'start_date': start_date,
                'end_date': end_date
            },
            "获取A50期指历史数据失败"
        )
        return None


# 保持向后兼容：fetch_a50_daily_em 作为 fetch_a50_daily_sina_hist 的别名
def fetch_a50_daily_em(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> Optional[pd.DataFrame]:
    """
    获取A50期指日线数据（向后兼容别名）
    
    此函数是 fetch_a50_daily_sina_hist 的别名，保留用于向后兼容。
    建议使用 fetch_a50_daily_sina_hist 函数。
    """
    return fetch_a50_daily_sina_hist(start_date, end_date, max_retries, retry_delay)


def fetch_etf_daily_em(
    symbol: str = "510300",
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    prefer_tushare: bool = False
) -> Optional[pd.DataFrame]:
    """
    获取ETF日线数据（Tushare优先，新浪/东方财富作为备用）
    
    数据源优先级：
    1. Tushare（主）- 优先使用
    2. 新浪接口（fund_etf_hist_sina）- 备用
    3. 东方财富接口（fund_etf_hist_em）- 备用
    
    Args:
        symbol: ETF代码（如 "510300"）
        period: 周期（"daily", "weekly", "monthly"），目前只支持"daily"
        start_date: 开始日期（格式："YYYYMMDD"），如果为None则自动计算
        end_date: 结束日期（格式："YYYYMMDD"），如果为None则使用当前日期
        max_retries: 最大重试次数（默认3次）
        retry_delay: 重试延迟（秒，默认1.0秒）
        prefer_tushare: 是否优先使用Tushare（默认False，使用新浪接口）
    
    Returns:
        pd.DataFrame: ETF日线数据，如果失败返回None
    """
    # 确保symbol是字符串类型（防止配置文件中是整数）
    symbol = str(symbol) if symbol else "510300"
    
    tz_shanghai = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz_shanghai)
    
    if end_date is None:
        end_date = now.strftime("%Y%m%d")
    
    if start_date is None:
        # 默认回看90天，确保有足够的交易日数据（60个交易日 ≈ 90个日历日）
        start = now - timedelta(days=90)
        start_date = start.strftime("%Y%m%d")
    
    log_function_call(logger, "fetch_etf_daily_em", 
                     symbol=symbol, period=period, start_date=start_date, end_date=end_date)
    
    # ========== 缓存逻辑：先检查缓存 ==========
    config_for_cache = load_system_config(use_cache=True)
    cached_partial_df = None  # 用于存储部分缓存的数据
    
    if _is_cache_enabled(config_for_cache) and period == "daily":
        try:
            from src.data_cache import (
                get_cached_etf_daily, save_etf_daily_cache, 
                merge_cached_and_fetched_data
            )
            
            # 检查缓存
            cached_df, missing_dates = get_cached_etf_daily(
                symbol, start_date, end_date, config=config_for_cache
            )
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中，直接返回
                logger.info(f"ETF日线数据全部从缓存加载: {symbol}, {start_date}~{end_date}, {len(cached_df)} 条")
                return cached_df
            
            # 计算总日期数
            from datetime import datetime as dt
            start_dt = dt.strptime(start_date, "%Y%m%d")
            end_dt = dt.strptime(end_date, "%Y%m%d")
            total_days = (end_dt - start_dt).days + 1
            
            if cached_df is not None and not cached_df.empty and missing_dates and len(missing_dates) < total_days:
                # 部分缓存命中，需要获取缺失部分并合并
                logger.info(f"ETF日线数据部分缓存命中: {symbol}, 缺失 {len(missing_dates)} 个日期")
                # 保存已缓存的数据，用于后续合并
                cached_partial_df = cached_df
                # 调整日期范围，只获取缺失部分
                if missing_dates:
                    start_date = min(missing_dates)
                    end_date = max(missing_dates)
        except Exception as e:
            logger.debug(f"缓存检查失败，继续从接口获取: {e}")
    # ========== 缓存逻辑结束 ==========

    # 方法1：优先使用Tushare（主数据源）
    last_error = None
    try:
        from src.tushare_fallback import fetch_etf_daily_tushare
        logger.info(f"【方法1】使用 Tushare 获取ETF日线（主数据源）: {symbol}")
        etf_df = fetch_etf_daily_tushare(symbol, start_date, end_date)
        
        if etf_df is not None and not etf_df.empty:
            log_function_result(logger, "fetch_etf_daily_em", 
                              f"Tushare主数据源成功，获取到{len(etf_df)}条数据", 0)
            
            # ========== 合并部分缓存数据 ==========
            if _is_cache_enabled(config_for_cache) and period == "daily" and cached_partial_df is not None:
                try:
                    from src.data_cache import merge_cached_and_fetched_data
                    # 找到日期列
                    date_col = None
                    for col in ['日期', 'date', '日期时间', 'datetime']:
                        if col in etf_df.columns:
                            date_col = col
                            break
                    cached_count = len(cached_partial_df)
                    # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                    etf_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_df, etf_df, date_col))
                    logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(etf_df) - cached_count} 条 = 总计 {len(etf_df)} 条")
                except Exception as e:
                    logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
            
            # ========== 保存到缓存 ==========
            if _is_cache_enabled(config_for_cache) and period == "daily":
                try:
                    from src.data_cache import save_etf_daily_cache
                    save_etf_daily_cache(symbol, etf_df, config=config_for_cache)
                except Exception as e:
                    logger.debug(f"保存缓存失败（不影响主流程）: {e}")
            # ========== 缓存保存结束 ==========
            
            return etf_df
        else:
            logger.warning(f"Tushare主数据源返回空数据，将尝试备用方案: {symbol}")
            last_error = "Tushare返回空数据"
    except Exception as e:
        last_error = str(e)
        logger.warning(f"Tushare主数据源失败: {symbol}, 错误: {last_error}, 将尝试备用方案")
    
    # 方法2：使用新浪接口（备用数据源1）
    if last_error is None:
        last_error = "Tushare主数据源失败"
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.debug(f"重试获取ETF日线数据（备用方案1）: symbol={symbol}, 第{attempt+1}次尝试")
                # 增加重试延迟（指数退避）
                time.sleep(retry_delay * (2 ** (attempt - 1)))
            
            if attempt == 0:
                logger.warning(f"【方法2】使用备用方案 fund_etf_hist_sina（新浪接口）: {symbol}")
            logger.debug(f"获取ETF日线数据（新浪接口）: symbol={symbol}, period={period}, "
                        f"start_date={start_date}, end_date={end_date}")
            
            start_time = time.time()
            # 新浪接口需要 "sh" 或 "sz" 前缀
            sina_symbol = f"sh{symbol}" if symbol.startswith('51') else f"sz{symbol}"
            etf_df = ak.fund_etf_hist_sina(symbol=sina_symbol)
            duration = time.time() - start_time
            
            if etf_df is not None and not etf_df.empty:
                # 转换数据格式：新浪返回 date, open, high, low, close, volume
                # 需要转换为系统标准格式：日期, 开盘, 收盘, 最高, 最低, 成交量
                column_mapping = {
                    'date': '日期',
                    'open': '开盘',
                    'close': '收盘',
                    'high': '最高',
                    'low': '最低',
                    'volume': '成交量'
                }
                
                # 重命名列
                for old_col, new_col in column_mapping.items():
                    if old_col in etf_df.columns:
                        etf_df = etf_df.rename(columns={old_col: new_col})
                
                # 转换日期格式并筛选日期范围
                if '日期' in etf_df.columns:
                    # 转换日期为datetime
                    etf_df['日期'] = pd.to_datetime(etf_df['日期'])
                    start_dt = datetime.strptime(start_date, "%Y%m%d")
                    end_dt = datetime.strptime(end_date, "%Y%m%d")
                    
                    # 筛选日期范围
                    etf_df = etf_df[(etf_df['日期'] >= start_dt) & (etf_df['日期'] <= end_dt)]
                    
                    # 转换日期为字符串格式（YYYYMMDD）
                    etf_df['日期'] = etf_df['日期'].dt.strftime('%Y%m%d')
                
                # 添加成交额列（如果没有，设为0或计算）
                if '成交额' not in etf_df.columns:
                    if '成交量' in etf_df.columns and '收盘' in etf_df.columns:
                        # 新浪接口的volume单位是"手"，需要乘以100转换为股数，再乘以价格得到成交额
                        etf_df['成交额'] = etf_df['成交量'] * etf_df['收盘'] * 100
                    else:
                        etf_df['成交额'] = 0
                
                # 添加涨跌额和涨跌幅列（如果没有，计算）
                if '涨跌额' not in etf_df.columns:
                    if '收盘' in etf_df.columns:
                        etf_df['涨跌额'] = etf_df['收盘'].diff()
                    else:
                        etf_df['涨跌额'] = 0
                
                if '涨跌幅' not in etf_df.columns:
                    if '收盘' in etf_df.columns:
                        etf_df['涨跌幅'] = etf_df['收盘'].pct_change() * 100
                    else:
                        etf_df['涨跌幅'] = 0
                
                if not etf_df.empty:
                    log_function_result(logger, "fetch_etf_daily_em", 
                                      f"获取到{len(etf_df)}条数据（新浪接口）", duration)
                    
                    # ========== 合并部分缓存数据 ==========
                    if _is_cache_enabled(config_for_cache) and period == "daily" and cached_partial_df is not None:
                        try:
                            from src.data_cache import merge_cached_and_fetched_data
                            # 找到日期列
                            date_col = None
                            for col in ['日期', 'date', '日期时间', 'datetime']:
                                if col in etf_df.columns:
                                    date_col = col
                                    break
                            cached_count = len(cached_partial_df)
                            # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                            etf_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_df, etf_df, date_col))
                            logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(etf_df) - cached_count} 条 = 总计 {len(etf_df)} 条")
                        except Exception as e:
                            logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
                    
                    # ========== 保存到缓存 ==========
                    if _is_cache_enabled(config_for_cache) and period == "daily":
                        try:
                            from src.data_cache import save_etf_daily_cache
                            save_etf_daily_cache(symbol, etf_df, config=config_for_cache)
                        except Exception as e:
                            logger.debug(f"保存缓存失败（不影响主流程）: {e}")
                    # ========== 缓存保存结束 ==========
                    
                    return etf_df
                else:
                    logger.warning(f"新浪接口返回空数据或筛选后为空: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                    last_error = "新浪接口返回空数据或筛选后为空"
            else:
                logger.warning(f"新浪接口返回None: symbol={symbol}, period={period}, 尝试{attempt+1}/{max_retries}")
                last_error = "新浪接口返回None"
                
        except Exception as e:
            last_error = str(e)
            logger.warning(f"获取ETF日线数据失败（新浪接口）: symbol={symbol}, 尝试{attempt+1}/{max_retries}, 错误: {last_error}")
            if attempt < max_retries - 1:
                continue
            else:
                logger.warning(f"新浪接口所有重试均失败（{max_retries}次），将尝试备用方案2")
                logger.info("数据源回退顺序: 1) Tushare (已失败) -> 2) fund_etf_hist_sina (已失败) -> 3) fund_etf_hist_em")
                log_error_with_context(
                    logger, e,
                    {
                        'function': 'fetch_etf_daily_em',
                        'symbol': symbol,
                        'period': period,
                        'start_date': start_date,
                        'end_date': end_date,
                        'attempts': max_retries,
                        'data_source': 'sina'
                    },
                    f"获取ETF日线数据失败（新浪接口，已重试{max_retries}次）"
                )
                break
    
    # 方法3：如果新浪接口失败，尝试东方财富接口作为备用
    if last_error:
        try:
            logger.warning(f"【方法3】使用备用方案 fund_etf_hist_em（东方财富接口）: {symbol}")
            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        logger.debug(f"重试获取ETF日线数据（备用方案2）: symbol={symbol}, 第{attempt+1}次尝试")
                        time.sleep(retry_delay * (2 ** (attempt - 1)))
                    
                    logger.debug(f"获取ETF日线数据（东方财富接口）: symbol={symbol}, period={period}, "
                                f"start_date={start_date}, end_date={end_date}")
                    
                    start_time = time.time()
                    etf_df = ak.fund_etf_hist_em(
                        symbol=symbol,
                        period=period,
                        start_date=start_date,
                        end_date=end_date
                    )
                    duration = time.time() - start_time
                    
                    if etf_df is not None and not etf_df.empty:
                        log_function_result(logger, "fetch_etf_daily_em", 
                                          f"获取到{len(etf_df)}条数据（东方财富接口）", duration)
                        
                        # ========== 合并部分缓存数据 ==========
                        if _is_cache_enabled(config_for_cache) and period == "daily" and cached_partial_df is not None:
                            try:
                                from src.data_cache import merge_cached_and_fetched_data
                                date_col = None
                                for col in ['日期', 'date', '日期时间', 'datetime']:
                                    if col in etf_df.columns:
                                        date_col = col
                                        break
                                cached_count = len(cached_partial_df)
                                # mypy：merge_cached_and_fetched_data 返回值类型较宽，这里明确为 DataFrame
                                etf_df = cast(pd.DataFrame, merge_cached_and_fetched_data(cached_partial_df, etf_df, date_col))
                                logger.info(f"合并缓存数据: 缓存 {cached_count} 条 + 新增 {len(etf_df) - cached_count} 条 = 总计 {len(etf_df)} 条")
                            except Exception as e:
                                logger.debug(f"合并缓存数据失败（不影响主流程）: {e}")
                        
                        # ========== 保存到缓存 ==========
                        if _is_cache_enabled(config_for_cache) and period == "daily":
                            try:
                                from src.data_cache import save_etf_daily_cache
                                save_etf_daily_cache(symbol, etf_df, config=config_for_cache)
                            except Exception as e:
                                logger.debug(f"保存缓存失败（不影响主流程）: {e}")
                        # ========== 缓存保存结束 ==========
                        
                        return etf_df
                    else:
                        if attempt < max_retries - 1:
                            continue
                except Exception as e:
                    if attempt < max_retries - 1:
                        continue
                    else:
                        logger.debug(f"东方财富接口也失败: {e}")
        except Exception as e:
            logger.debug(f"东方财富接口备用方案失败: {e}")
    
    logger.warning(f"获取ETF日线数据最终失败: symbol={symbol}, 原因: {last_error}")
    
    # 如果部分缓存命中，即使API失败也返回缓存数据
    if cached_partial_df is not None and not cached_partial_df.empty:
        logger.warning(f"API获取失败，但存在部分缓存数据，返回缓存数据: {symbol}, {len(cached_partial_df)} 条")
        return cached_partial_df
    
    return None


def get_etf_current_price(symbol: str = "510300") -> Optional[float]:
    """
    获取ETF当前价格
    
    Args:
        symbol: ETF代码（如 "510300"）
    
    Returns:
        float: ETF当前价格，如果失败返回None
    """
    try:
        clean_code = str(symbol).strip()
        if not clean_code:
            return None
        # 统一转成不带交易所前缀的 6 位数字（用于向下游取数）
        if clean_code.upper().endswith((".SH", ".SZ")):
            clean_code = clean_code.split(".")[0]
        if clean_code.lower().startswith(("sh", "sz")) and len(clean_code) > 2:
            clean_code = clean_code[2:]

        # 0) 优先实时通道：mootdx/TDX -> fetch_stock_realtime
        try:
            from plugins.data_collection.stock.fetch_realtime import fetch_stock_realtime

            rt = fetch_stock_realtime(stock_code=clean_code, mode="production", include_depth=False)
            if isinstance(rt, dict) and rt.get("success") and rt.get("data"):
                d = rt["data"][0] if isinstance(rt["data"], list) else rt["data"]
                cp = d.get("current_price") or 0.0
                cp = float(cp) if cp is not None else 0.0
                if cp > 0:
                    return cp
        except Exception:
            pass

        # 1) ETF 基金实时行情（同花顺）：fund_etf_spot_ths
        try:
            try:
                from src.realtime_full_fetch_cache import get_or_fetch
            except Exception:
                get_or_fetch = None

            if get_or_fetch is None:
                all_etf_df = ak.fund_etf_spot_ths(date="")
            else:
                all_etf_df = get_or_fetch("fund_etf_spot_ths:date=", lambda: ak.fund_etf_spot_ths(date=""))
            if all_etf_df is not None and not all_etf_df.empty:
                code_col = None
                for col in ["基金代码", "代码", "code", "symbol"]:
                    if col in all_etf_df.columns:
                        code_col = col
                        break

                if code_col:
                    target = all_etf_df[all_etf_df[code_col].astype(str) == str(clean_code)]
                    if not target.empty:
                        row = target.iloc[0]

                        def _try_get_price(*cols: str) -> float:
                            for c in cols:
                                if c in row.index:
                                    try:
                                        v = float(row[c])
                                        if v > 0:
                                            return v
                                    except (TypeError, ValueError):
                                        continue
                            return 0.0

                        price_value = _try_get_price(
                            "最新价", "最新", "现价", "当前价", "current_price", "close", "price"
                        )
                        if price_value > 0:
                            return price_value
        except Exception:
            pass

        # 1.5) ETF 基金实时行情（新浪全量分类列表）：fund_etf_category_sina
        try:
            try:
                from src.realtime_full_fetch_cache import get_or_fetch
            except Exception:
                get_or_fetch = None

            if get_or_fetch is None:
                cat_df = ak.fund_etf_category_sina(symbol="ETF基金")
            else:
                cat_df = get_or_fetch(
                    "fund_etf_category_sina:ETF基金",
                    lambda: ak.fund_etf_category_sina(symbol="ETF基金"),
                )

            if cat_df is not None and not cat_df.empty:
                code_col = None
                for col in ["代码", "code", "symbol"]:
                    if col in cat_df.columns:
                        code_col = col
                        break
                if code_col:
                    codes_norm = cat_df[code_col].astype(str).str.replace(r"^(sh|sz)", "", regex=True).str.strip()
                    target = cat_df[codes_norm == str(clean_code)]
                    if not target.empty:
                        row = target.iloc[0]
                        price_value = 0.0
                        for c in ["最新价", "最新", "current_price", "close", "price"]:
                            if c in target.columns:
                                try:
                                    v = float(row[c])
                                    if v > 0:
                                        price_value = v
                                        break
                                except Exception:
                                    continue
                        if price_value > 0:
                            return price_value
        except Exception:
            pass

        # 2) 分时数据（新浪）：stock_zh_a_minute，period=1 取最后 close
        try:
            etf_symbol = f"sz{clean_code}" if str(clean_code).startswith("159") else f"sh{clean_code}"
            minute_df = ak.stock_zh_a_minute(symbol=etf_symbol, period="1", adjust="qfq")
            if minute_df is not None and not minute_df.empty and "close" in minute_df.columns:
                minute_df = minute_df.reset_index(drop=True)
                cp = float(minute_df["close"].iloc[-1])
                if cp > 0:
                    return cp
        except Exception:
            pass

        logger.warning(f"无法获取ETF当前价格: {symbol}")
        return None
    except Exception as e:
        logger.warning(f"获取ETF当前价格失败: {symbol}, 错误: {e}")
        return None


def get_index_current_price(symbol: str = "000300") -> Optional[float]:
    """
    获取指数当前价格（尽量实时）

    优先使用东方财富指数行情接口（ak.stock_zh_index_spot_em），失败后使用新浪备用接口（ak.stock_zh_index_spot_sina）。
    """
    try:
        # 方法1：东方财富指数现货
        try:
            symbols_to_try = ["沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数"]
            all_df = None
            # 将“异常抓取”封装到函数里，避免 try/except 里直接 continue/pass
            # Bandit 会对 try/except/pass/continue 给出较高噪声，这里做结构性规避。
            def _safe_fetch_em(symbol_name: str) -> Optional[pd.DataFrame]:
                try:
                    return ak.stock_zh_index_spot_em(symbol=symbol_name)
                except Exception as e:
                    logger.debug(
                        f"东方财富指数现货获取失败: {symbol_name}, 错误: {e}",
                        exc_info=True,
                    )
                    return None

            for sym in symbols_to_try:
                df = _safe_fetch_em(sym)
                if df is not None and not df.empty:
                    all_df = df if all_df is None else pd.concat([all_df, df], ignore_index=True)

            if all_df is not None and not all_df.empty:
                code_col = None
                for col in ['代码', 'code', 'symbol']:
                    if col in all_df.columns:
                        code_col = col
                        break
                if code_col:
                    row = all_df[all_df[code_col].astype(str).str.contains(str(symbol), na=False)]
                    if not row.empty:
                        r = row.iloc[0]
                        # 常见现价列名
                        for price_col in ['最新价', '最新', '现价', '当前价', '成交价', 'price', 'last']:
                            if price_col in r.index:
                                try:
                                    v = float(r[price_col])
                                    if v > 0:
                                        logger.debug(f"获取指数当前价格（东方财富）: {symbol} -> {v}")
                                        return v
                                except (ValueError, TypeError):
                                    pass

                        # 兜底：从包含“价”的列中选第一个可解析数值
                        for c in list(all_df.columns):
                            if '价' in str(c):
                                try:
                                    v = float(r[c])
                                    if v > 0:
                                        logger.debug(f"获取指数当前价格（东方财富兜底）: {symbol} -> {v} (列: {c})")
                                        return v
                                except (ValueError, TypeError):
                                    continue
        except Exception as e:
            logger.debug(f"获取指数当前价格（东方财富）失败: {symbol}, 错误: {e}", exc_info=True)

        # 方法2：新浪指数现货（备用）
        try:
            df = ak.stock_zh_index_spot_sina()
            if df is not None and not df.empty:
                code_col = None
                for col in ['代码', 'code', 'symbol']:
                    if col in df.columns:
                        code_col = col
                        break
                if code_col:
                    # 新浪可能返回 sh000300 / sz399006 等
                    code = str(symbol)
                    possible = []
                    if code.startswith("399"):
                        possible = [f"sz{code}", code]
                    else:
                        possible = [f"sh{code}", code]

                    r = None
                    for p in possible:
                        row = df[df[code_col].astype(str).str.contains(p, na=False)]
                        if not row.empty:
                            r = row.iloc[0]
                            break
                    if r is not None:
                        for price_col in ['最新价', '现价', '当前价', 'price', 'last']:
                            if price_col in r.index:
                                try:
                                    v = float(r[price_col])
                                    if v > 0:
                                        logger.debug(f"获取指数当前价格（新浪）: {symbol} -> {v}")
                                        return v
                                except (ValueError, TypeError):
                                    pass
                        for c in list(df.columns):
                            if '价' in str(c):
                                try:
                                    v = float(r[c])
                                    if v > 0:
                                        logger.debug(f"获取指数当前价格（新浪兜底）: {symbol} -> {v} (列: {c})")
                                        return v
                                except (ValueError, TypeError):
                                    continue
        except Exception as e:
            logger.debug(f"获取指数当前价格（新浪）失败: {symbol}, 错误: {e}", exc_info=True)

        logger.warning(f"无法获取指数实时价格: {symbol}")
        return None
    except Exception as e:
        logger.warning(f"获取指数当前价格失败: {symbol}, 错误: {e}")
        return None


def get_option_current_price(contract_code: str) -> Optional[float]:
    """
    获取期权当前价格
    
    Args:
        contract_code: 期权合约代码
    
    Returns:
        float: 期权当前价格，如果失败返回None
    """
    try:
        spot_df = fetch_option_spot_sina(contract_code)
        if spot_df is None or spot_df.empty:
            logger.warning(f"无法获取期权实时数据: {contract_code}")
            return None
        
        # 从DataFrame中提取当前价格
        # AKShare返回格式：字段/值
        if '字段' in spot_df.columns and '值' in spot_df.columns:
            for idx, row in spot_df.iterrows():
                field = str(row.get('字段', '')).strip()
                value = row.get('值', '')
                
                # 查找价格相关字段
                if any(keyword in field for keyword in ['最新价', '当前价', '现价', '价格', 'last_price', 'current_price', 'price']):
                    try:
                        price = float(value)
                        if price > 0:
                            logger.debug(f"获取期权当前价格: {contract_code} -> {price}")
                            return price
                    except (ValueError, TypeError):
                        continue
        
        # 如果找不到价格字段，尝试从值列获取
        logger.warning(f"无法从期权数据中提取价格: {contract_code}")
        return None
        
    except Exception as e:
        logger.warning(f"获取期权当前价格失败: {contract_code}, 错误: {e}")
        return None


def fetch_index_opening_data(
    index_codes: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    retry_delay: float = 2.0
) -> Dict[str, Dict[str, Any]]:
    """
    获取主要指数的开盘数据（9:28集合竞价数据）
    
    Args:
        index_codes: 指数代码字典，格式 {"指数名称": "代码"}，如果为None则使用默认配置
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
    
    Returns:
        dict: 格式 {
            "上证": {
                "open_price": 4116.94,
                "close_yesterday": 4113.65,
                "change_pct": 0.08,
                "volume": 12345678,
                "code": "000001"
            },
            ...
        }
    """
    log_function_call(logger, "fetch_index_opening_data", 
                     index_codes=index_codes, max_retries=max_retries)
    
    # 默认指数代码
    if index_codes is None:
        index_codes = {
            "上证": "000001",
            "创业板": "399006",
            "深成指": "399001",
            "科创综指": "000688",
            "沪深300": "000300",
            "北证50": "899050"
        }
    
    opening_data = {}
    last_error = None
    
    # 方法1：尝试使用 stock_zh_index_spot_em（东方财富接口）
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.debug(f"重试获取指数开盘数据: 第{attempt+1}次尝试")
                time.sleep(retry_delay)
            
            start_time = time.time()
            
            # 尝试多个symbol参数，因为不同指数可能在不同分类中
            symbols_to_try = ["沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数"]
            all_data = None
            
            for symbol in symbols_to_try:
                try:
                    df = ak.stock_zh_index_spot_em(symbol=symbol)
                    if df is not None and not df.empty:
                        if all_data is None:
                            all_data = df
                        else:
                            all_data = pd.concat([all_data, df], ignore_index=True)
                except Exception as e:
                    logger.debug(f"尝试symbol={symbol}失败: {e}")
                    continue
            
            duration = time.time() - start_time
            
            if all_data is not None and not all_data.empty:
                # 提取目标指数的数据
                for name, code in index_codes.items():
                    # 尝试匹配代码列（可能是"代码"或"代码"列）
                    code_col = None
                    for col in ['代码', 'code', 'symbol']:
                        if col in all_data.columns:
                            code_col = col
                            break
                    
                    if code_col is None:
                        logger.warning(f"无法找到代码列，可用列: {list(all_data.columns)}")
                        continue
                    
                    # 查找匹配的指数
                    row = all_data[all_data[code_col].astype(str).str.contains(code, na=False)]
                    if not row.empty:
                        row = row.iloc[0]
                        
                        # 提取字段（尝试多种可能的列名）
                        open_price = None
                        close_yesterday = None
                        change_pct = None
                        volume = None
                        
                        # 今开
                        for col in ['今开', 'open', '开盘', 'open_price']:
                            if col in row.index:
                                try:
                                    open_price = float(row[col])
                                    break
                                except (ValueError, TypeError):
                                    continue
                        
                        # 昨收
                        for col in ['昨收', 'close', 'close_yesterday', 'pre_close']:
                            if col in row.index:
                                try:
                                    close_yesterday = float(row[col])
                                    break
                                except (ValueError, TypeError):
                                    continue
                        
                        # 涨跌幅
                        for col in ['涨跌幅', 'pct_chg', 'change_pct', '涨跌%']:
                            if col in row.index:
                                try:
                                    change_pct = float(row[col])
                                    break
                                except (ValueError, TypeError):
                                    continue
                        
                        # 成交量
                        for col in ['成交量', 'volume', 'vol', '成交']:
                            if col in row.index:
                                try:
                                    volume = float(row[col])
                                    break
                                except (ValueError, TypeError):
                                    continue
                        
                        # 如果获取到关键数据，保存
                        if open_price is not None or close_yesterday is not None:
                            opening_data[name] = {
                                "open_price": open_price,
                                "close_yesterday": close_yesterday,
                                "change_pct": change_pct,
                                "volume": volume,
                                "code": code
                            }
                            logger.debug(f"成功获取{name}({code})开盘数据: 开盘={open_price}, 昨收={close_yesterday}, 涨幅={change_pct}%")
                
                if opening_data:
                    log_function_result(logger, "fetch_index_opening_data", 
                                      f"成功获取{len(opening_data)}个指数数据", duration)
                    return opening_data
                else:
                    logger.warning(f"未找到任何目标指数的数据，尝试{attempt+1}/{max_retries}")
                    last_error = "未找到目标指数数据"
            
        except Exception as e:
            last_error = str(e)
            logger.warning(f"获取指数开盘数据失败: 尝试{attempt+1}/{max_retries}, 错误: {last_error}")
            if attempt < max_retries - 1:
                continue
    
    # 方法2：尝试使用 stock_zh_index_spot_sina（新浪接口，备用）
    if not opening_data:
        try:
            logger.debug("尝试使用新浪接口获取指数开盘数据")
            start_time = time.time()
            df = ak.stock_zh_index_spot_sina()
            duration = time.time() - start_time
            
            if df is not None and not df.empty:
                # 新浪接口返回的代码格式可能是 "sh000001" 或 "sz399006"
                for name, code in index_codes.items():
                    # 构建可能的代码格式
                    if code.startswith("000") or code.startswith("899"):
                        possible_codes = [f"sh{code}", code]
                    elif code.startswith("399"):
                        possible_codes = [f"sz{code}", code]
                    else:
                        possible_codes = [code]
                    
                    # 查找匹配的指数
                    code_col = None
                    for col in ['代码', 'code', 'symbol']:
                        if col in df.columns:
                            code_col = col
                            break
                    
                    if code_col is None:
                        continue
                    
                    for possible_code in possible_codes:
                        row = df[df[code_col].astype(str).str.contains(possible_code, na=False)]
                        if not row.empty:
                            row = row.iloc[0]
                            
                            # 提取字段
                            open_price = None
                            close_yesterday = None
                            change_pct = None
                            volume = None
                            
                            # 今开
                            for col in ['今开', 'open', '开盘']:
                                if col in row.index:
                                    try:
                                        open_price = float(row[col])
                                        break
                                    except (ValueError, TypeError):
                                        continue
                            
                            # 昨收
                            for col in ['昨收', 'close', 'pre_close']:
                                if col in row.index:
                                    try:
                                        close_yesterday = float(row[col])
                                        break
                                    except (ValueError, TypeError):
                                        continue
                            
                            # 涨跌幅
                            for col in ['涨跌幅', 'pct_chg', 'change_pct']:
                                if col in row.index:
                                    try:
                                        change_pct = float(row[col])
                                        break
                                    except (ValueError, TypeError):
                                        continue
                            
                            # 成交量
                            for col in ['成交量', 'volume', 'vol']:
                                if col in row.index:
                                    try:
                                        volume = float(row[col])
                                        break
                                    except (ValueError, TypeError):
                                        continue
                            
                            if open_price is not None or close_yesterday is not None:
                                opening_data[name] = {
                                    "open_price": open_price,
                                    "close_yesterday": close_yesterday,
                                    "change_pct": change_pct,
                                    "volume": volume,
                                    "code": code
                                }
                                logger.debug(f"成功获取{name}({code})开盘数据（新浪接口）")
                            break
                
                if opening_data:
                    log_function_result(logger, "fetch_index_opening_data", 
                                      f"成功获取{len(opening_data)}个指数数据（新浪接口）", duration)
                    return opening_data
        
        except Exception as e:
            logger.warning(f"新浪接口也失败: {e}")
    
    # 如果都失败，记录错误
    if not opening_data:
        log_error_with_context(
            logger, Exception(last_error or "所有接口都失败"),
            {
                'function': 'fetch_index_opening_data',
                'index_codes': index_codes,
                'attempts': max_retries
            },
            f"获取指数开盘数据失败（已重试{max_retries}次）"
        )
        logger.warning(f"获取指数开盘数据最终失败: {last_error}")
    
    return opening_data


def fetch_index_opening_history(
    index_code: str,
    lookback_days: int = 5
) -> Optional[pd.DataFrame]:
    """
    获取指数的历史开盘数据（用于计算均值）
    
    Args:
        index_code: 指数代码
        lookback_days: 回看天数（默认5天，实际会获取更多天数以确保有足够的交易日）
    
    Returns:
        DataFrame: 包含日期、开盘价、昨收、涨跌幅、成交量等
    """
    log_function_call(logger, "fetch_index_opening_history", 
                     index_code=index_code, lookback_days=lookback_days)
    
    try:
        # 计算日期范围（回看更多天数以确保有足够的交易日）
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        end_date = now.strftime("%Y%m%d")
        start_date = (now - timedelta(days=lookback_days * 2)).strftime("%Y%m%d")
        
        # 使用现有的fetch_index_daily_em函数获取日线数据
        daily_df = fetch_index_daily_em(
            symbol=index_code,
            period="daily",
            start_date=start_date,
            end_date=end_date
        )
        
        if daily_df is None or daily_df.empty:
            logger.warning(f"无法获取{index_code}的历史日线数据")
            return None
        
        # 提取最近lookback_days个交易日的数据
        # 确保有足够的交易日数据
        if len(daily_df) >= lookback_days:
            history_df = daily_df.tail(lookback_days).copy()
        else:
            history_df = daily_df.copy()
            logger.warning(f"{index_code}历史数据不足{lookback_days}天，只有{len(daily_df)}天")
        
        # 计算开盘涨跌幅（如果数据中有昨收和开盘）
        if '开盘' in history_df.columns and '昨收' in history_df.columns:
            history_df['开盘涨跌幅'] = (
                (history_df['开盘'] - history_df['昨收']) / history_df['昨收'] * 100
            )
        elif 'open' in history_df.columns and 'close' in history_df.columns:
            # 如果列名是英文，需要计算前一天的收盘价作为昨收
            history_df['开盘涨跌幅'] = history_df['open'].pct_change() * 100
        
        log_function_result(logger, "fetch_index_opening_history", 
                          f"获取到{len(history_df)}条历史数据", 0)
        return history_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'fetch_index_opening_history',
                'index_code': index_code,
                'lookback_days': lookback_days
            },
            "获取指数历史开盘数据失败"
        )
        return None
