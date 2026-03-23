"""
获取期权Greeks数据
融合 Coze 插件 get_option_greeks.py
OpenClaw 插件工具
"""

import pandas as pd
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
            get_cached_option_greeks, save_option_greeks_cache,
        )
        from src.config_loader import load_system_config
        CACHE_AVAILABLE = True
    else:
        CACHE_AVAILABLE = False
except Exception:
    CACHE_AVAILABLE = False


def fetch_option_greeks(
    contract_code: str,
    date: Optional[str] = None,
    mode: str = "production",
    use_cache: bool = True,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取期权Greeks数据（融合 Coze get_option_greeks.py）
    
    Args:
        contract_code: 期权合约代码（必填，上交所代码为纯数字如 10002273，深交所代码可能为纯数字如 90006938）
        date: 日期字符串（格式：YYYYMMDD），如果为None则查询当天数据
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        use_cache: 是否使用缓存（默认True）
        api_base_url: 原系统 API 基础地址
        api_key: API Key
    
    Returns:
        Dict: 包含Greeks数据的字典
    """
    try:
        # ========== 首先判断是否是交易日 ==========
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取期权Greeks数据")
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
        
        # 处理日期参数
        today = datetime.now().strftime("%Y%m%d")
        target_date = date[:8] if date and len(date) >= 8 else today
        
        # ========== 缓存逻辑：先检查缓存 ==========
        if use_cache and CACHE_AVAILABLE:
            try:
                config = load_system_config() if CACHE_AVAILABLE else None
                if config:
                    cached_df = get_cached_option_greeks(contract_code, target_date, use_closest=True, config=config)
                    if cached_df is not None and not cached_df.empty:
                        # 转换为输出格式
                        result_data = {}
                        for _, row in cached_df.iterrows():
                            for col in cached_df.columns:
                                if col not in ['采集时间', 'timestamp']:
                                    result_data[col] = row[col]
                        
                        return {
                            'success': True,
                            'message': 'Successfully fetched option Greeks data from cache',
                            'data': {
                                **result_data,
                                "contract_code": contract_code,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            },
                            'source': 'cache'
                        }
            except Exception:
                # 缓存失败不影响主流程
                pass
        
        # ========== 从API获取数据 ==========
        df = ak.option_sse_greeks_sina(symbol=str(contract_code))
        
        if df is None or df.empty:
            return {
                'success': False,
                'message': f'未获取到期权Greeks数据: {contract_code}',
                'data': None
            }
        
        # 解析字段/值格式
        greeks_dict = {}
        for _, row in df.iterrows():
            field_name = str(row.get('字段', ''))
            field_value = row.get('值', '')
            greeks_dict[field_name] = field_value
        
        # ========== 保存到缓存 ==========
        if use_cache and CACHE_AVAILABLE:
            try:
                # 将数据转换为DataFrame格式保存
                greeks_df = pd.DataFrame([greeks_dict])
                config = load_system_config() if CACHE_AVAILABLE else None
                if config:
                    save_option_greeks_cache(contract_code, greeks_df, target_date, config=config)
            except Exception:
                # 缓存保存失败不影响主流程
                pass
        
        def safe_float(value, default=0.0):
            """安全转换为float，处理NAN、-1等特殊值"""
            if pd.isna(value) or value == 'NAN' or str(value).upper() == 'NAN':
                return default
            try:
                val = float(value)
                return val
            except (ValueError, TypeError):
                return default
        
        # 提取主要Greeks值
        delta_val = safe_float(greeks_dict.get('Delta', 0))
        gamma_val = safe_float(greeks_dict.get('Gamma', 0))
        theta_val = safe_float(greeks_dict.get('Theta', 0))
        vega_val = safe_float(greeks_dict.get('Vega', 0))
        rho_val = safe_float(greeks_dict.get('Rho', 0))
        iv_val = safe_float(greeks_dict.get('隐含波动率', 0))
        
        # 数据质量评估
        data_quality_issues = []
        if delta_val == -1 or delta_val == 0:
            data_quality_issues.append("Delta无效")
        if pd.isna(greeks_dict.get('Gamma')) or str(greeks_dict.get('Gamma', '')).upper() == 'NAN':
            data_quality_issues.append("Gamma无效")
        if vega_val == 0:
            data_quality_issues.append("Vega为0")
        if iv_val == 0:
            data_quality_issues.append("隐含波动率为0")
        
        trading_code = str(greeks_dict.get('交易代码', ''))
        is_szse = trading_code.startswith('159') if trading_code else False
        
        # 构建结果数据
        result_data = {
            "contract_code": contract_code,
            "delta": delta_val,
            "gamma": gamma_val,
            "theta": theta_val,
            "vega": vega_val,
            "rho": rho_val,
            "implied_volatility": iv_val,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 添加数据质量警告
        if data_quality_issues:
            result_data["data_quality_warning"] = ", ".join(data_quality_issues)
            result_data["data_quality_note"] = "部分Greeks数据无效或缺失，可能影响分析准确性"
            if is_szse:
                result_data["data_quality_note"] += "（深交所期权Greeks数据质量通常较差）"
        
        # 提取额外信息
        if '期权合约简称' in greeks_dict:
            result_data["contract_name"] = str(greeks_dict.get('期权合约简称', ''))
        if '交易代码' in greeks_dict:
            result_data["trading_code"] = str(greeks_dict.get('交易代码', ''))
        if '行权价' in greeks_dict:
            result_data["strike_price"] = safe_float(greeks_dict.get('行权价', 0))
        if '最新价' in greeks_dict:
            result_data["current_price"] = safe_float(greeks_dict.get('最新价', 0))
        if '理论价值' in greeks_dict:
            result_data["theoretical_value"] = safe_float(greeks_dict.get('理论价值', 0))
        if '成交量' in greeks_dict:
            result_data["volume"] = int(safe_float(greeks_dict.get('成交量', 0)))
        if '最高价' in greeks_dict:
            result_data["high_price"] = safe_float(greeks_dict.get('最高价', 0))
        if '最低价' in greeks_dict:
            result_data["low_price"] = safe_float(greeks_dict.get('最低价', 0))
        
        return {
            'success': True,
            'message': 'Successfully fetched option Greeks data',
            'data': result_data,
            'source': 'akshare_sina'
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_fetch_option_greeks(
    contract_code: str,
    date: Optional[str] = None,
    mode: str = "production",
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取期权Greeks数据
    
    Args:
        contract_code: 期权合约代码（必填）
        date: 日期字符串（格式：YYYYMMDD），如果为None则查询当天数据
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        use_cache: 是否使用缓存（默认True）
    """
    return fetch_option_greeks(
        contract_code=contract_code,
        date=date,
        mode=mode,
        use_cache=use_cache
    )
