"""
获取A50期指数据
融合 Coze 插件 get_a50_index_data.py
OpenClaw 插件工具
"""

import pandas as pd
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import sys

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

# 尝试导入缓存/配置/交易日模块（优先使用当前环境中的本地 src 包）
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
            get_cache_dir, load_cached_data, save_cached_data,
            parse_date_range, merge_cached_and_fetched_data, _is_cache_enabled
        )
        from src.config_loader import load_system_config
        CACHE_AVAILABLE = True
except Exception:
    CACHE_AVAILABLE = False


def normalize_date(date_str: str) -> str:
    """统一日期格式为 YYYYMMDD"""
    if not date_str:
        return ""
    try:
        if '-' in date_str:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%Y%m%d")
        elif len(date_str) == 8:
            datetime.strptime(date_str, "%Y%m%d")
            return date_str
        else:
            return date_str
    except Exception:
        return date_str


def get_a50_cache_file_path(symbol: str, date: str, config: Optional[Dict] = None) -> Path:
    """
    获取A50期指缓存文件路径
    
    Args:
        symbol: A50期指代码（如 "A50" 或 "CHA50CFD"）
        date: 日期字符串（格式：YYYYMMDD）
        config: 系统配置
    
    Returns:
        Path: 缓存文件路径
    """
    if config is None and CACHE_AVAILABLE:
        try:
            config = load_system_config(use_cache=True)
        except:
            pass
    
    cache_dir = get_cache_dir(config) if CACHE_AVAILABLE else Path("data/cache")
    file_path = cache_dir / 'futures_daily' / symbol / f"{date}.parquet"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    return file_path


def get_cached_a50_daily(
    symbol: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None
) -> Tuple[Optional[pd.DataFrame], List[str]]:
    """
    获取缓存的A50期指日线数据
    
    Args:
        symbol: A50期指代码
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        config: 系统配置
    
    Returns:
        Tuple[Optional[pd.DataFrame], List[str]]: 
            - 缓存的数据（如果全部命中）或None（如果部分命中或未命中）
            - 缺失的日期列表
    """
    if not CACHE_AVAILABLE:
        return None, parse_date_range(start_date, end_date) if CACHE_AVAILABLE else []
    
    try:
        dates = parse_date_range(start_date, end_date)
        cached_dfs = []
        missing_dates = []
        date_col = None
        
        for date in dates:
            # A50期指是外盘期货，不遵循A股交易日，所以检查所有日期
            date_obj = datetime.strptime(date, "%Y%m%d")
            cache_path = get_a50_cache_file_path(symbol, date, config)
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
                    if not pd.api.types.is_datetime64_any_dtype(cached_df[date_col]):
                        cached_df[date_col] = pd.to_datetime(cached_df[date_col], errors='coerce')
                    # 使用日期对象进行比较
                    date_filtered = cached_df[
                        cached_df[date_col].dt.date == date_obj.date()
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
            # 部分缓存，返回已缓存的数据和缺失日期列表
            if cached_dfs:
                partial_df = pd.concat(cached_dfs, ignore_index=True)
                if date_col:
                    partial_df = partial_df.sort_values(by=date_col)
                return partial_df, missing_dates
            else:
                return None, missing_dates
        
        # 全部缓存命中，合并数据
        result_df = pd.concat(cached_dfs, ignore_index=True)
        if date_col:
            result_df = result_df.sort_values(by=date_col)
        else:
            result_df = result_df.sort_values(by=result_df.columns[0])
        
        return result_df, []
        
    except Exception:
        # 异常情况下，返回所有日期
        all_dates = parse_date_range(start_date, end_date)
        return None, all_dates


def save_a50_daily_cache(
    symbol: str,
    df: pd.DataFrame,
    config: Optional[Dict] = None
) -> bool:
    """
    保存A50期指日线数据到缓存（按日期拆分保存）
    
    Args:
        symbol: A50期指代码
        df: 日线数据DataFrame
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    if not CACHE_AVAILABLE:
        return False
    
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
            return False
        
        # 确保日期列为datetime类型
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        
        # 按日期分组保存
        saved_count = 0
        for date_str, group_df in df.groupby(df[date_col].dt.strftime('%Y%m%d')):
            cache_path = get_a50_cache_file_path(symbol, date_str, config)
            if save_cached_data(group_df, cache_path):
                saved_count += 1
        
        return saved_count > 0
        
    except Exception:
        return False


def fetch_a50_data(
    symbol: str = "A50期指",
    data_type: str = "both",  # "spot", "hist", "both"
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    获取A50期指数据（融合 Coze get_a50_index_data.py）
    
    Args:
        symbol: 指数名称，目前仅支持 "A50期指"
        data_type: 数据类型，"spot"（实时）, "hist"（历史）, "both"（两者）
        start_date: 历史数据开始日期（YYYYMMDD 或 YYYY-MM-DD），默认回看30天
        end_date: 历史数据结束日期（YYYYMMDD 或 YYYY-MM-DD），默认当前日期
        api_base_url: 原系统 API 基础地址
        api_key: API Key
        use_cache: 是否使用缓存（默认True）
    
    Returns:
        Dict: 包含A50期指数据的字典
    """
    try:
        if not AKSHARE_AVAILABLE:
            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
                'data': None
            }
        
        # 验证symbol是否支持（支持多种写法，避免编码问题）
        symbol_normalized = str(symbol).strip()
        valid_symbols = ["A50期指", "A50", "a50期指", "a50"]
        if symbol_normalized not in valid_symbols and not symbol_normalized.startswith("A50") and not symbol_normalized.startswith("a50"):
            return {
                'success': False,
                'message': f'不支持的指数类型: {symbol}。本工具仅支持A50期指（期货）',
                'data': None
            }
        
        # 处理日期
        now = datetime.now()
        if end_date:
            end_date = normalize_date(end_date)
        else:
            end_date = now.strftime("%Y%m%d")
        
        if start_date:
            start_date = normalize_date(start_date)
        else:
            start_date = (now - timedelta(days=30)).strftime("%Y%m%d")
        
        result = {
            'success': True,
            'symbol': symbol,
            'source': 'mixed',
            'spot_data': None,
            'hist_data': None,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 获取实时数据（使用期货接口）
        if data_type in ["spot", "both"]:
            try:
                spot_df = ak.futures_global_spot_em()
                
                if spot_df is not None and not spot_df.empty:
                    # 查找代码列和名称列
                    code_col = None
                    name_col = None
                    for col in spot_df.columns:
                        col_lower = str(col).lower()
                        if 'code' in col_lower or '代码' in col_lower or 'symbol' in col_lower:
                            code_col = col
                        if 'name' in col_lower or '名称' in col_lower or '品种' in col_lower:
                            name_col = col
                    
                    if code_col is None or name_col is None:
                        if len(spot_df.columns) >= 2:
                            code_col = spot_df.columns[0]
                            name_col = spot_df.columns[1]
                        else:
                            code_col = None
                            name_col = None
                    
                    # 查找A50期指相关合约（期货）
                    if code_col and name_col:
                        search_keywords = ["A50", "CHINA50", "XIN9", "富时", "FTSE"]
                        
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
                                    a50_code = str(row[code_col])
                                else:
                                    # 如果没有有价格的合约，至少选择有成交量的
                                    a50_with_volume = a50_all[pd.to_numeric(a50_all[volume_col], errors='coerce') > 0]
                                    if not a50_with_volume.empty:
                                        row = a50_with_volume.sort_values(volume_col, ascending=False).iloc[0]
                                        a50_code = str(row[code_col])
                                    else:
                                        # 最后选择：按代码排序，选择最近月份的
                                        row = a50_all.sort_values(code_col, ascending=False).iloc[0]
                                        a50_code = str(row[code_col])
                            else:
                                # 如果无法找到价格或成交量列，选择第一个匹配的
                                row = a50_all.iloc[0]
                                a50_code = str(row[code_col])
                            
                            # 提取实时数据
                            current_price = None
                            change_pct = None
                            volume = None
                            
                            # 查找价格相关列（处理NaN值）
                            for col in ['最新价', 'current_price', 'price', 'last_price', '现价']:
                                if col in row.index:
                                    try:
                                        price_val = row[col]
                                        if pd.notna(price_val) and str(price_val) != 'nan':
                                            current_price = float(price_val)
                                            break
                                    except (ValueError, TypeError):
                                        continue
                            
                            # 查找涨跌幅列（处理NaN值）
                            for col in ['涨跌幅', 'pct_chg', 'change_pct', '涨跌%']:
                                if col in row.index:
                                    try:
                                        pct_val = row[col]
                                        if pd.notna(pct_val) and str(pct_val) != 'nan':
                                            change_pct = float(pct_val)
                                            break
                                    except (ValueError, TypeError):
                                        continue
                            
                            # 查找成交量列（处理NaN值）
                            for col in ['成交量', 'volume', 'vol']:
                                if col in row.index:
                                    try:
                                        vol_val = row[col]
                                        if pd.notna(vol_val) and str(vol_val) != 'nan':
                                            volume = float(vol_val)
                                            break
                                    except (ValueError, TypeError):
                                        continue
                            
                            result['spot_data'] = {
                                "code": a50_code,
                                "name": str(row[name_col]),
                                "current_price": current_price,
                                "change_pct": change_pct,
                                "volume": volume,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                            result["source"] = "futures_global_spot_em"
            except Exception:
                pass
        
        # 获取历史数据（使用期货接口）
        if data_type in ["hist", "both"]:
            try:
                # A50期指代码（用于缓存）
                a50_symbol = "A50"
                
                # ========== 缓存逻辑：先检查缓存 ==========
                hist_df = None
                cached_partial_df = None
                missing_dates = []
                
                if use_cache and CACHE_AVAILABLE:
                    try:
                        config_for_cache = load_system_config(use_cache=True) if CACHE_AVAILABLE else None
                        if config_for_cache and _is_cache_enabled(config_for_cache):
                            cached_df, missing_dates = get_cached_a50_daily(
                                a50_symbol, start_date, end_date, config=config_for_cache
                            )
                            
                            if cached_df is not None and not cached_df.empty and not missing_dates:
                                # 全部缓存命中，直接使用缓存数据
                                hist_df = cached_df
                                result["source"] = "cache"
                            elif cached_df is not None and not cached_df.empty and missing_dates:
                                # 部分缓存命中，保存用于后续合并
                                cached_partial_df = cached_df
                    except Exception:
                        # 缓存失败不影响主流程
                        pass
                # ========== 缓存逻辑结束 ==========
                
                # 如果缓存未完全命中，从接口获取
                if hist_df is None or hist_df.empty:
                    # 如果有部分缓存，只获取缺失日期的数据
                    fetch_start_date = start_date
                    fetch_end_date = end_date
                    if cached_partial_df is not None and missing_dates:
                        fetch_start_date = min(missing_dates)
                        fetch_end_date = max(missing_dates)
                    
                    temp_df = ak.futures_foreign_hist(symbol="CHA50CFD")
                    
                    if temp_df is not None and not temp_df.empty:
                        # 统一数据格式
                        result_df = pd.DataFrame()
                        
                        # 日期列（转换为datetime类型，便于后续处理和缓存）
                        if 'date' in temp_df.columns:
                            result_df['日期'] = pd.to_datetime(temp_df['date'], errors='coerce')
                        else:
                            result_df['日期'] = pd.NaT
                        
                        # 价格列
                        result_df['开盘'] = pd.to_numeric(temp_df.get('open', 0), errors='coerce')
                        result_df['收盘'] = pd.to_numeric(temp_df.get('close', 0), errors='coerce')
                        result_df['最高'] = pd.to_numeric(temp_df.get('high', 0), errors='coerce')
                        result_df['最低'] = pd.to_numeric(temp_df.get('low', 0), errors='coerce')
                        result_df['成交量'] = pd.to_numeric(temp_df.get('volume', 0), errors='coerce')
                        result_df['成交额'] = 0.0  # futures_foreign_hist不提供成交额
                        
                        # 过滤无效日期
                        result_df = result_df[result_df['日期'].notna()].copy()
                        
                        # 日期范围筛选（使用datetime类型进行比较）
                        if fetch_start_date and fetch_end_date:
                            start_dt = datetime.strptime(fetch_start_date, "%Y%m%d")
                            end_dt = datetime.strptime(fetch_end_date, "%Y%m%d")
                            mask = (result_df['日期'] >= start_dt) & (result_df['日期'] <= end_dt)
                            result_df = result_df[mask].copy()
                        
                        # 按日期排序
                        result_df = result_df.sort_values('日期').reset_index(drop=True)
                        
                        if not result_df.empty:
                            hist_df = result_df
                # ========== 合并部分缓存数据 ==========
                if hist_df is not None and not hist_df.empty and cached_partial_df is not None:
                    try:
                        date_col = '日期'
                        hist_df = merge_cached_and_fetched_data(cached_partial_df, hist_df, date_col)
                        if result["source"] == "mixed" or result["source"] == "cache":
                            result["source"] = "futures_foreign_hist+cache"
                        else:
                            result["source"] = "futures_foreign_hist"
                    except Exception:
                        pass
                # ========== 缓存合并结束 ==========
                
                # ========== 保存到缓存 ==========
                if hist_df is not None and not hist_df.empty and use_cache and CACHE_AVAILABLE:
                    try:
                        config_for_cache = load_system_config(use_cache=True) if CACHE_AVAILABLE else None
                        if config_for_cache and _is_cache_enabled(config_for_cache):
                            save_a50_daily_cache(a50_symbol, hist_df, config=config_for_cache)
                    except Exception:
                        pass
                # ========== 缓存保存结束 ==========
                
                # 转换为输出格式
                if hist_df is not None and not hist_df.empty:
                    klines = []
                    for _, row in hist_df.iterrows():
                        # 日期格式转换（datetime -> YYYYMMDD字符串）
                        date_str = ""
                        if pd.notna(row['日期']):
                            if isinstance(row['日期'], pd.Timestamp):
                                date_str = row['日期'].strftime('%Y%m%d')
                            else:
                                date_str = str(row['日期']).replace('-', '')[:8]
                        
                        klines.append({
                            "date": date_str,
                            "open": float(row['开盘']) if pd.notna(row['开盘']) else None,
                            "close": float(row['收盘']) if pd.notna(row['收盘']) else None,
                            "high": float(row['最高']) if pd.notna(row['最高']) else None,
                            "low": float(row['最低']) if pd.notna(row['最低']) else None,
                            "volume": float(row['成交量']) if pd.notna(row['成交量']) else None
                        })
                    
                    result['hist_data'] = {
                        "count": len(klines),
                        "klines": klines
                    }
                    if result["source"] == "mixed":
                        result["source"] = "futures_foreign_hist"
                    elif "cache" not in result["source"]:
                        result["source"] = "mixed"
            except Exception:
                pass
        
        # 检查是否有数据
        if result["spot_data"] is None and result["hist_data"] is None:
            return {
                "success": False,
                "symbol": symbol,
                "source": "fallback",
                "spot_data": None,
                "hist_data": None,
                "message": "A50期指数据暂时不可用，请稍后重试",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        return result
    
    except Exception as e:
        return {
            'success': False,
            'symbol': symbol if 'symbol' in locals() else "unknown",
            'source': 'error',
            'spot_data': None,
            'hist_data': None,
            'message': f'获取A50期指数据失败: {str(e)}',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }


# OpenClaw 工具函数接口
def tool_fetch_a50_data(
    symbol: str = "A50期指",
    data_type: str = "both",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取A50期指数据
    
    支持TypeScript接口的参数映射：
    - "realtime" -> "spot"
    - "historical" -> "hist"
    """
    # 参数映射：兼容TypeScript接口的参数值
    data_type_mapping = {
        "realtime": "spot",
        "historical": "hist"
    }
    if data_type in data_type_mapping:
        data_type = data_type_mapping[data_type]
    
    # 如果只请求实时数据但获取失败，自动尝试获取历史数据作为fallback
    original_data_type = data_type
    result = fetch_a50_data(
        symbol=symbol,
        data_type=data_type,
        start_date=start_date,
        end_date=end_date,
        use_cache=use_cache
    )
    
    # 如果只请求实时数据但获取失败，且没有历史数据，自动尝试获取历史数据
    if (original_data_type == "spot" and 
        result.get("success") == False and 
        result.get("spot_data") is None and
        result.get("hist_data") is None):
        # 自动fallback到历史数据
        result = fetch_a50_data(
            symbol=symbol,
            data_type="hist",
            start_date=start_date,
            end_date=end_date,
            use_cache=use_cache
        )
        if result.get("hist_data"):
            result["message"] = "实时数据不可用，已返回历史数据"
    
    return result