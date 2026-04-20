# -*- coding: utf-8 -*-
"""
Tushare 数据备份模块
作为 akshare 的备用数据源，提升系统稳定性

方案2：指数日线 + ETF日线备份
方案3：期权数据备份（合约列表 + 日线）
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict
import tushare as ts
import time

from src.logger_config import get_module_logger
from src.config_loader import load_system_config

logger = get_module_logger(__name__)

# Tushare Pro API 实例（懒加载）
_tushare_pro = None

# Tushare API 调用频率控制
_last_api_call_time: Dict[str, float] = {}  # 记录每个接口的最后调用时间
_min_call_interval = 3.0  # 最小调用间隔（秒），确保不超过每分钟20次的限制
# stk_mins 接口特殊限制：每分钟最多2次
_stk_mins_call_times: list[float] = []  # 记录 stk_mins 接口的调用时间
_stk_mins_min_interval = 30.0  # stk_mins 接口最小调用间隔（秒），确保每分钟不超过2次


def get_tushare_pro():
    """
    获取 Tushare Pro API 实例（单例模式）
    
    Returns:
        tushare.pro_api 对象，如果配置未启用则返回 None
    """
    global _tushare_pro
    
    if _tushare_pro is not None:
        return _tushare_pro
    
    try:
        config = load_system_config()
        tushare_config = config.get('tushare', {})
        
        if not tushare_config.get('enabled', False):
            logger.debug("Tushare 未启用，跳过初始化")
            return None
        
        # token 可能来自分层配置的 "${TUSHARE_TOKEN}" 占位符解析（config_loader 会替换为 os.getenv 的值或 None）
        # 兼容：配置为 None/空时，直接从环境变量兜底（与 .env 配合）
        token = tushare_config.get('token')
        if token is not None:
            token = str(token).strip()
        if not token:
            token = (os.environ.get('TUSHARE_TOKEN') or '').strip()
        if not token:
            logger.warning("Tushare token 未配置，无法使用 tushare 备份")
            return None
        
        _tushare_pro = ts.pro_api(token)
        logger.info("Tushare Pro API 初始化成功")
        return _tushare_pro
        
    except Exception as e:
        logger.error(f"Tushare Pro API 初始化失败: {e}")
        return None


# ==================== 方案2：指数日线 + ETF日线备份 ====================

def fetch_index_daily_tushare(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    使用 Tushare 获取指数日线数据（方案2）
    
    Args:
        symbol: 指数代码（如 "000300" 表示沪深300）
        start_date: 开始日期 "YYYYMMDD"
        end_date: 结束日期 "YYYYMMDD"
    
    Returns:
        DataFrame: 指数日线数据，格式与 akshare 兼容，失败返回 None
    """
    pro = get_tushare_pro()
    if pro is None:
        return None
    
    try:
        # 指数代码映射：akshare -> tushare
        # akshare: 000300 (沪深300), tushare: 399300.SZ
        index_code_mapping = {
            "000300": "399300.SZ",  # 沪深300
            "000001": "000001.SH",  # 上证指数
            "000016": "000016.SH",  # 上证50
            "000905": "000905.SH",  # 中证500
            "399001": "399001.SZ",  # 深证成指
            "399006": "399006.SZ",  # 创业板指
        }
        
        ts_code = index_code_mapping.get(symbol)
        if ts_code is None:
            # 自动转换：000xxx -> 000xxx.SH, 399xxx -> 399xxx.SZ
            if symbol.startswith("000"):
                ts_code = f"{symbol}.SH"
            elif symbol.startswith("399"):
                ts_code = f"{symbol}.SZ"
            else:
                # 检查是否是ETF代码（通常以5或1开头），如果是，自动调用ETF接口
                if symbol.startswith("5") or symbol.startswith("1"):
                    logger.info(f"检测到ETF代码 {symbol}，自动使用 Tushare ETF 接口")
                    return fetch_etf_daily_tushare(symbol, start_date, end_date)
                else:
                    logger.warning(f"无法转换指数代码: {symbol}，代码格式不支持（仅支持以000或399开头的指数代码）")
                    return None
        
        logger.debug(f"使用 Tushare 获取指数日线: {symbol} -> {ts_code}")
        
        # 调用 tushare index_daily
        df = pro.index_daily(
            ts_code=ts_code,
            start_date=start_date or "",
            end_date=end_date or ""
        )
        
        if df is None or df.empty:
            logger.warning(f"Tushare index_daily 返回空数据: {ts_code}")
            return None
        
        # 转换为 akshare 兼容格式
        result = pd.DataFrame({
            '日期': pd.to_datetime(df['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d'),
            '开盘': df['open'],
            '收盘': df['close'],
            '最高': df['high'],
            '最低': df['low'],
            '成交量': df['vol'],
            '成交额': df['amount'],
            '涨跌额': df['change'],
            '涨跌幅': df['pct_chg']
        })
        
        logger.info(f"Tushare 获取指数日线成功: {symbol}, {len(result)} 条数据")
        return result
        
    except Exception as e:
        logger.warning(f"Tushare index_daily 失败: {symbol}, 错误: {e}")
        return None


def fetch_etf_daily_tushare(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    使用 Tushare 获取 ETF 日线数据（方案2）
    
    Args:
        symbol: ETF代码（如 "510300" 或 "sh510300"）
        start_date: 开始日期 "YYYYMMDD"
        end_date: 结束日期 "YYYYMMDD"
    
    Returns:
        DataFrame: ETF日线数据，格式与 akshare 兼容，失败返回 None
    """
    pro = get_tushare_pro()
    if pro is None:
        return None
    
    try:
        # 清理代码格式：sh510300 -> 510300.SH, 510300 -> 510300.SH
        if symbol.startswith('sh') or symbol.startswith('sz'):
            code = symbol[2:]
            exchange = symbol[:2].upper()
        else:
            code = symbol
            # 默认判断：510xxx 通常是上交所，159xxx 通常是深交所
            if code.startswith('510') or code.startswith('511') or code.startswith('512'):
                exchange = 'SH'
            elif code.startswith('159'):
                exchange = 'SZ'
            else:
                exchange = 'SH'  # 默认上交所
        
        ts_code = f"{code}.{exchange}"
        
        logger.debug(f"使用 Tushare 获取 ETF 日线: {symbol} -> {ts_code}")
        
        # 调用 tushare fund_daily
        df = pro.fund_daily(
            ts_code=ts_code,
            start_date=start_date or "",
            end_date=end_date or ""
        )
        
        if df is None or df.empty:
            logger.warning(f"Tushare fund_daily 返回空数据: {ts_code}")
            return None
        
        # 转换为 akshare 兼容格式
        result = pd.DataFrame({
            '日期': pd.to_datetime(df['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d'),
            '开盘': df['open'],
            '收盘': df['close'],
            '最高': df['high'],
            '最低': df['low'],
            '成交量': df['vol'],
            '成交额': df['amount'],
            '涨跌额': df['change'],
            '涨跌幅': df['pct_chg']
        })
        
        logger.info(f"Tushare 获取 ETF 日线成功: {symbol}, {len(result)} 条数据")
        return result
        
    except Exception as e:
        logger.warning(f"Tushare fund_daily 失败: {symbol}, 错误: {e}")
        return None


def fetch_stock_daily_tushare(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    使用 Tushare 获取 A 股个股日线数据（优先用于历史缓存采集）。

    Args:
        symbol: 股票代码（如 "600519" / "000001" / "sh600519" / "600519.SH"）
        start_date: 开始日期 "YYYYMMDD"
        end_date: 结束日期 "YYYYMMDD"

    Returns:
        DataFrame: 个股日线数据（与系统日线字段对齐），失败返回 None
    """
    pro = get_tushare_pro()
    if pro is None:
        return None

    try:
        code_raw = str(symbol or "").strip()
        if not code_raw:
            return None

        exchange = ""
        code = code_raw
        if code_raw.upper().endswith((".SH", ".SZ", ".BJ")):
            code, exchange = code_raw.split(".", 1)
            exchange = exchange.upper()
        elif code_raw.lower().startswith(("sh", "sz", "bj")) and len(code_raw) > 2:
            exchange = code_raw[:2].upper()
            code = code_raw[2:]
        else:
            exchange = "SH" if code_raw.startswith(("5", "6", "9")) else "SZ"

        if not code.isdigit() or len(code) != 6:
            logger.warning(f"无效股票代码，无法调用 Tushare daily: {symbol}")
            return None

        ts_code = f"{code}.{exchange}"
        logger.debug(f"使用 Tushare 获取股票日线: {symbol} -> {ts_code}")

        df = pro.daily(
            ts_code=ts_code,
            start_date=start_date or "",
            end_date=end_date or ""
        )
        if df is None or df.empty:
            logger.warning(f"Tushare daily 返回空数据: {ts_code}")
            return None

        result = pd.DataFrame({
            '日期': pd.to_datetime(df['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d'),
            '开盘': df['open'],
            '收盘': df['close'],
            '最高': df['high'],
            '最低': df['low'],
            '成交量': df['vol'],
            '成交额': df['amount'],
            '涨跌额': df['change'],
            '涨跌幅': df['pct_chg']
        })
        logger.info(f"Tushare 获取股票日线成功: {symbol}, {len(result)} 条数据")
        return result
    except Exception as e:
        logger.warning(f"Tushare daily 失败: {symbol}, 错误: {e}")
        return None


# ==================== 方案3：期权数据备份 ====================

def fetch_option_codes_tushare(
    option_type: str,
    target_month: str,
    underlying: str = "510300"
) -> Optional[pd.DataFrame]:
    """
    使用 Tushare 获取期权合约列表（方案3）
    
    Args:
        option_type: "call" 或 "put"
        target_month: 合约月份 "YYYYMM"（如 "202501"）
        underlying: 标的代码（默认 "510300"）
    
    Returns:
        DataFrame: 期权合约列表，格式与 akshare 兼容，失败返回 None
    """
    pro = get_tushare_pro()
    if pro is None:
        return None
    
    try:
        call_put = "C" if option_type.lower() == "call" else "P"
        
        logger.debug(f"使用 Tushare 获取期权合约列表: {option_type}, {target_month}, {underlying}")
        
        # 调用 tushare opt_basic
        df = pro.opt_basic(
            exchange="SSE",
            call_put=call_put
        )
        
        if df is None or df.empty:
            logger.warning("Tushare opt_basic 返回空数据")
            return None
        
        # 筛选目标月份和标的
        # opt_code 格式如 "OP510300.SH" 表示510300ETF期权
        df_filtered = df[df['s_month'] == target_month]
        
        # 筛选标的（通过 opt_code）
        if underlying == "510300":
            df_filtered = df_filtered[df_filtered['opt_code'].str.contains('510300', na=False)]
        elif underlying:
            df_filtered = df_filtered[df_filtered['opt_code'].str.contains(underlying, na=False)]
        
        if df_filtered.empty:
            logger.warning(f"Tushare opt_basic 筛选后无数据: {option_type}, {target_month}, {underlying}")
            return None
        
        # 转换为 akshare 兼容格式（使用'合约代码'列名，与akshare保持一致）
        result = pd.DataFrame({
            '合约代码': df_filtered['ts_code'].str.replace('.SH', '').astype(str),  # 去掉后缀，转为字符串
            '期权代码': df_filtered['ts_code'].str.replace('.SH', '').astype(str),  # 同时保留'期权代码'列名以兼容旧代码
            '行权价': df_filtered['exercise_price'],
            '到期日': df_filtered['maturity_date'].astype(str),
            '类型': '看涨期权' if call_put == 'C' else '看跌期权',
            '合约月份': df_filtered['s_month'].astype(str),
            '交易所': df_filtered['exchange']
        })
        
        logger.info(f"Tushare 获取期权合约列表成功: {option_type}, {len(result)} 个合约")
        return result
        
    except Exception as e:
        logger.warning(f"Tushare opt_basic 失败: {option_type}, {target_month}, 错误: {e}")
        return None


def fetch_option_daily_tushare(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Optional[pd.DataFrame]:
    """
    使用 Tushare 获取期权日线数据（方案3）
    
    Args:
        ts_code: 期权代码（tushare格式，如 "10010335.SH"）
                 也可以是 akshare 格式（如 "10010335"），会自动转换
        start_date: 开始日期 "YYYYMMDD"
        end_date: 结束日期 "YYYYMMDD"
    
    Returns:
        DataFrame: 期权日线数据，格式与 akshare 兼容，失败返回 None
    """
    pro = get_tushare_pro()
    if pro is None:
        return None
    
    try:
        # 如果代码没有后缀，添加 .SH（默认上交所）
        if '.' not in ts_code:
            ts_code = f"{ts_code}.SH"
        
        logger.debug(f"使用 Tushare 获取期权日线: {ts_code}")
        
        # 调用 tushare opt_daily
        df = pro.opt_daily(
            ts_code=ts_code,
            start_date=start_date or "",
            end_date=end_date or ""
        )
        
        if df is None or df.empty:
            logger.warning(f"Tushare opt_daily 返回空数据: {ts_code}")
            return None
        
        # 转换为 akshare 兼容格式
        result = pd.DataFrame({
            '日期': pd.to_datetime(df['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d'),
            '开盘': df['open'],
            '收盘': df['close'],
            '最高': df['high'],
            '最低': df['low'],
            '成交量': df['vol'],
            '成交额': df['amount'],
            '持仓量': df['oi']
        })
        
        logger.info(f"Tushare 获取期权日线成功: {ts_code}, {len(result)} 条数据")
        return result
        
    except Exception as e:
        logger.warning(f"Tushare opt_daily 失败: {ts_code}, 错误: {e}")
        return None


def fetch_option_minute_tushare(
    ts_code: str,
    date_str: str,
    freq: str = "15min"
) -> Optional[pd.DataFrame]:
    """
    使用 Tushare 获取期权分钟数据（已禁用 - 需要额外付费）
    
    注意：opt_mins 接口需要2000元/年的额外付费权限，2000积分无法使用。
    此函数已禁用，直接返回 None。
    
    Args:
        ts_code: 期权代码（tushare格式，如 "10010335.SH"）
        date_str: 日期 "YYYYMMDD"
        freq: 频率 "1min"/"5min"/"15min"/"30min"/"60min"（默认15min）
    
    Returns:
        None: 已禁用，始终返回 None
    """
    logger.debug(f"Tushare opt_mins 接口已禁用（需要额外付费2000元/年），跳过: {ts_code}, {date_str}, {freq}")
    return None


# ==================== ETF 分钟数据 ====================

def _calculate_daily_rows(period: str) -> int:
    """
    根据周期计算每天的数据量（交易日，9:30-15:00，共4小时=240分钟）
    
    Args:
        period: 周期（"1", "5", "15", "30", "60"）
    
    Returns:
        int: 每天的数据量
    """
    period_int = int(period)
    # 交易日：9:30-11:30 (120分钟) + 13:00-15:00 (120分钟) = 240分钟
    trading_minutes_per_day = 240
    return trading_minutes_per_day // period_int


def _should_split_by_time(period: str, days: int) -> bool:
    """
    判断是否需要按时间段分批获取数据
    
    Args:
        period: 周期（"1", "5", "15", "30", "60"）
        days: 天数
    
    Returns:
        bool: 如果需要分批返回 True
    """
    daily_rows = _calculate_daily_rows(period)
    total_rows = daily_rows * days
    # 如果总数据量可能超过8000行，需要分批
    return total_rows > 8000


def _wait_for_stk_mins_rate_limit():
    """
    控制 stk_mins 接口的调用频率，确保每分钟不超过2次
    
    该接口限制：每分钟最多访问2次
    可通过 config.yaml 中的 tushare.enable_rate_limit 配置项禁用
    """
    global _stk_mins_call_times
    
    # 检查配置是否启用频率限制
    try:
        config = load_system_config()
        enable_rate_limit = config.get('tushare', {}).get('enable_rate_limit', True)
        if not enable_rate_limit:
            logger.debug("stk_mins 接口频率限制已禁用（通过配置）")
            return
    except Exception as e:
        logger.debug(f"读取频率限制配置失败，使用默认值（启用）: {e}")
        # 如果读取配置失败，默认启用频率限制
    
    import time as time_module
    current_time = time_module.time()
    
    # 清理1分钟之前的调用记录
    _stk_mins_call_times = [t for t in _stk_mins_call_times if current_time - t < 60]
    
    # 如果最近1分钟内已经有2次调用，需要等待
    if len(_stk_mins_call_times) >= 2:
        # 计算需要等待的时间（等待到最早的那次调用超过1分钟）
        oldest_call_time = min(_stk_mins_call_times)
        wait_time = 60 - (current_time - oldest_call_time) + 1  # 多等1秒确保安全
        if wait_time > 0:
            logger.info(f"stk_mins 接口频率限制：等待 {wait_time:.1f} 秒（最近1分钟内已有 {len(_stk_mins_call_times)} 次调用）")
            time_module.sleep(wait_time)
            current_time = time_module.time()
            # 重新清理调用记录
            _stk_mins_call_times = [t for t in _stk_mins_call_times if current_time - t < 60]
    
    # 确保至少间隔30秒（保守策略，确保每分钟不超过2次）
    if len(_stk_mins_call_times) > 0:
        last_call_time = _stk_mins_call_times[-1]
        elapsed = current_time - last_call_time
        if elapsed < _stk_mins_min_interval:
            wait_time = _stk_mins_min_interval - elapsed
            logger.debug(f"stk_mins 接口间隔控制：等待 {wait_time:.1f} 秒（距离上次调用 {elapsed:.1f} 秒）")
            time_module.sleep(wait_time)
            current_time = time_module.time()
    
    # 记录本次调用时间
    _stk_mins_call_times.append(current_time)


def _convert_tushare_batch_to_standard_format(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    将 Tushare 返回的单个批次数据转换为标准格式（用于立即缓存）
    
    Args:
        df: Tushare 返回的 DataFrame（包含 trade_time, open, close, high, low, vol, amount）
    
    Returns:
        pd.DataFrame: 标准格式的 DataFrame（包含 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额）
    """
    if df is None or df.empty:
        return None
    
    try:
        # 转换为标准格式
        time_series = pd.to_datetime(df['trade_time'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
        
        result = pd.DataFrame({
            '时间': time_series.dt.strftime('%Y-%m-%d %H:%M:%S'),
            '开盘': df['open'],
            '收盘': df['close'],
            '最高': df['high'],
            '最低': df['low'],
            '成交量': df['vol'],
            '成交额': df['amount']
        })
        
        # 移除无效时间的数据
        result = result.dropna(subset=['时间'])
        
        return result
    except Exception as e:
        logger.warning(f"转换批次数据格式失败: {e}")
        return None


def fetch_etf_minute_tushare(
    symbol: str,
    period: str = "15",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    token: Optional[str] = None,
    config: Optional[Dict] = None
) -> Optional[pd.DataFrame]:
    """
    使用 Tushare 获取 ETF 分钟数据
    
    接口：stk_mins
    支持频度：1min/5min/15min/30min/60min
    单次最大：8000 行数据
    
    Args:
        symbol: ETF代码（如 "510300" 或 "sh510300"）
        period: 周期（"1", "5", "15", "30", "60"），对应 Tushare 的 "1min"/"5min"/"15min"/"30min"/"60min"
        start_date: 开始日期时间（格式："YYYYMMDD HHMMSS" 或 "YYYYMMDD" 或 "YYYY-MM-DD HH:MM:SS"）
        end_date: 结束日期时间（格式："YYYYMMDD HHMMSS" 或 "YYYYMMDD" 或 "YYYY-MM-DD HH:MM:SS"）
        token: Tushare Token（可选，如果为 None 则使用配置中的默认 token）
    
    Returns:
        DataFrame: ETF分钟数据，格式与 akshare 兼容，失败返回 None
    """
    # 如果提供了 token，使用该 token 初始化；否则使用 get_tushare_pro() 获取默认实例
    pro = None
    use_prefer_token = False
    if token and token.strip():
        try:
            pro = ts.pro_api(token.strip())
            use_prefer_token = True
            logger.debug("使用 prefer_token 初始化 Tushare Pro API")
        except Exception as e:
            logger.warning(f"使用 prefer_token 初始化 Tushare Pro API 失败: {e}")
            pro = None
    
    # 如果prefer_token无效或未提供，使用默认token
    if pro is None:
        pro = get_tushare_pro()
        if pro is None:
            logger.error("无法初始化 Tushare Pro API（prefer_token和默认token都无效）")
            return None
        else:
            logger.debug("使用默认token初始化 Tushare Pro API")
    
    try:
        # 清理代码格式：sh510300 -> 510300.SH, 510300 -> 510300.SH
        if symbol.startswith('sh') or symbol.startswith('sz'):
            code = symbol[2:]
            exchange = symbol[:2].upper()
        else:
            code = symbol
            # 默认判断：510xxx 通常是上交所，159xxx 通常是深交所
            if code.startswith('510') or code.startswith('511') or code.startswith('512'):
                exchange = 'SH'
            elif code.startswith('159'):
                exchange = 'SZ'
            else:
                exchange = 'SH'  # 默认上交所
        
        ts_code = f"{code}.{exchange}"
        
        # 转换 period 格式："1" -> "1min", "5" -> "5min" 等
        period_mapping = {
            "1": "1min",
            "5": "5min",
            "15": "15min",
            "30": "30min",
            "60": "60min"
        }
        freq = period_mapping.get(period, f"{period}min")
        
        # 处理日期时间格式转换
        def format_datetime(dt_str: Optional[str], is_start: bool = True) -> str:
            """将日期时间格式转换为 Tushare 需要的格式：YYYY-MM-DD HH:MM:SS"""
            if not dt_str:
                return ""
            
            dt_str = dt_str.strip()
            
            # 如果已经是 YYYY-MM-DD HH:MM:SS 格式，直接返回
            if len(dt_str) == 19 and dt_str.count('-') == 2 and dt_str.count(':') == 2:
                return dt_str
            
            # 移除分隔符，统一处理
            dt_clean = dt_str.replace("-", "").replace(":", "").replace(" ", "")
            
            # 如果只有日期（8位），添加时间部分
            if len(dt_clean) == 8:
                # 开始日期使用 09:30:00，结束日期使用 19:00:00（用户测试时使用19:00:00成功）
                time_part = "09:30:00" if is_start else "19:00:00"
                return f"{dt_clean[:4]}-{dt_clean[4:6]}-{dt_clean[6:8]} {time_part}"
            elif len(dt_clean) == 14:
                # 已经是完整格式 YYYYMMDDHHMMSS，转换为 YYYY-MM-DD HH:MM:SS
                return f"{dt_clean[:4]}-{dt_clean[4:6]}-{dt_clean[6:8]} {dt_clean[8:10]}:{dt_clean[10:12]}:{dt_clean[12:14]}"
            elif len(dt_clean) > 8:
                # 部分格式，尝试解析
                date_part = dt_clean[:8]
                time_part = dt_clean[8:] if len(dt_clean) >= 14 else ("093000" if is_start else "190000")
                if len(time_part) == 6:
                    return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} {time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
                else:
                    default_time = "09:30:00" if is_start else "19:00:00"
                    return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} {default_time}"
            else:
                logger.warning(f"无法识别的日期时间格式: {dt_str}")
                return ""
        
        start_date_str = format_datetime(start_date, is_start=True)
        end_date_str = format_datetime(end_date, is_start=False)
        
        logger.debug(f"使用 Tushare 获取 ETF 分钟数据: {symbol} -> {ts_code}, freq={freq}, "
                    f"start_date={start_date_str}, end_date={end_date_str}")
        
        # 处理单次 8000 行限制：智能分批获取
        all_dfs = []
        max_rows_per_call = 8000
        warning_threshold = 7500  # 如果返回数据量>=7500行，可能需要进一步分割
        
        # 如果日期范围较大，按日期循环获取
        if start_date_str and end_date_str:
            # 解析日期（支持 YYYY-MM-DD 和 YYYYMMDD 格式）
            try:
                if '-' in start_date_str:
                    start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d")
                else:
                    start_dt = datetime.strptime(start_date_str[:8], "%Y%m%d")
                if '-' in end_date_str:
                    end_dt = datetime.strptime(end_date_str[:10], "%Y-%m-%d")
                else:
                    end_dt = datetime.strptime(end_date_str[:8], "%Y%m%d")
            except ValueError as e:
                logger.warning(f"日期解析失败: start_date={start_date_str}, end_date={end_date_str}, 错误: {e}")
                return None
            days_diff = (end_dt - start_dt).days + 1
            
            # 计算每天的数据量
            daily_rows = _calculate_daily_rows(period)
            estimated_total_rows = daily_rows * days_diff
            
            # 判断是否需要分批获取
            if _should_split_by_time(period, days_diff):
                # 需要分批获取
                logger.info(f"数据量较大（预计{estimated_total_rows}行），将分批获取: {symbol}, {freq}, {days_diff}天")
                
                # 对于1分钟周期，如果多天数据超过8000行，按小时分批
                if period == "1" and estimated_total_rows > max_rows_per_call:
                    # 按小时分批：每个时间段最多获取约60条数据（1小时=60分钟）
                    current_date = start_dt
                    while current_date <= end_dt:
                        date_str = current_date.strftime("%Y-%m-%d")
                        # 按小时分批：9:30-10:30, 10:30-11:30, 13:00-14:00, 14:00-15:00
                        time_slots = [
                            ("09:30:00", "10:30:00"),
                            ("10:30:00", "11:30:00"),
                            ("13:00:00", "14:00:00"),
                            ("14:00:00", "15:00:00")
                        ]
                        
                        for slot_start, slot_end in time_slots:
                            slot_start_str = f"{date_str} {slot_start}"
                            slot_end_str = f"{date_str} {slot_end}"
                            
                            # 控制 stk_mins 接口调用频率
                            _wait_for_stk_mins_rate_limit()
                            
                            try:
                                df = pro.stk_mins(
                                    ts_code=ts_code,
                                    freq=freq,
                                    start_date=slot_start_str,
                                    end_date=slot_end_str
                                )
                                
                                if df is not None and not df.empty:
                                    # 检查返回数据量
                                    if len(df) >= warning_threshold:
                                        logger.warning(f"返回数据量接近限制: {len(df)}行，时间段: {slot_start_str} ~ {slot_end_str}")
                                    all_dfs.append(df)
                                    logger.debug(f"获取到 {date_str} {slot_start}-{slot_end} 的数据: {len(df)} 行")
                                    
                                    # 立即保存当前批次到缓存
                                    if config:
                                        try:
                                            batch_df = _convert_tushare_batch_to_standard_format(df)
                                            if batch_df is not None and not batch_df.empty:
                                                from src.data_cache import save_etf_minute_cache
                                                save_etf_minute_cache(symbol, period, batch_df, config=config)
                                                logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                        except Exception as e:
                                            logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                                
                                # stk_mins 接口的频率控制已在调用前完成，这里不需要额外等待
                                
                            except Exception as e:
                                error_msg = str(e)
                                # 如果是频率限制错误，等待更长时间后重试
                                if "每分钟最多访问" in error_msg or "频率" in error_msg.lower() or "rate limit" in error_msg.lower():
                                    logger.warning(f"遇到频率限制错误，等待60秒后重试: {error_msg}")
                                    time.sleep(60)
                                    # 清理调用记录，重新开始
                                    _stk_mins_call_times.clear()
                                    # 重新控制频率
                                    _wait_for_stk_mins_rate_limit()
                                    # 重试当前调用
                                    try:
                                        df = pro.stk_mins(
                                            ts_code=ts_code,
                                            freq=freq,
                                            start_date=slot_start_str,
                                            end_date=slot_end_str
                                        )
                                        if df is not None and not df.empty:
                                            if len(df) >= warning_threshold:
                                                logger.warning(f"返回数据量接近限制: {len(df)}行，时间段: {slot_start_str} ~ {slot_end_str}")
                                            all_dfs.append(df)
                                            logger.debug(f"获取到 {date_str} {slot_start}-{slot_end} 的数据: {len(df)} 行")
                                            
                                            # 立即保存当前批次到缓存
                                            if config:
                                                try:
                                                    batch_df = _convert_tushare_batch_to_standard_format(df)
                                                    if batch_df is not None and not batch_df.empty:
                                                        from src.data_cache import save_etf_minute_cache
                                                        save_etf_minute_cache(symbol, period, batch_df, config=config)
                                                        logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                                except Exception as e:
                                                    logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                                        continue
                                    except Exception as e3:
                                        logger.warning(f"重试后仍然失败: {e3}")
                                # 如果是token错误，尝试回退到默认token
                                elif use_prefer_token and ("token" in error_msg.lower() or "您的token不对" in error_msg):
                                    logger.warning(f"prefer_token 调用失败，尝试使用默认token: {error_msg}")
                                    pro = get_tushare_pro()
                                    if pro is None:
                                        logger.error("默认token也无效，无法继续获取数据")
                                        return None
                                    use_prefer_token = False
                                    # 重试当前调用
                                    # 控制 stk_mins 接口调用频率
                                    _wait_for_stk_mins_rate_limit()
                                    try:
                                        df = pro.stk_mins(
                                            ts_code=ts_code,
                                            freq=freq,
                                            start_date=slot_start_str,
                                            end_date=slot_end_str
                                        )
                                        if df is not None and not df.empty:
                                            if len(df) >= warning_threshold:
                                                logger.warning(f"返回数据量接近限制: {len(df)}行，时间段: {slot_start_str} ~ {slot_end_str}")
                                            all_dfs.append(df)
                                            logger.debug(f"获取到 {date_str} {slot_start}-{slot_end} 的数据: {len(df)} 行")
                                            
                                            # 立即保存当前批次到缓存
                                            if config:
                                                try:
                                                    batch_df = _convert_tushare_batch_to_standard_format(df)
                                                    if batch_df is not None and not batch_df.empty:
                                                        from src.data_cache import save_etf_minute_cache
                                                        save_etf_minute_cache(symbol, period, batch_df, config=config)
                                                        logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                                except Exception as e:
                                                    logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                                    # stk_mins 接口的频率控制已在调用前完成，这里不需要额外等待
                                    except Exception as e2:
                                        logger.warning(f"使用默认token重试失败: {e2}")
                                else:
                                    logger.warning(f"获取 {date_str} {slot_start}-{slot_end} 的 ETF 分钟数据失败: {error_msg}")
                        
                        current_date += timedelta(days=1)
                else:
                    # 对于其他周期，按批次获取多天数据（每批不超过8000条）
                    current_date = start_dt
                    daily_rows = _calculate_daily_rows(period)
                    
                    while current_date <= end_dt:
                        # 计算剩余天数
                        remaining_days = (end_dt - current_date).days + 1
                        
                        # 计算本批可以包含的天数（不超过8000条）
                        days_per_batch = max(1, min(8000 // daily_rows, remaining_days))
                        
                        # 计算批次结束日期
                        batch_end_date = current_date + timedelta(days=days_per_batch - 1)
                        
                        batch_start_str = f"{current_date.strftime('%Y-%m-%d')} 09:30:00"
                        batch_end_str = f"{batch_end_date.strftime('%Y-%m-%d')} 19:00:00"
                        
                        # 批次序号
                        batch_num = len(all_dfs) + 1
                        expected_rows = days_per_batch * daily_rows
                        logger.info(f"[批次 {batch_num}] 获取: {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')} ({days_per_batch}天, 预计约{expected_rows}条)")
                        
                        # 控制 stk_mins 接口调用频率
                        _wait_for_stk_mins_rate_limit()
                        
                        try:
                            df = pro.stk_mins(
                                ts_code=ts_code,
                                freq=freq,
                                start_date=batch_start_str,
                                end_date=batch_end_str
                            )
                            
                            if df is not None and not df.empty:
                                actual_rows = len(df)
                                
                                # 数据量检查逻辑
                                if actual_rows >= 8000:
                                    logger.warning(f"[批次 {batch_num}] 数据量达到上限: {actual_rows} 条，可能需要缩小批次大小")
                                elif actual_rows < expected_rows * 0.5:
                                    logger.debug(f"[批次 {batch_num}] 数据量明显小于预计值，可能已到数据末尾: {actual_rows} 条 (预计 {expected_rows} 条)")
                                
                                # 检查返回数据量
                                if actual_rows >= warning_threshold:
                                    logger.warning(f"[批次 {batch_num}] 返回数据量接近限制: {actual_rows}行，批次: {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')}")
                                
                                all_dfs.append(df)
                                logger.info(f"[批次 {batch_num}] 实际获取: {actual_rows} 条数据 (预计 {expected_rows} 条)")
                                logger.debug(f"[批次 {batch_num}] 获取到批次 {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')} 的数据: {actual_rows} 行")
                                
                                # 第一批次后，根据实际数据量动态调整 daily_rows
                                if len(all_dfs) == 1 and actual_rows > 0 and days_per_batch > 0:
                                    actual_daily_rows = actual_rows / days_per_batch
                                    if actual_daily_rows > daily_rows * 1.5:  # 如果实际值明显大于预计值
                                        old_daily_rows = daily_rows
                                        daily_rows = int(actual_daily_rows * 1.2)  # 使用实际值的1.2倍作为安全边际
                                        logger.info(f"[批次 {batch_num}] 根据实际数据量调整 daily_rows: {old_daily_rows} -> {daily_rows} 条/天 (实际 {actual_daily_rows:.1f} 条/天)")
                                
                                # 立即保存当前批次到缓存
                                if config:
                                    try:
                                        batch_df = _convert_tushare_batch_to_standard_format(df)
                                        if batch_df is not None and not batch_df.empty:
                                            from src.data_cache import save_etf_minute_cache
                                            save_etf_minute_cache(symbol, period, batch_df, config=config)
                                            logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                    except Exception as e:
                                        logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                            
                            # stk_mins 接口的频率控制已在调用前完成，这里不需要额外等待
                            
                        except Exception as e:
                            error_msg = str(e)
                            # 如果是频率限制错误，等待更长时间后重试
                            if "每分钟最多访问" in error_msg or "频率" in error_msg.lower() or "rate limit" in error_msg.lower():
                                logger.warning(f"遇到频率限制错误，等待60秒后重试: {error_msg}")
                                time.sleep(60)
                                # 清理调用记录，重新开始
                                _stk_mins_call_times.clear()
                                # 重新控制频率
                                _wait_for_stk_mins_rate_limit()
                                # 重试当前调用
                                try:
                                    df = pro.stk_mins(
                                        ts_code=ts_code,
                                        freq=freq,
                                        start_date=batch_start_str,
                                        end_date=batch_end_str
                                    )
                                    if df is not None and not df.empty:
                                        actual_rows = len(df)
                                        if actual_rows >= warning_threshold:
                                            logger.warning(f"[批次 {batch_num}] 返回数据量接近限制: {actual_rows}行，批次: {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')}")
                                        all_dfs.append(df)
                                        logger.info(f"[批次 {batch_num}] 实际获取: {actual_rows} 条数据 (预计 {expected_rows} 条)")
                                        logger.debug(f"[批次 {batch_num}] 获取到批次 {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')} 的数据: {actual_rows} 行")
                                        
                                        # 第一批次后，根据实际数据量动态调整 daily_rows
                                        if len(all_dfs) == 1 and actual_rows > 0 and days_per_batch > 0:
                                            actual_daily_rows = actual_rows / days_per_batch
                                            if actual_daily_rows > daily_rows * 1.5:
                                                old_daily_rows = daily_rows
                                                daily_rows = int(actual_daily_rows * 1.2)
                                                logger.info(f"[批次 {batch_num}] 根据实际数据量调整 daily_rows: {old_daily_rows} -> {daily_rows} 条/天 (实际 {actual_daily_rows:.1f} 条/天)")
                                        
                                        # 立即保存当前批次到缓存
                                        if config:
                                            try:
                                                batch_df = _convert_tushare_batch_to_standard_format(df)
                                                if batch_df is not None and not batch_df.empty:
                                                    from src.data_cache import save_etf_minute_cache
                                                    save_etf_minute_cache(symbol, period, batch_df, config=config)
                                                    logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                            except Exception as e:
                                                logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                                    continue
                                except Exception as e3:
                                    logger.warning(f"重试后仍然失败: {e3}")
                            # 如果是token错误，尝试回退到默认token
                            elif use_prefer_token and ("token" in error_msg.lower() or "您的token不对" in error_msg):
                                logger.warning(f"prefer_token 调用失败，尝试使用默认token: {error_msg}")
                                pro = get_tushare_pro()
                                if pro is None:
                                    logger.error("默认token也无效，无法继续获取数据")
                                    return None
                                use_prefer_token = False
                                # 重试当前调用
                                # 控制 stk_mins 接口调用频率
                                _wait_for_stk_mins_rate_limit()
                                try:
                                    df = pro.stk_mins(
                                        ts_code=ts_code,
                                        freq=freq,
                                        start_date=batch_start_str,
                                        end_date=batch_end_str
                                    )
                                    if df is not None and not df.empty:
                                        actual_rows = len(df)
                                        if actual_rows >= warning_threshold:
                                            logger.warning(f"[批次 {batch_num}] 返回数据量接近限制: {actual_rows}行，批次: {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')}")
                                        all_dfs.append(df)
                                        logger.info(f"[批次 {batch_num}] 实际获取: {actual_rows} 条数据 (预计 {expected_rows} 条)")
                                        logger.debug(f"[批次 {batch_num}] 获取到批次 {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')} 的数据: {actual_rows} 行")
                                        
                                        # 第一批次后，根据实际数据量动态调整 daily_rows
                                        if len(all_dfs) == 1 and actual_rows > 0 and days_per_batch > 0:
                                            actual_daily_rows = actual_rows / days_per_batch
                                            if actual_daily_rows > daily_rows * 1.5:
                                                old_daily_rows = daily_rows
                                                daily_rows = int(actual_daily_rows * 1.2)
                                                logger.info(f"[批次 {batch_num}] 根据实际数据量调整 daily_rows: {old_daily_rows} -> {daily_rows} 条/天 (实际 {actual_daily_rows:.1f} 条/天)")
                                        
                                        # 立即保存当前批次到缓存
                                        if config:
                                            try:
                                                batch_df = _convert_tushare_batch_to_standard_format(df)
                                                if batch_df is not None and not batch_df.empty:
                                                    from src.data_cache import save_etf_minute_cache
                                                    save_etf_minute_cache(symbol, period, batch_df, config=config)
                                                    logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                            except Exception as e:
                                                logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                                    # stk_mins 接口的频率控制已在调用前完成，这里不需要额外等待
                                except Exception as e2:
                                    logger.warning(f"使用默认token重试失败: {e2}")
                            else:
                                logger.warning(f"[批次 {batch_num}] 获取批次 {current_date.strftime('%Y-%m-%d')} ~ {batch_end_date.strftime('%Y-%m-%d')} 的 ETF 分钟数据失败: {error_msg}")
                        
                        # 更新当前日期到下一批次的开始
                        old_date = current_date
                        current_date = batch_end_date + timedelta(days=1)
                        logger.debug(f"[批次 {batch_num}] 批次完成，日期更新: {old_date.strftime('%Y-%m-%d')} -> {current_date.strftime('%Y-%m-%d')}")
            else:
                # 数据量不大，可以直接获取，但仍需要检查返回数据量
                # 控制 stk_mins 接口调用频率
                _wait_for_stk_mins_rate_limit()
                
                try:
                    df = pro.stk_mins(
                        ts_code=ts_code,
                        freq=freq,
                        start_date=start_date_str,
                        end_date=end_date_str
                    )
                    if df is not None and not df.empty:
                        # 检查返回数据量
                        if len(df) >= warning_threshold:
                            logger.warning(f"返回数据量接近限制: {len(df)}行，可能需要分批获取")
                            # 如果超过8000行，需要分批
                            if len(df) >= max_rows_per_call:
                                logger.warning(f"返回数据量超过限制: {len(df)}行，数据可能不完整，建议分批获取")
                        all_dfs.append(df)
                        
                        # 立即保存当前批次到缓存
                        if config:
                            try:
                                batch_df = _convert_tushare_batch_to_standard_format(df)
                                if batch_df is not None and not batch_df.empty:
                                    from src.data_cache import save_etf_minute_cache
                                    save_etf_minute_cache(symbol, period, batch_df, config=config)
                                    logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                            except Exception as e:
                                logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                except Exception as e:
                    error_msg = str(e)
                    # 如果是频率限制错误，等待更长时间后重试
                    if "每分钟最多访问" in error_msg or "频率" in error_msg.lower() or "rate limit" in error_msg.lower():
                        logger.warning(f"遇到频率限制错误，等待60秒后重试: {error_msg}")
                        time.sleep(60)
                        # 清理调用记录，重新开始
                        _stk_mins_call_times.clear()
                        # 重新控制频率
                        _wait_for_stk_mins_rate_limit()
                        # 重试当前调用
                        try:
                            df = pro.stk_mins(
                                ts_code=ts_code,
                                freq=freq,
                                start_date=start_date_str,
                                end_date=end_date_str
                            )
                            if df is not None and not df.empty:
                                if len(df) >= warning_threshold:
                                    logger.warning(f"返回数据量接近限制: {len(df)}行，可能需要分批获取")
                                if len(df) >= max_rows_per_call:
                                    logger.warning(f"返回数据量超过限制: {len(df)}行，数据可能不完整，建议分批获取")
                                all_dfs.append(df)
                                
                                # 立即保存当前批次到缓存
                                if config:
                                    try:
                                        batch_df = _convert_tushare_batch_to_standard_format(df)
                                        if batch_df is not None and not batch_df.empty:
                                            from src.data_cache import save_etf_minute_cache
                                            save_etf_minute_cache(symbol, period, batch_df, config=config)
                                            logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                    except Exception as e:
                                        logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                            return None if not all_dfs else None  # 继续后续处理
                        except Exception as e3:
                            logger.warning(f"重试后仍然失败: {e3}")
                            return None
                    # 如果是token错误，尝试回退到默认token
                    elif use_prefer_token and ("token" in error_msg.lower() or "您的token不对" in error_msg):
                        logger.warning(f"prefer_token 调用失败，尝试使用默认token: {error_msg}")
                        pro = get_tushare_pro()
                        if pro is None:
                            logger.error("默认token也无效，无法继续获取数据")
                            return None
                        use_prefer_token = False
                        # 重试当前调用
                        # 控制 stk_mins 接口调用频率
                        _wait_for_stk_mins_rate_limit()
                        try:
                            df = pro.stk_mins(
                                ts_code=ts_code,
                                freq=freq,
                                start_date=start_date_str,
                                end_date=end_date_str
                            )
                            if df is not None and not df.empty:
                                if len(df) >= warning_threshold:
                                    logger.warning(f"返回数据量接近限制: {len(df)}行，可能需要分批获取")
                                if len(df) >= max_rows_per_call:
                                    logger.warning(f"返回数据量超过限制: {len(df)}行，数据可能不完整，建议分批获取")
                                all_dfs.append(df)
                                
                                # 立即保存当前批次到缓存
                                if config:
                                    try:
                                        batch_df = _convert_tushare_batch_to_standard_format(df)
                                        if batch_df is not None and not batch_df.empty:
                                            from src.data_cache import save_etf_minute_cache
                                            save_etf_minute_cache(symbol, period, batch_df, config=config)
                                            logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                    except Exception as e:
                                        logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                        except Exception as e2:
                            logger.warning(f"使用默认token重试失败: {e2}")
                            return None
                    else:
                        logger.warning(f"获取 ETF 分钟数据失败: {error_msg}")
                        return None
        else:
            # 没有日期范围，直接获取（可能只获取最近的数据）
            # 控制 stk_mins 接口调用频率
            _wait_for_stk_mins_rate_limit()
            
            try:
                df = pro.stk_mins(
                    ts_code=ts_code,
                    freq=freq,
                    start_date=start_date_str or "",
                    end_date=end_date_str or ""
                )
                if df is not None and not df.empty:
                    # 检查返回数据量
                    if len(df) >= warning_threshold:
                        logger.warning(f"返回数据量接近限制: {len(df)}行，可能需要分批获取")
                    all_dfs.append(df)
                    
                    # 立即保存当前批次到缓存
                    if config:
                        try:
                            batch_df = _convert_tushare_batch_to_standard_format(df)
                            if batch_df is not None and not batch_df.empty:
                                from src.data_cache import save_etf_minute_cache
                                save_etf_minute_cache(symbol, period, batch_df, config=config)
                                logger.debug(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                        except Exception as e:
                            logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
            except Exception as e:
                error_msg = str(e)
                # 如果是频率限制错误，等待更长时间后重试
                if "每分钟最多访问" in error_msg or "频率" in error_msg.lower() or "rate limit" in error_msg.lower():
                    logger.warning(f"遇到频率限制错误，等待60秒后重试: {error_msg}")
                    time.sleep(60)
                    # 清理调用记录，重新开始
                    _stk_mins_call_times.clear()
                    # 重新控制频率
                    _wait_for_stk_mins_rate_limit()
                    # 重试当前调用
                    try:
                        df = pro.stk_mins(
                            ts_code=ts_code,
                            freq=freq,
                            start_date=start_date_str or "",
                            end_date=end_date_str or ""
                        )
                        if df is not None and not df.empty:
                            if len(df) >= warning_threshold:
                                logger.warning(f"返回数据量接近限制: {len(df)}行，可能需要分批获取")
                            all_dfs.append(df)
                            
                            # 立即保存当前批次到缓存
                            if config:
                                try:
                                    batch_df = _convert_tushare_batch_to_standard_format(df)
                                    if batch_df is not None and not batch_df.empty:
                                        from src.data_cache import save_etf_minute_cache
                                        save_etf_minute_cache(symbol, period, batch_df, config=config)
                                        logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                except Exception as e:
                                    logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                        return None if not all_dfs else None  # 继续后续处理
                    except Exception as e3:
                        logger.warning(f"重试后仍然失败: {e3}")
                        return None
                # 如果是token错误，尝试回退到默认token
                elif use_prefer_token and ("token" in error_msg.lower() or "您的token不对" in error_msg):
                    logger.warning(f"prefer_token 调用失败，尝试使用默认token: {error_msg}")
                    pro = get_tushare_pro()
                    if pro is None:
                        logger.error("默认token也无效，无法继续获取数据")
                        return None
                    use_prefer_token = False
                    # 重试当前调用
                    # 控制 stk_mins 接口调用频率
                    _wait_for_stk_mins_rate_limit()
                    try:
                        df = pro.stk_mins(
                            ts_code=ts_code,
                            freq=freq,
                            start_date=start_date_str or "",
                            end_date=end_date_str or ""
                        )
                        if df is not None and not df.empty:
                            if len(df) >= warning_threshold:
                                logger.warning(f"返回数据量接近限制: {len(df)}行，可能需要分批获取")
                            all_dfs.append(df)
                            
                            # 立即保存当前批次到缓存
                            if config:
                                try:
                                    batch_df = _convert_tushare_batch_to_standard_format(df)
                                    if batch_df is not None and not batch_df.empty:
                                        from src.data_cache import save_etf_minute_cache
                                        save_etf_minute_cache(symbol, period, batch_df, config=config)
                                        logger.info(f"已保存批次数据到缓存: {symbol}, {period}, {len(batch_df)} 条")
                                except Exception as e:
                                    logger.debug(f"保存批次缓存失败（不影响主流程）: {e}")
                    except Exception as e2:
                        logger.warning(f"使用默认token重试失败: {e2}")
                        return None
                else:
                    logger.warning(f"获取 ETF 分钟数据失败: {error_msg}")
                    return None
        
        if not all_dfs:
            logger.warning(f"Tushare stk_mins 返回空数据: {ts_code}, {freq}")
            return None
        
        # 合并所有数据
        combined_df = pd.concat(all_dfs, ignore_index=True)
        
        # 去重（按交易时间）
        combined_df = combined_df.drop_duplicates(subset=['trade_time'], keep='last')
        
        # 按交易时间排序
        combined_df = combined_df.sort_values(by='trade_time')
        
        # 转换为 akshare 兼容格式
        # Tushare 返回的 trade_time 格式是 YYYY-MM-DD HH:MM:SS
        try:
            # 尝试使用标准格式解析
            time_series = pd.to_datetime(combined_df['trade_time'], format='%Y-%m-%d %H:%M:%S')
        except ValueError:
            # 如果失败，尝试自动推断格式
            time_series = pd.to_datetime(combined_df['trade_time'])
        
        result = pd.DataFrame({
            '时间': time_series.dt.strftime('%Y-%m-%d %H:%M:%S'),
            '开盘': combined_df['open'],
            '收盘': combined_df['close'],
            '最高': combined_df['high'],
            '最低': combined_df['low'],
            '成交量': combined_df['vol'],
            '成交额': combined_df['amount']
        })
        
        logger.info(f"Tushare 获取 ETF 分钟数据成功: {symbol}, {freq}, {len(result)} 条数据")
        return result
        
    except Exception as e:
        logger.warning(f"Tushare stk_mins 失败: {symbol}, {period}, 错误: {e}")
        return None