"""
数据缓存模块
缓存历史交易日数据，减少网络请求，提高系统稳定性
"""

import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from src.logger_config import get_module_logger, log_error_with_context
from src.config_loader import load_system_config, get_data_storage_config
from src.system_status import is_trading_day

logger = get_module_logger(__name__)


def _df_drop_duplicate_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    去掉重复列名，仅保留每个名称第一次出现（常见于多源日线 merge 后出现重复「成交量」）。
    """
    if df is None or getattr(df, "empty", True):
        return df
    if not df.columns.duplicated().any():
        return df
    return df.loc[:, ~df.columns.duplicated()].copy()


def get_holidays(config: Optional[Dict] = None) -> set:
    """
    获取节假日集合（从配置文件读取）
    
    Args:
        config: 系统配置，如果为None则自动加载
    
    Returns:
        set: 节假日日期集合（格式：YYYYMMDD字符串）
    """
    if config is None:
        config = load_system_config()
    
    from src.config_loader import get_holidays_config
    return get_holidays_config(config)


def get_cache_dir(config: Optional[Dict] = None) -> Path:
    """
    获取缓存目录路径
    
    Args:
        config: 系统配置
    
    Returns:
        Path: 缓存目录路径
    """
    if config is None:
        config = load_system_config()
    
    storage_config = get_data_storage_config(config)
    data_dir = storage_config.get('data_dir', 'data')
    
    cache_dir = Path(data_dir) / 'cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    return cache_dir


def _is_cache_enabled(config: Optional[Dict] = None) -> bool:
    """
    是否启用本地 parquet 缓存（与 data_collector 口径一致）。

    ``plugins/data_collection/futures/fetch_a50`` 等模块在启动时从本模块导入此符号；
    若缺失会导致 CACHE_AVAILABLE=False，期货日线无法落盘。
    """
    from src.data_collector import _is_cache_enabled as _dc_cache_enabled

    return _dc_cache_enabled(config)


def get_cache_file_path(
    data_type: str,
    symbol: str,
    date: str,
    period: Optional[str] = None,
    config: Optional[Dict] = None
) -> Path:
    """
    获取缓存文件路径
    
    Args:
        data_type: 数据类型（'index_daily', 'index_minute', 'etf_daily', 'etf_minute',
            'global_index_daily', 'stock_daily', 'stock_minute', 'option_minute', 'option_greeks'）
        symbol: 指数/ETF/期权代码（如 '000300', '510300', 或期权合约代码，可以是字符串或整数）
        date: 日期字符串（格式：YYYYMMDD）
        period: 周期（仅用于分钟数据，如 '5', '15', '30'）
        config: 系统配置
    
    Returns:
        Path: 缓存文件路径
    """
    # 确保 symbol 是字符串类型，用于路径拼接
    symbol = str(symbol)
    cache_dir = get_cache_dir(config)
    
    if data_type == 'index_daily':
        file_path = cache_dir / 'index_daily' / symbol / f"{date}.parquet"
    elif data_type == 'index_minute':
        if period:
            file_path = cache_dir / 'index_minute' / symbol / period / f"{date}.parquet"
        else:
            file_path = cache_dir / 'index_minute' / symbol / f"{date}.parquet"
    elif data_type == 'etf_daily':
        file_path = cache_dir / 'etf_daily' / symbol / f"{date}.parquet"
    elif data_type == 'etf_minute':
        if period:
            file_path = cache_dir / 'etf_minute' / symbol / period / f"{date}.parquet"
        else:
            file_path = cache_dir / 'etf_minute' / symbol / f"{date}.parquet"
    elif data_type == 'stock_daily':
        file_path = cache_dir / 'stock_daily' / symbol / f"{date}.parquet"
    elif data_type == 'global_index_daily':
        # 外盘指数日线切片（normalized 代码作目录名，如 IXIC、N225）
        file_path = cache_dir / 'global_index_daily' / symbol / f"{date}.parquet"
    elif data_type == 'stock_minute':
        if period:
            file_path = cache_dir / 'stock_minute' / symbol / period / f"{date}.parquet"
        else:
            file_path = cache_dir / 'stock_minute' / symbol / f"{date}.parquet"
    elif data_type == 'option_minute':
        if period:
            file_path = cache_dir / 'option_minute' / symbol / period / f"{date}.parquet"
        else:
            file_path = cache_dir / 'option_minute' / symbol / f"{date}.parquet"
    elif data_type == 'option_greeks':
        file_path = cache_dir / 'option_greeks' / symbol / f"{date}.parquet"
    else:
        raise ValueError(f"不支持的数据类型: {data_type}")
    
    # 创建目录
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    return file_path


def load_cached_data(file_path: Path) -> Optional[pd.DataFrame]:
    """
    加载缓存的DataFrame数据
    
    如果读取失败，会尝试删除损坏文件并返回None，供调用方重新拉取数据。
    
    Args:
        file_path: 缓存文件路径
    
    Returns:
        pd.DataFrame: 缓存的数据，如果失败返回None
    """
    try:
        if not file_path.exists():
            return None
        
        df = pd.read_parquet(file_path)
        
        if df is None or df.empty:
            logger.warning(f"缓存文件为空: {file_path}")
            return None
        
        logger.debug(f"从缓存加载数据: {file_path}, {len(df)} 条")
        return df
        
    except Exception as e:
        # 读缓存失败时，认为该文件可能已损坏，尝试删除以便后续重建
        logger.warning(f"加载缓存失败: {file_path}, 错误: {e}，将尝试删除该缓存文件以便重建")
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"已删除损坏的缓存文件: {file_path}")
        except Exception as delete_error:
            logger.warning(f"删除损坏缓存文件失败: {file_path}, 错误: {delete_error}")
        return None


def save_cached_data(df: pd.DataFrame, file_path: Path) -> bool:
    """
    保存DataFrame数据到缓存
    
    Args:
        df: 要保存的DataFrame
        file_path: 缓存文件路径
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            logger.warning(f"数据为空，不保存缓存: {file_path}")
            return False

        # pyarrow/pandas parquet writer 要求列名唯一；部分数据源在 merge/rename 后可能产生重复列名
        # 这里做一次“可逆”的去重：保留所有列，仅对重复列名追加后缀，避免直接丢列。
        if df.columns.duplicated().any():
            cols = [str(c) for c in df.columns.tolist()]
            seen: Dict[str, int] = {}
            new_cols: List[str] = []
            for c in cols:
                if c not in seen:
                    seen[c] = 0
                    new_cols.append(c)
                else:
                    seen[c] += 1
                    new_cols.append(f"{c}__dup{seen[c]}")
            df = df.copy()
            df.columns = new_cols
            logger.warning(
                f"检测到重复列名，已自动重命名以便写入 parquet: {file_path} | "
                f"dup_cols={sorted({c for c in cols if cols.count(c) > 1})}"
            )
        
        # 确保目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存为Parquet格式
        df.to_parquet(file_path, index=False, compression='snappy')
        
        logger.debug(f"数据已保存到缓存: {file_path}, {len(df)} 条")
        return True
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_cached_data', 'file_path': str(file_path)},
            "保存缓存失败"
        )
        return False


def parse_date_range(start_date: str, end_date: str) -> List[str]:
    """
    解析日期范围，返回所有日期列表（包括非交易日）
    
    Args:
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
    
    Returns:
        List[str]: 日期列表
    """
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    
    return dates


def get_cached_index_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    获取缓存的指数日线数据
    
    Args:
        symbol: 指数代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        Tuple[Optional[pd.DataFrame], List[str]]: 
            - 缓存的数据（如果全部命中）或None（如果部分命中或未命中）
            - 缺失的日期列表
    """
    try:
        if config is None:
            config = load_system_config(use_cache=True)
        dates = parse_date_range(start_date, end_date)
        cached_dfs = []
        missing_dates = []
        date_col = None
        
        for date in dates:
            # 只检查交易日，跳过非交易日（周末、节假日）
            date_obj = datetime.strptime(date, "%Y%m%d")
            if not is_trading_day(date_obj, config):
                continue  # 跳过非交易日（is_trading_day已处理周末和节假日）
            
            cache_path = get_cache_file_path('index_daily', symbol, date, config=config)
            cached_df = load_cached_data(cache_path)
            
            if cached_df is not None and not cached_df.empty:
                # 找到日期列
                if date_col is None:
                    for col in ['日期', 'date', '日期时间', 'datetime']:
                        if col in cached_df.columns:
                            date_col = col
                            break
                
                if date_col:
                    # 转换为datetime并过滤
                    # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
                    if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                        cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce', )
                    date_filtered = cached_df[
                        cached_df[date_col].dt.strftime('%Y%m%d') == date
                    ]
                    if not date_filtered.empty:
                        cached_dfs.append(date_filtered)
                        continue
                else:
                    # 没有日期列，假设整个文件都是该日期的数据（日线数据通常只有一条）
                    cached_dfs.append(cached_df)
                    continue
            
            missing_dates.append(date)
        
        if not cached_dfs:
            # 完全没有缓存
            return None, missing_dates
        
        if missing_dates:
            # 部分命中：返回可用数据与缺失列表，供上层决定是否补拉或降级使用
            partial_df = pd.concat(cached_dfs, ignore_index=True)
            if date_col:
                partial_df = partial_df.sort_values(by=date_col)
            logger.info(
                f"指数日线缓存部分命中: {symbol}, {start_date}~{end_date}, "
                f"已缓存 {len(partial_df)} 条, 缺失 {len(missing_dates)} 个交易日"
            )
            return partial_df, missing_dates
        
        # 全部缓存命中，合并数据
        result_df = pd.concat(cached_dfs, ignore_index=True)
        if date_col:
            result_df = result_df.sort_values(by=date_col)
        else:
            result_df = result_df.sort_values(by=result_df.columns[0])
        
        logger.info(f"指数日线数据缓存全部命中: {symbol}, {start_date}~{end_date}, {len(result_df)} 条")
        return result_df, []
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_index_daily',
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date
            },
            "获取缓存数据失败"
        )
        # 异常情况下，返回所有交易日（而不是所有日期）
        all_dates = parse_date_range(start_date, end_date)
        trading_dates = [date for date in all_dates if is_trading_day(datetime.strptime(date, "%Y%m%d"), config)]
        return None, trading_dates


def get_cached_etf_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    获取缓存的ETF日线数据
    
    Args:
        symbol: ETF代码（如 "510300"）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        Tuple[Optional[pd.DataFrame], List[str]]: 
            - 缓存的数据（如果全部命中）或None（如果部分命中或未命中）
            - 缺失的日期列表
    """
    try:
        if config is None:
            config = load_system_config(use_cache=True)
        dates = parse_date_range(start_date, end_date)
        cached_dfs = []
        missing_dates = []
        date_col = None
        
        for date in dates:
            # 只检查交易日，跳过非交易日（周末、节假日）
            date_obj = datetime.strptime(date, "%Y%m%d")
            if not is_trading_day(date_obj, config):
                continue  # 跳过非交易日（is_trading_day已处理周末和节假日）
            
            cache_path = get_cache_file_path('etf_daily', symbol, date, config=config)
            cached_df = load_cached_data(cache_path)
            
            if cached_df is not None and not cached_df.empty:
                # 找到日期列
                if date_col is None:
                    for col in ['日期', 'date', '日期时间', 'datetime']:
                        if col in cached_df.columns:
                            date_col = col
                            break
                
                if date_col:
                    # 转换为datetime并过滤
                    # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
                    if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                        cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce', )
                    date_filtered = cached_df[
                        cached_df[date_col].dt.strftime('%Y%m%d') == date
                    ]
                    if not date_filtered.empty:
                        cached_dfs.append(date_filtered)
                        continue
                else:
                    # 没有日期列，假设整个文件都是该日期的数据（日线数据通常只有一条）
                    cached_dfs.append(cached_df)
                    continue
            
            missing_dates.append(date)
        
        if not cached_dfs:
            # 完全没有缓存
            return None, missing_dates
        
        if missing_dates:
            # 部分命中：返回可用数据与缺失列表，供上层决定是否补拉或降级使用
            partial_df = pd.concat(cached_dfs, ignore_index=True)
            if date_col:
                partial_df = partial_df.sort_values(by=date_col)
            logger.info(
                f"ETF日线缓存部分命中: {symbol}, {start_date}~{end_date}, "
                f"已缓存 {len(partial_df)} 条, 缺失 {len(missing_dates)} 个交易日"
            )
            return partial_df, missing_dates
        
        # 全部缓存命中，合并数据
        result_df = pd.concat(cached_dfs, ignore_index=True)
        if date_col:
            result_df = result_df.sort_values(by=date_col)
        else:
            result_df = result_df.sort_values(by=result_df.columns[0])
        
        logger.info(f"ETF日线数据缓存全部命中: {symbol}, {start_date}~{end_date}, {len(result_df)} 条")
        return result_df, []
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_etf_daily',
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date
            },
            "获取缓存数据失败"
        )
        # 异常情况下，返回所有交易日（而不是所有日期）
        all_dates = parse_date_range(start_date, end_date)
        trading_dates = [date for date in all_dates if is_trading_day(datetime.strptime(date, "%Y%m%d"), config)]
        return None, trading_dates


def get_cached_stock_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    获取缓存的股票日线数据

    Args:
        symbol: 股票代码（如 "600000"）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        config: 系统配置

    Returns:
        Tuple[Optional[pd.DataFrame], List[str]]:
            - 缓存的数据（如果全部命中）或None（如果部分命中或未命中）
            - 缺失的日期列表
    """
    try:
        if config is None:
            config = load_system_config(use_cache=True)
        dates = parse_date_range(start_date, end_date)
        cached_dfs: List[pd.DataFrame] = []
        missing_dates: List[str] = []
        date_col: Optional[str] = None

        for date in dates:
            date_obj = datetime.strptime(date, "%Y%m%d")
            if not is_trading_day(date_obj, config):
                continue

            cache_path = get_cache_file_path('stock_daily', symbol, date, config=config)
            cached_df = load_cached_data(cache_path)

            if cached_df is not None and not cached_df.empty:
                if date_col is None:
                    for col in ['日期', 'date', '日期时间', 'datetime']:
                        if col in cached_df.columns:
                            date_col = col
                            break

                if date_col:
                    if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                        cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
                    date_filtered = cached_df[cached_df[date_col].dt.strftime('%Y%m%d') == date]
                    if not date_filtered.empty:
                        cached_dfs.append(date_filtered)
                        continue
                else:
                    cached_dfs.append(cached_df)
                    continue

            missing_dates.append(date)

        if not cached_dfs:
            return None, missing_dates

        if missing_dates:
            partial_df = pd.concat(cached_dfs, ignore_index=True)
            if date_col:
                partial_df = partial_df.sort_values(by=date_col)
            logger.info(
                f"股票日线缓存部分命中: {symbol}, {start_date}~{end_date}, "
                f"已缓存 {len(partial_df)} 条, 缺失 {len(missing_dates)} 个交易日"
            )
            return partial_df, missing_dates

        result_df = pd.concat(cached_dfs, ignore_index=True)
        if date_col:
            result_df = result_df.sort_values(by=date_col)
        else:
            result_df = result_df.sort_values(by=result_df.columns[0])

        logger.info(f"股票日线数据缓存全部命中: {symbol}, {start_date}~{end_date}, {len(result_df)} 条")
        return result_df, []

    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_stock_daily',
                'symbol': symbol,
                'start_date': start_date,
                'end_date': end_date
            },
            "获取缓存数据失败"
        )
        all_dates = parse_date_range(start_date, end_date)
        trading_dates = [date for date in all_dates if is_trading_day(datetime.strptime(date, "%Y%m%d"), config)]
        return None, trading_dates


def save_etf_daily_cache(
    symbol: str,
    df: pd.DataFrame,
    config: Optional[Dict] = None
) -> bool:
    """
    保存ETF日线数据到缓存（按日期拆分保存）
    
    Args:
        symbol: ETF代码
        df: 日线数据DataFrame
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            return False
        
        # 找到日期列
        date_col = None
        for col in ['日期', 'date', '日期时间', 'datetime']:
            if col in df.columns:
                date_col = col
                break
        
        if not date_col:
            logger.warning("无法找到日期列，无法按日期拆分保存缓存")
            return False
        
        # 确保日期列为datetime类型
        # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce', )
        
        # 按日期分组保存
        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_cache_file_path('etf_daily', symbol, date_str, config=config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1
        
        logger.info(f"ETF日线数据已保存到缓存: {symbol}, {saved_count} 个日期")
        return saved_count > 0
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_etf_daily_cache', 'symbol': symbol},
            "保存缓存失败"
        )
        return False


def save_stock_daily_cache(
    symbol: str,
    df: pd.DataFrame,
    config: Optional[Dict] = None
) -> bool:
    """
    保存股票日线数据到缓存（按日期拆分保存）

    Args:
        symbol: 股票代码
        df: 日线数据DataFrame
        config: 系统配置

    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            return False

        df = _df_drop_duplicate_column_names(df)

        date_col: Optional[str] = None
        for col in ['日期', 'date', '日期时间', 'datetime']:
            if col in df.columns:
                date_col = col
                break

        if not date_col:
            logger.warning("无法找到日期列，无法按日期拆分保存股票日线缓存")
            return False

        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_cache_file_path('stock_daily', symbol, date_str, config=config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1

        logger.info(f"股票日线数据已保存到缓存: {symbol}, {saved_count} 个日期")
        return saved_count > 0

    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_stock_daily_cache', 'symbol': symbol},
            "保存缓存失败"
        )
        return False


def save_index_daily_cache(
    symbol: str,
    df: pd.DataFrame,
    config: Optional[Dict] = None
) -> bool:
    """
    保存指数日线数据到缓存（按日期拆分保存）
    
    Args:
        symbol: 指数代码
        df: 日线数据DataFrame
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            return False
        
        # 找到日期列
        date_col = None
        for col in ['日期', 'date', '日期时间', 'datetime']:
            if col in df.columns:
                date_col = col
                break
        
        if not date_col:
            logger.warning("无法找到日期列，无法按日期拆分保存缓存")
            return False
        
        # 确保日期列为datetime类型
        # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce', )
        
        # 按日期分组保存
        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_cache_file_path('index_daily', symbol, date_str, config=config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1
        
        logger.info(f"指数日线数据已保存到缓存: {symbol}, {saved_count} 个日期")
        return saved_count > 0
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_index_daily_cache', 'symbol': symbol},
            "保存缓存失败"
        )
        return False


def save_global_index_daily_from_records(
    symbol_key: str,
    records: List[Dict[str, Any]],
    *,
    config: Optional[Dict] = None,
) -> int:
    """
    将外盘指数日线记录写入 data/cache/global_index_daily/<symbol_key>/YYYYMMDD.parquet。

    records 项约定与 ``tool_fetch_global_index_hist_sina`` 的 data 行一致：date, open, high, low, close, volume。
    """
    if not records:
        return 0
    dc = (config or {}).get("data_cache") if isinstance((config or {}).get("data_cache"), dict) else {}
    if not dc.get("enabled", True):
        return 0
    saved = 0
    sym = str(symbol_key).strip()
    if not sym:
        return 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        ds = str(rec.get("date") or "").strip()
        if not ds:
            continue
        ds_compact = ds.replace("-", "")[:8]
        if len(ds_compact) != 8 or not ds_compact.isdigit():
            continue
        row = {
            "date": ds,
            "open": rec.get("open"),
            "high": rec.get("high"),
            "low": rec.get("low"),
            "close": rec.get("close"),
            "volume": rec.get("volume"),
        }
        df = pd.DataFrame([row])
        path = get_cache_file_path("global_index_daily", sym, ds_compact, config=config)
        if save_cached_data(df, path):
            saved += 1
    if saved:
        logger.info("外盘指数日线已写入缓存: %s, %s 行", sym, saved)
    return saved


def get_cached_index_minute(
    symbol: str,
    period: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    获取缓存的指数分钟数据
    
    Args:
        symbol: 指数代码
        period: 周期（'5', '15', '30', '60'）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        Tuple[Optional[pd.DataFrame], List[str]]: 
            - 缓存的数据（如果全部命中）或None（如果部分命中或未命中）
            - 缺失的日期列表
    """
    try:
        dates = parse_date_range(start_date, end_date)
        cached_dfs = []
        missing_dates = []
        date_col = None
        
        for date in dates:
            # 仅针对交易日检查缓存，跳过周末和节假日，避免对不存在行情的日期反复报 missing
            date_obj = datetime.strptime(date, "%Y%m%d")
            if not is_trading_day(date_obj, config):
                continue
            
            cache_path = get_cache_file_path('index_minute', symbol, date, period=period, config=config)
            cached_df = load_cached_data(cache_path)
            
            if cached_df is not None and not cached_df.empty:
                # 过滤出该日期的数据
                if date_col is None:
                    for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                        if col in cached_df.columns:
                            date_col = col
                            break
                
                if date_col:
                    # 转换为datetime并过滤
                    # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
                    if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                        cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce', )
                    date_filtered = cached_df[
                        cached_df[date_col].dt.strftime('%Y%m%d') == date
                    ]
                    if not date_filtered.empty:
                        cached_dfs.append(date_filtered)
                        continue
                else:
                    # 没有日期列，假设整个文件都是该日期的数据
                    cached_dfs.append(cached_df)
                    continue
            
            missing_dates.append(date)
        
        if not cached_dfs:
            # 完全没有缓存
            return None, missing_dates
        
        if missing_dates:
            # 部分缓存，返回已缓存的数据和缺失交易日期列表
            partial_df = pd.concat(cached_dfs, ignore_index=True) if cached_dfs else None
            if partial_df is not None and date_col:
                partial_df = partial_df.sort_values(by=date_col)
            if partial_df is not None:
                logger.info(
                    f"指数分钟数据部分缓存命中: {symbol}, {period}分钟, {start_date}~{end_date}, "
                    f"已缓存 {len(partial_df)} 条, 缺失 {len(missing_dates)} 个交易日"
                )
                return partial_df, missing_dates
            return None, missing_dates
        
        # 全部缓存命中，合并数据
        result_df = pd.concat(cached_dfs, ignore_index=True)
        if date_col:
            result_df = result_df.sort_values(by=date_col)
        
        logger.info(f"指数分钟数据缓存全部命中: {symbol}, {period}分钟, {start_date}~{end_date}, {len(result_df)} 条")
        return result_df, []
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_index_minute',
                'symbol': symbol,
                'period': period,
                'start_date': start_date,
                'end_date': end_date
            },
            "获取缓存数据失败"
        )
        return None, parse_date_range(start_date, end_date)


def get_cached_stock_minute(
    symbol: str,
    period: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    获取缓存的股票分钟数据

    Args:
        symbol: 股票代码
        period: 周期（'1', '5', '15', '30', '60'）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        config: 系统配置

    Returns:
        Tuple[Optional[pd.DataFrame], List[str]]:
            - 已缓存的数据（可能是全部或部分命中），或None
            - 缺失的交易日期列表
    """
    try:
        dates = parse_date_range(start_date, end_date)
        cached_dfs: List[pd.DataFrame] = []
        missing_dates: List[str] = []
        date_col: Optional[str] = None

        for date in dates:
            date_obj = datetime.strptime(date, "%Y%m%d")
            if not is_trading_day(date_obj, config):
                continue

            cache_path = get_cache_file_path('stock_minute', symbol, date, period=period, config=config)
            cached_df = load_cached_data(cache_path)

            if cached_df is not None and not cached_df.empty:
                if date_col is None:
                    for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                        if col in cached_df.columns:
                            date_col = col
                            break

                if date_col:
                    if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                        cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
                    date_filtered = cached_df[cached_df[date_col].dt.strftime('%Y%m%d') == date]
                    if not date_filtered.empty:
                        cached_dfs.append(date_filtered)
                        continue
                else:
                    cached_dfs.append(cached_df)
                    continue

            missing_dates.append(date)

        if not cached_dfs:
            return None, missing_dates

        if missing_dates:
            partial_df = pd.concat(cached_dfs, ignore_index=True) if cached_dfs else None
            if partial_df is not None and date_col:
                partial_df = partial_df.sort_values(by=date_col)
            if partial_df is not None:
                logger.info(
                    f"股票分钟数据部分缓存命中: {symbol}, {period}分钟, {start_date}~{end_date}, "
                    f"已缓存 {len(partial_df)} 条, 缺失 {len(missing_dates)} 个交易日"
                )
                return partial_df, missing_dates
            return None, missing_dates

        result_df = pd.concat(cached_dfs, ignore_index=True)
        if date_col:
            result_df = result_df.sort_values(by=date_col)

        logger.info(f"股票分钟数据缓存全部命中: {symbol}, {period}分钟, {start_date}~{end_date}, {len(result_df)} 条")
        return result_df, []

    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_stock_minute',
                'symbol': symbol,
                'period': period,
                'start_date': start_date,
                'end_date': end_date
            },
            "获取缓存数据失败"
        )
        return None, parse_date_range(start_date, end_date)


def save_index_minute_cache(
    symbol: str,
    period: str,
    df: pd.DataFrame,
    config: Optional[Dict] = None
) -> bool:
    """
    保存指数分钟数据到缓存（按日期拆分保存）
    
    Args:
        symbol: 指数代码
        period: 周期（'5', '15', '30', '60'）
        df: 分钟数据DataFrame
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            return False
        
        # 找到日期/时间列
        date_col = None
        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
            if col in df.columns:
                date_col = col
                break
        
        if not date_col:
            logger.warning("无法找到日期列，无法按日期拆分保存缓存")
            return False
        
        # 确保日期列为datetime类型
        # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce', )
        
        # 按日期分组保存
        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_cache_file_path('index_minute', symbol, date_str, period=period, config=config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1
        
        logger.info(f"指数分钟数据已保存到缓存: {symbol}, {period}分钟, {saved_count} 个日期")
        return saved_count > 0
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_index_minute_cache', 'symbol': symbol, 'period': period},
            "保存缓存失败"
        )
        return False


def save_stock_minute_cache(
    symbol: str,
    period: str,
    df: pd.DataFrame,
    config: Optional[Dict] = None
) -> bool:
    """
    保存股票分钟数据到缓存（按日期拆分保存）

    Args:
        symbol: 股票代码
        period: 周期（'1', '5', '15', '30', '60'）
        df: 分钟数据DataFrame
        config: 系统配置

    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            return False

        date_col: Optional[str] = None
        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
            if col in df.columns:
                date_col = col
                break

        if not date_col:
            logger.warning("无法找到日期列，无法按日期拆分保存股票分钟缓存")
            return False

        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')

        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_cache_file_path('stock_minute', symbol, date_str, period=period, config=config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1

        logger.info(f"股票分钟数据已保存到缓存: {symbol}, {period}分钟, {saved_count} 个日期")
        return saved_count > 0

    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_stock_minute_cache', 'symbol': symbol, 'period': period},
            "保存缓存失败"
        )
        return False


def get_cached_etf_minute(
    symbol: str,
    period: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    获取缓存的ETF日内分钟数据
    
    Args:
        symbol: ETF代码
        period: 周期（'5', '15', '30', '60'）
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        Tuple[Optional[pd.DataFrame], List[str]]: 
            - 缓存的数据（如果全部命中）或None（如果部分命中或未命中）
            - 缺失的日期列表
    """
    try:
        dates = parse_date_range(start_date, end_date)
        cached_dfs = []
        missing_dates = []
        date_col = None
        
        for date in dates:
            # 仅检查交易日缓存，跳过周末和节假日，避免对无行情日期报缺失
            date_obj = datetime.strptime(date, "%Y%m%d")
            if not is_trading_day(date_obj, config):
                continue
            
            cache_path = get_cache_file_path('etf_minute', symbol, date, period=period, config=config)
            cached_df = load_cached_data(cache_path)
            
            if cached_df is not None and not cached_df.empty:
                # 过滤出该日期的数据
                if date_col is None:
                    for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                        if col in cached_df.columns:
                            date_col = col
                            break
                
                if date_col:
                    # 转换为datetime并过滤
                    # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
                    if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                        cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce', )
                    date_filtered = cached_df[
                        cached_df[date_col].dt.strftime('%Y%m%d') == date
                    ]
                    if not date_filtered.empty:
                        cached_dfs.append(date_filtered)
                        continue
                else:
                    # 没有日期列，假设整个文件都是该日期的数据
                    cached_dfs.append(cached_df)
                    continue
            
            missing_dates.append(date)
        
        if not cached_dfs:
            # 完全没有缓存
            return None, missing_dates
        
        if missing_dates:
            partial_df = pd.concat(cached_dfs, ignore_index=True) if cached_dfs else None
            if partial_df is not None and date_col:
                partial_df = partial_df.sort_values(by=date_col)
            if partial_df is not None:
                logger.info(
                    f"ETF日内分钟数据部分缓存命中: {symbol}, {period}分钟, {start_date}~{end_date}, "
                    f"已缓存 {len(partial_df)} 条, 缺失 {len(missing_dates)} 个交易日"
                )
                return partial_df, missing_dates
            return None, missing_dates
        
        # 全部缓存命中，合并数据
        result_df = pd.concat(cached_dfs, ignore_index=True)
        if date_col:
            result_df = result_df.sort_values(by=date_col)
        
        logger.info(f"ETF日内分钟数据缓存全部命中: {symbol}, {period}分钟, {start_date}~{end_date}, {len(result_df)} 条")
        return result_df, []
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_etf_minute',
                'symbol': symbol,
                'period': period,
                'start_date': start_date,
                'end_date': end_date
            },
            "获取缓存数据失败"
        )
        return None, parse_date_range(start_date, end_date)


def save_etf_minute_cache(
    symbol: str,
    period: str,
    df: pd.DataFrame,
    config: Optional[Dict] = None
) -> bool:
    """
    保存ETF日内分钟数据到缓存（按日期拆分保存）
    
    Args:
        symbol: ETF代码
        period: 周期（'5', '15', '30', '60'）
        df: 分钟数据DataFrame
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            return False
        
        # 找到日期/时间列
        date_col = None
        for col in ['时间', '日期', 'date', '日期时间', 'datetime']:
            if col in df.columns:
                date_col = col
                break
        
        if not date_col:
            logger.warning("无法找到日期列，无法按日期拆分保存缓存")
            return False
        
        # 确保日期列为datetime类型
        # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce', )
        
        # 按日期分组保存
        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_cache_file_path('etf_minute', symbol, date_str, period=period, config=config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1
        
        logger.info(f"ETF日内分钟数据已保存到缓存: {symbol}, {period}分钟, {saved_count} 个日期")
        return saved_count > 0
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_etf_minute_cache', 'symbol': symbol, 'period': period},
            "保存缓存失败"
        )
        return False


def merge_cached_and_fetched_data(
    cached_df: Optional[pd.DataFrame],
    fetched_df: Optional[pd.DataFrame],
    date_col: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    合并缓存数据和获取的数据
    
    Args:
        cached_df: 缓存的数据
        fetched_df: 新获取的数据
        date_col: 日期列名（用于去重）
    
    Returns:
        pd.DataFrame: 合并后的数据
    """
    try:
        if cached_df is None or cached_df.empty:
            return fetched_df
        
        if fetched_df is None or fetched_df.empty:
            return cached_df
        
        # 统一日期列类型（确保都是datetime类型）
        if date_col and date_col in cached_df.columns and date_col in fetched_df.columns:
            # 复制DataFrame避免修改原始数据
            cached_df = cached_df.copy()
            fetched_df = fetched_df.copy()
            
            # 确保两个DataFrame的日期列都是datetime类型
            if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
            
            if not pd.api.types.is_datetime64_any_dtype(fetched_df[date_col]):
                fetched_df[date_col] = pd.to_datetime(fetched_df[date_col], errors='coerce')
        
        # 合并数据
        merged_df = pd.concat([cached_df, fetched_df], ignore_index=True)
        
        # 去重（如果有日期列）
        if date_col and date_col in merged_df.columns:
            # 按日期列去重，保留最后一条
            merged_df = merged_df.drop_duplicates(subset=[date_col], keep='last')
            # 确保日期列是datetime类型后再排序
            if not pd.api.types.is_datetime64_any_dtype(merged_df[date_col]):
                merged_df[date_col] = pd.to_datetime(merged_df[date_col], errors='coerce')
            merged_df = merged_df.sort_values(by=date_col)
        else:
            # 没有日期列，简单去重
            merged_df = merged_df.drop_duplicates(keep='last')
        
        return merged_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'merge_cached_and_fetched_data'},
            "合并数据失败"
        )
        return fetched_df if fetched_df is not None else cached_df


def get_cache_stats(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    获取缓存统计信息
    
    Args:
        config: 系统配置
    
    Returns:
        dict: 缓存统计信息
    """
    try:
        cache_dir = get_cache_dir(config)
        
        stats: Dict[str, Any] = {
            'total_size_mb': 0.0,
            'index_daily': {
                'symbols': [],
                'total_files': 0,
                'total_size_mb': 0.0,
                'date_range': {'earliest': None, 'latest': None}
            },
            'index_minute': {
                'symbols': [],
                'periods': {},
                'total_files': 0,
                'total_size_mb': 0.0,
                'date_range': {'earliest': None, 'latest': None}
            },
            'etf_daily': {
                'symbols': [],
                'total_files': 0,
                'total_size_mb': 0.0,
                'date_range': {'earliest': None, 'latest': None}
            },
            'etf_minute': {
                'symbols': [],
                'periods': {},
                'total_files': 0,
                'total_size_mb': 0.0,
                'date_range': {'earliest': None, 'latest': None}
            },
            'stock_daily': {
                'symbols': [],
                'total_files': 0,
                'total_size_mb': 0.0,
                'date_range': {'earliest': None, 'latest': None}
            },
            'global_index_daily': {
                'symbols': [],
                'total_files': 0,
                'total_size_mb': 0.0,
                'date_range': {'earliest': None, 'latest': None}
            },
            'stock_minute': {
                'symbols': [],
                'periods': {},
                'total_files': 0,
                'total_size_mb': 0.0,
                'date_range': {'earliest': None, 'latest': None}
            },
            'option_minute': {
                'symbols': [],
                'periods': {},
                'total_files': 0,
                'total_size_mb': 0.0
            },
            'option_greeks': {
                'symbols': [],
                'total_files': 0,
                'total_size_mb': 0.0
            }
        }
        
        # 统计指数日线缓存
        index_daily_dir = cache_dir / 'index_daily'
        if index_daily_dir.exists():
            for symbol_dir in index_daily_dir.iterdir():
                if symbol_dir.is_dir():
                    symbol = symbol_dir.name
                    stats['index_daily']['symbols'].append(symbol)
                    
                    files = list(symbol_dir.glob('*.parquet'))
                    stats['index_daily']['total_files'] += len(files)
                    
                    for file_path in files:
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        stats['index_daily']['total_size_mb'] += size_mb
                        stats['total_size_mb'] += size_mb
                        
                        # 提取日期
                        date_str = file_path.stem
                        if stats['index_daily']['date_range']['earliest'] is None or date_str < stats['index_daily']['date_range']['earliest']:
                            stats['index_daily']['date_range']['earliest'] = date_str
                        if stats['index_daily']['date_range']['latest'] is None or date_str > stats['index_daily']['date_range']['latest']:
                            stats['index_daily']['date_range']['latest'] = date_str
        
        # 统计指数分钟缓存
        index_minute_dir = cache_dir / 'index_minute'
        if index_minute_dir.exists():
            for symbol_dir in index_minute_dir.iterdir():
                if symbol_dir.is_dir():
                    symbol = symbol_dir.name
                    if symbol not in stats['index_minute']['symbols']:
                        stats['index_minute']['symbols'].append(symbol)
                    
                    # 检查是否有周期子目录
                    for period_dir in symbol_dir.iterdir():
                        if period_dir.is_dir():
                            period = period_dir.name
                            if period not in stats['index_minute']['periods']:
                                stats['index_minute']['periods'][period] = {
                                    'total_files': 0,
                                    'total_size_mb': 0.0
                                }
                            
                            files = list(period_dir.glob('*.parquet'))
                            stats['index_minute']['periods'][period]['total_files'] += len(files)
                            stats['index_minute']['total_files'] += len(files)
                            
                            for file_path in files:
                                size_mb = file_path.stat().st_size / (1024 * 1024)
                                stats['index_minute']['periods'][period]['total_size_mb'] += size_mb
                                stats['index_minute']['total_size_mb'] += size_mb
                                stats['total_size_mb'] += size_mb
                                
                                # 提取日期
                                date_str = file_path.stem
                                if stats['index_minute']['date_range']['earliest'] is None or date_str < stats['index_minute']['date_range']['earliest']:
                                    stats['index_minute']['date_range']['earliest'] = date_str
                                if stats['index_minute']['date_range']['latest'] is None or date_str > stats['index_minute']['date_range']['latest']:
                                    stats['index_minute']['date_range']['latest'] = date_str
        
        # 统计ETF日线缓存
        etf_daily_dir = cache_dir / 'etf_daily'
        if etf_daily_dir.exists():
            for symbol_dir in etf_daily_dir.iterdir():
                if symbol_dir.is_dir():
                    symbol = symbol_dir.name
                    stats['etf_daily']['symbols'].append(symbol)
                    
                    files = list(symbol_dir.glob('*.parquet'))
                    stats['etf_daily']['total_files'] += len(files)
                    
                    for file_path in files:
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        stats['etf_daily']['total_size_mb'] += size_mb
                        stats['total_size_mb'] += size_mb
                        
                        # 提取日期
                        date_str = file_path.stem
                        if stats['etf_daily']['date_range']['earliest'] is None or date_str < stats['etf_daily']['date_range']['earliest']:
                            stats['etf_daily']['date_range']['earliest'] = date_str
                        if stats['etf_daily']['date_range']['latest'] is None or date_str > stats['etf_daily']['date_range']['latest']:
                            stats['etf_daily']['date_range']['latest'] = date_str
        
        # 统计ETF分钟缓存
        etf_minute_dir = cache_dir / 'etf_minute'
        if etf_minute_dir.exists():
            for symbol_dir in etf_minute_dir.iterdir():
                if symbol_dir.is_dir():
                    symbol = symbol_dir.name
                    if symbol not in stats['etf_minute']['symbols']:
                        stats['etf_minute']['symbols'].append(symbol)
                    
                    # 检查是否有周期子目录
                    for period_dir in symbol_dir.iterdir():
                        if period_dir.is_dir():
                            period = period_dir.name
                            if period not in stats['etf_minute']['periods']:
                                stats['etf_minute']['periods'][period] = {
                                    'total_files': 0,
                                    'total_size_mb': 0.0
                                }
                            
                            files = list(period_dir.glob('*.parquet'))
                            stats['etf_minute']['periods'][period]['total_files'] += len(files)
                            stats['etf_minute']['total_files'] += len(files)
                            
                            for file_path in files:
                                size_mb = file_path.stat().st_size / (1024 * 1024)
                                stats['etf_minute']['periods'][period]['total_size_mb'] += size_mb
                                stats['etf_minute']['total_size_mb'] += size_mb
                                stats['total_size_mb'] += size_mb
                                
                                # 提取日期
                                date_str = file_path.stem
                                if stats['etf_minute']['date_range']['earliest'] is None or date_str < stats['etf_minute']['date_range']['earliest']:
                                    stats['etf_minute']['date_range']['earliest'] = date_str
                                if stats['etf_minute']['date_range']['latest'] is None or date_str > stats['etf_minute']['date_range']['latest']:
                                    stats['etf_minute']['date_range']['latest'] = date_str
        
        # 统计股票日线缓存
        stock_daily_dir = cache_dir / 'stock_daily'
        if stock_daily_dir.exists():
            for symbol_dir in stock_daily_dir.iterdir():
                if symbol_dir.is_dir():
                    symbol = symbol_dir.name
                    stats['stock_daily']['symbols'].append(symbol)

                    files = list(symbol_dir.glob('*.parquet'))
                    stats['stock_daily']['total_files'] += len(files)

                    for file_path in files:
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        stats['stock_daily']['total_size_mb'] += size_mb
                        stats['total_size_mb'] += size_mb

                        date_str = file_path.stem
                        if stats['stock_daily']['date_range']['earliest'] is None or date_str < stats['stock_daily']['date_range']['earliest']:
                            stats['stock_daily']['date_range']['earliest'] = date_str
                        if stats['stock_daily']['date_range']['latest'] is None or date_str > stats['stock_daily']['date_range']['latest']:
                            stats['stock_daily']['date_range']['latest'] = date_str

        # 统计外盘指数日线缓存（global_index_daily）
        global_idx_dir = cache_dir / 'global_index_daily'
        if global_idx_dir.exists():
            for symbol_dir in global_idx_dir.iterdir():
                if symbol_dir.is_dir():
                    symbol = symbol_dir.name
                    stats['global_index_daily']['symbols'].append(symbol)
                    files = list(symbol_dir.glob('*.parquet'))
                    stats['global_index_daily']['total_files'] += len(files)
                    for file_path in files:
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        stats['global_index_daily']['total_size_mb'] += size_mb
                        stats['total_size_mb'] += size_mb
                        date_str = file_path.stem
                        er = stats['global_index_daily']['date_range']
                        if er['earliest'] is None or date_str < er['earliest']:
                            er['earliest'] = date_str
                        if er['latest'] is None or date_str > er['latest']:
                            er['latest'] = date_str

        # 统计股票分钟缓存
        stock_minute_dir = cache_dir / 'stock_minute'
        if stock_minute_dir.exists():
            for symbol_dir in stock_minute_dir.iterdir():
                if symbol_dir.is_dir():
                    symbol = symbol_dir.name
                    if symbol not in stats['stock_minute']['symbols']:
                        stats['stock_minute']['symbols'].append(symbol)

                    for period_dir in symbol_dir.iterdir():
                        if period_dir.is_dir():
                            period = period_dir.name
                            if period not in stats['stock_minute']['periods']:
                                stats['stock_minute']['periods'][period] = {
                                    'total_files': 0,
                                    'total_size_mb': 0.0
                                }

                            files = list(period_dir.glob('*.parquet'))
                            stats['stock_minute']['periods'][period]['total_files'] += len(files)
                            stats['stock_minute']['total_files'] += len(files)

                            for file_path in files:
                                size_mb = file_path.stat().st_size / (1024 * 1024)
                                stats['stock_minute']['periods'][period]['total_size_mb'] += size_mb
                                stats['stock_minute']['total_size_mb'] += size_mb
                                stats['total_size_mb'] += size_mb

                                date_str = file_path.stem
                                if stats['stock_minute']['date_range']['earliest'] is None or date_str < stats['stock_minute']['date_range']['earliest']:
                                    stats['stock_minute']['date_range']['earliest'] = date_str
                                if stats['stock_minute']['date_range']['latest'] is None or date_str > stats['stock_minute']['date_range']['latest']:
                                    stats['stock_minute']['date_range']['latest'] = date_str

        # 统计期权分钟K缓存
        option_minute_dir = cache_dir / 'option_minute'
        if option_minute_dir.exists():
            for contract_dir in option_minute_dir.iterdir():
                if contract_dir.is_dir():
                    contract_code = contract_dir.name
                    if contract_code not in stats['option_minute']['symbols']:
                        stats['option_minute']['symbols'].append(contract_code)
                    
                    # 检查是否有周期子目录
                    has_period_dirs = any(p.is_dir() for p in contract_dir.iterdir())
                    if has_period_dirs:
                        for period_dir in contract_dir.iterdir():
                            if period_dir.is_dir():
                                period = period_dir.name
                                if period not in stats['option_minute']['periods']:
                                    stats['option_minute']['periods'][period] = {
                                        'total_files': 0,
                                        'total_size_mb': 0.0
                                    }
                                
                                files = list(period_dir.glob('*.parquet'))
                                stats['option_minute']['periods'][period]['total_files'] += len(files)
                                stats['option_minute']['total_files'] += len(files)
                                
                                for file_path in files:
                                    size_mb = file_path.stat().st_size / (1024 * 1024)
                                    stats['option_minute']['periods'][period]['total_size_mb'] += size_mb
                                    stats['option_minute']['total_size_mb'] += size_mb
                                    stats['total_size_mb'] += size_mb
                    else:
                        # 没有周期子目录，直接统计文件
                        files = list(contract_dir.glob('*.parquet'))
                        stats['option_minute']['total_files'] += len(files)
                        for file_path in files:
                            size_mb = file_path.stat().st_size / (1024 * 1024)
                            stats['option_minute']['total_size_mb'] += size_mb
                            stats['total_size_mb'] += size_mb
        
        # 统计期权Greeks缓存
        option_greeks_dir = cache_dir / 'option_greeks'
        if option_greeks_dir.exists():
            for contract_dir in option_greeks_dir.iterdir():
                if contract_dir.is_dir():
                    contract_code = contract_dir.name
                    if contract_code not in stats['option_greeks']['symbols']:
                        stats['option_greeks']['symbols'].append(contract_code)
                    
                    files = list(contract_dir.glob('*.parquet'))
                    stats['option_greeks']['total_files'] += len(files)
                    
                    for file_path in files:
                        size_mb = file_path.stat().st_size / (1024 * 1024)
                        stats['option_greeks']['total_size_mb'] += size_mb
                        stats['total_size_mb'] += size_mb
        
        return stats
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'get_cache_stats'},
            "获取缓存统计失败"
        )
        return {}


def clear_index_daily_cache(symbol: str, date: str, config: Optional[Dict] = None) -> bool:
    """
    清除指定指数在指定日期的日线数据缓存
    
    Args:
        symbol: 指数代码
        date: 日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        bool: 是否成功删除
    """
    try:
        cache_path = get_cache_file_path('index_daily', symbol, date, config=config)
        if cache_path.exists():
            cache_path.unlink()
            logger.info(f"已删除缓存: {symbol}, {date}")
            return True
        return False
    except Exception as e:
        logger.warning(f"删除缓存失败: {symbol}, {date}, {e}")
        return False


def clean_cache(
    keep_days: int = 90,
    data_type: Optional[str] = None,
    symbol: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    清理缓存（删除指定天数之前的数据）
    
    Args:
        keep_days: 保留最近N天的数据（默认90天）
        data_type: 数据类型（'index_daily' 或 'index_minute'），如果为None则清理所有
        symbol: 指数代码，如果为None则清理所有
        config: 系统配置
    
    Returns:
        dict: 清理结果统计
    """
    try:
        cache_dir = get_cache_dir(config)
        cutoff_date = (datetime.now() - timedelta(days=keep_days)).strftime("%Y%m%d")
        
        result: Dict[str, Any] = {
            'deleted_files': 0,
            'deleted_size_mb': 0.0,
            'cutoff_date': cutoff_date
        }
        
        data_types = [data_type] if data_type else ['index_daily', 'index_minute', 'etf_daily', 'stock_daily', 'stock_minute']
        
        for dt in data_types:
            if dt == 'index_daily':
                type_dir = cache_dir / 'index_daily'
                if not type_dir.exists():
                    continue
                
                symbols = [symbol] if symbol else [d.name for d in type_dir.iterdir() if d.is_dir()]
                
                for sym in symbols:
                    symbol_dir = type_dir / sym
                    if not symbol_dir.exists():
                        continue
                    
                    for file_path in symbol_dir.glob('*.parquet'):
                        date_str = file_path.stem
                        if date_str < cutoff_date:
                            size_mb = file_path.stat().st_size / (1024 * 1024)
                            file_path.unlink()
                            result['deleted_files'] += 1
                            result['deleted_size_mb'] += size_mb
                            
                            # 如果目录为空，删除目录
                            if not any(symbol_dir.iterdir()):
                                symbol_dir.rmdir()
            
            elif dt == 'index_minute':
                type_dir = cache_dir / 'index_minute'
                if not type_dir.exists():
                    continue
                
                symbols = [symbol] if symbol else [d.name for d in type_dir.iterdir() if d.is_dir()]
                
                for sym in symbols:
                    symbol_dir = type_dir / sym
                    if not symbol_dir.exists():
                        continue
                    
                    # 遍历周期目录
                    for period_dir in symbol_dir.iterdir():
                        if not period_dir.is_dir():
                            continue
                        
                        for file_path in period_dir.glob('*.parquet'):
                            date_str = file_path.stem
                            if date_str < cutoff_date:
                                size_mb = file_path.stat().st_size / (1024 * 1024)
                                file_path.unlink()
                                result['deleted_files'] += 1
                                result['deleted_size_mb'] += size_mb
                        
                        # 如果周期目录为空，删除目录
                        if period_dir.exists() and not any(period_dir.iterdir()):
                            period_dir.rmdir()
                    
                    # 如果符号目录为空，删除目录
                    if symbol_dir.exists() and not any(symbol_dir.iterdir()):
                        symbol_dir.rmdir()
            
            elif dt == 'etf_daily':
                type_dir = cache_dir / 'etf_daily'
                if not type_dir.exists():
                    continue
                
                symbols = [symbol] if symbol else [d.name for d in type_dir.iterdir() if d.is_dir()]
                
                for sym in symbols:
                    symbol_dir = type_dir / sym
                    if not symbol_dir.exists():
                        continue
                    
                    for file_path in symbol_dir.glob('*.parquet'):
                        date_str = file_path.stem
                        if date_str < cutoff_date:
                            size_mb = file_path.stat().st_size / (1024 * 1024)
                            file_path.unlink()
                            result['deleted_files'] += 1
                            result['deleted_size_mb'] += size_mb
                            
                            # 如果目录为空，删除目录
                            if not any(symbol_dir.iterdir()):
                                symbol_dir.rmdir()
            elif dt == 'stock_daily':
                type_dir = cache_dir / 'stock_daily'
                if not type_dir.exists():
                    continue

                symbols = [symbol] if symbol else [d.name for d in type_dir.iterdir() if d.is_dir()]

                for sym in symbols:
                    symbol_dir = type_dir / sym
                    if not symbol_dir.exists():
                        continue

                    for file_path in symbol_dir.glob('*.parquet'):
                        date_str = file_path.stem
                        if date_str < cutoff_date:
                            size_mb = file_path.stat().st_size / (1024 * 1024)
                            file_path.unlink()
                            result['deleted_files'] += 1
                            result['deleted_size_mb'] += size_mb

                            if not any(symbol_dir.iterdir()):
                                symbol_dir.rmdir()
            elif dt == 'stock_minute':
                type_dir = cache_dir / 'stock_minute'
                if not type_dir.exists():
                    continue

                symbols = [symbol] if symbol else [d.name for d in type_dir.iterdir() if d.is_dir()]

                for sym in symbols:
                    symbol_dir = type_dir / sym
                    if not symbol_dir.exists():
                        continue

                    for period_dir in symbol_dir.iterdir():
                        if not period_dir.is_dir():
                            continue

                        for file_path in period_dir.glob('*.parquet'):
                            date_str = file_path.stem
                            if date_str < cutoff_date:
                                size_mb = file_path.stat().st_size / (1024 * 1024)
                                file_path.unlink()
                                result['deleted_files'] += 1
                                result['deleted_size_mb'] += size_mb

                        if period_dir.exists() and not any(period_dir.iterdir()):
                            period_dir.rmdir()

                    if symbol_dir.exists() and not any(symbol_dir.iterdir()):
                        symbol_dir.rmdir()
        
        logger.info(f"缓存清理完成: 删除 {result['deleted_files']} 个文件, "
                   f"释放 {result['deleted_size_mb']:.2f} MB, 保留 {keep_days} 天数据")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'clean_cache',
                'keep_days': keep_days,
                'data_type': data_type,
                'symbol': symbol
            },
            "清理缓存失败"
        )
        return {'deleted_files': 0, 'deleted_size_mb': 0.0}


def validate_cache(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    验证缓存数据的完整性
    
    Args:
        config: 系统配置
    
    Returns:
        dict: 验证结果
    """
    try:
        cache_dir = get_cache_dir(config)
        
        result: Dict[str, Any] = {
            'total_files': 0,
            'valid_files': 0,
            'invalid_files': 0,
            'errors': []
        }
        
        # 验证指数日线缓存
        index_daily_dir = cache_dir / 'index_daily'
        if index_daily_dir.exists():
            for symbol_dir in index_daily_dir.iterdir():
                if symbol_dir.is_dir():
                    for file_path in symbol_dir.glob('*.parquet'):
                        result['total_files'] += 1
                        try:
                            df = pd.read_parquet(file_path)
                            if df is not None and not df.empty:
                                result['valid_files'] += 1
                            else:
                                result['invalid_files'] += 1
                                result['errors'].append(f"文件为空: {file_path}")
                        except Exception as e:
                            result['invalid_files'] += 1
                            result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")
        
        # 验证指数分钟缓存
        index_minute_dir = cache_dir / 'index_minute'
        if index_minute_dir.exists():
            for symbol_dir in index_minute_dir.iterdir():
                if symbol_dir.is_dir():
                    for period_dir in symbol_dir.iterdir():
                        if period_dir.is_dir():
                            for file_path in period_dir.glob('*.parquet'):
                                result['total_files'] += 1
                                try:
                                    df = pd.read_parquet(file_path)
                                    if df is not None and not df.empty:
                                        result['valid_files'] += 1
                                    else:
                                        result['invalid_files'] += 1
                                        result['errors'].append(f"文件为空: {file_path}")
                                except Exception as e:
                                    result['invalid_files'] += 1
                                    result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")
        
        # 验证ETF日线缓存
        etf_daily_dir = cache_dir / 'etf_daily'
        if etf_daily_dir.exists():
            for symbol_dir in etf_daily_dir.iterdir():
                if symbol_dir.is_dir():
                    for file_path in symbol_dir.glob('*.parquet'):
                        result['total_files'] += 1
                        try:
                            df = pd.read_parquet(file_path)
                            if df is not None and not df.empty:
                                result['valid_files'] += 1
                            else:
                                result['invalid_files'] += 1
                                result['errors'].append(f"文件为空: {file_path}")
                        except Exception as e:
                            result['invalid_files'] += 1
                            result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")
        
        # 验证ETF日内分钟缓存
        etf_minute_dir = cache_dir / 'etf_minute'
        if etf_minute_dir.exists():
            for symbol_dir in etf_minute_dir.iterdir():
                if symbol_dir.is_dir():
                    for period_dir in symbol_dir.iterdir():
                        if period_dir.is_dir():
                            for file_path in period_dir.glob('*.parquet'):
                                result['total_files'] += 1
                                try:
                                    df = pd.read_parquet(file_path)
                                    if df is not None and not df.empty:
                                        result['valid_files'] += 1
                                    else:
                                        result['invalid_files'] += 1
                                        result['errors'].append(f"文件为空: {file_path}")
                                except Exception as e:
                                    result['invalid_files'] += 1
                                    result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")
        
        # 验证股票日线缓存
        stock_daily_dir = cache_dir / 'stock_daily'
        if stock_daily_dir.exists():
            for symbol_dir in stock_daily_dir.iterdir():
                if symbol_dir.is_dir():
                    for file_path in symbol_dir.glob('*.parquet'):
                        result['total_files'] += 1
                        try:
                            df = pd.read_parquet(file_path)
                            if df is not None and not df.empty:
                                result['valid_files'] += 1
                            else:
                                result['invalid_files'] += 1
                                result['errors'].append(f"文件为空: {file_path}")
                        except Exception as e:
                            result['invalid_files'] += 1
                            result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")

        # 验证股票分钟缓存
        stock_minute_dir = cache_dir / 'stock_minute'
        if stock_minute_dir.exists():
            for symbol_dir in stock_minute_dir.iterdir():
                if symbol_dir.is_dir():
                    for period_dir in symbol_dir.iterdir():
                        if period_dir.is_dir():
                            for file_path in period_dir.glob('*.parquet'):
                                result['total_files'] += 1
                                try:
                                    df = pd.read_parquet(file_path)
                                    if df is not None and not df.empty:
                                        result['valid_files'] += 1
                                    else:
                                        result['invalid_files'] += 1
                                        result['errors'].append(f"文件为空: {file_path}")
                                except Exception as e:
                                    result['invalid_files'] += 1
                                    result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")

        # 验证期权分钟K缓存
        option_minute_dir = cache_dir / 'option_minute'
        if option_minute_dir.exists():
            for contract_dir in option_minute_dir.iterdir():
                if contract_dir.is_dir():
                    for period_dir in contract_dir.iterdir():
                        if period_dir.is_dir():
                            for file_path in period_dir.glob('*.parquet'):
                                result['total_files'] += 1
                                try:
                                    df = pd.read_parquet(file_path)
                                    if df is not None and not df.empty:
                                        result['valid_files'] += 1
                                    else:
                                        result['invalid_files'] += 1
                                        result['errors'].append(f"文件为空: {file_path}")
                                except Exception as e:
                                    result['invalid_files'] += 1
                                    result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")
        
        # 验证期权Greeks缓存
        option_greeks_dir = cache_dir / 'option_greeks'
        if option_greeks_dir.exists():
            for contract_dir in option_greeks_dir.iterdir():
                if contract_dir.is_dir():
                    for file_path in contract_dir.glob('*.parquet'):
                        result['total_files'] += 1
                        try:
                            df = pd.read_parquet(file_path)
                            if df is not None and not df.empty:
                                result['valid_files'] += 1
                            else:
                                result['invalid_files'] += 1
                                result['errors'].append(f"文件为空: {file_path}")
                        except Exception as e:
                            result['invalid_files'] += 1
                            result['errors'].append(f"文件损坏: {file_path}, 错误: {e}")
        
        logger.info(f"缓存验证完成: 总计 {result['total_files']} 个文件, "
                   f"有效 {result['valid_files']} 个, 无效 {result['invalid_files']} 个")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'validate_cache'},
            "验证缓存失败"
        )
        return {'total_files': 0, 'valid_files': 0, 'invalid_files': 0, 'errors': []}


def get_cached_option_minute(
    contract_code: str,
    date: str,
    period: Optional[str] = None,
    config: Optional[Dict] = None
) -> Optional[pd.DataFrame]:
    """
    获取缓存的期权分钟K数据
    
    Args:
        contract_code: 期权合约代码
        date: 日期字符串（格式：YYYYMMDD）
        period: 周期（可选，如 '15', '30'）
        config: 系统配置
    
    Returns:
        pd.DataFrame: 缓存的数据，如果不存在返回None
    """
    try:
        cache_path = get_cache_file_path('option_minute', contract_code, date, period=period, config=config)
        cached_df = load_cached_data(cache_path)
        
        if cached_df is not None and not cached_df.empty:
            logger.debug(f"期权分钟K数据缓存命中: {contract_code}, {date}, period={period}")
            return cached_df
        
        return None
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_option_minute',
                'contract_code': contract_code,
                'date': date,
                'period': period
            },
            "获取缓存数据失败"
        )
        return None


def save_option_minute_cache(
    contract_code: str,
    df: pd.DataFrame,
    period: Optional[str] = None,
    config: Optional[Dict] = None
) -> bool:
    """
    保存期权分钟K数据到缓存（按日期拆分保存）
    
    Args:
        contract_code: 期权合约代码
        df: 分钟数据DataFrame
        period: 周期（可选，如 '15', '30'）
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if df is None or df.empty:
            return False
        
        # 找到日期/时间列
        date_col = None
        for col in ['时间', '日期', 'date', '日期时间', 'datetime', '时间戳']:
            if col in df.columns:
                date_col = col
                break
        
        if not date_col:
            logger.warning("无法找到日期列，无法按日期拆分保存缓存")
            return False
        
        # 确保日期列为datetime类型
        # 如果已经是datetime类型，跳过转换；否则使用errors='coerce'避免警告
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce', )
        
        # 按日期分组保存
        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_cache_file_path('option_minute', contract_code, date_str, period=period, config=config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1
        
        logger.info(f"期权分钟K数据已保存到缓存: {contract_code}, period={period}, {saved_count} 个日期")
        return saved_count > 0
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_option_minute_cache', 'contract_code': contract_code, 'period': period},
            "保存缓存失败"
        )
        return False


def find_closest_cached_date(
    data_type: str,
    symbol: str,
    target_date: str,
    max_days_back: int = 30,
    config: Optional[Dict] = None
) -> Optional[str]:
    """
    查找最接近目标日期的缓存日期（在目标日期之前最近的交易日）
    
    Args:
        data_type: 数据类型（'option_greeks', 'option_minute' 等）
        symbol: 合约代码
        target_date: 目标日期字符串（格式：YYYYMMDD）
        max_days_back: 最多往前查找的天数（默认30天）
        config: 系统配置
    
    Returns:
        Optional[str]: 最接近的缓存日期（格式：YYYYMMDD），如果不存在返回None
    """
    try:
        from datetime import datetime, timedelta
        
        contract_code_str = str(symbol)
        cache_dir = get_cache_dir(config)
        
        # 构建缓存目录路径
        if data_type == 'option_greeks':
            cache_base_dir = cache_dir / 'option_greeks' / contract_code_str
        elif data_type == 'option_minute':
            cache_base_dir = cache_dir / 'option_minute' / contract_code_str
        else:
            logger.warning(f"不支持的数据类型: {data_type}")
            return None
        
        if not cache_base_dir.exists():
            return None
        
        # 解析目标日期
        target_dt = datetime.strptime(target_date, '%Y%m%d')
        
        # 从目标日期往前查找，最多查找 max_days_back 天
        current_dt = target_dt
        for _ in range(max_days_back):
            # 跳过周末
            if current_dt.weekday() >= 5:  # 周六=5, 周日=6
                current_dt = current_dt - timedelta(days=1)
                continue
            
            check_date = current_dt.strftime('%Y%m%d')
            cache_path = get_cache_file_path(data_type, contract_code_str, check_date, config=config)
            
            if cache_path.exists():
                logger.debug(f"找到最接近的缓存日期: {check_date} (目标日期: {target_date})")
                return check_date
            
            # 往前推一天
            current_dt = current_dt - timedelta(days=1)
        
        return None
        
    except Exception as e:
        logger.debug(f"查找最接近缓存日期失败: {e}")
        return None


def get_cached_option_greeks(
    contract_code: str,
    date: str,
    use_closest: bool = True,
    config: Optional[Dict] = None
) -> Optional[pd.DataFrame]:
    """
    获取缓存的期权Greeks数据
    
    Args:
        contract_code: 期权合约代码（可以是字符串或整数）
        date: 日期字符串（格式：YYYYMMDD 或 YYYYMMDD hh:mm:ss）
        use_closest: 如果精确日期不存在，是否查找最接近的缓存日期（默认True）
        config: 系统配置
    
    Returns:
        pd.DataFrame: 缓存的数据，如果不存在返回None
    """
    try:
        # 确保 contract_code 是字符串类型，用于路径拼接
        contract_code_str = str(contract_code)
        # 提取日期部分（YYYYMMDD），忽略时间部分
        date_only = date[:8] if len(date) >= 8 else date
        cache_path = get_cache_file_path('option_greeks', contract_code_str, date_only, config=config)
        cached_df = load_cached_data(cache_path)
        
        if cached_df is not None and not cached_df.empty:
            logger.debug(f"期权Greeks数据缓存命中: {contract_code}, {date}")
            return cached_df
        
        # 如果精确日期不存在，且允许查找最接近的缓存
        if use_closest:
            closest_date = find_closest_cached_date('option_greeks', contract_code_str, date_only, config=config)
            if closest_date:
                closest_path = get_cache_file_path('option_greeks', contract_code_str, closest_date, config=config)
                closest_df = load_cached_data(closest_path)
                if closest_df is not None and not closest_df.empty:
                    logger.info(f"使用最接近的缓存日期: {contract_code}, 目标日期: {date}, 实际使用: {closest_date}")
                    return closest_df
        
        return None
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_cached_option_greeks',
                'contract_code': contract_code,
                'date': date
            },
            "获取缓存数据失败"
        )
        return None


def save_option_greeks_cache(
    contract_code: str,
    greeks_data: pd.DataFrame,
    date: str,
    config: Optional[Dict] = None
) -> bool:
    """
    保存期权Greeks数据到缓存（追加模式，按时间戳去重）
    
    Args:
        contract_code: 期权合约代码
        greeks_data: Greeks数据DataFrame
        date: 日期字符串（格式：YYYYMMDD）
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if greeks_data is None or greeks_data.empty:
            return False
        
        cache_path = get_cache_file_path('option_greeks', contract_code, date, config=config)
        
        # 添加时间戳列（如果不存在）
        if '采集时间' not in greeks_data.columns and 'timestamp' not in greeks_data.columns:
            from datetime import datetime
            greeks_data = greeks_data.copy()
            greeks_data['采集时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 如果文件已存在，读取现有数据并合并（追加模式）
        if cache_path.exists():
            try:
                existing_df = load_cached_data(cache_path)
                if existing_df is not None and not existing_df.empty:
                    # 检查时间戳列，避免重复保存相同时间点的数据
                    time_col = None
                    for col in ['采集时间', 'timestamp', '时间', '日期时间', 'datetime']:
                        if col in existing_df.columns and col in greeks_data.columns:
                            time_col = col
                            break
                    
                    if time_col:
                        # 检查新数据的时间戳是否已存在
                        existing_timestamps = set(existing_df[time_col].astype(str))
                        
                        # 只添加新的时间点数据
                        new_rows = greeks_data[~greeks_data[time_col].astype(str).isin(existing_timestamps)]
                        if not new_rows.empty:
                            combined_df = pd.concat([existing_df, new_rows], ignore_index=True)
                            # 按时间排序
                            combined_df = combined_df.sort_values(by=time_col)
                            greeks_data = combined_df
                            logger.debug(f"合并Greeks数据: {contract_code}, {date}, 新增 {len(new_rows)} 条, 总计 {len(combined_df)} 条")
                        else:
                            logger.info(f"Greeks数据已存在（时间戳相同）: {contract_code}, {date}, 跳过保存")
                            return True
                    else:
                        # 没有时间戳列，直接合并（去重）
                        combined_df = pd.concat([existing_df, greeks_data], ignore_index=True)
                        combined_df = combined_df.drop_duplicates(keep='last')
                        greeks_data = combined_df
                        logger.debug(f"合并Greeks数据: {contract_code}, {date}, 总计 {len(combined_df)} 条")
            except Exception as e:
                logger.warning(f"读取现有Greeks数据失败，将覆盖保存: {e}")
        
        if save_cached_data(greeks_data, cache_path):
            logger.info(f"期权Greeks数据已保存到缓存: {contract_code}, {date}, {len(greeks_data)} 条")
            return True
        
        return False
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_option_greeks_cache', 'contract_code': contract_code, 'date': date},
            "保存缓存失败"
        )
        return False


def get_previous_trading_day_option_data(
    contract_code: str,
    period: Optional[str] = None,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    获取前一交易日的期权数据（分钟K和Greeks）
    
    Args:
        contract_code: 期权合约代码
        period: 周期（可选，如 '15', '30'）
        config: 系统配置
    
    Returns:
        Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]: 
            - 前一交易日的分钟K数据
            - 前一交易日的Greeks数据
    """
    try:
        from datetime import datetime, timedelta
        import pytz
        
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        today = datetime.now(tz_shanghai)
        
        # 计算前一交易日（跳过周末）
        previous_day = today - timedelta(days=1)
        while previous_day.weekday() >= 5:  # 周六=5, 周日=6
            previous_day = previous_day - timedelta(days=1)
        
        previous_date = previous_day.strftime('%Y%m%d')
        
        # 获取前一交易日的分钟K数据
        minute_data = get_cached_option_minute(contract_code, previous_date, period=period, config=config)
        
        # 获取前一交易日的Greeks数据
        greeks_data = get_cached_option_greeks(contract_code, previous_date, config=config)
        
        if minute_data is not None or greeks_data is not None:
            logger.info(f"获取前一交易日期权数据: {contract_code}, {previous_date}, "
                       f"分钟K: {'有' if minute_data is not None else '无'}, "
                       f"Greeks: {'有' if greeks_data is not None else '无'}")
        
        return minute_data, greeks_data
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'get_previous_trading_day_option_data',
                'contract_code': contract_code,
                'period': period
            },
            "获取前一交易日期权数据失败"
        )
        return None, None


def aggregate_daily_greeks_data(
    contract_code: str,
    date: str,
    config: Optional[Dict] = None,
    method: str = 'mean'  # 'mean', 'median', 'close', 'last'
) -> Optional[pd.DataFrame]:
    """
    汇聚当天的Greeks数据，生成代表性数据点
    
    Args:
        contract_code: 期权合约代码
        date: 日期字符串（格式：YYYYMMDD）
        config: 系统配置
        method: 汇聚方法
            - 'mean': 平均值（推荐，用于GARCH模型）
            - 'median': 中位数
            - 'close': 收盘时的值（15:00附近）
            - 'last': 最后一次的值
    
    Returns:
        pd.DataFrame: 汇聚后的Greeks数据，如果失败返回None
    """
    try:
        cache_path = get_cache_file_path('option_greeks', contract_code, date, config=config)
        
        if not cache_path.exists():
            logger.warning(f"当天Greeks数据不存在: {contract_code}, {date}")
            return None
        
        # 读取当天所有的Greeks数据
        all_greeks_df = load_cached_data(cache_path)
        if all_greeks_df is None or all_greeks_df.empty:
            logger.warning(f"当天Greeks数据为空: {contract_code}, {date}")
            return None
        
        logger.info(f"读取当天Greeks数据: {contract_code}, {date}, 共 {len(all_greeks_df)} 条记录")
        
        # 找到时间戳列
        time_col = None
        for col in ['采集时间', 'timestamp', '时间', '日期时间', 'datetime']:
            if col in all_greeks_df.columns:
                time_col = col
                break
        
        # 根据汇聚方法生成代表性数据点
        if method == 'close':
            # 使用收盘时的值（15:00附近）
            if time_col:
                # 转换为datetime类型以便比较
                all_greeks_df = all_greeks_df.copy()
                if not pd.api.types.is_datetime64_any_dtype(all_greeks_df[time_col]):
                    all_greeks_df[time_col] = pd.to_datetime(all_greeks_df[time_col], errors='coerce')
                
                # 找到最接近15:00的记录
                target_time = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8] + ' 15:00:00')
                time_diffs = (all_greeks_df[time_col] - target_time).abs()
                closest_idx = time_diffs.idxmin()
                aggregated_df = all_greeks_df.loc[[closest_idx]].copy()
                logger.info(f"使用收盘时的Greeks数据: {contract_code}, {date}, 时间: {all_greeks_df.loc[closest_idx, time_col]}")
            else:
                # 没有时间戳列，使用最后一条
                aggregated_df = all_greeks_df.iloc[[-1]].copy()
                logger.info(f"使用最后一条Greeks数据: {contract_code}, {date}")
        
        elif method == 'last':
            # 使用最后一次的值
            aggregated_df = all_greeks_df.iloc[[-1]].copy()
            if time_col:
                logger.info(f"使用最后一次Greeks数据: {contract_code}, {date}, 时间: {aggregated_df[time_col].iloc[0]}")
            else:
                logger.info(f"使用最后一次Greeks数据: {contract_code}, {date}")
        
        elif method == 'mean':
            # 使用平均值（推荐用于GARCH模型）
            # Greeks数据格式是"字段-值"格式，需要按字段分组汇聚
            if '字段' in all_greeks_df.columns and '值' in all_greeks_df.columns:
                # 按字段分组，对每个字段的值计算平均值
                aggregated_rows = []
                unique_fields = all_greeks_df['字段'].unique()
                
                for field in unique_fields:
                    field_data = all_greeks_df[all_greeks_df['字段'] == field]
                    
                    # 提取"值"列并计算平均值
                    try:
                        values = pd.to_numeric(field_data['值'], errors='coerce')
                        if not values.isna().all():
                            mean_value = values.mean()
                        else:
                            # 如果无法转换为数值，使用第一个值
                            mean_value = field_data['值'].iloc[0]
                    except (ValueError, TypeError):
                        mean_value = field_data['值'].iloc[0]
                    
                    # 创建汇聚后的行
                    row_dict = {'字段': field, '值': mean_value}
                    # 保留其他列（如果有）
                    for col in all_greeks_df.columns:
                        if col not in ['字段', '值', time_col]:
                            row_dict[col] = field_data[col].iloc[0]
                    
                    aggregated_rows.append(row_dict)
                
                aggregated_df = pd.DataFrame(aggregated_rows)
                
                # 添加时间戳
                if time_col:
                    aggregated_df[time_col] = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8] + ' 15:30:00').strftime('%Y-%m-%d %H:%M:%S')
                elif '采集时间' not in aggregated_df.columns:
                    aggregated_df['采集时间'] = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8] + ' 15:30:00').strftime('%Y-%m-%d %H:%M:%S')
                
                logger.info(f"使用平均值汇聚Greeks数据: {contract_code}, {date}, 基于 {len(all_greeks_df)} 条记录, {len(unique_fields)} 个字段")
            else:
                # 如果不是标准格式，使用原来的逻辑
                aggregated_df = all_greeks_df.copy()
                for col in aggregated_df.columns:
                    if col == time_col or col in ['字段', 'field']:
                        continue
                    try:
                        numeric_values = pd.to_numeric(aggregated_df[col], errors='coerce')
                        if not numeric_values.isna().all():
                            mean_value = numeric_values.mean()
                            aggregated_df[col] = mean_value
                    except (ValueError, TypeError):
                        aggregated_df[col] = aggregated_df[col].iloc[0]
                aggregated_df = aggregated_df.iloc[[0]].copy()
                if time_col:
                    aggregated_df[time_col] = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8] + ' 15:30:00').strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"使用平均值汇聚Greeks数据: {contract_code}, {date}, 基于 {len(all_greeks_df)} 条记录")
        
        elif method == 'median':
            # 使用中位数
            # Greeks数据格式是"字段-值"格式，需要按字段分组汇聚
            if '字段' in all_greeks_df.columns and '值' in all_greeks_df.columns:
                aggregated_rows = []
                unique_fields = all_greeks_df['字段'].unique()
                
                for field in unique_fields:
                    field_data = all_greeks_df[all_greeks_df['字段'] == field]
                    
                    try:
                        values = pd.to_numeric(field_data['值'], errors='coerce')
                        if not values.isna().all():
                            median_value = values.median()
                        else:
                            median_value = field_data['值'].iloc[0]
                    except (ValueError, TypeError):
                        median_value = field_data['值'].iloc[0]
                    
                    row_dict = {'字段': field, '值': median_value}
                    for col in all_greeks_df.columns:
                        if col not in ['字段', '值', time_col]:
                            row_dict[col] = field_data[col].iloc[0]
                    
                    aggregated_rows.append(row_dict)
                
                aggregated_df = pd.DataFrame(aggregated_rows)
                
                if time_col:
                    aggregated_df[time_col] = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8] + ' 15:30:00').strftime('%Y-%m-%d %H:%M:%S')
                elif '采集时间' not in aggregated_df.columns:
                    aggregated_df['采集时间'] = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8] + ' 15:30:00').strftime('%Y-%m-%d %H:%M:%S')
                
                logger.info(f"使用中位数汇聚Greeks数据: {contract_code}, {date}, 基于 {len(all_greeks_df)} 条记录, {len(unique_fields)} 个字段")
            else:
                aggregated_df = all_greeks_df.copy()
                for col in aggregated_df.columns:
                    if col == time_col or col in ['字段', 'field']:
                        continue
                    try:
                        numeric_values = pd.to_numeric(aggregated_df[col], errors='coerce')
                        if not numeric_values.isna().all():
                            median_value = numeric_values.median()
                            aggregated_df[col] = median_value
                    except (ValueError, TypeError):
                        aggregated_df[col] = aggregated_df[col].iloc[0]
                aggregated_df = aggregated_df.iloc[[0]].copy()
                if time_col:
                    aggregated_df[time_col] = pd.Timestamp(date[:4] + '-' + date[4:6] + '-' + date[6:8] + ' 15:30:00').strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"使用中位数汇聚Greeks数据: {contract_code}, {date}, 基于 {len(all_greeks_df)} 条记录")
        
        else:
            logger.warning(f"未知的汇聚方法: {method}，使用平均值")
            return aggregate_daily_greeks_data(contract_code, date, config, method='mean')
        
        # 添加汇聚标记
        aggregated_df['汇聚方法'] = method
        aggregated_df['原始记录数'] = len(all_greeks_df)
        
        return aggregated_df
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'aggregate_daily_greeks_data',
                'contract_code': contract_code,
                'date': date,
                'method': method
            },
            "汇聚当天Greeks数据失败"
        )
        return None


def aggregate_all_contracts_greeks_data(
    date: str,
    config: Optional[Dict] = None,
    method: str = 'mean'
) -> Dict[str, pd.DataFrame]:
    """
    汇聚所有合约当天的Greeks数据
    
    Args:
        date: 日期字符串（格式：YYYYMMDD）
        config: 系统配置
        method: 汇聚方法（'mean', 'median', 'close', 'last'）
    
    Returns:
        Dict[str, pd.DataFrame]: {contract_code: aggregated_df}
    """
    try:
        if config is None:
            config = load_system_config()
        
        from src.config_loader import get_underlyings
        
        option_contracts = config.get('option_contracts', {})
        underlyings_list = get_underlyings(option_contracts)
        
        aggregated_data = {}
        
        for underlying_config in underlyings_list:
            call_contracts_config = underlying_config.get('call_contracts', [])
            put_contracts_config = underlying_config.get('put_contracts', [])
            
            # 汇聚Call合约
            for call_config in call_contracts_config:
                contract_code = call_config.get('contract_code')
                if contract_code:
                    aggregated_df = aggregate_daily_greeks_data(contract_code, date, config, method)
                    if aggregated_df is not None:
                        aggregated_data[contract_code] = aggregated_df
            
            # 汇聚Put合约
            for put_config in put_contracts_config:
                contract_code = put_config.get('contract_code')
                if contract_code:
                    aggregated_df = aggregate_daily_greeks_data(contract_code, date, config, method)
                    if aggregated_df is not None:
                        aggregated_data[contract_code] = aggregated_df
        
        logger.info(f"汇聚完成: {date}, 共 {len(aggregated_data)} 个合约")
        return aggregated_data
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'aggregate_all_contracts_greeks_data',
                'date': date,
                'method': method
            },
            "汇聚所有合约Greeks数据失败"
        )
        return {}
