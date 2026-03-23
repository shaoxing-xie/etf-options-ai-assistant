"""
采集期权数据（实时/Greeks）
OpenClaw 插件工具
"""

import requests
from typing import Optional, Dict, Any
from datetime import datetime
import pytz
import os


def fetch_option_data(
    contract_code: str,
    data_type: str = "greeks",  # "spot", "greeks", "minute"
    period: str = "15",  # 分钟数据周期：15, 30
    date: Optional[str] = None,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    采集期权数据并写入原系统缓存
    
    Args:
        contract_code: 期权合约代码（如 "10010466"）
        data_type: 数据类型（"spot", "greeks", "minute"）
        period: 分钟数据周期（仅用于分钟数据）
        date: 日期（YYYYMMDD），如果为None则使用当前日期
        api_base_url: 原系统 API 基础地址
        api_key: API Key（如果未提供，从环境变量获取）
    
    Returns:
        Dict: 包含状态和结果的字典
    """
    try:
        # 获取 API Key
        if not api_key:
            api_key = os.environ.get('OPENCLAW_API_KEY', '')
        
        # 计算日期
        if not date:
            tz_shanghai = pytz.timezone('Asia/Shanghai')
            now = datetime.now(tz_shanghai)
            date = now.strftime('%Y%m%d')
        
        # 调用第三方API获取数据
        try:
            import akshare as ak
            
            if data_type == "spot":
                # 获取期权实时数据
                df = ak.option_sse_spot_price_sina(symbol=contract_code)
            elif data_type == "greeks":
                # 获取期权Greeks数据
                df = ak.option_sse_greeks_sina(symbol=contract_code)
            elif data_type == "minute":
                # 获取期权分钟数据
                df = ak.option_sse_minute_sina(symbol=contract_code)
            else:
                return {
                    'success': False,
                    'message': f'Unsupported data_type: {data_type}',
                    'data': None
                }
        except ImportError:
            return {
                'success': False,
                'message': 'akshare not installed. Please install: pip install akshare',
                'data': None
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to fetch data from API: {str(e)}',
                'data': None
            }
        
        if df is None or df.empty:
            return {
                'success': False,
                'message': 'Failed to fetch data from data source',
                'data': None
            }
        
        # 准备写入缓存的数据
        if data_type == "greeks":
            # Greeks数据：按日期保存
            data_payload = {
                'contract_code': contract_code,
                'date': date,
                'data': {
                    'df': df.to_dict('records'),
                    'columns': df.columns.tolist(),
                    'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()}
                }
            }
            
            url = f"{api_base_url}/api/cache/option_greeks"
            headers = {'Content-Type': 'application/json'}
            if api_key:
                headers['X-API-Key'] = api_key
            
            response = requests.post(url, json=data_payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'message': 'Successfully saved Greeks data',
                    'data': {
                        'contract_code': contract_code,
                        'date': date,
                        'rows': len(df)
                    }
                }
            else:
                return {
                    'success': False,
                    'message': f'Failed to write cache: {response.status_code} - {response.text}',
                    'data': None
                }
        
        elif data_type == "minute":
            # 分钟数据：按日期保存
            data_payload = {
                'contract_code': contract_code,
                'period': period,
                'date': date,
                'data': {
                    'df': df.to_dict('records'),
                    'columns': df.columns.tolist(),
                    'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()}
                }
            }
            
            url = f"{api_base_url}/api/cache/option_minute"
            headers = {'Content-Type': 'application/json'}
            if api_key:
                headers['X-API-Key'] = api_key
            
            response = requests.post(url, json=data_payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'message': 'Successfully saved minute data',
                    'data': {
                        'contract_code': contract_code,
                        'period': period,
                        'date': date,
                        'rows': len(df)
                    }
                }
            else:
                return {
                    'success': False,
                    'message': f'Failed to write cache: {response.status_code} - {response.text}',
                    'data': None
                }
        
        else:
            # spot 数据通常不需要缓存（实时数据）
            return {
                'success': True,
                'message': 'Spot data fetched (not cached)',
                'data': {
                    'contract_code': contract_code,
                    'rows': len(df),
                    'data': df.to_dict('records')
                }
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
    date: Optional[str] = None
) -> Dict[str, Any]:
    """OpenClaw 工具：采集期权Greeks数据"""
    return fetch_option_data(
        contract_code=contract_code,
        data_type="greeks",
        date=date
    )


def tool_fetch_option_minute(
    contract_code: str,
    period: str = "15",
    date: Optional[str] = None
) -> Dict[str, Any]:
    """OpenClaw 工具：采集期权分钟数据"""
    return fetch_option_data(
        contract_code=contract_code,
        data_type="minute",
        period=period,
        date=date
    )
