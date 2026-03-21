"""
采集ETF数据（日线/分钟）
OpenClaw 插件工具
"""

import requests
import pandas as pd
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import pytz
import os


def fetch_etf_data(
    symbol: str = "510300",
    data_type: str = "daily",  # "daily" 或 "minute"
    period: str = "5",  # 分钟数据周期：1, 5, 15, 30, 60
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    采集ETF数据并写入原系统缓存
    
    Args:
        symbol: ETF代码（如 "510300"）
        data_type: 数据类型（"daily" 或 "minute"）
        period: 分钟数据周期（仅用于分钟数据）
        start_date: 开始日期（YYYYMMDD），如果为None则自动计算
        end_date: 结束日期（YYYYMMDD），如果为None则使用当前日期
        lookback_days: 回看天数（默认5天）
        api_base_url: 原系统 API 基础地址
        api_key: API Key（如果未提供，从环境变量获取）
    
    Returns:
        Dict: 包含状态和结果的字典
    """
    try:
        # 获取 API Key
        if not api_key:
            api_key = os.environ.get('OPENCLAW_API_KEY', '')
        
        # 计算日期范围
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        
        if not end_date:
            end_date = now.strftime('%Y%m%d')
        
        if not start_date:
            start_date_obj = now - timedelta(days=lookback_days)
            start_date = start_date_obj.strftime('%Y%m%d')
        
        # 调用第三方API获取数据
        try:
            import akshare as ak
            
            if data_type == "daily":
                # 获取ETF日线数据
                df = ak.fund_etf_hist_em(
                    symbol=symbol,
                    period="日",
                    start_date=start_date.replace('-', '') if '-' in start_date else start_date,
                    end_date=end_date.replace('-', '') if '-' in end_date else end_date,
                    adjust=""
                )
            else:
                # 获取ETF分钟数据
                df = ak.fund_etf_hist_min_em(
                    symbol=symbol,
                    period=period,
                    start_date=start_date.replace('-', '') if '-' in start_date else start_date,
                    end_date=end_date.replace('-', '') if '-' in end_date else end_date,
                    adjust=""
                )
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
        if data_type == "daily":
            # 按日期拆分数据
            date_col = None
            for col in ['日期', 'date', '日期时间', 'datetime']:
                if col in df.columns:
                    date_col = col
                    break
            
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                dates = df[date_col].dt.strftime('%Y%m%d').unique()
            else:
                dates = [end_date]
            
            # 按日期写入缓存
            success_count = 0
            failed_dates = []
            for date in dates:
                date_df = df[df[date_col].dt.strftime('%Y%m%d') == date] if date_col else df
                
                data_payload = {
                    'symbol': symbol,
                    'date': date,
                    'data': {
                        'df': date_df.to_dict('records'),
                        'columns': date_df.columns.tolist(),
                        'dtypes': {col: str(dtype) for col, dtype in date_df.dtypes.items()}
                    }
                }
                
                url = f"{api_base_url}/api/cache/etf_daily"
                headers = {'Content-Type': 'application/json'}
                if api_key:
                    headers['X-API-Key'] = api_key
                
                try:
                    response = requests.post(url, json=data_payload, headers=headers, timeout=30)
                    if response.status_code == 200:
                        success_count += 1
                    else:
                        failed_dates.append(date)
                except Exception as e:
                    failed_dates.append(date)
            
            return {
                'success': success_count > 0,
                'message': f'Saved {success_count}/{len(dates)} days of data',
                'data': {
                    'symbol': symbol,
                    'data_type': data_type,
                    'dates_saved': [d for d in dates if d not in failed_dates],
                    'failed_dates': failed_dates,
                    'rows': len(df)
                }
            }
        
        elif data_type == "minute":
            # 分钟数据：直接替换当天数据
            data_payload = {
                'symbol': symbol,
                'period': period,
                'date': end_date,
                'data': {
                    'df': df.to_dict('records'),
                    'columns': df.columns.tolist(),
                    'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()}
                }
            }
            
            url = f"{api_base_url}/api/cache/etf_minute"
            headers = {'Content-Type': 'application/json'}
            if api_key:
                headers['X-API-Key'] = api_key
            
            response = requests.post(url, json=data_payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return {
                    'success': True,
                    'message': 'Successfully saved minute data',
                    'data': {
                        'symbol': symbol,
                        'period': period,
                        'date': end_date,
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
            return {
                'success': False,
                'message': f'Unsupported data_type: {data_type}',
                'data': None
            }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_fetch_etf_daily(
    symbol: str = "510300",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5
) -> Dict[str, Any]:
    """OpenClaw 工具：采集ETF日线数据"""
    return fetch_etf_data(
        symbol=symbol,
        data_type="daily",
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days
    )


def tool_fetch_etf_minute(
    symbol: str = "510300",
    period: str = "5",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    lookback_days: int = 5
) -> Dict[str, Any]:
    """OpenClaw 工具：采集ETF分钟数据"""
    return fetch_etf_data(
        symbol=symbol,
        data_type="minute",
        period=period,
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days
    )
