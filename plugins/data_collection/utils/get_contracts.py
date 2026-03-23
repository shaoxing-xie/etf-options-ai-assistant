"""
获取期权合约列表（上交所 ETF 期权标的）

融合 Coze 插件 get_option_contracts.py。合约 **主数据**（挂牌月份、最后交易日、行权价阶梯）
以交易所规则为准；本工具通过新浪接口拉取 **当前可查询月份** 下的合约代码列表，
与 `ROADMAP.md` 附录 D 及 `option/README.md` 描述一致。
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta

try:
    import akshare as ak
    import pandas as pd
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


def get_option_contracts(
    underlying: str = "510300",
    option_type: str = "all",  # "call", "put", "all"
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取期权合约列表（融合 Coze get_option_contracts.py）
    
    Args:
        underlying: 标的代码，如 "510300"(300ETF), "510050"(50ETF), "510500"(500ETF)
        option_type: 期权类型 "call"(认购)/"put"(认沽)/"all"(全部)
        api_base_url: 原系统 API 基础地址
        api_key: API Key
    
    Returns:
        Dict: 包含期权合约列表的字典
    """
    try:
        if not AKSHARE_AVAILABLE:
            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
                'data': None
            }
        
        # 上交所（SSE）期权标的物ETF映射
        underlying_mapping = {
            "510050": {"name": "华夏上证50ETF", "exchange": "SSE", "symbol_for_list": "50ETF"},
            "510300": {"name": "沪深300ETF", "exchange": "SSE", "symbol_for_list": "300ETF"},
            "510500": {"name": "南方中证500ETF", "exchange": "SSE", "symbol_for_list": "500ETF"},
            "588000": {"name": "科创50ETF", "exchange": "SSE", "symbol_for_list": "科创50ETF"},
            "588080": {"name": "科创板50ETF", "exchange": "SSE", "symbol_for_list": "科创板50ETF"},
        }
        
        underlying_info = underlying_mapping.get(underlying)
        if not underlying_info:
            return {
                'success': False,
                'message': f'不支持的标的代码: {underlying}，当前仅支持上交所期权标的',
                'supported_codes': list(underlying_mapping.keys()),
                'data': None
            }
        
        option_type = option_type.strip().lower() if option_type else "all"
        
        contracts = []
        symbol_for_list = underlying_info.get('symbol_for_list', '300ETF')
        
        # 获取到期月份列表
        expiry_months = []
        try:
            expiry_list = ak.option_sse_list_sina(symbol=symbol_for_list, exchange="null")
            if expiry_list is not None:
                if isinstance(expiry_list, list):
                    expiry_months = expiry_list
                elif hasattr(expiry_list, 'tolist'):
                    expiry_months = expiry_list.tolist()
                elif isinstance(expiry_list, pd.DataFrame) and not expiry_list.empty:
                    expiry_months = expiry_list.iloc[:, 0].astype(str).tolist()
                else:
                    expiry_months = list(expiry_list) if expiry_list else []
                
                # 清理月份格式
                cleaned_months = []
                for month in expiry_months:
                    month_str = str(month).strip()
                    month_str = month_str.replace('-', '').replace('/', '').replace(' ', '')
                    if len(month_str) == 6 and month_str.isdigit():
                        cleaned_months.append(month_str)
                expiry_months = cleaned_months
        except Exception:
            # 使用默认月份
            current_month = datetime.now().strftime("%Y%m")
            next_month = (datetime.now() + timedelta(days=32)).replace(day=1).strftime("%Y%m")
            expiry_months = [current_month, next_month]
        
        # 只取最近2个月份
        if len(expiry_months) > 2:
            expiry_months = expiry_months[:2]
        
        # 遍历每个月份，获取合约代码
        for trade_date in expiry_months:
            # 获取认购期权合约代码
            if option_type in ["all", "call"]:
                try:
                    call_codes_df = ak.option_sse_codes_sina(
                        symbol="看涨期权",
                        trade_date=trade_date,
                        underlying=underlying
                    )
                    
                    if call_codes_df is not None and not call_codes_df.empty:
                        for _, row in call_codes_df.iterrows():
                            contract_code = str(row.iloc[0]).strip()
                            if contract_code:
                                contracts.append({
                                    'contract_code': contract_code,
                                    'option_type': 'call',
                                    'trade_month': trade_date
                                })
                except Exception:
                    pass
            
            # 获取认沽期权合约代码
            if option_type in ["all", "put"]:
                try:
                    put_codes_df = ak.option_sse_codes_sina(
                        symbol="看跌期权",
                        trade_date=trade_date,
                        underlying=underlying
                    )
                    
                    if put_codes_df is not None and not put_codes_df.empty:
                        for _, row in put_codes_df.iterrows():
                            contract_code = str(row.iloc[0]).strip()
                            if contract_code:
                                contracts.append({
                                    'contract_code': contract_code,
                                    'option_type': 'put',
                                    'trade_month': trade_date
                                })
                except Exception:
                    pass
        
        return {
            'success': True,
            'message': f'Successfully fetched {len(contracts)} contracts',
            'data': {
                'underlying': underlying,
                'underlying_name': underlying_info.get('name'),
                'option_type': option_type,
                'contracts': contracts,
                'count': len(contracts),
                'expiry_months_queried': expiry_months,
            }
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_get_option_contracts(
    underlying: str = "510300",
    option_type: str = "all"
) -> Dict[str, Any]:
    """OpenClaw 工具：获取期权合约列表"""
    return get_option_contracts(underlying=underlying, option_type=option_type)
