"""
获取A股股票历史数据
在指数/ETF 日线采集工具基础上实现，复用缓存与字段统一逻辑。
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import sys

try:
    import akshare as ak
    import tushare as ts
    AKSHARE_AVAILABLE = True
    TUSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    TUSHARE_AVAILABLE = False

try:
    from mootdx.quotes import Quotes
    MOOTDX_AVAILABLE = True
except Exception:  # noqa: BLE001
    MOOTDX_AVAILABLE = False

try:
    import baostock as bs  # noqa: F401
    BAOSTOCK_AVAILABLE = True
except ImportError:
    BAOSTOCK_AVAILABLE = False


def _ensure_src_import():
    """
    将项目根目录（包含 src/）加入 sys.path，保持与指数/ETF 工具一致的动态导入方式。
    """
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
        get_cached_stock_daily,
        save_stock_daily_cache,
        merge_cached_and_fetched_data,
    )
    from src.config_loader import load_system_config
    CACHE_AVAILABLE = True
except Exception:
    CACHE_AVAILABLE = False
    load_system_config = None  # type: ignore[arg-type]


def normalize_date(date_str: str) -> Optional[str]:
    """将日期格式统一为 YYYY-MM-DD"""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    if len(date_str) == 10 and date_str.count("-") == 2:
        return date_str
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一字段名映射：将英文字段名转换为中文字段名
    """
    if df is None or df.empty:
        return df

    column_mapping: Dict[str, str] = {}

    # 日期字段
    if "date" in df.columns and "日期" not in df.columns:
        column_mapping["date"] = "日期"
    if "trade_date" in df.columns and "日期" not in df.columns:
        column_mapping["trade_date"] = "日期"

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

    # 涨跌幅
    if "pct_chg" in df.columns and "涨跌幅" not in df.columns:
        column_mapping["pct_chg"] = "涨跌幅"

    if column_mapping:
        df = df.rename(columns=column_mapping)

    return df


def calculate_missing_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    自动计算缺失的成交额和涨跌幅
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # 成交额
    if "成交额" not in df.columns or df["成交额"].isna().all() or (df["成交额"] == 0).all():
        if "成交量" in df.columns and "收盘" in df.columns:
            df["成交额"] = df["成交量"] * df["收盘"] * 100
        else:
            df["成交额"] = 0

    # 涨跌幅
    if "涨跌幅" not in df.columns:
        if "收盘" in df.columns:
            df["涨跌幅"] = df["收盘"].pct_change() * 100
            df["涨跌幅"] = df["涨跌幅"].fillna(0)
        else:
            df["涨跌幅"] = 0

    return df


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and (value != value)):
            return default
        if isinstance(value, (np.integer, np.floating)):
            return float(value)
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_stock_daily_mootdx(
    clean_code: str,
    start_date_norm: str,
    end_date_norm: str,
    max_bars: int = 800,
) -> Optional[pd.DataFrame]:
    """
    使用 mootdx 获取股票日线数据。

    参数:
        clean_code: 不带交易所前缀的6位股票代码，例如 "600519"
        start_date_norm: yyyy-mm-dd
        end_date_norm: yyyy-mm-dd
        max_bars: 从服务器取回的最大K线数量，最多800（mootdx限制）
    """
    if not MOOTDX_AVAILABLE:
        return None

    try:
        client = Quotes.factory(market="std")
    except Exception:
        return None

    try:
        # frequency=9 为日K（参考 mootdx 文档）
        df = client.bars(symbol=clean_code, frequency=9, offset=max_bars)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df = df.copy()
    # mootdx 返回列通常包含 datetime/open/high/low/close/vol/amount
    if "datetime" in df.columns and "日期" not in df.columns:
        df["日期"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d")

    df = normalize_column_names(df)
    df = calculate_missing_fields(df)

    if "日期" in df.columns:
        try:
            df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
            df = df[(df["日期"] >= start_date_norm) & (df["日期"] <= end_date_norm)].copy()
        except Exception:
            # 过滤失败时，仍然返回原始 df
            pass

    if df.empty:
        return None

    return df


def _fetch_stock_daily_baostock(
    clean_code: str,
    start_date_norm: str,
    end_date_norm: str,
) -> Optional[pd.DataFrame]:
    """Baostock 日线（无 token，长历史；前复权 adjustflag=3）。"""
    if not BAOSTOCK_AVAILABLE:
        return None
    try:
        import baostock as bs
    except ImportError:
        return None
    prefix = "sh" if clean_code.startswith(("5", "6", "9")) else "sz"
    code_bs = f"{prefix}.{clean_code}"
    lg = bs.login()
    if lg.error_code != "0":
        try:
            bs.logout()
        except Exception:
            pass
        return None
    try:
        rs = bs.query_history_k_data_plus(
            code_bs,
            "date,open,high,low,close,volume,amount,adjustflag",
            start_date=start_date_norm,
            end_date=end_date_norm,
            frequency="d",
            adjustflag="3",
        )
        rows: List[List[str]] = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=rs.fields)
    except Exception:
        return None
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    if df is None or df.empty:
        return None
    if "date" in df.columns:
        df["日期"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = normalize_column_names(df)
    df = calculate_missing_fields(df)
    return df if not df.empty else None


def _to_ak_tx_symbol(clean_code: str) -> str:
    if clean_code.startswith(("5", "6", "9")):
        return f"sh{clean_code}"
    return f"sz{clean_code}"


def _fetch_stock_daily_tencent_ak(
    clean_code: str,
    start_date_yyyymmdd: str,
    end_date_yyyymmdd: str,
) -> Optional[pd.DataFrame]:
    """AkShare 腾讯日线 stock_zh_a_hist_tx（第三备用免费源）。"""
    if not AKSHARE_AVAILABLE:
        return None
    try:
        ak_df = ak.stock_zh_a_hist_tx(
            symbol=_to_ak_tx_symbol(clean_code),
            start_date=start_date_yyyymmdd,
            end_date=end_date_yyyymmdd,
            adjust="qfq",
        )
    except Exception:
        return None
    if ak_df is None or ak_df.empty:
        return None
    ak_df = normalize_column_names(ak_df)
    if "日期" in ak_df.columns:
        ak_df["日期"] = pd.to_datetime(ak_df["日期"]).dt.strftime("%Y-%m-%d")
    return calculate_missing_fields(ak_df)


def fetch_single_stock_historical(
    stock_code: str,
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tushare_token: Optional[str] = None,
    use_cache: bool = True,
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    获取单只 A 股股票历史数据（日线为主）

    Provider 顺序（与 ROADMAP 一致）：
    1. 本地缓存（stock_daily）
    2. mootdx 日线
    3. Baostock（无 token）
    4. AkShare 新浪 stock_zh_a_daily
    5. AkShare 东财 stock_zh_a_hist（前复权）
    6. AkShare 腾讯 stock_zh_a_hist_tx
    7. Tushare pro.daily（EOD，需 token，置后）
    """
    if period != "daily":
        # 目前仅规划/实现日线，周/月后续扩展
        return None, None

    # 规范代码：接受 600000 / 600000.SH / sh600000 等形式
    clean_code = stock_code
    if clean_code.upper().endswith((".SH", ".SZ", ".BJ")):
        clean_code = clean_code.split(".")[0]
    if clean_code.lower().startswith(("sh", "sz", "bj")) and len(clean_code) > 2:
        clean_code = clean_code[2:]

    # 日期处理
    if end_date:
        end_date_norm = normalize_date(end_date)
    else:
        end_date_norm = datetime.now().strftime("%Y-%m-%d")

    if start_date:
        start_date_norm = normalize_date(start_date)
    else:
        start_date_norm = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    if not start_date_norm or not end_date_norm:
        return None, None

    start_date_yyyymmdd = start_date_norm.replace("-", "")
    end_date_yyyymmdd = end_date_norm.replace("-", "")

    df: Optional[pd.DataFrame] = None
    source: Optional[str] = None
    cached_partial_df: Optional[pd.DataFrame] = None

    # 1. 缓存
    if use_cache and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True) if load_system_config else None
            cached_df, missing_dates = get_cached_stock_daily(
                clean_code, start_date_yyyymmdd, end_date_yyyymmdd, config=config
            )
            if cached_df is not None and not cached_df.empty and not missing_dates:
                return cached_df, "cache"
            if cached_df is not None and not cached_df.empty and missing_dates:
                cached_partial_df = cached_df
                if missing_dates:
                    start_date_yyyymmdd = min(missing_dates)
                    end_date_yyyymmdd = max(missing_dates)
                    start_date_norm = normalize_date(start_date_yyyymmdd) or start_date_norm
                    end_date_norm = normalize_date(end_date_yyyymmdd) or end_date_norm
        except Exception:
            pass

    # 2. mootdx 作为优先日线数据源（如果可用）
    if (df is None or df.empty) and MOOTDX_AVAILABLE:
        try:
            df_mootdx = _fetch_stock_daily_mootdx(
                clean_code=clean_code,
                start_date_norm=start_date_norm,
                end_date_norm=end_date_norm,
            )
            if df_mootdx is not None and not df_mootdx.empty:
                df = df_mootdx
                source = "mootdx"
        except Exception:
            df_mootdx = None

    # 3. Baostock
    if (df is None or df.empty) and BAOSTOCK_AVAILABLE:
        try:
            bs_df = _fetch_stock_daily_baostock(
                clean_code=clean_code,
                start_date_norm=start_date_norm,
                end_date_norm=end_date_norm,
            )
            if bs_df is not None and not bs_df.empty:
                df = bs_df
                source = "baostock"
        except Exception:
            pass

    # 4. AkShare 新浪日线接口（stock_zh_a_daily）
    if (df is None or df.empty) and AKSHARE_AVAILABLE:
        try:
            # stock_zh_a_daily 需要带交易所前缀的 symbol，例如 sz000001 / sh600000
            if clean_code.startswith(("5", "6")):
                sina_symbol = f"sh{clean_code}"
            else:
                sina_symbol = f"sz{clean_code}"

            daily_df = ak.stock_zh_a_daily(
                symbol=sina_symbol,
                start_date=start_date_yyyymmdd,
                end_date=end_date_yyyymmdd,
                adjust="",
            )
            if daily_df is not None and not daily_df.empty:
                daily_df = normalize_column_names(daily_df)
                if "日期" in daily_df.columns:
                    daily_df["日期"] = pd.to_datetime(daily_df["日期"]).dt.strftime(
                        "%Y-%m-%d"
                    )
                df = calculate_missing_fields(daily_df)
                source = "akshare_sina_daily"
        except Exception:
            pass

    # 5. AkShare 股票历史（日线，东财 stock_zh_a_hist）
    if (df is None or df.empty) and AKSHARE_AVAILABLE:
        try:
            ak_df = ak.stock_zh_a_hist(
                symbol=clean_code,
                period="daily",
                start_date=start_date_yyyymmdd,
                end_date=end_date_yyyymmdd,
                adjust="qfq",
            )
            if ak_df is not None and not ak_df.empty:
                ak_df = normalize_column_names(ak_df)
                if "日期" in ak_df.columns:
                    ak_df["日期"] = pd.to_datetime(ak_df["日期"]).dt.strftime("%Y-%m-%d")
                df = calculate_missing_fields(ak_df)
                source = "akshare_eastmoney"
        except Exception:
            pass

    # 6. AkShare 腾讯日线（stock_zh_a_hist_tx）
    if (df is None or df.empty) and AKSHARE_AVAILABLE:
        try:
            tx_df = _fetch_stock_daily_tencent_ak(
                clean_code=clean_code,
                start_date_yyyymmdd=start_date_yyyymmdd,
                end_date_yyyymmdd=end_date_yyyymmdd,
            )
            if tx_df is not None and not tx_df.empty:
                df = tx_df
                source = "akshare_tencent_daily"
        except Exception:
            pass

    # 7. Tushare（EOD，需 token，置后）
    if (df is None or df.empty) and TUSHARE_AVAILABLE:
        try:
            token = tushare_token
            if not token and hasattr(ts, "get_apis"):
                pass
            if token:
                pro = ts.pro_api(token)
            else:
                pro = ts.pro_api()
            ts_code = f"{clean_code}.SH" if clean_code.startswith(("5", "6")) else f"{clean_code}.SZ"
            ts_df = pro.daily(
                ts_code=ts_code,
                start_date=start_date_yyyymmdd,
                end_date=end_date_yyyymmdd,
            )
            if ts_df is not None and not ts_df.empty:
                ts_df = ts_df.sort_values("trade_date")
                ts_df["date"] = pd.to_datetime(ts_df["trade_date"]).dt.strftime("%Y-%m-%d")
                ts_df = normalize_column_names(ts_df)
                df = calculate_missing_fields(ts_df)
                source = "tushare"
        except Exception:
            pass

    # 合并部分缓存
    if df is not None and not df.empty and cached_partial_df is not None:
        try:
            date_col = None
            for col in ["日期", "date", "日期时间", "datetime"]:
                if col in df.columns:
                    date_col = col
                    break
            if date_col:
                df = merge_cached_and_fetched_data(cached_partial_df, df, date_col)
                source = f"{source}+cache" if source else "cache"
        except Exception:
            pass

    # 保存缓存
    if df is not None and not df.empty and use_cache and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True) if load_system_config else None
            save_stock_daily_cache(clean_code, df, config=config)
        except Exception:
            pass

    return df, source


def fetch_stock_historical(
    stock_code: str,
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tushare_token: Optional[str] = None,
    use_cache: bool = True,
    lookback_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    获取A股股票历史数据，支持多股票代码（逗号分隔或列表），返回结构与指数/ETF 日线工具对齐。
    """
    try:
        if period != "daily":
            return {
                "success": False,
                "message": f"暂不支持的周期: {period}，当前仅支持 daily",
                "data": None,
            }

        if isinstance(stock_code, str):
            codes = [c.strip() for c in stock_code.split(",") if c.strip()]
        elif isinstance(stock_code, list):
            codes = [str(c).strip() for c in stock_code if str(c).strip()]
        else:
            codes = [str(stock_code).strip()]

        if not codes:
            return {"success": False, "message": "未提供有效的股票代码", "data": None}

        # 处理日期显示用的规范化形式
        if end_date:
            end_date_norm = normalize_date(end_date)
        else:
            end_date_norm = datetime.now().strftime("%Y-%m-%d")
        if start_date:
            start_date_norm = normalize_date(start_date)
        else:
            days = lookback_days if lookback_days is not None else 30
            start_date_norm = (datetime.now() - timedelta(days=days)).strftime(
                "%Y-%m-%d"
            )

        if not start_date_norm or not end_date_norm:
            return {
                "success": False,
                "message": "日期格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD",
                "data": None,
            }

        results: List[Dict[str, Any]] = []
        source: Optional[str] = None

        for code in codes:
            df, data_source = fetch_single_stock_historical(
                stock_code=code,
                period=period,
                start_date=start_date_norm,
                end_date=end_date_norm,
                tushare_token=tushare_token,
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
                        "message": "股票历史数据暂时不可用，请稍后重试",
                    }
                )
                continue

            klines: List[Dict[str, Any]] = []
            for _, row in df.iterrows():
                date_val = ""
                for col in ["日期", "date", "日期时间", "datetime"]:
                    if col in row.index:
                        try:
                            v = row[col]
                            if hasattr(v, "strftime"):
                                date_val = v.strftime("%Y-%m-%d")
                            else:
                                date_val = str(v)
                            break
                        except Exception:
                            continue

                klines.append(
                    {
                        "date": date_val,
                        "open": _safe_float(row.get("开盘")),
                        "high": _safe_float(row.get("最高")),
                        "low": _safe_float(row.get("最低")),
                        "close": _safe_float(row.get("收盘")),
                        "volume": _safe_float(row.get("成交量")),
                        "amount": _safe_float(row.get("成交额")),
                        "change_percent": _safe_float(row.get("涨跌幅")),
                    }
                )

            results.append(
                {
                    "stock_code": code,
                    "period": period,
                    "start_date": start_date_norm,
                    "end_date": end_date_norm,
                    "klines": klines,
                    "count": len(klines),
                }
            )

        if not results:
            return {
                "success": False,
                "message": "未获取到任何数据",
                "data": None,
                "source": source or "unknown",
                "count": 0,
            }

        final_data: Any = results[0] if len(results) == 1 else results
        return {
            "success": True,
            "message": f"Successfully fetched {sum(r.get('count', 0) for r in results)} records",
            "data": final_data,
            "source": source or "akshare",
            "count": len(results),
        }

    except Exception as e:
        return {"success": False, "message": f"Error: {e}", "data": None}


def tool_fetch_stock_historical(
    stock_code: str = "600000",
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True,
    lookback_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取股票历史数据
    """
    return fetch_stock_historical(
        stock_code=stock_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        use_cache=use_cache,
        lookback_days=lookback_days,
    )

