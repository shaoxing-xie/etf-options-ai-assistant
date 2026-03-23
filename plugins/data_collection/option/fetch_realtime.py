"""
获取期权实时数据
融合 Coze 插件 get_option_realtime.py
OpenClaw 插件工具
"""

import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime
import os
import sys
import re

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


def _parse_spot_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """解析 option_sse_spot_price_sina 返回的字段/值格式DataFrame"""
    data_dict = {}
    if df is None or df.empty:
        return data_dict
    
    if '字段' in df.columns and '值' in df.columns:
        for idx, row in df.iterrows():
            field = str(row.get('字段', '')).strip()
            value = row.get('值', '')
            if field and value is not None:
                data_dict[field] = str(value).strip()
    else:
        if len(df) > 0:
            data_dict = df.iloc[0].to_dict()
    
    return data_dict


def fetch_option_realtime(
    contract_code: Optional[str] = None,
    underlying: Optional[str] = None,
    mode: str = "production",
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取期权实时数据（融合 Coze get_option_realtime.py）
    
    Args:
        contract_code: 期权合约代码（单个合约查询，如 "10011077"）
        underlying: 标的代码（批量查询该标的所有期权，如 "510300"）
        注意：如果同时提供两个参数，优先使用 contract_code（单个查询）
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        api_base_url: 原系统 API 基础地址
        api_key: API Key
    
    Returns:
        Dict: 包含实时数据的字典
    """
    try:
        # ========== 首先判断是否是交易日 ==========
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取期权实时数据")
            if trading_day_check:
                return trading_day_check
        # ========== 交易日判断结束 ==========
        
        if not AKSHARE_AVAILABLE:
            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
                'data': None
            }
        
        if contract_code:
            return _get_single_option(contract_code)
        elif underlying:
            return _get_underlying_options(underlying)
        else:
            return {
                'success': False,
                'message': '请提供期权合约代码(contract_code)或标的代码(underlying)',
                'data': None
            }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


def _get_single_option(contract_code: str) -> Dict[str, Any]:
    """获取单个期权合约的实时数据（仅支持上交所）"""
    try:
        # 验证和清理合约代码
        if not contract_code:
            return {
                'success': False,
                'message': '合约代码不能为空',
                'data': None
            }

        raw_code = str(contract_code).strip()
        # 兼容多种格式，例如：10010891、CON_OP_10010891、10010891.SH 等
        # 优先使用纯 8 位数字，其次从字符串中提取连续 8 位数字
        normalized = raw_code
        if not (normalized.isdigit() and len(normalized) == 8):
            digits_only = "".join(ch for ch in raw_code if ch.isdigit())
            if len(digits_only) == 8:
                normalized = digits_only
            else:
                match = re.search(r"\d{8}", raw_code)
                if match:
                    normalized = match.group(0)

        # 如果仍然无法得到 8 位纯数字，不直接报错，而是尝试用原始代码调用一次 API
        if not (normalized.isdigit() and len(normalized) == 8):
            try_code = raw_code
        else:
            try_code = normalized

        # 调用 akshare API（优先使用规范化后的 8 位代码，但也兼容原始格式）
        try:
            df = ak.option_sse_spot_price_sina(symbol=try_code)
        except Exception as api_error:
            return {
                'success': False,
                'message': f'调用 akshare API 失败: {str(api_error)}',
                'data': None
            }
        
        if df is None or df.empty:
            return {
                'success': False,
                'message': f'未获取到上交所期权数据: {contract_code}（尝试代码: {try_code}）',
                'data': None
            }
        
        data_dict = _parse_spot_dataframe(df)
        
        def get_field_value(field_names: List[str], default=0):
            for field_name in field_names:
                if field_name in data_dict:
                    try:
                        value = data_dict[field_name]
                        if isinstance(value, str):
                            value = value.replace(',', '').replace(' ', '').strip()
                            if value:
                                return float(value)
                            else:
                                return default
                        elif isinstance(value, (int, float)):
                            return float(value)
                        else:
                            return default
                    except (ValueError, TypeError):
                        continue
            return default
        
        current_price = get_field_value(['最新价', '当前价', '现价', 'last_price', 'price'], 0)
        
        # 自动计算涨跌和涨跌幅
        change = 0
        change_percent = 0
        prev_close = get_field_value(['昨收价', 'prev_close', 'pre_close'], 0)
        
        if current_price > 0 and prev_close > 0:
            change = current_price - prev_close
            change_percent = (change / prev_close) * 100
        else:
            # 如果无法计算，尝试从字段中获取
            change = get_field_value(['涨跌', 'change', '涨跌额'], 0)
            change_percent = get_field_value(['涨幅', '涨跌幅', 'pct_chg', 'change_percent'], 0)
            
            # 如果涨跌幅为0或缺失，但涨跌不为0，尝试计算
            if change != 0 and change_percent == 0 and prev_close > 0:
                change_percent = (change / prev_close) * 100
        bid_price = get_field_value(['买价', 'bid', 'bid_price'], 0)
        ask_price = get_field_value(['卖价', 'ask', 'ask_price'], 0)
        bid_volume = get_field_value(['买量', 'bid_volume', '买盘量'], 0)
        ask_volume = get_field_value(['卖量', 'ask_volume', '卖盘量'], 0)
        volume = get_field_value(['成交量', 'volume', '成交'], 0)
        open_interest = get_field_value(['持仓量', 'open_interest', 'oi', '持仓'], 0)
        open_price = get_field_value(['今开', 'open', 'open_price', '开盘价'], 0)
        high = get_field_value(['最高', 'high', 'high_price', '最高价'], 0)
        low = get_field_value(['最低', 'low', 'low_price', '最低价'], 0)
        
        # 自动计算成交额（如果缺失）
        amount = get_field_value(['成交额', 'amount', '成交金额'], 0)
        if amount == 0 and volume > 0 and current_price > 0:
            # 成交额 = 成交量 * 当前价 * 合约单位（期权通常是100）
            amount = volume * current_price * 100
        
        # 结果中保留规范化后的 8 位代码，便于后续工具链统一使用
        final_code = normalized if (normalized.isdigit() and len(normalized) == 8) else try_code

        option_data = {
            "contract_code": final_code,
            "current_price": current_price,
            "change": change,
            "change_percent": change_percent,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "volume": volume,
            "open_interest": open_interest,
            "prev_close": prev_close,
            "open": open_price,
            "high": high,
            "low": low,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 提取额外信息
        if '期权合约简称' in data_dict:
            option_data["contract_name"] = str(data_dict.get('期权合约简称', ''))
        if '交易代码' in data_dict:
            option_data["trading_code"] = str(data_dict.get('交易代码', ''))
        
        return {
            'success': True,
            'message': 'Successfully fetched option realtime data',
            'data': option_data,
            'source': 'akshare_sina'
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


def _get_underlying_options(underlying: str) -> Dict[str, Any]:
    """批量查询标的下所有期权"""
    try:
        # 验证输入参数
        if not underlying:
            return {
                'success': False,
                'message': '标的代码不能为空',
                'data': None
            }
        
        underlying = str(underlying).strip()
        if not underlying:
            return {
                'success': False,
                'message': '标的代码不能为空',
                'data': None
            }
        
        # 获取当前年月作为 trade_date（格式：YYYYMM）
        from datetime import datetime
        current_date = datetime.now()
        trade_date = current_date.strftime("%Y%m")[:6]
        
        # 使用 option_sse_codes_sina 获取期权合约代码列表
        # 这个方法可以直接使用 underlying="510300"，比 option_sse_list_sina 更可靠
        contract_codes = []
        
        try:
            # 获取看涨期权代码
            call_codes_df = ak.option_sse_codes_sina(
                symbol="看涨期权",
                trade_date=trade_date,
                underlying=underlying
            )
            if call_codes_df is not None and not call_codes_df.empty:
                if '期权代码' in call_codes_df.columns:
                    call_codes = call_codes_df['期权代码'].astype(str).tolist()
                    contract_codes.extend(call_codes)
        except Exception:
            # 看涨期权获取失败，继续尝试看跌期权
            pass
        
        try:
            # 获取看跌期权代码
            put_codes_df = ak.option_sse_codes_sina(
                symbol="看跌期权",
                trade_date=trade_date,
                underlying=underlying
            )
            if put_codes_df is not None and not put_codes_df.empty:
                if '期权代码' in put_codes_df.columns:
                    put_codes = put_codes_df['期权代码'].astype(str).tolist()
                    contract_codes.extend(put_codes)
        except Exception:
            # 看跌期权获取失败，继续处理已获取的看涨期权
            pass
        
        # 如果当前月份没有数据，尝试上一个月
        if not contract_codes:
            try:
                # 计算上一个月（手动计算，避免依赖 dateutil）
                year = current_date.year
                month = current_date.month
                if month == 1:
                    prev_year = year - 1
                    prev_month = 12
                else:
                    prev_year = year
                    prev_month = month - 1
                prev_date = f"{prev_year}{prev_month:02d}"
                
                call_codes_df = ak.option_sse_codes_sina(symbol="看涨期权", trade_date=prev_date, underlying=underlying)
                if call_codes_df is not None and not call_codes_df.empty and '期权代码' in call_codes_df.columns:
                    contract_codes.extend(call_codes_df['期权代码'].astype(str).tolist())
                put_codes_df = ak.option_sse_codes_sina(symbol="看跌期权", trade_date=prev_date, underlying=underlying)
                if put_codes_df is not None and not put_codes_df.empty and '期权代码' in put_codes_df.columns:
                    contract_codes.extend(put_codes_df['期权代码'].astype(str).tolist())
            except:
                pass
        
        # 去重并过滤有效的合约代码（8位数字）
        contract_codes = list(set([code for code in contract_codes if code and len(str(code)) == 8 and str(code).isdigit()]))
        
        if not contract_codes:
            return {
                'success': False,
                'message': f'未获取到标的 {underlying} 的期权合约代码列表（trade_date={trade_date}）',
                'data': None
            }
        
        # 批量获取每个期权的实时数据
        options_data = []
        success_count = 0
        for contract_code in contract_codes:
            try:
                single_result = _get_single_option(contract_code)
                if single_result.get('success'):
                    options_data.append(single_result.get('data'))
                    success_count += 1
            except Exception:
                # 跳过单个合约的错误，继续处理下一个
                continue
        
        if not options_data:
            return {
                'success': False,
                'message': f'获取到 {len(contract_codes)} 个合约代码，但未能成功获取任何实时数据',
                'data': None
            }
        
        return {
            'success': True,
            'message': f'Successfully fetched {len(options_data)} options (from {len(contract_codes)} contracts)',
            'data': options_data,
            'count': len(options_data),
            'source': 'akshare_sina'
        }
    
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None,
            'error_detail': error_detail if len(error_detail) < 500 else str(e)
        }


# OpenClaw 工具函数接口
def tool_fetch_option_realtime(
    contract_code: Optional[str] = None,
    underlying: Optional[str] = None,
    mode: str = "production"
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取期权实时数据
    
    Args:
        contract_code: 期权合约代码（单个合约查询）
        underlying: 标的代码（批量查询该标的所有期权）
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
    """
    return fetch_option_realtime(
        contract_code=contract_code,
        underlying=underlying,
        mode=mode
    )
