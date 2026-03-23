"""
获取指数历史数据
融合 Coze 插件 get_index_historical.py
OpenClaw 插件工具
改进版本：支持缓存、多指数、自动计算成交额/涨跌幅、完善字段映射
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
            get_cached_index_daily, save_index_daily_cache,
            merge_cached_and_fetched_data,
        )
        from src.config_loader import load_system_config
        # 引入原系统的 Tushare 备份模块（集中管理 token / 频率限制）
        from src.tushare_fallback import fetch_index_daily_tushare
        CACHE_AVAILABLE = True
    else:
        CACHE_AVAILABLE = False
        fetch_index_daily_tushare = None  # type: ignore
except Exception:
    CACHE_AVAILABLE = False
    fetch_index_daily_tushare = None  # type: ignore


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


def _fetch_index_daily_mootdx(
    index_code: str,
    start_date: str,
    end_date: str,
    max_bars: int = 800,
) -> Optional[pd.DataFrame]:
    """
    使用 mootdx 获取指数日线数据。

    说明:
        - index_code 使用如 "000300", "000001" 等代码。
        - frequency=9 对应日K线（参考 mootdx 文档）。
        - 只在内存中过滤日期区间，不写缓存，由上层负责缓存。
    """
    if not MOOTDX_AVAILABLE:
        return None

    try:
        client = Quotes.factory(market="std")
    except Exception:
        return None

    try:
        df = client.bars(symbol=index_code, frequency=9, offset=max_bars)
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


def fetch_single_index_historical(
    index_code: str,
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tushare_token: Optional[str] = None,
    use_cache: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    获取单个指数的历史数据
    
    优先顺序：
    1. 原系统缓存
    2. 直接调用新浪 HTTP 接口 (money.finance.sina.com.cn)
    3. akshare / 东财等备用数据源
    """
    # 指数代码映射
    index_mapping = {
        "000001": {"name": "上证指数", "symbol": "sh000001"},
        "399001": {"name": "深证成指", "symbol": "sz399001"},
        "399006": {"name": "创业板指", "symbol": "sz399006"},
        "000300": {"name": "沪深300", "symbol": "sh000300"},
        "000016": {"name": "上证50", "symbol": "sh000016"},
        "000905": {"name": "中证500", "symbol": "sh000905"},
    }
    
    index_info = index_mapping.get(index_code)
    if not index_info:
        return None, None
    
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
    
    # 日期格式转换（YYYY-MM-DD -> YYYYMMDD）
    start_date_formatted = start_date.replace("-", "")
    end_date_formatted = end_date.replace("-", "")
    
    # 指数代码映射（使用正确的新浪代码，全部通过交易所前缀区分）
    index_code_mapping = {
        "000300": "sh000300",
        "000001": "sh000001",
        "000016": "sh000016",
        "000905": "sh000905",
        "399001": "sz399001",
        "399006": "sz399006",
    }
    sina_symbol = index_code_mapping.get(index_code, index_code)
    
    df = None
    source = None
    cached_partial_df = None
    
    # ========== 缓存逻辑：先检查缓存 ==========
    if use_cache and period == "daily" and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True)
            cached_df, missing_dates = get_cached_index_daily(
                index_code, start_date_formatted, end_date_formatted, config=config
            )
            
            if cached_df is not None and not cached_df.empty and not missing_dates:
                # 全部缓存命中，直接返回
                return cached_df, "cache"
            
            # 注意：原系统的 get_cached_index_daily 在部分缓存命中时返回 None
            # 这里保留 missing_dates，后续如有需要可做更精细的合并
            if missing_dates and len(missing_dates) < 100:
                cached_partial_df = None
        except Exception:
            # 缓存失败不影响主流程
            pass
    # ========== 缓存逻辑结束 ==========
    
    # 方法1：优先使用 mootdx 日线（如果可用）
    if period == "daily" and MOOTDX_AVAILABLE:
        try:
            df_mootdx = _fetch_index_daily_mootdx(
                index_code=index_code,
                start_date=start_date,
                end_date=end_date,
            )
            if df_mootdx is not None and not df_mootdx.empty:
                df = df_mootdx
                source = "mootdx"
        except Exception:
            df_mootdx = None

    # 方法2：原系统封装的 Tushare 备份（src.tushare_fallback）
    if period == "daily" and fetch_index_daily_tushare is not None:
        try:
            ts_df = fetch_index_daily_tushare(
                symbol=index_code,
                start_date=start_date_formatted,
                end_date=end_date_formatted,
            )
            if ts_df is not None and not ts_df.empty:
                df = ts_df.copy()
                source = "tushare"
        except Exception:
            pass
    
    # 方法3：如果显式提供了 tushare_token，则直接使用本地 tushare 调用（兼容旧参数）
    if (df is None or df.empty) and tushare_token and TUSHARE_AVAILABLE and period == "daily":
        try:
            pro = ts.pro_api(tushare_token)
            ts_code_mapping = {
                "000300": "399300.SZ",
                "000001": "000001.SH",
                "000016": "000016.SH",
                "000905": "000905.SH",
                "399001": "399001.SZ",
                "399006": "399006.SZ",
            }
            ts_code = ts_code_mapping.get(index_code)
            if ts_code:
                temp_df = pro.index_daily(ts_code=ts_code, start_date=start_date_formatted, end_date=end_date_formatted)
                if temp_df is not None and not temp_df.empty:
                    temp_df = temp_df.sort_values('trade_date')
                    temp_df['date'] = pd.to_datetime(temp_df['trade_date']).dt.strftime('%Y-%m-%d')
                    # 统一字段名
                    temp_df = normalize_column_names(temp_df)
                    df = temp_df.copy()
                    # 计算缺失字段
                    df = calculate_missing_fields(df)
                    source = "tushare"
        except Exception:
            pass
    
    # 方法4：直接调用新浪 HTTP 接口（money.finance.sina.com.cn）
    if (df is None or df.empty) and period == "daily":
        try:
            # 使用与分钟数据相同的 K 线接口，scale=240 近似日线
            from urllib.parse import urlencode
            from urllib.request import Request, urlopen
            from urllib.error import HTTPError

            url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
            # 估算需要的条数，最多 512
            try:
                sd = datetime.strptime(start_date_formatted, "%Y%m%d")
                ed = datetime.strptime(end_date_formatted, "%Y%m%d")
                days_diff = (ed - sd).days + 1
                datalen = min(max(days_diff * 2, 64), 512)
            except Exception:
                datalen = 512

            params = {
                "symbol": sina_symbol,
                "scale": 240,  # 240 分钟 ≈ 日 K
                "ma": "no",
                "datalen": datalen,
            }
            headers = {
                "Referer": "http://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }

            full_url = f"{url}?{urlencode(params)}"
            req = Request(full_url, headers=headers)
            with urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    raise HTTPError(full_url, resp.status, resp.reason, resp.headers, None)
                raw = resp.read().decode("utf-8")
                try:
                    data = json.loads(raw)
                except ValueError:
                    data = None

            if data and isinstance(data, list):
                temp_df = pd.DataFrame(data)
                if not temp_df.empty:
                    # 映射字段
                    temp_df = normalize_column_names(temp_df)
                    # 将 day/时间 列规范为日期
                    if "日期" not in temp_df.columns and "时间" in temp_df.columns:
                        temp_df["日期"] = pd.to_datetime(temp_df["时间"]).dt.strftime("%Y-%m-%d")
                    elif "日期" in temp_df.columns:
                        temp_df["日期"] = pd.to_datetime(temp_df["日期"]).dt.strftime("%Y-%m-%d")

                    # 过滤日期范围
                    if "日期" in temp_df.columns:
                        mask = (temp_df["日期"] >= start_date) & (temp_df["日期"] <= end_date)
                        temp_df = temp_df[mask].copy()

                    if not temp_df.empty:
                        df = temp_df.copy()
                        df = calculate_missing_fields(df)
                        source = "sina_http"
        except Exception:
            pass
    
    # 方法5：使用 akshare 接口（备用）
    if (df is None or df.empty) and AKSHARE_AVAILABLE:
        try:
            if period == "daily":
                temp_df = ak.index_zh_a_hist(symbol=sina_symbol, period="日k", start_date=start_date_formatted, end_date=end_date_formatted)
            elif period == "weekly":
                temp_df = ak.index_zh_a_hist(symbol=sina_symbol, period="周k", start_date=start_date_formatted, end_date=end_date_formatted)
            elif period == "monthly":
                temp_df = ak.index_zh_a_hist(symbol=sina_symbol, period="月k", start_date=start_date_formatted, end_date=end_date_formatted)
            else:
                temp_df = None
            
            if temp_df is not None and not temp_df.empty:
                temp_df = normalize_column_names(temp_df)
                df = temp_df.copy()
                df = calculate_missing_fields(df)
                source = "akshare"
        except Exception:
            pass
    
    # 方法6：使用东方财富接口（备用）
    if df is None or df.empty:
        try:
            temp_df = ak.index_zh_a_hist_min_em(symbol=index_code, period="日k", start_date=start_date_formatted, end_date=end_date_formatted)
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
            date_col = '日期'
            df = merge_cached_and_fetched_data(cached_partial_df, df, date_col)
            source = f"{source}+cache" if source else "cache"
        except Exception:
            pass
    # ========== 缓存合并结束 ==========
    
    # ========== 保存到缓存 ==========
    if df is not None and not df.empty and use_cache and period == "daily" and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True)
            save_index_daily_cache(index_code, df, config=config)
        except Exception:
            pass
    # ========== 缓存保存结束 ==========
    
    return df, source


def fetch_index_historical(
    index_code: str = "000001",
    period: str = "daily",  # "daily", "weekly", "monthly"
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tushare_token: Optional[str] = None,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    获取指数历史数据（融合 Coze get_index_historical.py）
    支持多指数查询（逗号分隔）
    
    Args:
        index_code: 指数代码，支持单个或多个（用逗号分隔），如 "000001" 或 "000300,000001"
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
        
        # 指数代码映射
        index_mapping = {
            "000001": {"name": "上证指数", "symbol": "sh000001"},
            "399001": {"name": "深证成指", "symbol": "sz399001"},
            "399006": {"name": "创业板指", "symbol": "sz399006"},
            "000300": {"name": "沪深300", "symbol": "sh000300"},
            "000016": {"name": "上证50", "symbol": "sh000016"},
            "000905": {"name": "中证500", "symbol": "sh000905"},
        }
        
        # 解析指数代码（支持单个或多个，用逗号分隔）
        if isinstance(index_code, str):
            index_codes = [code.strip() for code in index_code.split(",") if code.strip()]
        elif isinstance(index_code, list):
            index_codes = [str(code).strip() for code in index_code if str(code).strip()]
        else:
            index_codes = [str(index_code).strip()]
        
        if not index_codes:
            return {
                'success': False,
                'message': '未提供有效的指数代码',
                'data': None
            }
        
        # ========== 自动识别 ETF 代码并调用对应的 ETF 函数 ==========
        # ETF代码通常以5或1开头（如510300, 159915），指数代码通常以000或399开头（如000300, 399001）
        etf_codes = [code for code in index_codes if code.startswith("5") or code.startswith("1")]
        index_codes_only = [code for code in index_codes if code not in etf_codes]
        etf_result = None
        
        if etf_codes:
            # 如果有ETF代码，自动调用ETF函数
            try:
                from plugins.data_collection.etf.fetch_historical import fetch_etf_historical
                logger.info(f"检测到 ETF 代码 {', '.join(etf_codes)}，自动调用 fetch_etf_historical")
                etf_result = fetch_etf_historical(
                    etf_code=",".join(etf_codes),
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    tushare_token=tushare_token,
                    api_base_url=api_base_url,
                    api_key=api_key,
                    use_cache=use_cache
                )
                # 如果只有ETF代码，直接返回ETF结果
                if not index_codes_only:
                    return etf_result
                # 如果还有指数代码，继续处理指数代码，然后合并结果
            except Exception as e:
                logger.warning(f"调用 fetch_etf_historical 失败: {e}，继续处理指数代码")
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
        
        # 验证所有指数代码
        invalid_codes = []
        for code in index_codes_only:
            if code not in index_mapping:
                invalid_codes.append(code)
        
        if invalid_codes:
            return {
                'success': False,
                'message': f'不支持的指数代码: {", ".join(invalid_codes)}',
                'supported_codes': list(index_mapping.keys()),
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
                        "index_name": f"ETF-{etf_code}",
                        "period": period,
                        "count": len(etf_data.get('klines', [])),
                        "klines": etf_data.get('klines', []),
                        "source": etf_data.get('source', 'etf_historical')
                    })
        
        for index_code_item in index_codes_only:
            index_info = index_mapping[index_code_item]
            
            # 获取数据
            df, data_source = fetch_single_index_historical(
                index_code_item, period, start_date, end_date, tushare_token, use_cache
            )
            
            if data_source:
                source = data_source
            
            if df is None or df.empty:
                results.append({
                    "index_code": index_code_item,
                    "index_name": index_info['name'],
                    "period": period,
                    "count": 0,
                    "klines": [],
                    "message": "指数历史数据暂时不可用，请稍后重试"
                })
                continue
            
            # 统一输出格式
            klines = []
            for _, row in df.iterrows():
                # 安全转换数值，处理NaN和None
                def safe_get(row, *keys, default=0):
                    for key in keys:
                        if key in row.index:
                            try:
                                value = row[key]
                                if value is not None and str(value) != 'nan' and str(value) != '':
                                    # 确保返回原生Python类型
                                    if isinstance(value, (np.integer, np.floating)):
                                        return float(value)
                                    return float(value)
                            except (ValueError, TypeError):
                                continue
                    return default
                
                klines.append({
                    "date": str(row.get('日期', '')),
                    "open": safe_get(row, '开盘', default=0),
                    "high": safe_get(row, '最高', default=0),
                    "low": safe_get(row, '最低', default=0),
                    "close": safe_get(row, '收盘', default=0),
                    "volume": safe_get(row, '成交量', default=0),
                    "amount": safe_get(row, '成交额', default=0),
                    "change_percent": safe_get(row, '涨跌幅', default=0)
                })
            
            result_data = {
                'index_code': index_code_item,
                'index_name': index_info['name'],
                'period': period,
                'start_date': start_date or '',
                'end_date': end_date or '',
                'klines': klines,
                'count': len(klines)
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
        
        # 构建返回结果：单个指数返回对象，多个指数返回数组
        final_data = results[0] if len(results) == 1 else results
        
        return {
            'success': True,
            'message': f'Successfully fetched {len(results)} index(es) historical data',
            'data': final_data,
            'source': source or 'akshare',
            'count': len(results)
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_fetch_index_historical(
    index_code: str = "000001",
    period: str = "daily",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tushare_token: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """OpenClaw 工具：获取指数历史数据"""
    return fetch_index_historical(
        index_code=index_code,
        period=period,
        start_date=start_date,
        end_date=end_date,
        tushare_token=tushare_token,
        use_cache=use_cache
    )
