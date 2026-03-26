"""
获取指数分钟数据
融合 Coze 插件 get_index_minute.py
OpenClaw 插件工具
改进版本：支持缓存、多指数、自动计算成交额/涨跌幅、完善字段映射
"""

import pandas as pd
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timedelta
from pathlib import Path
import pytz
import os
import sys
import json
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
import logging

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

# 尝试导入原系统的缓存模块（优先使用当前环境下的 /home/xie/src，其次回退到 Windows 路径）
try:
    selected_root = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "src").exists():
            selected_root = parent
            break

    candidate_paths = []
    if selected_root is not None:
        candidate_paths.append(selected_root)

    root_for_import = None
    for root in candidate_paths:
        if root is not None and (root / "src").exists():
            root_for_import = root
            break

    if root_for_import is not None:
        if str(root_for_import) not in sys.path:
            sys.path.insert(0, str(root_for_import))
        from src.data_cache import (
            get_cached_index_minute, save_index_minute_cache,
            merge_cached_and_fetched_data,
        )
        from src.config_loader import load_system_config
        CACHE_AVAILABLE = True
    else:
        CACHE_AVAILABLE = False
except Exception:
    CACHE_AVAILABLE = False


logger = logging.getLogger(__name__)

# 常见指数中文名（仅展示用；任意 6 位代码均可走拉数链路）
_INDEX_KNOWN_NAMES: Dict[str, str] = {
    "000001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000300": "沪深300",
    "000016": "上证50",
    "000905": "中证500",
    "000852": "中证1000",
}


def normalize_index_code_for_minute(raw: str) -> Optional[str]:
    """
    统一为 6 位数字指数代码（用于缓存键、mootdx symbol、与 sh/sz 推导）。
    支持：000300 / sh000300 / sz399001 / 000300.SH 等形式。
    无法解析则返回 None。
    """
    s = str(raw).strip()
    if not s:
        return None
    u = s.upper().replace("．", ".")
    for suf in (".SH", ".SZ"):
        if u.endswith(suf):
            u = u[: -len(suf)]
            break
    low = u.lower()
    if low.startswith("sh") and len(u) > 2:
        u = u[2:]
    elif low.startswith("sz") and len(u) > 2:
        u = u[2:]
    u = u.strip()
    if not u.isdigit():
        return None
    if len(u) != 6:
        return None
    return u


def index_sina_symbol(digits: str) -> str:
    """新浪 getKLineData / 东财 index_zh_a_hist_min_em 的 symbol：深证 39xxxx -> sz，其余默认 sh。"""
    if digits.startswith("39"):
        return f"sz{digits}"
    return f"sh{digits}"


def index_display_name(digits: str) -> str:
    return _INDEX_KNOWN_NAMES.get(digits, f"指数{digits}")


def _is_dataframe(obj: Any) -> bool:
    """统一 DataFrame 类型检查，避免对 None/非DataFrame对象访问 .columns。"""
    return isinstance(obj, pd.DataFrame)


def fetch_index_minute_sina_direct(
    index_code: str,
    period: str,
    start_date_str: str,
    end_date_str: str,
    lookback_days: int = 5,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Optional[pd.DataFrame]:
    """
    直接从新浪接口获取指数分钟数据（主数据源），参考原 Coze 插件实现。

    使用 http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
    """
    if logger:
        logger.info(
            "fetch_index_minute_sina_direct: index_code=%s, period=%s, start=%s, end=%s, lookback_days=%s",
            index_code,
            period,
            start_date_str,
            end_date_str,
            lookback_days,
        )

    clean = normalize_index_code_for_minute(index_code)
    if not clean:
        if logger:
            logger.warning("无法解析指数代码: %s", index_code)
        return None
    sina_symbol = index_sina_symbol(clean)

    period_to_scale = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60}
    scale = period_to_scale.get(period, 30)

    # 计算需要拉取的大致条数（防止一次请求不足）
    try:
        start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days + 1
        datalen = min(int(days_diff * (240 / scale) * 1.2), 1023)
    except Exception:
        datalen = 1023

    url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": sina_symbol,
        "scale": scale,
        "ma": "no",
        "datalen": datalen,
    }
    headers = {
        "Referer": "http://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    last_error: Optional[str] = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(min(retry_delay * (2 ** (attempt - 1)), 30.0))

            full_url = f"{url}?{urlencode(params)}"
            req = Request(full_url, headers=headers)
            with urlopen(req, timeout=10) as response:
                if response.status != 200:
                    raise HTTPError(full_url, response.status, response.reason, response.headers, None)

                try:
                    data = json.loads(response.read().decode("utf-8"))
                except ValueError:
                    last_error = "JSON解析失败"
                    continue

                if not data or not isinstance(data, list):
                    last_error = "API返回空数据"
                    continue

                df = pd.DataFrame(data)
                if df.empty:
                    last_error = "API返回空数据"
                    continue

                # 字段标准化
                column_mapping = {
                    "day": "时间",
                    "open": "开盘",
                    "close": "收盘",
                    "high": "最高",
                    "low": "最低",
                    "volume": "成交量",
                }
                available_columns = [col for col in column_mapping.keys() if col in df.columns]
                df = df[available_columns].copy().rename(columns=column_mapping)

                # 成交额占位
                if "成交额" not in df.columns:
                    df["成交额"] = 0.0

                # 时间处理（不再强制按时间窗口二次过滤，避免“过滤后数据为空”导致主数据源形同失效）
                if "时间" in df.columns:
                    df["时间"] = pd.to_datetime(df["时间"], errors="coerce")
                    df = df[df["时间"].notna()].copy()
                    df["时间"] = df["时间"].dt.strftime("%Y-%m-%d %H:%M:%S")

                for col in ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                if "时间" in df.columns:
                    df = df.sort_values("时间").reset_index(drop=True)

                if logger:
                    logger.info(
                        "fetch_index_minute_sina_direct 成功: index_code=%s, period=%s, records=%d",
                        index_code,
                        period,
                        len(df),
                    )
                return df

        except Exception as e:  # pragma: no cover - 网络相关异常
            last_error = str(e)
            if logger:
                logger.warning(
                    "fetch_index_minute_sina_direct 第 %d 次尝试失败: %s", attempt + 1, last_error
                )
            if attempt >= max_retries - 1:
                break

    if logger:
        logger.warning(
            "fetch_index_minute_sina_direct 最终失败: index_code=%s, period=%s, error=%s",
            index_code,
            period,
            last_error,
        )
    return None


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
    
    # 1. 计算成交额（如果缺失或全为0）
    if '成交额' not in df.columns or df['成交额'].isna().all() or (df['成交额'] == 0).all():
        if '成交量' in df.columns and '收盘' in df.columns:
            # 成交量单位是"手"，需要乘以100转换为股数，再乘以价格得到成交额
            df['成交额'] = df['成交量'] * df['收盘'] * 100
        else:
            df['成交额'] = 0
    
    # 2. 计算涨跌幅（如果缺失）
    if '涨跌幅' not in df.columns:
        if '收盘' in df.columns:
            # 计算涨跌幅：当前收盘价相对于前一个收盘价的百分比变化
            df['涨跌幅'] = df['收盘'].pct_change() * 100
            # 第一行的涨跌幅设为0（因为没有前一行）
            df['涨跌幅'] = df['涨跌幅'].fillna(0)
        else:
            df['涨跌幅'] = 0
    
    return df


def _fetch_index_minute_mootdx(
    index_code: str,
    period: str,
    start_date_str: str,
    end_date_str: str,
    max_bars: int = 800,
) -> Optional[pd.DataFrame]:
    """
    使用 mootdx 获取指数分钟数据。

    参数:
        index_code: 指数代码，如 "000300"
        period: "1", "5", "15", "30", "60"
        start_date_str/end_date_str: "YYYY-MM-DD HH:MM:SS"
    """
    if not MOOTDX_AVAILABLE:
        return None

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
        df = client.bars(symbol=index_code, frequency=frequency, offset=max_bars)
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


def _get_latest_cached_timestamp_index(
    symbol: str,
    period: str,
    date_yyyymmdd: str,
    config: Optional[Dict] = None
) -> Optional[datetime]:
    """
    获取指定 symbol/period/date 的缓存中最新一条数据的时间戳。
    用于判断缓存新鲜度：若 (当前时间 - 最新时间) > period 分钟，则需要拉取。
    
    Returns:
        最新时间（上海时区），若无缓存返回 None
    """
    if not CACHE_AVAILABLE:
        return None
    try:
        cached_df, missing = get_cached_index_minute(
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


def fetch_single_index_minute(
    index_code: str,
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    use_cache: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    获取单个指数的分钟数据
    
    Returns:
        Tuple[Optional[pd.DataFrame], Optional[str]]: (数据DataFrame, 数据源名称)
    """
    if period not in ["1", "5", "15", "30", "60"]:
        return None, None

    clean = normalize_index_code_for_minute(index_code)
    if not clean:
        return None, None
    # 下游统一用 6 位代码（缓存、mootdx）
    index_code = clean

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
    
    sina_symbol = index_sina_symbol(index_code)
    
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
            
            cached_df, missing_dates = get_cached_index_minute(
                index_code, period, start_date_formatted, end_date_formatted, config=config
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
    df = _fetch_index_minute_mootdx(
        index_code=index_code,
        period=period,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
    )
    if df is not None and not df.empty:
        source = "mootdx"

    # 方法2：新浪直连接口（避免 akshare 限制）
    if df is None or df.empty:
        df = fetch_index_minute_sina_direct(
            index_code=index_code,
            period=period,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            lookback_days=lookback_days,
        )
        if df is not None and not df.empty:
            source = "sina"

    # 方法3：尝试使用 akshare 接口（备用数据源）
    if (df is None or df.empty) and AKSHARE_AVAILABLE:
        try:
            temp_df = ak.index_zh_a_hist_min_em(
                symbol=sina_symbol,
                period=period,
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
    if _is_dataframe(df) and not df.empty and _is_dataframe(cached_partial_df):
        try:
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
    
    # ========== 保存到缓存 ==========
    if _is_dataframe(df) and not df.empty and use_cache and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True)
            save_index_minute_cache(index_code, period, df, config=config)
        except Exception:
            pass
    # ========== 缓存保存结束 ==========
    
    return df, source


def fetch_index_minute(
    index_code: str = "000300",
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
    获取指数分钟数据（融合 Coze get_index_minute.py）
    支持多指数查询（逗号分隔）
    
    Args:
        index_code: 指数代码，支持单个或多个（用逗号分隔），如 "000300" 或 "000300,000001"
        period: 周期，"5", "15", "30", "60" 分钟
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
            trading_day_check = check_trading_day_before_operation("获取指数分钟数据")
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
            if isinstance(index_code, str):
                raw_batch = [c.strip() for c in index_code.split(",") if c.strip()]
            else:
                raw_batch = [str(index_code).strip()]
            index_codes = []
            for c in raw_batch:
                n = normalize_index_code_for_minute(c)
                if n is None:
                    return {
                        "success": False,
                        "message": f"无法解析指数代码: {c}（需 6 位数字或 sh/sz 前缀）",
                        "data": None,
                    }
                if n.startswith("5") or n.startswith("1"):
                    return {
                        "success": False,
                        "message": f"批量预热仅支持指数，不含 ETF 代码: {n}",
                        "data": None,
                    }
                index_codes.append(n)
            if not index_codes:
                return {'success': False, 'message': '未提供有效的指数代码', 'data': None}
            for code in index_codes:
                for p in periods_to_fetch:
                    latest_ts = _get_latest_cached_timestamp_index(code, p, today, config) if CACHE_AVAILABLE else None
                    need_fetch = latest_ts is None
                    if not need_fetch:
                        gap_min = (now - latest_ts).total_seconds() / 60
                        need_fetch = gap_min > int(p)
                    if need_fetch:
                        df_out, _ = fetch_single_index_minute(code, p, None, None, lookback_days or 5, use_cache)
                        if _is_dataframe(df_out) and not df_out.empty:
                            fetched.append(f"{code}/{p}min")
                        else:
                            skipped.append(f"{code}/{p}min(fetch_failed)")
                    else:
                        skipped.append(f"{code}/{p}min")
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
        
        # 解析指数代码（支持单个或多个，用逗号分隔），规范为 6 位数字
        if isinstance(index_code, str):
            raw_codes = [code.strip() for code in index_code.split(",") if code.strip()]
        elif isinstance(index_code, list):
            raw_codes = [str(code).strip() for code in index_code if str(code).strip()]
        else:
            raw_codes = [str(index_code).strip()]

        if not raw_codes:
            return {
                "success": False,
                "message": "未提供有效的指数代码",
                "data": None,
            }

        index_codes: List[str] = []
        for rc in raw_codes:
            n = normalize_index_code_for_minute(rc)
            if n is None:
                return {
                    "success": False,
                    "message": f"无法解析指数代码: {rc}（需 6 位数字或 sh/sz 前缀）",
                    "data": None,
                }
            index_codes.append(n)

        # ========== 自动识别 ETF 代码并调用对应的 ETF 函数 ==========
        # ETF代码通常以5或1开头（如510300, 159915），其余 6 位按指数处理
        etf_codes = [code for code in index_codes if code.startswith("5") or code.startswith("1")]
        index_codes_only = [code for code in index_codes if code not in etf_codes]
        etf_result = None
        
        if etf_codes:
            # 如果有ETF代码，自动调用ETF函数
            try:
                from plugins.data_collection.etf.fetch_minute import fetch_etf_minute
                logger.info(f"检测到 ETF 代码 {', '.join(etf_codes)}，自动调用 fetch_etf_minute")
                etf_result = fetch_etf_minute(
                    etf_code=",".join(etf_codes),
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    lookback_days=lookback_days,
                    api_base_url=api_base_url,
                    api_key=api_key,
                    use_cache=use_cache
                )
                # 如果只有ETF代码，直接返回ETF结果
                if not index_codes_only:
                    return etf_result
                # 如果还有指数代码，继续处理指数代码，然后合并结果
            except Exception as e:
                logger.warning(f"调用 fetch_etf_minute 失败: {e}，继续处理指数代码")
                etf_result = None
        # ========== ETF 代码处理结束 ==========
        
        # 如果没有指数代码，直接返回ETF结果（如果有）
        if not index_codes_only:
            if etf_codes and etf_result:
                return etf_result
            else:
                return {
                    'success': False,
                    'message': '未提供有效的指数代码',
                    'data': None
                }
        
        # 处理多个指数（逐个获取）
        results = []
        source = None
        
        # 如果有ETF结果，先添加到结果中
        if etf_codes and etf_result and etf_result.get('success'):
            etf_data = etf_result.get('data', {})
            if isinstance(etf_data, dict) and 'klines' in etf_data:
                for etf_code in etf_codes:
                    results.append({
                        "index_code": etf_code,
                        "period": period,
                        "count": len(etf_data.get('klines', [])),
                        "klines": etf_data.get('klines', []),
                        "source": etf_data.get('source', 'etf_minute')
                    })
        
        for index_code_item in index_codes_only:
            # 获取数据
            df, data_source = fetch_single_index_minute(
                index_code_item, period, start_date, end_date, lookback_days, use_cache
            )
            
            if data_source:
                source = data_source
            
            if not _is_dataframe(df) or df.empty:
                results.append({
                    "index_code": index_code_item,
                    "name": index_display_name(index_code_item),
                    "period": period,
                    "count": 0,
                    "klines": [],
                    "message": "指数分钟数据暂时不可用，请稍后重试"
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
                "index_code": index_code_item,
                "name": index_display_name(index_code_item),
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
        
        # 构建返回结果：单个指数返回对象，多个指数返回数组
        final_data = results[0] if len(results) == 1 else results

        returned_total = 0
        try:
            returned_total = sum(int(r.get("returned_count", r.get("count", 0)) or 0) for r in results)
        except Exception:
            returned_total = 0

        if returned_total <= 0:
            return {
                "success": False,
                "message": "未从外部源获取到分钟数据（returned_count=0）",
                "data": final_data,
                # 默认标记为新浪HTTP（主数据源），若实际为其他源会被上游覆盖
                "source": source or "unknown",
                "count": len(results),
            }
        
        return {
            "success": True,
            "message": f"Successfully fetched {returned_total} records",
            "data": final_data,
            # 默认标记为新浪HTTP（主数据源），若实际为其他源会被上游覆盖
            "source": source or "sina_http",
            "count": len(results)
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_fetch_index_minute(
    index_code: str = "000300",
    period: str = "30",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    mode: str = "production",
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取指数分钟数据
    
    Args:
        index_code: 指数代码，支持单个或多个（用逗号分隔）
        period: 周期，"5", "15", "30", "60" 分钟
        start_date: 开始日期（YYYY-MM-DD 或 YYYYMMDD）
        end_date: 结束日期（YYYY-MM-DD 或 YYYYMMDD），默认今天
        lookback_days: 回看天数（仅在未提供start_date时生效），默认5天
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        use_cache: 是否使用缓存（默认True）
    """
    return fetch_index_minute(
        index_code=index_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        mode=mode,
        use_cache=use_cache
    )
