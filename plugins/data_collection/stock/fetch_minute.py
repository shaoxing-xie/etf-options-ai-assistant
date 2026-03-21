"""
获取A股股票分钟数据
在指数/ETF 分钟采集工具基础上实现，复用缓存与字段统一逻辑。
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import os
import sys
import pytz

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


def _ensure_src_import():
    selected_root: Optional[Path] = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "src").exists():
            selected_root = parent
            break
    if selected_root is not None and str(selected_root) not in sys.path:
        sys.path.insert(0, str(selected_root))
    return selected_root


_ROOT = _ensure_src_import()

try:
    from src.data_cache import (
        get_cached_stock_minute,
        save_stock_minute_cache,
        merge_cached_and_fetched_data,
    )
    from src.config_loader import load_system_config
    CACHE_AVAILABLE = True
except Exception:
    CACHE_AVAILABLE = False
    load_system_config = None  # type: ignore[arg-type]

# 交易日判断工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
utils_path = os.path.join(parent_dir, "utils")
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.trading_day import check_trading_day_before_operation
    TRADING_DAY_CHECK_AVAILABLE = True
except ImportError:
    TRADING_DAY_CHECK_AVAILABLE = False

    def check_trading_day_before_operation(*args, **kwargs):
        return None


def normalize_date(date_str: str) -> str:
    """统一日期格式为 YYYY-MM-DD HH:MM:SS"""
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 09:30:00"
    if len(date_str) == 10 and "-" in date_str:
        return f"{date_str} 09:30:00"
    return date_str


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """统一字段名映射：将英文字段名转换为中文字段名"""
    if df is None or df.empty:
        return df

    column_mapping: Dict[str, str] = {}

    # 时间字段
    if "time" in df.columns and "时间" not in df.columns:
        column_mapping["time"] = "时间"
    if "date" in df.columns and "时间" not in df.columns:
        column_mapping["date"] = "时间"
    if "datetime" in df.columns and "时间" not in df.columns:
        column_mapping["datetime"] = "时间"
    if "day" in df.columns and "时间" not in df.columns:
        column_mapping["day"] = "时间"

    # 价格字段
    if "open" in df.columns and "开盘" not in df.columns:
        column_mapping["open"] = "开盘"
    if "close" in df.columns and "收盘" not in df.columns:
        column_mapping["close"] = "收盘"
    if "high" in df.columns and "最高" not in df.columns:
        column_mapping["high"] = "最高"
    if "low" in df.columns and "最低" not in df.columns:
        column_mapping["low"] = "最低"

    # 成交量字段
    if "volume" in df.columns and "成交量" not in df.columns:
        column_mapping["volume"] = "成交量"
    if "vol" in df.columns and "成交量" not in df.columns:
        column_mapping["vol"] = "成交量"

    # 成交额字段
    if "amount" in df.columns and "成交额" not in df.columns:
        column_mapping["amount"] = "成交额"

    if column_mapping:
        df = df.rename(columns=column_mapping)
    return df


def calculate_missing_fields(df: pd.DataFrame) -> pd.DataFrame:
    """自动计算缺失的成交额和涨跌幅"""
    if df is None or df.empty:
        return df

    df = df.copy()

    if "成交额" not in df.columns or df["成交额"].isna().all() or (df["成交额"] == 0).all():
        if "成交量" in df.columns and "收盘" in df.columns:
            df["成交额"] = df["成交量"] * df["收盘"] * 100
        else:
            df["成交额"] = 0

    if "涨跌幅" not in df.columns:
        if "收盘" in df.columns:
            df["涨跌幅"] = df["收盘"].pct_change() * 100
            df["涨跌幅"] = df["涨跌幅"].fillna(0)
        else:
            df["涨跌幅"] = 0

    return df


def _get_latest_cached_timestamp_stock(
    symbol: str,
    period: str,
    date_yyyymmdd: str,
    config: Optional[Dict] = None,
) -> Optional[datetime]:
    """
    获取指定 symbol/period/date 的缓存中最新一条数据的时间戳。
    用于判断缓存新鲜度：若 (当前时间 - 最新时间) > period 分钟，则需要拉取。
    """
    if not CACHE_AVAILABLE:
        return None
    try:
        cached_df, missing = get_cached_stock_minute(
            symbol, period, date_yyyymmdd, date_yyyymmdd, config=config
        )
        if cached_df is None or cached_df.empty:
            return None
        time_col = None
        for col in ["时间", "date", "日期时间", "datetime"]:
            if col in cached_df.columns:
                time_col = col
                break
        if not time_col:
            return None
        last_val = cached_df[time_col].iloc[-1]
        if pd.isna(last_val):
            return None
        dt = pd.to_datetime(last_val)
        if hasattr(dt, "to_pydatetime"):
            dt = dt.to_pydatetime()
        tz_sh = pytz.timezone("Asia/Shanghai")
        if dt.tzinfo is None:
            dt = tz_sh.localize(dt)
        elif str(dt.tzinfo) != "Asia/Shanghai":
            dt = dt.astimezone(tz_sh)
        return dt
    except Exception:
        return None


def _fetch_stock_minute_sina(
    stock_code: str,
    period: str,
    start_date_str: str,
    end_date_str: str,
) -> Optional[pd.DataFrame]:
    """
    使用 AkShare 的新浪分钟接口获取股票分钟数据（主数据源）
    对应 docs 中的 stock_zh_a_minute(symbol='sh600751', period='1', adjust="")
    """
    if not AKSHARE_AVAILABLE:
        return None
    # 构造带交易所前缀的 symbol
    clean = stock_code
    if clean.upper().endswith((".SH", ".SZ", ".BJ")):
        clean = clean.split(".")[0]
    if clean.lower().startswith(("sh", "sz", "bj")) and len(clean) > 2:
        clean = clean[2:]
    if clean.startswith("6"):
        symbol = f"sh{clean}"
    else:
        symbol = f"sz{clean}"
    try:
        df = ak.stock_zh_a_minute(symbol=symbol, period=period, adjust="")
        if df is None or df.empty:
            return None
        # stock_zh_a_minute 返回列名为 day/open/high/low/close/volume
        df = normalize_column_names(df)
        df = calculate_missing_fields(df)
        if "时间" in df.columns:
            df["时间"] = pd.to_datetime(df["时间"], errors="coerce")
            df = df[df["时间"].notna()].copy()
            df["时间"] = df["时间"].dt.strftime("%Y-%m-%d %H:%M:%S")
            df = df.sort_values("时间").reset_index(drop=True)
        return df
    except Exception:
        return None


def _fetch_stock_minute_eastmoney(
    clean_code: str,
    period: str,
    start_date_str: str,
    end_date_str: str,
) -> Optional[pd.DataFrame]:
    """
    使用 AkShare 的东财分钟接口获取股票分钟数据（备用数据源）
    对应 docs 中的 stock_zh_a_hist_min_em
    """
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = ak.stock_zh_a_hist_min_em(
            symbol=clean_code,
            period=period,
            start_date=start_date_str,
            end_date=end_date_str,
            adjust="",
        )
        if df is None or df.empty:
            return None
        df = normalize_column_names(df)
        df = calculate_missing_fields(df)
        if "时间" in df.columns:
            df["时间"] = pd.to_datetime(df["时间"], errors="coerce")
            df = df[df["时间"].notna()].copy()
            df["时间"] = df["时间"].dt.strftime("%Y-%m-%d %H:%M:%S")
            df = df.sort_values("时间").reset_index(drop=True)
        return df
    except Exception:
        return None


def _fetch_stock_minute_mootdx(
    stock_code: str,
    period: str,
    start_date_str: str,
    end_date_str: str,
    max_bars: int = 800,
) -> Optional[pd.DataFrame]:
    """
    使用 mootdx 获取股票分钟数据。

    参数:
        stock_code: 可以是 600519 / sh600519 / 600519.SH 等，会在内部标准化为6位代码
        period: "1", "5", "15", "30", "60"
        start_date_str/end_date_str: "YYYY-MM-DD HH:MM:SS"
    """
    if not MOOTDX_AVAILABLE:
        return None

    clean = stock_code
    if clean.upper().endswith((".SH", ".SZ", ".BJ")):
        clean = clean.split(".")[0]
    if clean.lower().startswith(("sh", "sz", "bj")) and len(clean) > 2:
        clean = clean[2:]

    freq_map = {
        "1": 7,   # 1 分钟
        "5": 0,   # 5 分钟
        "15": 1,  # 15 分钟
        "30": 2,  # 30 分钟
        "60": 3,  # 60 分钟
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

    # mootdx 返回字段: datetime/open/high/low/close/vol/amount 等
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

            time_vals = pd.to_datetime(df["时间"], errors="coerce")
            mask = (time_vals >= start_dt) & (time_vals <= end_dt)
            df = df[mask].copy()
        except Exception:
            pass

    if df.empty:
        return None

    return df


def fetch_single_stock_minute(
    stock_code: str,
    period: str = "5",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    use_cache: bool = True,
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    获取单只股票的分钟数据
    """
    if period not in ["1", "5", "15", "30", "60"]:
        return None, None

    clean_code = stock_code
    if clean_code.upper().endswith((".SH", ".SZ", ".BJ")):
        clean_code = clean_code.split(".")[0]
    if clean_code.lower().startswith(("sh", "sz", "bj")) and len(clean_code) > 2:
        clean_code = clean_code[2:]

    now = datetime.now()
    if not end_date:
        end_date_str = now.strftime("%Y-%m-%d 15:00:00")
    else:
        end_date_str = normalize_date(end_date)
        if not end_date_str.endswith(" 15:00:00"):
            end_date_str = end_date_str.replace(" 09:30:00", " 15:00:00")

    if not start_date:
        start = now - timedelta(days=lookback_days * 2)
        start_date_str = start.strftime("%Y-%m-%d 09:30:00")
    else:
        start_date_str = normalize_date(start_date)

    df: Optional[pd.DataFrame] = None
    source: Optional[str] = None
    cached_partial_df: Optional[pd.DataFrame] = None

    # 缓存
    if use_cache and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True) if load_system_config else None
            start_date_formatted = start_date_str[:10].replace("-", "")
            end_date_formatted = end_date_str[:10].replace("-", "")
            cached_df, missing_dates = get_cached_stock_minute(
                clean_code, period, start_date_formatted, end_date_formatted, config=config
            )
            if cached_df is not None and not cached_df.empty and not missing_dates:
                return cached_df, "cache"
            if cached_df is not None and not cached_df.empty and missing_dates:
                cached_partial_df = cached_df
                if missing_dates:
                    start_date_formatted = min(missing_dates)
                    end_date_formatted = max(missing_dates)
                    start_date_str = f"{start_date_formatted[:4]}-{start_date_formatted[4:6]}-{start_date_formatted[6:8]} 09:30:00"
                    end_date_str = f"{end_date_formatted[:4]}-{end_date_formatted[4:6]}-{end_date_formatted[6:8]} 15:00:00"
        except Exception:
            pass

    # 主数据源1：mootdx 分钟K线（如果可用）
    df = _fetch_stock_minute_mootdx(
        stock_code=stock_code,
        period=period,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
    )
    if df is not None and not df.empty:
        source = "mootdx"

    # 主数据源2：AkShare + 新浪接口
    if (df is None or df.empty) and AKSHARE_AVAILABLE:
        df = _fetch_stock_minute_sina(
            stock_code=stock_code,
            period=period,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
        )
        if df is not None and not df.empty:
            source = "sina_akshare"

    # 备用：东财分钟接口
    if (df is None or df.empty) and AKSHARE_AVAILABLE:
        df = _fetch_stock_minute_eastmoney(
            clean_code=clean_code,
            period=period,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
        )
        if df is not None and not df.empty:
            source = "eastmoney_akshare"

    # 合并部分缓存
    if df is not None and not df.empty and cached_partial_df is not None:
        try:
            time_col = None
            for col in ["时间", "date", "日期时间", "datetime"]:
                if col in df.columns:
                    time_col = col
                    break
            if time_col:
                df = merge_cached_and_fetched_data(cached_partial_df, df, time_col)
                source = f"{source}+cache" if source else "cache"
        except Exception:
            pass

    # 如果外部数据源失败但有部分缓存，返回缓存
    if (df is None or df.empty) and cached_partial_df is not None and not cached_partial_df.empty:
        df = cached_partial_df
        if not source:
            source = "cache_partial"

    # 保存缓存
    if df is not None and not df.empty and use_cache and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True) if load_system_config else None
            save_stock_minute_cache(clean_code, period, df, config=config)
        except Exception:
            pass

    return df, source


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and (value != value)):
            return default
        if isinstance(value, (np.integer, np.floating)):
            return float(value)
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and (value != value)):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fetch_stock_minute(
    stock_code: str = "600000",
    period: str = "5",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    mode: str = "production",
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    获取股票分钟数据，支持多股票代码（逗号分隔）
    """
    # 交易日检查
    if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
        trading_day_check = check_trading_day_before_operation("获取股票分钟数据")
        if trading_day_check:
            return trading_day_check

    if period not in ["1", "5", "15", "30", "60", "5,15,30", "all"]:
        return {
            "success": False,
            "message": f"不支持的周期: {period}，支持: 1, 5, 15, 30, 60, 5,15,30, all",
            "data": None,
        }

    # 批量多周期采集模式：仅更新缓存，不返回明细
    if period in ("5,15,30", "all"):
        periods_to_fetch = ["5", "15", "30"]
        tz_sh = pytz.timezone("Asia/Shanghai")
        now = datetime.now(tz_sh)
        today = now.strftime("%Y%m%d")
        config = None
        if CACHE_AVAILABLE and load_system_config:
            try:
                config = load_system_config(use_cache=True)
            except Exception:
                config = None
        fetched: List[str] = []
        skipped: List[str] = []

        if isinstance(stock_code, str):
            codes = [c.strip() for c in stock_code.split(",") if c.strip()]
        else:
            codes = [str(stock_code).strip()]

        if not codes:
            return {"success": False, "message": "未提供有效的股票代码", "data": None}

        for code in codes:
            clean_code = code
            if clean_code.upper().endswith((".SH", ".SZ", ".BJ")):
                clean_code = clean_code.split(".")[0]
            if clean_code.lower().startswith(("sh", "sz", "bj")) and len(clean_code) > 2:
                clean_code = clean_code[2:]

            for p in periods_to_fetch:
                latest_ts = (
                    _get_latest_cached_timestamp_stock(clean_code, p, today, config)
                    if CACHE_AVAILABLE
                    else None
                )
                need_fetch = latest_ts is None
                if not need_fetch and latest_ts is not None:
                    gap_min = (now - latest_ts).total_seconds() / 60
                    need_fetch = gap_min > int(p)
                if need_fetch:
                    df_out, _ = fetch_single_stock_minute(
                        stock_code=clean_code,
                        period=p,
                        start_date=None,
                        end_date=None,
                        lookback_days=lookback_days or 5,
                        use_cache=use_cache,
                    )
                    if df_out is not None and not df_out.empty:
                        fetched.append(f"{clean_code}/{p}min")
                    else:
                        skipped.append(f"{clean_code}/{p}min(fetch_failed)")
                else:
                    skipped.append(f"{clean_code}/{p}min")

        return {
            "success": True,
            "message": "批量采集完成，股票分钟数据已缓存",
            "data": {"fetched": fetched, "skipped": skipped},
        }

    # 单周期模式，返回 klines
    if isinstance(stock_code, str):
        codes = [c.strip() for c in stock_code.split(",") if c.strip()]
    elif isinstance(stock_code, list):
        codes = [str(c).strip() for c in stock_code if str(c).strip()]
    else:
        codes = [str(stock_code).strip()]

    if not codes:
        return {"success": False, "message": "未提供有效的股票代码", "data": None}

    now = datetime.now()
    if end_date:
        end_date_norm = normalize_date(end_date)[:10]
    else:
        end_date_norm = now.strftime("%Y-%m-%d")
    if start_date:
        start_date_norm = normalize_date(start_date)[:10]
    else:
        start = now - timedelta(days=lookback_days * 2)
        start_date_norm = start.strftime("%Y-%m-%d")

    results: List[Dict[str, Any]] = []
    source: Optional[str] = None

    for code in codes:
        df, data_source = fetch_single_stock_minute(
            stock_code=code,
            period=period,
            start_date=start_date_norm,
            end_date=end_date_norm,
            lookback_days=lookback_days,
            use_cache=use_cache,
        )
        if data_source:
            source = data_source

        if df is None or df.empty:
            results.append(
                {
                    "stock_code": code,
                    "period": period,
                    "count": 0,
                    "klines": [],
                    "message": "股票分钟数据暂时不可用，请稍后重试",
                }
            )
            continue

        MAX_RECORDS = 350
        total_count = len(df)
        if total_count > MAX_RECORDS:
            df = df.tail(MAX_RECORDS).copy()

        klines: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            time_str = ""
            for col in ["时间", "日期", "date", "日期时间", "datetime"]:
                if col in row.index:
                    try:
                        v = row[col]
                        if hasattr(v, "strftime"):
                            time_str = v.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            time_str = str(v)
                        break
                    except Exception:
                        continue

            klines.append(
                {
                    "time": time_str,
                    "open": _safe_float(row.get("开盘")),
                    "close": _safe_float(row.get("收盘")),
                    "high": _safe_float(row.get("最高")),
                    "low": _safe_float(row.get("最低")),
                    "volume": _safe_int(row.get("成交量")),
                    "amount": _safe_float(row.get("成交额")),
                    "change_percent": _safe_float(row.get("涨跌幅")),
                }
            )

        result_data: Dict[str, Any] = {
            "stock_code": code,
            "period": period,
            "total_count": total_count,
            "returned_count": len(klines),
            "klines": klines,
            "start_date": start_date_norm,
            "end_date": end_date_norm,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if total_count > len(klines):
            result_data["note"] = f"共获取{total_count}条数据，只返回最新的{len(klines)}条"

        results.append(result_data)

    if not results:
        return {
            "success": False,
            "message": "未获取到任何数据",
            "data": None,
            "source": source or "unknown",
            "count": 0,
        }

    final_data: Any = results[0] if len(results) == 1 else results
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


def tool_fetch_stock_minute(
    stock_code: str = "600000",
    period: str = "5",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    mode: str = "production",
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取股票分钟数据
    """
    return fetch_stock_minute(
        stock_code=stock_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        mode=mode,
        use_cache=use_cache,
    )

