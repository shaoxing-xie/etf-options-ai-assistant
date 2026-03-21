"""
获取指数实时数据
融合 Coze 插件 get_index_realtime.py
OpenClaw 插件工具
"""

import requests
import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime
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


def _fetch_index_realtime_mootdx_single(index_code: str) -> Optional[Dict[str, Any]]:
    """
    使用 mootdx 获取单个指数的实时行情。

    说明:
        - index_code 例如 "000300"、"000001" 等。
        - 使用 Quotes.factory('std').bars(frequency=9, offset=1) 取最新一根日K 作为近似实时快照。
          （mootdx 指数 quotes 支持有限，使用 bars 是一个稳定方案；实时精度由后续需要再精细化）
    """
    if not MOOTDX_AVAILABLE:
        return None

    try:
        client = Quotes.factory(market="std")
    except Exception:
        return None

    try:
        df = client.bars(symbol=index_code, frequency=9, offset=1)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    row = df.iloc[-1]
    # 安全取值
    def safe_get(name: str, default: float = 0.0) -> float:
        try:
            if name in row.index:
                v = row[name]
                if v is not None and str(v) != "nan":
                    return float(v)
        except Exception:
            pass
        return default

    close_price = safe_get("close", 0.0)
    open_price = safe_get("open", 0.0)
    high = safe_get("high", 0.0)
    low = safe_get("low", 0.0)
    volume = safe_get("vol", 0.0)
    amount = safe_get("amount", 0.0)

    # 这里日K中不直接包含昨收，用前一根K线近似；若失败则留为0
    prev_close = 0.0
    try:
        df_prev = client.bars(symbol=index_code, frequency=9, offset=2)
        if df_prev is not None and len(df_prev) >= 2:
            prev_close = float(df_prev.iloc[-2]["close"])
    except Exception:
        prev_close = 0.0

    if prev_close != 0.0:
        change = close_price - prev_close
        change_percent = change / prev_close * 100
    else:
        change = 0.0
        change_percent = 0.0

    return {
        "current_price": close_price,
        "open": open_price,
        "high": high,
        "low": low,
        "prev_close": prev_close,
        "change": change,
        "change_percent": change_percent,
        "volume": volume,
        "amount": amount,
    }


def fetch_index_realtime(
    index_code: str = "000001",  # 支持单个或多个（用逗号分隔）
    mode: str = "production",
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取指数实时数据（融合 Coze get_index_realtime.py）
    
    Args:
        index_code: 指数代码，支持单个或多个（用逗号分隔），如 "000001" 或 "000300,000001"
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        api_base_url: 原系统 API 基础地址
        api_key: API Key（如果未提供，从环境变量获取）
    
    Returns:
        Dict: 包含实时数据的字典
    """
    try:
        # ========== 首先判断是否是交易日 ==========
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取指数实时数据")
            if trading_day_check:
                return trading_day_check
        # ========== 交易日判断结束 ==========
        
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
                from plugins.data_collection.etf.fetch_realtime import fetch_etf_realtime
                logger.info(f"检测到 ETF 代码 {', '.join(etf_codes)}，自动调用 fetch_etf_realtime")
                etf_result = fetch_etf_realtime(
                    etf_code=",".join(etf_codes),
                    api_base_url=api_base_url,
                    api_key=api_key
                )
                # 如果只有ETF代码，直接返回ETF结果
                if not index_codes_only:
                    return etf_result
                # 如果还有指数代码，继续处理指数代码，然后合并结果
            except Exception as e:
                logger.warning(f"调用 fetch_etf_realtime 失败: {e}，继续处理指数代码")
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
        
        # 指数代码映射（复用 Coze 插件的映射）
        index_mapping = {
            "000001": {"name": "上证指数", "symbol": "sh000001"},
            "399001": {"name": "深证成指", "symbol": "sz399001"},
            "399006": {"name": "创业板指", "symbol": "sz399006"},
            "000300": {"name": "沪深300", "symbol": "sh000300"},
            "000016": {"name": "上证50", "symbol": "sh000016"},
            "000905": {"name": "中证500", "symbol": "sh000905"},
            "000852": {"name": "中证1000", "symbol": "sh000852"},
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
        
        # ====== 第一优先：尝试通过 mootdx 获取实时/近实时快照 ======
        df = None
        source = None

        mootdx_snapshots: Dict[str, Dict[str, Any]] = {}
        if MOOTDX_AVAILABLE:
            for code in index_codes_only:
                snap = _fetch_index_realtime_mootdx_single(code)
                if snap is not None:
                    mootdx_snapshots[code] = snap

        # 如果所有指数都从 mootdx 拿到了数据，则直接用 mootdx 结果返回
        if mootdx_snapshots and len(mootdx_snapshots) == len(index_codes_only):
            results = []
            for code in index_codes_only:
                base = index_mapping[code]
                snap = mootdx_snapshots[code]
                snap_data = {
                    "code": code,
                    "name": base["name"],
                    **snap,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                results.append(snap_data)

            # 如果有ETF结果，先添加到结果中
            if etf_codes and etf_result and etf_result.get('success'):
                etf_data = etf_result.get('data', {})
                if isinstance(etf_data, list):
                    results.extend(etf_data)
                elif isinstance(etf_data, dict):
                    results.append(etf_data)

            return {
                "success": True,
                "message": "Successfully fetched index realtime data via mootdx",
                "data": results[0] if len(results) == 1 else results,
                "source": "mootdx",
                "count": len(results),
            }

        # ====== 第二优先：保留原有 akshare / 新浪 / 东财 链路，作为 fallback ======
        if not AKSHARE_AVAILABLE:
            # akshare 不可用时，若 mootdx 至少给出部分数据，就返回部分 + 其余降级
            if mootdx_snapshots:
                results: List[Dict[str, Any]] = []
                for code in index_codes_only:
                    if code in mootdx_snapshots:
                        base = index_mapping[code]
                        snap = mootdx_snapshots[code]
                        results.append({
                            "code": code,
                            "name": base["name"],
                            **snap,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                    else:
                        results.append(_get_fallback_data(code, index_mapping)["data"])
                return {
                    "success": True,
                    "message": "Partially fetched via mootdx; others fallback",
                    "data": results[0] if len(results) == 1 else results,
                    "source": "mootdx+fallback",
                    "count": len(results),
                }

            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
                'data': None
            }

        # 方法：尝试使用 stock_zh_index_spot_sina（新浪接口，主用）
        try:
            df = ak.stock_zh_index_spot_sina()
            source = "stock_zh_index_spot_sina"
        except Exception:
            # 如果新浪失败，尝试东方财富接口
            try:
                symbols_to_try = set()
                for code in index_codes_only:
                    if code.startswith("000"):
                        symbols_to_try.update(["上证系列指数", "沪深重要指数", "中证系列指数"])
                    elif code.startswith("399"):
                        symbols_to_try.update(["深证系列指数", "沪深重要指数"])
                    else:
                        symbols_to_try.update(["沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数"])

                all_df = None
                for sym in symbols_to_try:
                    try:
                        temp_df = ak.stock_zh_index_spot_em(symbol=sym)
                        if temp_df is not None and not temp_df.empty:
                            if all_df is None:
                                all_df = temp_df
                            else:
                                all_df = pd.concat([all_df, temp_df], ignore_index=True)
                    except Exception:
                        continue

                if all_df is not None and not all_df.empty:
                    df = all_df
                    source = "stock_zh_index_spot_em"
            except Exception:
                df = None
        
        # 如果有ETF结果，先添加到结果中
        results = []
        if etf_codes and etf_result and etf_result.get('success'):
            etf_data = etf_result.get('data', {})
            if isinstance(etf_data, list):
                results.extend(etf_data)
            elif isinstance(etf_data, dict):
                results.append(etf_data)
        
        if df is None or df.empty:
            # 使用降级数据
            for code in index_codes_only:
                results.append(_get_fallback_data(code, index_mapping)["data"])
            return {
                'success': True,
                'message': '使用降级数据',
                'data': results[0] if len(results) == 1 else results,
                'source': 'fallback',
                'is_fallback': True
            }
        
        # 筛选数据
        code_col = None
        for col in ['代码', 'code', 'symbol']:
            if col in df.columns:
                code_col = col
                break
        
        if not code_col:
            for code in index_codes_only:
                results.append(_get_fallback_data(code, index_mapping)["data"])
            return {
                'success': True,
                'message': '使用降级数据',
                'data': results[0] if len(results) == 1 else results,
                'source': 'fallback',
                'is_fallback': True
            }
        
        # 处理多个指数
        for index_code_item in index_codes_only:
            index_info = index_mapping[index_code_item]
            
            # 构建可能的代码格式进行匹配
            possible_codes = [index_info['symbol']]
            if index_code_item.startswith("399"):
                possible_codes.extend([f"sz{index_code_item}", index_code_item])
            else:
                possible_codes.extend([f"sh{index_code_item}", index_code_item])
            
            # 尝试匹配
            target_row = None
            for code_pattern in possible_codes:
                try:
                    mask = df[code_col].astype(str).str.contains(code_pattern, na=False, regex=False)
                    if mask.any():
                        target_row = df[mask].iloc[0]
                        break
                except Exception:
                    continue
            
            if target_row is None or target_row.empty:
                results.append(_get_fallback_data(index_code_item, index_mapping)["data"])
                continue
            
            row = target_row
            
            # 安全获取值
            def safe_get(row, *keys, default=0):
                for key in keys:
                    if key in row.index:
                        try:
                            value = row[key]
                            if value is not None and str(value) != 'nan' and str(value) != '':
                                return float(value)
                        except (ValueError, TypeError):
                            continue
                return default
            
            current_price = safe_get(row, '最新价', 'close', 'price', 'last', '当前价', '现价', default=0)
            prev_close = safe_get(row, '昨收', 'pre_close', 'preclose', '昨收价', default=0)
            change = safe_get(row, '涨跌额', 'change', '涨跌', default=0)
            change_percent = safe_get(row, '涨跌幅', 'pct_chg', '涨跌幅%', default=0)
            
            # 自动计算涨跌额和涨跌幅（如果缺失或为0）
            if prev_close != 0 and current_price != 0:
                if change == 0:
                    change = current_price - prev_close
                if change_percent == 0:
                    change_percent = (change / prev_close) * 100 if prev_close != 0 else 0
            
            open_price = safe_get(row, '今开', 'open', '开盘', '开盘价', default=0)
            high = safe_get(row, '最高', 'high', '最高价', default=0)
            low = safe_get(row, '最低', 'low', '最低价', default=0)
            volume = safe_get(row, '成交量', 'volume', 'vol', default=0)
            amount = safe_get(row, '成交额', 'amount', '成交金额', default=0)
            
            # 获取名称
            name = index_info['name']
            for name_col in ['名称', 'name', '指数名称']:
                if name_col in row.index:
                    try:
                        name_value = str(row[name_col])
                        if name_value and name_value != 'nan':
                            name = name_value
                            break
                    except:
                        pass
            
            index_data = {
                "code": index_code_item,
                "name": name,
                "current_price": current_price,
                "change": change,
                "change_percent": change_percent,
                "open": open_price,
                "high": high,
                "low": low,
                "prev_close": prev_close,
                "volume": volume,
                "amount": amount,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            results.append(index_data)
        
        # 返回结果：单个指数返回对象，多个指数返回数组
        return {
            'success': True,
            'message': 'Successfully fetched index realtime data',
            'data': results[0] if len(results) == 1 else results,
            'source': source or 'akshare',
            'count': len(results)
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


def _get_fallback_data(index_code: str, index_mapping: Dict) -> Dict[str, Any]:
    """返回降级数据"""
    index_info = index_mapping.get(index_code, {"name": "未知指数"})
    
    return {
        "success": True,
        "data": {
            "code": index_code,
            "name": index_info.get('name', '未知'),
            "current_price": 0,
            "change": 0,
            "change_percent": 0,
            "message": "数据暂时不可用，请稍后重试"
        },
        "source": "fallback",
        "is_fallback": True
    }


# OpenClaw 工具函数接口
def tool_fetch_index_realtime(
    index_code: str = "000001",
    mode: str = "production"
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取指数实时数据
    
    Args:
        index_code: 指数代码，支持单个或多个（用逗号分隔）
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
    """
    return fetch_index_realtime(index_code=index_code, mode=mode)
