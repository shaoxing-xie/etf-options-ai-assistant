"""
获取ETF实时数据
融合 Coze 插件 get_etf_realtime.py
OpenClaw 插件工具
"""

import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime
from contextlib import nullcontext
import os
import sys
import time
from threading import Lock

# 导入重试工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from plugins.utils.retry import retry_on_failure, create_requests_retry_config
    RETRY_AVAILABLE = True
except ImportError:
    RETRY_AVAILABLE = False
    # 如果导入失败，定义占位装饰器
    def retry_on_failure(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def create_requests_retry_config(*args, **kwargs):
        return None

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
    from src.realtime_full_fetch_cache import get_or_fetch
except Exception:  # 保险：即使导入失败，也保底返回 None
    get_or_fetch = None  # type: ignore[assignment]


def _get_fund_etf_category_sina_cached(category_symbol: str = "ETF基金") -> Optional[pd.DataFrame]:
    """
    fund_etf_category_sina：拉全量分类列表后筛选目标 ETF
    使用统一的进程内短缓存（配置见 config.yaml: realtime_full_fetch_cache）
    """
    if not AKSHARE_AVAILABLE:
        return None
    if get_or_fetch is None:
        try:
            return ak.fund_etf_category_sina(symbol=category_symbol)
        except Exception:
            return None

    cache_key = f"fund_etf_category_sina:{category_symbol}"

    def _fetch():
        with without_proxy_env() if PROXY_ENV_AVAILABLE else nullcontext():  # type: ignore[name-defined]
            return ak.fund_etf_category_sina(symbol=category_symbol)

    try:
        return get_or_fetch(cache_key, _fetch)
    except Exception:
        return None

try:
    # 复用股票实时行情的主数据源（mootdx / TDX）
    from plugins.data_collection.stock.fetch_realtime import fetch_stock_realtime
    STOCK_REALTIME_AVAILABLE = True
except Exception:
    STOCK_REALTIME_AVAILABLE = False

try:
    from plugins.utils.proxy_env import without_proxy_env
    PROXY_ENV_AVAILABLE = True
except Exception:
    PROXY_ENV_AVAILABLE = False

    def without_proxy_env(*args, **kwargs):  # type: ignore[no-redef]
        # fallback: no-op context manager
        from contextlib import contextmanager

        @contextmanager
        def _noop():
            yield

        return _noop()

def fetch_etf_realtime(
    etf_code: str = "510300",  # 支持单个或多个（用逗号分隔）
    mode: str = "production",
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取ETF实时数据（融合 Coze get_etf_realtime.py）
    
    Args:
        etf_code: ETF代码，支持单个或多个（用逗号分隔），如 "510300" 或 "510300,510050"
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        api_base_url: 原系统 API 基础地址
        api_key: API Key
    
    Returns:
        Dict: 包含实时数据的字典
    """
    try:
        debug: Dict[str, Any] = {}
        if mode == "test":
            debug = {
                "sys_executable": sys.executable,
                "stock_realtime_available": STOCK_REALTIME_AVAILABLE,
                "attempt_order": ["stock_realtime(mootdx/TDX)", "akshare_sina_option_underlying", "fund_etf_spot_ths", "fallback"],
                "attempted": [],
                "notes": [],
            }

        # ========== 首先判断是否是交易日 ==========
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取ETF实时数据")
            if trading_day_check:
                return trading_day_check
        # ========== 交易日判断结束 ==========
        
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
        
        # ETF代码映射
        etf_mapping = {
            "510050": {"name": "华夏上证50ETF", "market": "sh"},
            "510300": {"name": "沪深300ETF", "market": "sh"},
            "510500": {"name": "南方中证500ETF", "market": "sh"},
            "588000": {"name": "科创50ETF", "market": "sh"},
            "588080": {"name": "科创板50ETF", "market": "sh"},
            "159919": {"name": "易方达创业板ETF", "market": "sz"},
            "159915": {"name": "易方达创业板ETF", "market": "sz"},
            "512100": {"name": "中证1000ETF", "market": "sh"},
            "159901": {"name": "深证100ETF", "market": "sz"},
        }
        
        # 取 ETF 当前价的逻辑统一走：mootdx/TDX -> 同花顺 spot -> 新浪分时(1min close)。
        # 不再优先使用期权底层 ETF 的 sina 通道（option_sse_underlying_spot_price_sina），因为其覆盖范围有限。
        
        results: List[Dict[str, Any]] = []

        # ========== 优先数据源：复用股票实时行情（mootdx / TDX 主通道） ==========
        # 对于主流 ETF（510300 等），其本质上是场内基金，与股票实时行情接口完全兼容。
        # 因此这里优先尝试通过 fetch_stock_realtime 获取 ETF 的实时数据，以充分利用 mootdx 能力。
        if STOCK_REALTIME_AVAILABLE:
            try:
                if mode == "test":
                    debug["attempted"].append("stock_realtime(mootdx/TDX)")
                stock_rt = fetch_stock_realtime(
                    stock_code=",".join(etf_codes),
                    mode=mode or "production",
                )
                if stock_rt.get("success") and stock_rt.get("data"):
                    stock_data = stock_rt["data"]
                    if isinstance(stock_data, list):
                        stock_items: List[Dict[str, Any]] = stock_data
                    else:
                        stock_items = [stock_data]

                    by_code: Dict[str, Dict[str, Any]] = {}
                    for item in stock_items:
                        code_key = str(item.get("stock_code") or "").strip()
                        if code_key:
                            by_code[code_key] = item

                    for etf_code_item in etf_codes:
                        clean_code = etf_code_item[2:] if etf_code_item.startswith(("sh", "sz")) else etf_code_item
                        src = by_code.get(clean_code)
                        if not src:
                            continue
                        results.append(
                            {
                                "code": etf_code_item,
                                "name": str(src.get("name") or etf_mapping.get(clean_code, {}).get("name", "ETF")),
                                "current_price": float(src.get("current_price") or 0.0),
                                "change": float(src.get("change") or 0.0),
                                "change_percent": float(src.get("change_percent") or 0.0),
                                "open": float(src.get("open") or 0.0),
                                "high": float(src.get("high") or 0.0),
                                "low": float(src.get("low") or 0.0),
                                "prev_close": float(src.get("prev_close") or 0.0),
                                "volume": float(src.get("volume") or 0.0),
                                "amount": float(src.get("amount") or 0.0),
                                "timestamp": src.get("timestamp")
                                or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        )

                    if results:
                        ret = {
                            "success": True,
                            "message": "Successfully fetched ETF realtime data via stock_realtime (mootdx/TDX)",
                            "data": results[0] if len(results) == 1 else results,
                            "source": stock_rt.get("source", "mootdx"),
                            "count": len(results),
                        }
                        if mode == "test":
                            ret["debug"] = {
                                **debug,
                                "stock_realtime_source": stock_rt.get("source"),
                                "stock_realtime_debug": stock_rt.get("debug"),
                            }
                        return ret
            except Exception:
                results = []
                if mode == "test":
                    debug["notes"].append("stock_realtime 通道异常/失败，已回退到 akshare/同花顺")

        # 如果 stock_realtime 没拿到数据，而 akshare 又不可用，则直接返回（避免不必要的依赖）
        if not AKSHARE_AVAILABLE:
            ret = {
                "success": False,
                "message": "akshare not installed and stock_realtime fallback produced no data. Please install: pip install akshare",
                "data": None,
                "source": "none",
                "count": 0,
            }
            if mode == "test":
                ret["debug"] = debug
            return ret

        for etf_code_item in etf_codes:
            etf_info = etf_mapping.get(etf_code_item, {"name": "未知ETF", "market": "sh"})
            
            # 构建ETF符号
            if etf_code_item.startswith('sh') or etf_code_item.startswith('sz'):
                etf_symbol = etf_code_item
                clean_code = etf_code_item[2:]
            else:
                clean_code = etf_code_item
                if clean_code.startswith('510') or clean_code.startswith('511') or clean_code.startswith('512'):
                    etf_symbol = f"sh{clean_code}"
                elif clean_code.startswith('159'):
                    etf_symbol = f"sz{clean_code}"
                else:
                    etf_symbol = f"sh{clean_code}"
            
            spot_df = None
            source = None
            
            # 创建重试配置（用于网络请求）
            if RETRY_AVAILABLE:
                retry_config = create_requests_retry_config(max_attempts=3, initial_delay=1.0, max_delay=10.0)
            else:
                retry_config = None
            
            def _fetch_etf_spot_ths():
                def _fetch():
                    with without_proxy_env():
                        return ak.fund_etf_spot_ths(date="")

                if get_or_fetch is None:
                    return _fetch()
                return get_or_fetch("fund_etf_spot_ths:date=", _fetch)
            
            # 应用重试装饰器（如果可用）
            if RETRY_AVAILABLE and retry_config:
                _fetch_etf_spot_ths = retry_on_failure(config=retry_config)(_fetch_etf_spot_ths)

            # 方法1（备用）：同花顺接口
            if spot_df is None or spot_df.empty:
                try:
                    if mode == "test":
                        debug["attempted"].append("fund_etf_spot_ths")
                    all_etf_df = _fetch_etf_spot_ths()
                    if all_etf_df is not None and not all_etf_df.empty:
                        code_col = None
                        for col in ['基金代码', '代码', 'code', 'symbol']:
                            if col in all_etf_df.columns:
                                code_col = col
                                break
                        
                        if code_col:
                            target_row = all_etf_df[all_etf_df[code_col] == etf_code_item]
                            if not target_row.empty:
                                spot_df = target_row.iloc[0:1]
                                source = "fund_etf_spot_ths"
                except Exception:
                    pass
            
            if spot_df is None or spot_df.empty:
                # 方法2（推荐兜底）：新浪基金实时全量列表 -> 筛选目标 ETF
                try:
                    if mode == "test":
                        debug["attempted"].append("fund_etf_category_sina(symbol=ETF基金)")
                    cat_df = _get_fund_etf_category_sina_cached(category_symbol="ETF基金")
                    if cat_df is not None and not cat_df.empty:
                        # 统一比较：把 shXXXX / szXXXX 转成 XXXX
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

                                def _try_float(col_name: str, default: float = 0.0, positive_only: bool = False) -> float:
                                    try:
                                        v = row[col_name] if col_name in target.columns else default
                                        v = float(v)
                                        if positive_only:
                                            return v if v > 0 else default
                                        return v
                                    except Exception:
                                        return default

                                current_price = _try_float("最新价", default=0.0, positive_only=True)
                                if current_price <= 0:
                                    # fallback：有些数据源可能列名不同
                                    current_price = _try_float("最新", default=0.0, positive_only=True)
                                if current_price > 0:
                                    change = _try_float("涨跌额", default=0.0)
                                    change_percent = _try_float("涨跌幅", default=0.0)
                                    open_p = _try_float("今开", default=current_price, positive_only=True)
                                    high_p = _try_float("最高", default=current_price, positive_only=True)
                                    low_p = _try_float("最低", default=current_price, positive_only=True)
                                    prev_close = _try_float("昨收", default=current_price, positive_only=True)
                                    volume_p = _try_float("成交量", default=0.0, positive_only=True)
                                    amount_p = _try_float("成交额", default=0.0, positive_only=True)
                                    name = str(row["名称"]) if "名称" in target.columns else etf_info.get("name", "未知ETF")

                                    etf_data = {
                                        "code": etf_code_item,
                                        "name": name,
                                        "current_price": current_price,
                                        "change": change,
                                        "change_percent": change_percent,
                                        "open": open_p,
                                        "high": high_p,
                                        "low": low_p,
                                        "prev_close": prev_close,
                                        "volume": volume_p,
                                        "amount": amount_p,
                                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    }
                                    source = "fund_etf_category_sina"
                                    results.append(etf_data)
                                    continue
                except Exception:
                    pass

                # 方法3（最后兜底）：新浪分时 1min close
                try:
                    if mode == "test":
                        debug["attempted"].append("stock_zh_a_minute(period=1)")
                    with without_proxy_env():
                        minute_df = ak.stock_zh_a_minute(symbol=etf_symbol, period='1', adjust="qfq")
                    if minute_df is not None and not minute_df.empty:
                        minute_df = minute_df.reset_index(drop=True)
                        last = minute_df.iloc[-1]
                        prev_close = float(minute_df['close'].iloc[-2]) if len(minute_df) >= 2 else 0.0
                        current_price = float(last.get('close', 0) or 0)
                        if current_price <= 0:
                            raise ValueError("minute close not available")

                        change = current_price - prev_close if prev_close else 0.0
                        change_percent = (change / prev_close * 100.0) if prev_close else 0.0
                        open_p = float(minute_df['open'].iloc[0]) if 'open' in minute_df.columns else current_price
                        high_p = float(minute_df['high'].max()) if 'high' in minute_df.columns else current_price
                        low_p = float(minute_df['low'].min()) if 'low' in minute_df.columns else current_price
                        volume_p = float(last.get('volume', 0) or 0)
                        amount_p = 0.0

                        etf_data = {
                            "code": etf_code_item,
                            "name": etf_info.get('name', '未知ETF'),
                            "current_price": current_price,
                            "change": change,
                            "change_percent": change_percent,
                            "open": open_p,
                            "high": high_p,
                            "low": low_p,
                            "prev_close": prev_close,
                            "volume": volume_p,
                            "amount": amount_p,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        source = "stock_zh_a_minute(period=1)"
                        results.append(etf_data)
                        continue
                except Exception:
                    pass

                results.append(_get_fallback_data(etf_code_item, etf_mapping)["data"])
                continue
            
            # 解析数据（根据不同的返回格式）
            etf_data = None
            
            # 格式1：option_sse_underlying_spot_price_sina 返回字段/值格式
            if '字段' in spot_df.columns and '值' in spot_df.columns:
                # 转换为字典格式
                data_dict = {}
                for idx, row in spot_df.iterrows():
                    field = str(row.get('字段', '')).strip()
                    value = row.get('值', '')
                    if field and value:
                        data_dict[field] = value
                
                # 安全获取值
                def safe_get_dict(d, *keys, default=0):
                    """从字典中安全获取值"""
                    for key in keys:
                        if key in d:
                            try:
                                value = d[key]
                                if value is not None and str(value) != 'nan' and str(value) != '':
                                    return float(value)
                            except (ValueError, TypeError):
                                continue
                    return default
                
                # 获取名称
                name = etf_info.get('name', '未知ETF')
                for name_key in ['证券简称', '名称', 'name']:
                    if name_key in data_dict:
                        name = str(data_dict[name_key]).strip()
                        if name:
                            break
                
                current_price = safe_get_dict(data_dict, '最近成交价', '最新价', '当前价', default=0)
                prev_close = safe_get_dict(data_dict, '昨日收盘价', '昨收', '前收盘', default=0)
                change = safe_get_dict(data_dict, '涨跌额', '涨跌', default=0)
                change_percent = safe_get_dict(data_dict, '涨跌幅', '涨跌幅%', default=0)
                
                # 如果涨跌额或涨跌幅为0，尝试计算
                if change == 0 and current_price > 0 and prev_close > 0:
                    change = current_price - prev_close
                
                if change_percent == 0 and prev_close > 0:
                    change_percent = (change / prev_close) * 100
                
                etf_data = {
                    "code": etf_code_item,
                    "name": name,
                    "current_price": current_price,
                    "change": change,
                    "change_percent": change_percent,
                    "open": safe_get_dict(data_dict, '今日开盘价', '开盘价', '今开', default=0),
                    "high": safe_get_dict(data_dict, '最高价', '最高', default=0),
                    "low": safe_get_dict(data_dict, '最低价', '最低', default=0),
                    "prev_close": prev_close,
                    "volume": safe_get_dict(data_dict, '成交量', '成交数量', default=0),
                    "amount": safe_get_dict(data_dict, '成交额', '成交金额', default=0),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            
            # 格式2：fund_etf_spot_ths（同花顺）返回标准DataFrame格式
            else:
                row = spot_df.iloc[0] if isinstance(spot_df, pd.DataFrame) else spot_df
                
                # 安全获取值
                def safe_get(row, *keys, default=0):
                    for key in keys:
                        if key in row.index if hasattr(row, 'index') else key in row:
                            try:
                                value = row[key] if hasattr(row, '__getitem__') else getattr(row, key, None)
                                if value is not None and str(value) != 'nan' and str(value) != '':
                                    return float(value)
                            except (ValueError, TypeError):
                                continue
                    return default
                
                # 获取名称
                name = etf_info.get('name', '未知ETF')
                for name_col in ['基金名称', '名称', 'name']:
                    if name_col in (row.index if hasattr(row, 'index') else []):
                        try:
                            name_value = str(row[name_col])
                            if name_value and name_value != 'nan':
                                name = name_value
                                break
                        except:
                            pass
                
                # 同花顺接口返回的字段可能包含：单位净值/涨跌/成交等（不同版本字段名可能略有差异）
                current_nav = safe_get(row, '当前-单位净值', '最新-单位净值', '单位净值', 'nav', default=0)
                prev_nav = safe_get(row, '前一日-单位净值', '昨收', 'pre_close', default=0)
                change_value = safe_get(row, '增长值', '涨跌额', 'change', default=0)
                change_percent_value = safe_get(row, '增长率', '涨跌幅', 'pct_chg', default=0)

                # 优先用价格列（最新价/现价等）；若不存在再退化到单位净值
                price_value = safe_get(row, '最新价', '最新', '现价', '当前价', 'current_price', 'close', 'price', default=0)
                
                # 如果增长值或涨跌幅为0，尝试计算
                if change_value == 0 and current_nav > 0 and prev_nav > 0:
                    change_value = current_nav - prev_nav
                
                if change_percent_value == 0 and prev_nav > 0:
                    change_percent_value = (change_value / prev_nav) * 100

                prev_close_value = prev_nav if prev_nav > 0 else safe_get(row, '昨收', 'pre_close', '前一日收盘', default=0)
                if (change_value == 0 or change_percent_value == 0) and price_value > 0 and prev_close_value > 0:
                    change_value = price_value - prev_close_value
                    change_percent_value = (change_value / prev_close_value) * 100
                
                etf_data = {
                    "code": etf_code_item,
                    "name": name,
                    "current_price": price_value if price_value > 0 else current_nav,
                    "change": change_value,
                    "change_percent": change_percent_value,
                    "open": safe_get(row, '今开', 'open', '开盘价', default=0),
                    "high": safe_get(row, '最高', 'high', '最高价', default=0),
                    "low": safe_get(row, '最低', 'low', '最低价', default=0),
                    "prev_close": prev_close_value if prev_close_value > 0 else prev_nav,
                    "volume": safe_get(row, '成交量', 'volume', default=0),
                    "amount": safe_get(row, '成交额', 'amount', default=0),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            
            if etf_data:
                results.append(etf_data)
        
        ret = {
            'success': True,
            'message': 'Successfully fetched ETF realtime data',
            'data': results[0] if len(results) == 1 else results,
            'source': source or 'akshare',
            'count': len(results)
        }
        if mode == "test":
            ret["debug"] = debug
        return ret
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


def _get_fallback_data(etf_code: str, etf_mapping: Dict) -> Dict[str, Any]:
    """返回降级数据"""
    etf_info = etf_mapping.get(etf_code, {"name": "未知ETF"})
    
    return {
        "success": True,
        "data": {
            "code": etf_code,
            "name": etf_info.get('name', '未知'),
            "current_price": 0,
            "change": 0,
            "change_percent": 0,
            "message": "数据暂时不可用，请稍后重试"
        },
        "source": "fallback",
        "is_fallback": True
    }


# OpenClaw 工具函数接口
def tool_fetch_etf_realtime(
    etf_code: str = "510300",
    mode: str = "production"
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取ETF实时数据
    
    Args:
        etf_code: ETF代码，支持单个或多个（用逗号分隔）
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
    """
    return fetch_etf_realtime(etf_code=etf_code, mode=mode)


def fetch_etf_iopv_snapshot(
    etf_code: str = "510300",
) -> Dict[str, Any]:
    """
    从东方财富 ETF 列表拉取 IOPV 实时估值与基金折价率（AkShare fund_etf_spot_em）。
    失败时返回 success=False，不抛异常。
    """
    if not AKSHARE_AVAILABLE:
        return {
            "success": False,
            "message": "akshare not installed",
            "data": None,
            "source": "fund_etf_spot_em",
        }
    codes = [c.strip() for c in str(etf_code).split(",") if c.strip()]
    if not codes:
        return {
            "success": False,
            "message": "未提供有效的 ETF 代码",
            "data": None,
            "source": "fund_etf_spot_em",
        }
    try:
        ctx = without_proxy_env() if PROXY_ENV_AVAILABLE else nullcontext()
        with ctx:
            spot_df = ak.fund_etf_spot_em()
    except Exception as e:
        return {
            "success": False,
            "message": f"fund_etf_spot_em failed: {e}",
            "data": None,
            "source": "fund_etf_spot_em",
        }
    if spot_df is None or spot_df.empty or "代码" not in spot_df.columns:
        return {
            "success": False,
            "message": "东财 ETF 列表为空或格式变更",
            "data": None,
            "source": "fund_etf_spot_em",
        }

    rows: List[Dict[str, Any]] = []
    for raw in codes:
        c = raw.upper().replace(".SH", "").replace(".SZ", "")
        if c.lower().startswith(("sh", "sz")) and len(c) > 2:
            c = c[2:]
        m = spot_df[spot_df["代码"].astype(str) == c]
        if m.empty:
            rows.append(
                {
                    "code": c,
                    "found": False,
                    "message": "未在东财 ETF 列表中匹配",
                }
            )
            continue
        r = m.iloc[0]
        iopv = None
        discount = None
        for col in spot_df.columns:
            if "IOPV" in str(col):
                try:
                    iopv = float(r[col])
                except (TypeError, ValueError):
                    pass
            if "折价" in str(col):
                try:
                    discount = float(r[col])
                except (TypeError, ValueError):
                    pass
        name_val = ""
        if "名称" in r.index:
            name_val = str(r["名称"])
        px = 0.0
        if "最新价" in r.index:
            try:
                px = float(r["最新价"])
            except (TypeError, ValueError):
                px = 0.0
        rows.append(
            {
                "code": c,
                "found": True,
                "name": name_val,
                "latest_price": px,
                "iopv": iopv,
                "discount_pct": discount,
            }
        )

    data_out: Any = rows[0] if len(rows) == 1 else rows
    return {
        "success": True,
        "message": "Successfully fetched ETF IOPV / discount metadata",
        "data": data_out,
        "source": "fund_etf_spot_em",
        "count": len(rows),
    }


def tool_fetch_etf_iopv_snapshot(
    etf_code: str = "510300",
) -> Dict[str, Any]:
    """OpenClaw 工具：ETF IOPV / 折价率（东财列表）"""
    return fetch_etf_iopv_snapshot(etf_code=etf_code)
