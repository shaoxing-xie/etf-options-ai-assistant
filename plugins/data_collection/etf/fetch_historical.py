"""
获取ETF历史数据
融合 Coze 插件 get_etf_historical.py
OpenClaw 插件工具
改进版本：支持缓存、多ETF、自动计算成交额/涨跌幅、完善字段映射
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, Tuple
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

# 尝试导入原系统的缓存模块（优先使用当前环境下的 /home/xie/src，其次回退到 Windows 路径）
try:
    # 1. 自底向上查找带有 src 目录的项目根（例如 /home/xie）
    selected_root = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "src").exists():
            selected_root = parent
            break

    # 2. 构造候选根路径（仅使用当前环境下可见的本地路径）
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
            get_cached_etf_daily, save_etf_daily_cache,
            merge_cached_and_fetched_data
        )
        from src.config_loader import load_system_config
        # 引入原系统的 Tushare 备份模块（统一 token / 频控）
        from src.tushare_fallback import fetch_etf_daily_tushare
        CACHE_AVAILABLE = True
    else:
        CACHE_AVAILABLE = False
        fetch_etf_daily_tushare = None  # type: ignore
except Exception:
    CACHE_AVAILABLE = False
    fetch_etf_daily_tushare = None  # type: ignore


def normalize_date(date_str: str) -> Optional[str]:
    """将日期格式统一为 YYYY-MM-DD"""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    elif len(date_str) == 10 and date_str.count('-') == 2:
        return date_str
    else:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d")
        except:
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                return dt.strftime("%Y-%m-%d")
            except:
                return None


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一字段名映射：将英文字段名转换为中文字段名
    
    Args:
        df: 原始DataFrame
    
    Returns:
        DataFrame: 字段名统一后的DataFrame
    """
    if df is None or df.empty:
        return df
    
    column_mapping = {}
    
    # 日期字段
    if 'date' in df.columns and '日期' not in df.columns:
        column_mapping['date'] = '日期'
    if 'trade_date' in df.columns and '日期' not in df.columns:
        column_mapping['trade_date'] = '日期'
    
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
    
    # 涨跌幅字段
    if 'pct_chg' in df.columns and '涨跌幅' not in df.columns:
        column_mapping['pct_chg'] = '涨跌幅'
    if 'change' in df.columns and '涨跌额' not in df.columns:
        column_mapping['change'] = '涨跌额'
    
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
    if df is None or df.empty:
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


def _fetch_etf_daily_mootdx(
    clean_code: str,
    start_date: str,
    end_date: str,
    max_bars: int = 800,
) -> Optional[pd.DataFrame]:
    """
    使用 mootdx 获取 ETF 日线数据。

    参数:
        clean_code: 纯代码，如 "510300"
        start_date/end_date: YYYY-MM-DD
    """
    if not MOOTDX_AVAILABLE:
        return None

    try:
        client = Quotes.factory(market="std")
    except Exception:
        return None

    try:
        df = client.bars(symbol=clean_code, frequency=9, offset=max_bars)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df = df.copy()
    if "datetime" in df.columns and "日期" not in df.columns:
        df["日期"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d")

    df = normalize_column_names(df)
    df = calculate_missing_fields(df)

    if "日期" in df.columns:
        try:
            df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
            df = df[(df["日期"] >= start_date) & (df["日期"] <= end_date)].copy()
        except Exception:
            pass

    if df.empty:
        return None

    return df


def fetch_single_etf_historical(
    etf_code: str,
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tushare_token: Optional[str] = None,
    use_cache: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    获取单个ETF的历史数据
    
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
    
    # 处理日期
    if end_date:
        end_date = normalize_date(end_date)
    else:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    if start_date:
        start_date = normalize_date(start_date)
    else:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    if not start_date or not end_date:
        return None, None
    
    # 日期格式转换
    start_date_formatted = start_date.replace("-", "")
    end_date_formatted = end_date.replace("-", "")
    
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
    if use_cache and CACHE_AVAILABLE and period == "daily":
        try:
            config = load_system_config()
            cached_df, missing_dates = get_cached_etf_daily(
                clean_code, start_date_formatted, end_date_formatted, config=config
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
                    # 更新start_date和end_date用于后续筛选
                    start_date = normalize_date(start_date_formatted)
                    end_date = normalize_date(end_date_formatted)
        except Exception:
            # 缓存失败不影响主流程
            pass
    # ========== 缓存逻辑结束 ==========
    
    # 方法1：优先使用 mootdx 日线（如果可用）
    if period == "daily" and MOOTDX_AVAILABLE:
        try:
            df_mootdx = _fetch_etf_daily_mootdx(
                clean_code=clean_code,
                start_date=start_date,
                end_date=end_date,
            )
            if df_mootdx is not None and not df_mootdx.empty:
                df = df_mootdx
                source = "mootdx"
        except Exception:
            df_mootdx = None

    # 方法2：原系统封装的 Tushare 备份（src.tushare_fallback）
    if period == "daily" and fetch_etf_daily_tushare is not None:
        try:
            ts_df = fetch_etf_daily_tushare(
                symbol=etf_code,
                start_date=start_date_formatted,
                end_date=end_date_formatted,
            )
            if ts_df is not None and not ts_df.empty:
                df = ts_df.copy()
                source = "tushare"
        except Exception:
            pass
    
    # 方法3：如果显式提供了 tushare_token，则继续保留原有 Tushare 调用（兼容旧参数）
    if (df is None or df.empty) and tushare_token and TUSHARE_AVAILABLE and period == "daily":
        try:
            pro = ts.pro_api(tushare_token)
            ts_code = f"{clean_code}.SH" if sina_symbol.startswith('sh') else f"{clean_code}.SZ"
            tushare_df = pro.fund_daily(ts_code=ts_code, start_date=start_date_formatted, end_date=end_date_formatted)
            
            if tushare_df is not None and not tushare_df.empty:
                # 转换为标准格式
                df = pd.DataFrame({
                    '日期': pd.to_datetime(tushare_df['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d'),
                    '开盘': tushare_df['open'],
                    '收盘': tushare_df['close'],
                    '最高': tushare_df['high'],
                    '最低': tushare_df['low'],
                    '成交量': tushare_df['vol'],
                    '成交额': tushare_df['amount'],
                    '涨跌额': tushare_df['change'],
                    '涨跌幅': tushare_df['pct_chg']
                })
                source = "tushare"
        except Exception:
            pass
    
    # 方法4：使用新浪接口
    if df is None or df.empty:
        try:
            temp_df = ak.fund_etf_hist_sina(symbol=sina_symbol)
            if temp_df is not None and not temp_df.empty:
                # 统一字段名
                temp_df = normalize_column_names(temp_df)
                
                # 筛选日期范围
                date_col = '日期' if '日期' in temp_df.columns else None
                if date_col:
                    try:
                        temp_df[date_col] = pd.to_datetime(temp_df[date_col])
                        start_dt = pd.to_datetime(start_date)
                        end_dt = pd.to_datetime(end_date)
                        mask = (temp_df[date_col] >= start_dt) & (temp_df[date_col] <= end_dt)
                        filtered_df = temp_df[mask].copy()
                        
                        if not filtered_df.empty:
                            df = filtered_df
                            # 计算缺失字段
                            df = calculate_missing_fields(df)
                            source = "sina"
                    except Exception:
                        pass
        except Exception:
            pass
    
    # 方法5：使用东方财富接口（备用）
    if df is None or df.empty:
        try:
            temp_df = ak.fund_etf_hist_em(
                symbol=clean_code,
                period="日k" if period == "daily" else period,
                start_date=start_date_formatted,
                end_date=end_date_formatted
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
            # 找到日期列
            date_col = None
            for col in ['日期', 'date', '日期时间', 'datetime']:
                if col in df.columns:
                    date_col = col
                    break
            
            if date_col:
                df = merge_cached_and_fetched_data(cached_partial_df, df, date_col)
                source = f"{source}+cache" if source else "cache"
        except Exception:
            pass
    # ========== 缓存合并结束 ==========
    
    # ========== 保存到缓存 ==========
    if df is not None and not df.empty and use_cache and CACHE_AVAILABLE and period == "daily":
        try:
            config = load_system_config()
            save_etf_daily_cache(clean_code, df, config=config)
        except Exception:
            pass
    # ========== 缓存保存结束 ==========
    
    return df, source


def fetch_etf_historical(
    etf_code: str = "510300",
    period: str = "daily",  # "daily", "weekly", "monthly"
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tushare_token: Optional[str] = None,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    获取ETF历史数据（融合 Coze get_etf_historical.py）
    支持多ETF查询（逗号分隔）
    
    Args:
        etf_code: ETF代码，支持单个或多个（用逗号分隔），如 "510300" 或 "510300,510050"
        period: 周期类型 "daily"/"weekly"/"monthly"，默认 "daily"
        start_date: 开始日期（YYYY-MM-DD 或 YYYYMMDD），默认30天前
        end_date: 结束日期（YYYY-MM-DD 或 YYYYMMDD），默认今天
        tushare_token: Tushare Token（可选）
        api_base_url: 原系统 API 基础地址
        api_key: API Key
        use_cache: 是否使用缓存（默认True）
    
    Returns:
        Dict: 包含历史数据的字典
    """
    try:
        if not AKSHARE_AVAILABLE:
            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
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
        
        # 处理日期
        if end_date:
            end_date = normalize_date(end_date)
        else:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        if start_date:
            start_date = normalize_date(start_date)
        else:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        if not start_date or not end_date:
            return {
                'success': False,
                'message': '日期格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD 格式',
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
            df, data_source = fetch_single_etf_historical(
                etf_code_item, period, start_date, end_date, tushare_token, use_cache
            )
            
            if data_source:
                source = data_source
            
            if df is None or df.empty:
                # 使用降级数据
                results.append({
                    "code": clean_code,
                    "name": etf_info['name'],
                    "period": period,
                    "start_date": start_date,
                    "end_date": end_date,
                    "count": 0,
                    "klines": [],
                    "message": "ETF历史数据暂时不可用，请稍后重试"
                })
                continue
            
            # 转换数据格式（统一字段名）
            klines = []
            for _, row in df.iterrows():
                # 安全获取值
                def safe_get(row, *keys, default=0):
                    """安全获取值，尝试多个可能的列名"""
                    for key in keys:
                        if key in row.index:
                            try:
                                value = row[key]
                                if value is not None and str(value) != 'nan' and str(value) != '':
                                    # 如果是numpy类型，转换为Python原生类型
                                    if isinstance(value, (np.integer, np.floating)):
                                        result = value.item()
                                    else:
                                        result = float(value)
                                    return result
                            except (ValueError, TypeError):
                                continue
                    return default
                
                # 获取日期
                date_value = ""
                for date_col in ['日期', 'date', '日期时间', 'datetime', 'trade_date']:
                    if date_col in row.index:
                        try:
                            date_value = str(row[date_col])
                            if date_value and date_value != 'nan':
                                # 如果是datetime类型，转换为字符串
                                if hasattr(date_value, 'strftime'):
                                    date_value = date_value.strftime('%Y-%m-%d')
                                break
                        except:
                            pass
                
                klines.append({
                    "date": date_value,
                    "open": safe_get(row, '开盘', 'open', '开盘价', default=0),
                    "high": safe_get(row, '最高', 'high', '最高价', default=0),
                    "low": safe_get(row, '最低', 'low', '最低价', default=0),
                    "close": safe_get(row, '收盘', 'close', '收盘价', default=0),
                    "volume": safe_get(row, '成交量', 'volume', 'vol', default=0),
                    "amount": safe_get(row, '成交额', 'amount', default=0),
                    "change_percent": safe_get(row, '涨跌幅', 'pct_chg', '涨跌幅%', default=0)
                })
            
            result_data = {
                "code": clean_code,
                "name": etf_info['name'],
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "count": len(klines),
                "klines": klines
            }
            
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
        
        # 构建返回结果：单个ETF返回对象，多个ETF返回数组
        final_data = results[0] if len(results) == 1 else results
        
        return {
            "success": True,
            "message": f'Successfully fetched {sum(r.get("count", 0) for r in results)} records',
            "data": final_data,
            "source": source or "akshare",
            "count": len(results)
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_fetch_etf_historical(
    etf_code: str = "510300",
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """OpenClaw 工具：获取ETF历史数据"""
    return fetch_etf_historical(
        etf_code=etf_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        use_cache=use_cache
    )
