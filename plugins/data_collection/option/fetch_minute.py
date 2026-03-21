"""
获取期权分钟数据
融合 Coze 插件 get_option_minute.py
OpenClaw 插件工具
"""

import requests
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path
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

# 尝试导入原系统的缓存模块（优先使用当前环境 /home/xie/src，其次回退到 Windows 路径）
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
            get_cache_file_path, load_cached_data, save_cached_data,
            get_cached_option_minute, save_option_minute_cache,
            merge_cached_and_fetched_data
        )
        from src.config_loader import load_system_config
        CACHE_AVAILABLE = True
    else:
        CACHE_AVAILABLE = False
except Exception:
    CACHE_AVAILABLE = False


def fetch_option_minute(
    contract_code: str,
    date: Optional[str] = None,
    use_cache: bool = True,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
    mode: str = "production"
) -> Dict[str, Any]:
    """
    获取期权分钟数据（融合 Coze get_option_minute.py）
    
    Args:
        contract_code: 期权合约代码（必填）
            - 上交所期权：纯8位数字，如 "10010896"
            - 深交所期权：数字或字母+数字组合，如 "90007021"
        date: 日期字符串（格式：YYYYMMDD），如果为None则查询当天数据
        use_cache: 是否使用缓存（默认True）
        api_base_url: 原系统 API 基础地址
        api_key: API Key
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
    
    Returns:
        Dict: 包含分钟数据的字典
    """
    try:
        # ========== 首先判断是否是交易日 ==========
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取期权分钟数据")
            if trading_day_check:
                return trading_day_check
        # ========== 交易日判断结束 ==========
        
        if not AKSHARE_AVAILABLE:
            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
                'data': None
            }
        
        if not contract_code:
            return {
                'success': False,
                'message': '请提供期权合约代码',
                'data': None
            }
        
        contract_code = str(contract_code).strip()
        if not contract_code:
            return {
                'success': False,
                'message': '合约代码不能为空',
                'data': None
            }
        
        # 处理日期参数
        today = datetime.now().strftime("%Y%m%d")
        target_date = date[:8] if date and len(date) >= 8 else today
        
        # ========== 缓存逻辑：历史数据使用缓存 ==========
        if target_date != today and use_cache and CACHE_AVAILABLE:
            try:
                config = load_system_config(use_cache=True) if CACHE_AVAILABLE else None
                if config:
                    cached_df = get_cached_option_minute(contract_code, target_date, period=None, config=config)
                    if cached_df is not None and not cached_df.empty:
                        # 转换为输出格式
                        klines = []
                        for _, row in cached_df.iterrows():
                            klines.append({
                                "date": str(row.get('日期', row.get('date', ''))),
                                "time": str(row.get('时间', row.get('time', ''))),
                                "price": float(row.get('价格', row.get('price', 0))),
                                "volume": int(row.get('成交量', row.get('成交', row.get('volume', 0)))),
                                "open_interest": int(row.get('持仓量', row.get('持仓', row.get('open_interest', 0)))),
                                "avg_price": float(row.get('均价', row.get('avg_price', 0)))
                            })
                        
                        return {
                            'success': True,
                            'message': f'Successfully fetched {len(klines)} records from cache',
                            'data': {
                                "contract_code": contract_code,
                                "count": len(klines),
                                "klines": klines,
                                "date": target_date,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            },
                            'source': 'cache',
                            'note': '历史数据来自缓存'
                        }
            except Exception:
                # 缓存失败不影响主流程
                pass
        
        # ========== 从API获取数据（仅支持当天数据）==========
        if target_date != today:
            return {
                'success': True,
                'message': '历史日期数据请使用缓存，API仅支持当天数据',
                'data': {
                    "contract_code": contract_code,
                    "count": 0,
                    "klines": [],
                    "date": target_date,
                    "message": "历史日期数据请使用缓存",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                'source': 'akshare_sina',
                'is_fallback': True,
                'note': '此接口只能返回当天的分钟数据'
            }
        
        # 使用 option_sse_minute_sina 获取期权分钟数据
        # 注意：此接口支持上交所和深交所期权，但只能返回当天的分钟数据
        df = ak.option_sse_minute_sina(symbol=contract_code)
        
        if df is None or df.empty:
            return {
                'success': True,
                'message': '未获取到期权分钟数据（可能非交易时间）',
                'data': {
                    "contract_code": contract_code,
                    "count": 0,
                    "klines": [],
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "message": "期权分钟数据暂时不可用，请稍后重试",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                'source': 'akshare_sina',
                'is_fallback': True,
                'note': '此接口只能返回当天的分钟数据'
            }
        
        # ========== 统一字段名 ==========
        # 统一列名（处理中英文字段名混用）
        column_mapping = {
            '日期': '日期', 'date': '日期',
            '时间': '时间', 'time': '时间',
            '价格': '价格', 'price': '价格',
            '成交': '成交量', 'volume': '成交量',
            '持仓': '持仓量', 'open_interest': '持仓量',
            '均价': '均价', 'avg_price': '均价'
        }
        
        for old_col, new_col in column_mapping.items():
            if old_col in df.columns and old_col != new_col:
                if new_col not in df.columns:
                    df[new_col] = df[old_col]
                df = df.drop(columns=[old_col], errors='ignore')
        
        # 确保必要的列存在
        if '日期' not in df.columns:
            df['日期'] = datetime.now().strftime("%Y-%m-%d")
        if '时间' not in df.columns:
            df['时间'] = ''
        if '价格' not in df.columns:
            df['价格'] = 0.0
        if '成交量' not in df.columns:
            df['成交量'] = 0
        if '持仓量' not in df.columns:
            df['持仓量'] = 0
        if '均价' not in df.columns:
            df['均价'] = 0.0
        
        # ========== 保存到缓存 ==========
        if use_cache and CACHE_AVAILABLE:
            try:
                config = load_system_config(use_cache=True) if CACHE_AVAILABLE else None
                if config:
                    save_option_minute_cache(contract_code, df, period=None, config=config)
            except Exception:
                # 缓存保存失败不影响主流程
                pass
        
        # 转换数据格式
        klines = []
        for _, row in df.iterrows():
            klines.append({
                "date": str(row.get('日期', '')),
                "time": str(row.get('时间', '')),
                "price": float(row.get('价格', 0)),
                "volume": int(row.get('成交量', 0)),
                "open_interest": int(row.get('持仓量', 0)),
                "avg_price": float(row.get('均价', 0))
            })
        
        return {
            'success': True,
            'message': f'Successfully fetched {len(klines)} records',
            'data': {
                "contract_code": contract_code,
                "count": len(klines),
                "klines": klines,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            'source': 'akshare_sina',
            'note': '此接口支持上交所和深交所期权，但只能返回当天的分钟数据'
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_fetch_option_minute(
    contract_code: str,
    date: Optional[str] = None,
    mode: str = "production",
    use_cache: bool = True,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取期权分钟数据
    
    Args:
        contract_code: 期权合约代码（必填）
        date: 日期字符串（格式：YYYYMMDD），如果为None则查询当天数据
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        use_cache: 是否使用缓存（默认True）
        period: 期权分钟周期（目前底层接口只提供单一周期，此参数主要用于兼容上层统一调用签名）
    """
    # 为了兼容上层 merged.fetch_option_data 在调用时传入的 period 参数，
    # 这里接受 period 但当前实现并不区分不同周期，仍然使用单一分钟数据源。
    return fetch_option_minute(
        contract_code=contract_code,
        date=date,
        mode=mode,
        use_cache=use_cache,
    )
