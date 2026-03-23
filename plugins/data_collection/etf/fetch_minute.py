"""
获取ETF分钟数据
融合 Coze 插件 get_etf_minute.py
OpenClaw 插件工具
改进版本：支持缓存、多ETF、自动计算成交额/涨跌幅、完善字段映射
"""

import requests
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import pytz
import os
import sys

# 导入交易日判断工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.trading_day import check_trading_day_before_operation
    TRADING_DAY_CHECK_AVAILABLE = True
except ImportError:
    TRADING_DAY_CHECK_AVAILABLE = False

    def check_trading_day_before_operation(*args, **kwargs):
        return None

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

try:
    from mootdx.quotes import Quotes
    MOOTDX_AVAILABLE = True
except Exception:  # noqa: BLE001
    MOOTDX_AVAILABLE = False

# 尝试导入缓存与配置模块（优先使用当前环境下的本地 src 包）
try:
    selected_root = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "src").exists():
            selected_root = parent
            break

    CACHE_AVAILABLE = False
    if selected_root is not None:
        if str(selected_root) not in sys.path:
            sys.path.insert(0, str(selected_root))
        from src.data_cache import (
            get_cached_etf_minute, save_etf_minute_cache,
            merge_cached_and_fetched_data
        )
        from src.config_loader import load_system_config
        CACHE_AVAILABLE = True
except Exception:
    CACHE_AVAILABLE = False


def _is_dataframe(obj: Any) -> bool:
    """统一 DataFrame 类型检查，避免对 None/非DataFrame对象访问 .columns。"""
    return isinstance(obj, pd.DataFrame)


def normalize_date(date_str: str) -> str:
    """统一日期格式为 YYYY-MM-DD HH:MM:SS"""
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 09:30:00"
    elif len(date_str) == 10 and '-' in date_str:
        return f"{date_str} 09:30:00"
    else:
        return date_str


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一字段名映射：将英文字段名转换为中文字段名
    
    Args:
        df: 原始DataFrame
    
    Returns:
        DataFrame: 字段名统一后的DataFrame
    """
    if not _is_dataframe(df) or df.empty:
        return df
    
    column_mapping = {}
    
    # 时间字段
    if 'time' in df.columns and '时间' not in df.columns:
        column_mapping['time'] = '时间'
    if 'date' in df.columns and '时间' not in df.columns:
        column_mapping['date'] = '时间'
    if 'datetime' in df.columns and '时间' not in df.columns:
        column_mapping['datetime'] = '时间'
    if 'day' in df.columns and '时间' not in df.columns:
        column_mapping['day'] = '时间'
    
    # 价格字段
    if 'open' in df.columns and '开盘' not in df.columns:
        column_mapping['open'] = '开盘'
    if 'close' in df.columns and '收盘' not in df.columns:
        column_mapping['close'] = '收盘'
    if 'high' in df.columns and '最高' not in df.columns:
        column_mapping['high'] = '最高'
    if 'low' in df.columns and '最低' not in df.columns:
        column_mapping['low'] = '最低'
    
    # 成交量字段
    if 'volume' in df.columns and '成交量' not in df.columns:
        column_mapping['volume'] = '成交量'
    if 'vol' in df.columns and '成交量' not in df.columns:
        column_mapping['vol'] = '成交量'
    
    # 成交额字段
    if 'amount' in df.columns and '成交额' not in df.columns:
        column_mapping['amount'] = '成交额'
    
    if column_mapping:
        df = df.rename(columns=column_mapping)
    
    return df


def calculate_missing_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    自动计算缺失的成交额和涨跌幅
    
    Args:
        df: DataFrame（需要包含'成交量'和'收盘'列）
    
    Returns:
        DataFrame: 补充了成交额和涨跌幅的DataFrame
    """
    if not _is_dataframe(df) or df.empty:
        return df


    df = df.copy()

    # 1) 计算成交额（如果缺失或全为0）
    if "成交额" not in df.columns or df["成交额"].isna().all() or (df["成交额"] == 0).all():
        if "成交量" in df.columns and "收盘" in df.columns:
            vol = pd.to_numeric(df["成交量"], errors="coerce")
            close = pd.to_numeric(df["收盘"], errors="coerce")
            # 成交量常见单位为“手”，乘以100换算为股数
            df["成交额"] = vol * close * 100
        else:
            df["成交额"] = 0

    # 2) 计算涨跌幅（如果缺失）
    if "涨跌幅" not in df.columns:
        if "收盘" in df.columns:
            close = pd.to_numeric(df["收盘"], errors="coerce")
            df["涨跌幅"] = close.pct_change() * 100
            df["涨跌幅"] = df["涨跌幅"].replace([np.inf, -np.inf], np.nan).fillna(0)
        else:
            df["涨跌幅"] = 0

    return df


def _fetch_etf_minute_mootdx(
    etf_code: str,
    period: str,
    start_date_str: str,
    end_date_str: str,
    max_bars: int = 800,
) -> Optional[pd.DataFrame]:
    """
    使用 mootdx 获取 ETF 分钟数据。

    参数:
        etf_code: 可以是 510300 / sh510300 / 510300.SH 等
        period: "1", "5", "15", "30", "60"
    """
    if not MOOTDX_AVAILABLE:
        return None

    clean = etf_code
    if clean.upper().endswith((".SH", ".SZ", ".BJ")):
        clean = clean.split(".")[0]
    if clean.lower().startswith(("sh", "sz", "bj")) and len(clean) > 2:
        clean = clean[2:]

    freq_map = {
        "1": 7,
        "5": 0,
        "15": 1,
        "30": 2,
        "60": 3,
    }
    frequency = freq_map.get(period)
    if frequency is None:
        return None

    try:
        client = Quotes.factory(market="std")
    except Exception:
        return None

    try:
        df = client.bars(symbol=clean, frequency=frequency, offset=max_bars)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df = df.copy()
    if "datetime" in df.columns and "时间" not in df.columns:
        df["时间"] = pd.to_datetime(df["datetime"], errors="coerce")

    df = normalize_column_names(df)
    df = calculate_missing_fields(df)

    if "时间" in df.columns:
        try:
            df["时间"] = pd.to_datetime(df["时间"], errors="coerce")
            df = df[df["时间"].notna()].copy()
            df["时间"] = df["时间"].dt.strftime("%Y-%m-%d %H:%M:%S")

            start_dt = datetime.strptime(start_date_str[:19], "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(end_date_str[:19], "%Y-%m-%d %H:%M:%S")
            times = pd.to_datetime(df["时间"], errors="coerce")
            mask = (times >= start_dt) & (times <= end_dt)
            df = df[mask].copy()
        except Exception:
            pass

    if df.empty:
        return None

    return df


def _get_latest_cached_timestamp_etf(
    symbol: str,
    period: str,
    date_yyyymmdd: str,
    config: Optional[Dict] = None
) -> Optional[datetime]:
    """
    获取指定 symbol/period/date 的缓存中最新一条数据的时间戳。
    用于判断缓存新鲜度：若 (当前时间 - 最新时间) > period 分钟，则需要拉取。

    symbol: 纯净代码如 510300，不含 sh/sz 前缀

    Returns:
        最新时间（上海时区），若无缓存返回 None
    """
    if not CACHE_AVAILABLE:
        return None
    try:
        cached_df, missing = get_cached_etf_minute(
            symbol, period, date_yyyymmdd, date_yyyymmdd, config=config
        )
        if not _is_dataframe(cached_df) or cached_df.empty:
            return None
        time_col = None
        for col in ['时间', 'date', '日期时间', 'datetime']:
            if col in cached_df.columns:
                time_col = col
                break
        if not time_col:
            return None
        last_val = cached_df[time_col].iloc[-1]
        if pd.isna(last_val):
            return None
        dt = pd.to_datetime(last_val)
        if hasattr(dt, 'to_pydatetime'):
            dt = dt.to_pydatetime()
        tz_sh = pytz.timezone('Asia/Shanghai')
        if dt.tzinfo is None:
            dt = tz_sh.localize(dt)
        elif str(dt.tzinfo) != 'Asia/Shanghai':
            dt = dt.astimezone(tz_sh)
        return dt
    except Exception:
        return None


def _fetch_etf_minute_sina(
    etf_code: str,
    period: str,
    start_date_str: str,
    end_date_str: str,
    lookback_days: int
) -> Optional[pd.DataFrame]:
    """
    使用新浪接口获取ETF分钟数据
    参照Coze版本和原系统的实现逻辑
    """
    try:
        # ETF代码转换：转换为新浪财经格式（sh/sz前缀）
        if etf_code.startswith('sh') or etf_code.startswith('sz'):
            sina_symbol = etf_code
            clean_code = etf_code[2:]
        else:
            clean_code = etf_code
            if clean_code.startswith("51") or clean_code.startswith("588"):
                sina_symbol = f"sh{clean_code}"  # 上交所ETF
            elif clean_code.startswith("159"):
                sina_symbol = f"sz{clean_code}"  # 深交所ETF
            else:
                sina_symbol = f"sh{clean_code}"  # 默认上交所
        
        # 周期映射：转换为新浪财经的scale参数
        period_to_scale = {
            "5": 5,
            "15": 15,
            "30": 30,
            "60": 60
        }
        scale = period_to_scale.get(period)
        if scale is None:
            return None
        
        # 计算datalen参数（新浪接口限制：datalen最大1023）
        try:
            start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
            end_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
            days_diff = (end_dt - start_dt).days + 1
            # 估算：每个交易日约4小时 = 240分钟，按周期计算数据点数
            estimated_points = int(days_diff * (240 / scale) * 1.2)
            datalen = min(estimated_points, 1023)  # 新浪接口限制
        except Exception:
            datalen = 1023  # 默认值
        
        # 调用新浪接口
        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": sina_symbol,
            "scale": scale,
            "ma": "no",  # 不计算均线
            "datalen": datalen
        }
        
        headers = {
            "Referer": "http://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None
        
        # 解析JSON响应
        try:
            data = response.json()
        except ValueError:
            return None
        
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        
        # 转换为DataFrame并统一格式
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
        if not available_columns:
            return None
        
        df = df[available_columns].copy()
        df = df.rename(columns=column_mapping)
        
        # 添加成交额列（新浪接口不提供，设为0，后续会自动计算）
        if "成交额" not in df.columns:
            df["成交额"] = 0.0
        
        # 确保时间列为datetime类型，然后转换为字符串格式
        if "时间" in df.columns:
            df["时间"] = pd.to_datetime(df["时间"], errors='coerce')
            df = df[df["时间"].notna()].copy()
            df["时间"] = df["时间"].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 确保数值列为float类型
        numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 按时间排序
        if "时间" in df.columns:
            df = df.sort_values("时间").reset_index(drop=True)
        
        # 日期范围过滤
        if start_date_str and end_date_str:
            try:
                start_dt = datetime.strptime(start_date_str[:19], "%Y-%m-%d %H:%M:%S")
                end_dt = datetime.strptime(end_date_str[:19], "%Y-%m-%d %H:%M:%S")
                
                df_time = pd.to_datetime(df["时间"], errors='coerce')
                mask = (df_time >= start_dt) & (df_time <= end_dt)
                filtered_df = df[mask].copy()
                
                # 如果过滤后数据为空，放宽过滤条件（只过滤结束时间）
                if filtered_df.empty and not df.empty:
                    mask = df_time <= end_dt
                    filtered_df = df[mask].copy()
                
                df = filtered_df
            except Exception:
                pass
        
        if df.empty:
            return None
        
        return df
        
    except Exception:
        return None


def fetch_single_etf_minute(
    etf_code: str,
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    use_cache: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    获取单个ETF的分钟数据
    
    Returns:
        Tuple[Optional[pd.DataFrame], Optional[str]]: (数据DataFrame, 数据源名称)
    """
    # ETF代码映射
    etf_mapping = {
        "510300": {"name": "沪深300ETF", "market": "sh"},
        "510050": {"name": "上证50ETF", "market": "sh"},
        "510500": {"name": "中证500ETF", "market": "sh"},
        "159919": {"name": "沪深300ETF", "market": "sz"},
        "159915": {"name": "创业板ETF", "market": "sz"},
    }
    
    if period not in ["1", "5", "15", "30", "60"]:
        return None, None
    
    # 计算日期范围
    now = datetime.now()
    if not end_date:
        end_date_str = now.strftime("%Y-%m-%d 15:00:00")
    else:
        end_date_str = normalize_date(end_date)
        if not end_date_str.endswith(" 15:00:00"):
            end_date_str = end_date_str.replace(" 09:30:00", " 15:00:00")
    
    if not start_date:
        start = now - timedelta(days=lookback_days * 2)  # 乘以2以确保包含非交易日
        start_date_str = start.strftime("%Y-%m-%d 09:30:00")
    else:
        start_date_str = normalize_date(start_date)
    
    # 构建ETF符号
    if etf_code.startswith('sh') or etf_code.startswith('sz'):
        sina_symbol = etf_code
        clean_code = etf_code[2:]
    else:
        clean_code = etf_code
        if clean_code.startswith('510') or clean_code.startswith('511') or clean_code.startswith('512'):
            sina_symbol = f"sh{clean_code}"
        elif clean_code.startswith('159'):
            sina_symbol = f"sz{clean_code}"
        else:
            sina_symbol = f"sh{clean_code}"
    
    df = None
    source = None
    cached_partial_df = None
    
    # ========== 缓存逻辑：先检查缓存 ==========
    if use_cache and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True)
            # 转换日期格式为YYYYMMDD
            start_date_formatted = start_date_str[:10].replace("-", "")
            end_date_formatted = end_date_str[:10].replace("-", "")
            
            cached_df, missing_dates = get_cached_etf_minute(
                clean_code, period, start_date_formatted, end_date_formatted, config=config
            )
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中，直接返回
                return cached_df, "cache"
            
            if cached_df is not None and not cached_df.empty and missing_dates:
                # 部分缓存命中，保存用于后续合并
                cached_partial_df = cached_df
                # 调整日期范围，只获取缺失部分
                if missing_dates:
                    start_date_formatted = min(missing_dates)
                    end_date_formatted = max(missing_dates)
                    # 更新start_date_str和end_date_str用于后续筛选
                    start_date_str = f"{start_date_formatted[:4]}-{start_date_formatted[4:6]}-{start_date_formatted[6:8]} 09:30:00"
                    end_date_str = f"{end_date_formatted[:4]}-{end_date_formatted[4:6]}-{end_date_formatted[6:8]} 15:00:00"
        except Exception:
            # 缓存失败不影响主流程
            pass
    # ========== 缓存逻辑结束 ==========
    
    # 方法1：优先使用 mootdx 分钟K线（如果可用）
    df = _fetch_etf_minute_mootdx(
        etf_code=etf_code,
        period=period,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
    )
    if df is not None and not df.empty:
        source = "mootdx"

    # 方法2：尝试使用新浪接口（主数据源，不支持1分钟）
    if (df is None or df.empty) and period != "1":
        try:
            temp_df = _fetch_etf_minute_sina(clean_code, period, start_date_str, end_date_str, lookback_days)
            if temp_df is not None and not temp_df.empty:
                df = temp_df
                # 统一字段名
                df = normalize_column_names(df)
                # 计算缺失字段
                df = calculate_missing_fields(df)
                source = "sina"
        except Exception:
            pass
    
    # 方法3：使用东方财富接口（备用）
    if df is None or df.empty:
        try:
            temp_df = ak.fund_etf_hist_min_em(
                symbol=clean_code,
                period=period,
                adjust="",
                start_date=start_date_str,
                end_date=end_date_str
            )
            if temp_df is not None and not temp_df.empty:
                # 统一字段名
                temp_df = normalize_column_names(temp_df)
                df = temp_df.copy()
                # 计算缺失字段
                df = calculate_missing_fields(df)
                source = "eastmoney"
        except Exception:
            pass
    
    # ========== 合并部分缓存数据 ==========
    if df is not None and not df.empty and cached_partial_df is not None:
        try:
            # 安全检查：确保df有columns属性
            if _is_dataframe(df):
                # 找到时间列
                time_col = None
                for col in ['时间', 'date', '日期时间', 'datetime']:
                    if col in df.columns:
                        time_col = col
                        break
                
                if time_col:
                    df = merge_cached_and_fetched_data(cached_partial_df, df, time_col)
                    source = f"{source}+cache" if source else "cache"
        except Exception:
            pass
    # ========== 缓存合并结束 ==========
    
    # 如果外部数据源完全失败，但有部分缓存数据，优先返回缓存（避免“空数据”）
    if (not _is_dataframe(df) or df.empty) and _is_dataframe(cached_partial_df) and not cached_partial_df.empty:
        df = cached_partial_df
        if not source:
            source = "cache_partial"
    
    # ========== 保存到缓存 ==========
    if _is_dataframe(df) and not df.empty and use_cache and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True)
            save_etf_minute_cache(clean_code, period, df, config=config)
        except Exception:
            pass
    # ========== 缓存保存结束 ==========
    
    return df, source


def fetch_etf_minute(
    etf_code: str = "510300",
    period: str = "30",  # "5", "15", "30", "60"
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    mode: str = "production",
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    获取ETF分钟数据（融合 Coze get_etf_minute.py）
    支持多ETF查询（逗号分隔）
    
    Args:
        etf_code: ETF代码，支持单个或多个（用逗号分隔），如 "510300" 或 "510300,510050"
        period: 周期，"5", "15", "30", "60" 分钟（注意：新浪不支持1分钟）
        start_date: 开始日期（YYYY-MM-DD 或 YYYYMMDD）
        end_date: 结束日期（YYYY-MM-DD 或 YYYYMMDD），默认今天
        lookback_days: 回看天数（仅在未提供start_date时生效），默认5天
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        api_base_url: 原系统 API 基础地址
        api_key: API Key
        use_cache: 是否使用缓存（默认True）
    
    Returns:
        Dict: 包含分钟数据的字典
    """
    try:
        # ========== 首先判断是否是交易日 ==========
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取ETF分钟数据")
            if trading_day_check:
                return trading_day_check
        # ========== 交易日判断结束 ==========
        
        if not AKSHARE_AVAILABLE:
            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
                'data': None
            }

        # ========== 批量多周期采集模式（5,15,30）：仅缓存，不返回数据 ==========
        if period in ("5,15,30", "all"):
            periods_to_fetch = ["5", "15", "30"]
            tz_sh = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_sh)
            today = now.strftime("%Y%m%d")
            config = None
            if CACHE_AVAILABLE:
                try:
                    config = load_system_config(use_cache=True)
                except Exception:
                    pass
            fetched, skipped = [], []
            etf_mapping = {"510300": {}, "510050": {}, "510500": {}, "159919": {}, "159915": {}}
            if isinstance(etf_code, str):
                etf_codes = [c.strip() for c in etf_code.split(",") if c.strip()]
            else:
                etf_codes = [str(etf_code).strip()]
            clean_codes = []
            for c in etf_codes:
                clean = c[2:] if c.startswith(('sh', 'sz')) else c
                clean_codes.append(clean)
            if not clean_codes:
                return {'success': False, 'message': '未提供有效的ETF代码', 'data': None}
            for clean_code in clean_codes:
                for p in periods_to_fetch:
                    latest_ts = _get_latest_cached_timestamp_etf(clean_code, p, today, config) if CACHE_AVAILABLE else None
                    need_fetch = latest_ts is None
                    if not need_fetch:
                        gap_min = (now - latest_ts).total_seconds() / 60
                        need_fetch = gap_min > int(p)
                    if need_fetch:
                        df_out, _ = fetch_single_etf_minute(clean_code, p, None, None, lookback_days or 5, use_cache)
                        if _is_dataframe(df_out) and not df_out.empty:
                            fetched.append(f"{clean_code}/{p}min")
                        else:
                            skipped.append(f"{clean_code}/{p}min(fetch_failed)")
                    else:
                        skipped.append(f"{clean_code}/{p}min")
            return {
                'success': True,
                'message': '批量采集完成，数据已缓存',
                'data': {'fetched': fetched, 'skipped': skipped}
            }
        # ========== 批量模式结束 ==========
        
        if period not in ["1", "5", "15", "30", "60"]:
            return {
                'success': False,
                'message': f'不支持的周期: {period}，支持: 1, 5, 15, 30, 60',
                'data': None
            }
        
        # ETF代码映射
        etf_mapping = {
            "510300": {"name": "沪深300ETF", "market": "sh"},
            "510050": {"name": "上证50ETF", "market": "sh"},
            "510500": {"name": "中证500ETF", "market": "sh"},
            "159919": {"name": "沪深300ETF", "market": "sz"},
            "159915": {"name": "创业板ETF", "market": "sz"},
        }
        
        # 解析ETF代码（支持单个或多个，用逗号分隔）
        if isinstance(etf_code, str):
            etf_codes = [code.strip() for code in etf_code.split(",") if code.strip()]
        elif isinstance(etf_code, list):
            etf_codes = [str(code).strip() for code in etf_code if str(code).strip()]
        else:
            etf_codes = [str(etf_code).strip()]
        
        if not etf_codes:
            return {
                'success': False,
                'message': '未提供有效的ETF代码',
                'data': None
            }
        
        # 处理多个ETF（逐个获取）
        results = []
        source = None
        
        for etf_code_item in etf_codes:
            # 构建ETF符号
            if etf_code_item.startswith('sh') or etf_code_item.startswith('sz'):
                clean_code = etf_code_item[2:]
            else:
                clean_code = etf_code_item
            
            etf_info = etf_mapping.get(clean_code, {"name": "ETF", "market": "sh"})
            
            # 获取数据
            df, data_source = fetch_single_etf_minute(
                etf_code_item, period, start_date, end_date, lookback_days, use_cache
            )
            
            if data_source:
                source = data_source
            
            if not _is_dataframe(df) or df.empty:
                # 使用降级数据
                results.append({
                    "etf_code": clean_code,
                    "period": period,
                    "count": 0,
                    "klines": [],
                    "message": "ETF分钟数据暂时不可用，请稍后重试"
                })
                continue
            
            # 统一输出格式（Coze平台输出限制：最多返回350条记录）
            MAX_RECORDS = 350
            total_count = len(df)
            
            # 如果数据超过限制，只返回最新的数据
            if total_count > MAX_RECORDS:
                df = df.tail(MAX_RECORDS).copy()
            
            # 转换数据格式
            klines = []
            for _, row in df.iterrows():
                # 安全转换数值，处理NaN和None
                def safe_float(value, default=0.0):
                    try:
                        if value is None or (isinstance(value, float) and (value != value or value == float('inf') or value == float('-inf'))):
                            return default
                        result = float(value)
                        if result != result or result == float('inf') or result == float('-inf'):
                            return default
                        return result
                    except (ValueError, TypeError):
                        return default
                
                def safe_int(value, default=0):
                    try:
                        if value is None or (isinstance(value, float) and (value != value)):
                            return default
                        result = int(float(value))
                        return result
                    except (ValueError, TypeError):
                        return default
                
                # 获取时间
                time_str = ""
                for time_col in ['时间', '日期', 'date', '日期时间', 'datetime']:
                    if time_col in row.index:
                        try:
                            time_str = str(row[time_col])
                            if time_str and time_str != 'nan':
                                break
                        except:
                            pass
                
                klines.append({
                    "time": time_str,
                    "open": safe_float(row.get('开盘', row.get('open', 0))),
                    "close": safe_float(row.get('收盘', row.get('close', 0))),
                    "high": safe_float(row.get('最高', row.get('high', 0))),
                    "low": safe_float(row.get('最低', row.get('low', 0))),
                    "volume": safe_int(row.get('成交量', row.get('volume', 0))),
                    "amount": safe_float(row.get('成交额', row.get('amount', 0))),
                    "change_percent": safe_float(row.get('涨跌幅', row.get('pct_chg', 0)))
                })
            
            # 计算日期字符串用于返回
            now = datetime.now()
            if end_date:
                end_date_display = normalize_date(end_date)[:10]
            else:
                end_date_display = now.strftime("%Y-%m-%d")
            
            if start_date:
                start_date_display = normalize_date(start_date)[:10]
            else:
                start = now - timedelta(days=lookback_days * 2)
                start_date_display = start.strftime("%Y-%m-%d")
            
            result_data = {
                "etf_code": clean_code,
                "period": period,
                "total_count": total_count,  # 实际获取的总数据量
                "returned_count": len(klines),  # 返回的数据量
                "klines": klines,
                "start_date": start_date_display,
                "end_date": end_date_display,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # 如果数据被截断，添加提示
            if total_count > len(klines):
                result_data["note"] = f"共获取{total_count}条数据，因输出限制只返回最新的{len(klines)}条"
            
            results.append(result_data)
        
        # 确保results不为空
        if not results:
            return {
                "success": False,
                "message": "未获取到任何数据",
                "data": None,
                "source": source or "unknown",
                "count": 0
            }
        
        # 统计返回记录数：用于决定 success（避免“success=True 但 0 条数据”掩盖采集失败）
        returned_total = 0
        try:
            returned_total = sum(int(r.get("returned_count", r.get("count", 0)) or 0) for r in results)
        except Exception:
            returned_total = 0

        # 构建返回结果：单个ETF返回对象，多个ETF返回数组
        final_data = results[0] if len(results) == 1 else results
        
        if returned_total <= 0:
            return {
                "success": False,
                "message": "未从外部源获取到分钟数据（returned_count=0）",
                "data": final_data,
                "source": source or "unknown",
                "count": len(results),
            }

        return {
            "success": True,
            "message": f"Successfully fetched {returned_total} records",
            "data": final_data,
            "source": source or "akshare",
            "count": len(results),
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_fetch_etf_minute(
    etf_code: str = "510300",
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    mode: str = "production",
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取ETF分钟数据
    
    Args:
        etf_code: ETF代码，支持单个或多个（用逗号分隔）
        period: 周期，"5", "15", "30", "60" 分钟
        start_date: 开始日期（YYYY-MM-DD 或 YYYYMMDD）
        end_date: 结束日期（YYYY-MM-DD 或 YYYYMMDD），默认今天
        lookback_days: 回看天数（仅在未提供start_date时生效），默认5天
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        use_cache: 是否使用缓存（默认True）
    """
    return fetch_etf_minute(
        etf_code=etf_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        mode=mode,
        use_cache=use_cache
    )
