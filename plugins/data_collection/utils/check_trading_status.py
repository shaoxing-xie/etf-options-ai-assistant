"""
判断交易时间状态
融合 Coze 插件 check_trading_status.py
OpenClaw 插件工具
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, time, timedelta
import os
import json
import pytz


def check_trading_status(
    timezone: str = "Asia/Shanghai",
    morning_start: str = "09:30",
    morning_end: str = "11:30",
    afternoon_start: str = "13:00",
    afternoon_end: str = "15:00",
    holidays: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    判断当前是否是交易时间，返回市场状态信息
    融合 Coze check_trading_status.py
    
    Args:
        timezone: 时区，默认 "Asia/Shanghai"
        morning_start: 上午开盘时间，默认 "09:30"
        morning_end: 上午收盘时间，默认 "11:30"
        afternoon_start: 下午开盘时间，默认 "13:00"
        afternoon_end: 下午收盘时间，默认 "15:00"
        holidays: 节假日列表（格式：YYYYMMDD），如果为None则从环境变量获取
    
    Returns:
        Dict: 包含市场状态信息的字典
    """
    try:
        # 获取节假日列表（从环境变量或参数）
        if holidays is None:
            holidays_str = os.getenv("TRADING_HOURS_HOLIDAYS_2026", "[]")
            try:
                holidays = json.loads(holidays_str) if holidays_str else []
            except:
                holidays = []
        
        # 获取当前时间
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)
        current_time = now.time()
        
        # 解析交易时间
        morning_start_time = time.fromisoformat(morning_start)
        morning_end_time = time.fromisoformat(morning_end)
        afternoon_start_time = time.fromisoformat(afternoon_start)
        afternoon_end_time = time.fromisoformat(afternoon_end)
        
        # 判断是否是交易日
        weekday = now.weekday()  # 0=Monday, 6=Sunday
        is_weekday = weekday < 5
        
        # 检查是否是节假日
        date_str = now.strftime("%Y%m%d")
        is_holiday = date_str in holidays
        
        is_trading_day_flag = is_weekday and not is_holiday
        
        # 状态映射（中文）
        status_map = {
            'before_open': '开盘前',
            'trading': '交易中',
            'lunch_break': '午休',
            'after_close': '收盘后',
            'non_trading_day': '非交易日'
        }
        
        # 判断市场状态
        if not is_trading_day_flag:
            status = 'non_trading_day'
            is_trading_time = False
            next_trading_time = None
            remaining_minutes = 0
        elif current_time < morning_start_time:
            status = 'before_open'
            is_trading_time = False
            next_time = datetime.combine(now.date(), morning_start_time)
            next_time = tz.localize(next_time)
            next_trading_time = next_time.strftime('%Y-%m-%d %H:%M:%S')
            remaining = (next_time - now).total_seconds() / 60
            remaining_minutes = int(remaining)
        elif morning_start_time <= current_time <= morning_end_time:
            status = 'trading'
            is_trading_time = True
            next_time = datetime.combine(now.date(), afternoon_start_time)
            next_time = tz.localize(next_time)
            next_trading_time = next_time.strftime('%Y-%m-%d %H:%M:%S')
            remaining = (afternoon_end_time.hour * 60 + afternoon_end_time.minute) - (current_time.hour * 60 + current_time.minute)
            remaining_minutes = max(0, int(remaining))
        elif morning_end_time < current_time < afternoon_start_time:
            status = 'lunch_break'
            is_trading_time = False
            next_time = datetime.combine(now.date(), afternoon_start_time)
            next_time = tz.localize(next_time)
            next_trading_time = next_time.strftime('%Y-%m-%d %H:%M:%S')
            remaining = (next_time - now).total_seconds() / 60
            remaining_minutes = int(remaining)
        elif afternoon_start_time <= current_time <= afternoon_end_time:
            status = 'trading'
            is_trading_time = True
            next_time = datetime.combine(now.date(), afternoon_end_time)
            next_time = tz.localize(next_time)
            next_trading_time = next_time.strftime('%Y-%m-%d %H:%M:%S')
            remaining = (afternoon_end_time.hour * 60 + afternoon_end_time.minute) - (current_time.hour * 60 + current_time.minute)
            remaining_minutes = max(0, int(remaining))
        else:
            status = 'after_close'
            is_trading_time = False
            # 计算下一个交易日
            next_trading_day = now
            max_days = 7
            days_checked = 0
            while days_checked < max_days:
                next_trading_day += timedelta(days=1)
                days_checked += 1
                next_weekday = next_trading_day.weekday()
                next_date_str = next_trading_day.strftime("%Y%m%d")
                if next_weekday < 5 and next_date_str not in holidays:
                    break
            next_time = datetime.combine(next_trading_day.date(), morning_start_time)
            next_time = tz.localize(next_time)
            next_trading_time = next_time.strftime('%Y-%m-%d %H:%M:%S')
            remaining = (next_time - now).total_seconds() / 60
            remaining_minutes = int(remaining)
        
        market_status_cn = status_map.get(status, status)
        
        # 构建返回结果
        result = {
            "success": True,
            "data": {
                "status": status,
                "market_status_cn": market_status_cn,
                "is_trading_time": is_trading_time,
                "is_trading_day": is_trading_day_flag,
                "current_time": now.strftime('%Y-%m-%d %H:%M:%S'),
                "next_trading_time": next_trading_time,
                "remaining_minutes": remaining_minutes,
                "timezone": timezone
            }
        }
        
        return result
    
    except Exception as e:
        return {
            "success": False,
            "message": f"判断交易时间状态失败: {str(e)}",
            "data": None
        }


# OpenClaw 工具函数接口
def tool_check_trading_status() -> Dict[str, Any]:
    """OpenClaw 工具：判断交易时间状态"""
    return check_trading_status()
