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

        # Agent 门禁：连续竞价未进行时，禁止把行情接口返回值叙述成「已开盘/盘中实况」
        a_share_continuous_bidding_active = bool(is_trading_time and status == "trading")
        if not is_trading_day_flag:
            quote_narration_rule_cn = (
                "非交易日：A 股连续竞价未进行。指数/ETF「实时」类接口多返回上一交易日收盘或空数据。"
                "禁止写「市场已开盘」「今日开盘实况」「今开/最高/最低/盘中」等连续竞价表述；"
                "若需展望下一交易日，须明确为预测并标注数据为历史收盘。"
            )
        elif status == "before_open":
            quote_narration_rule_cn = (
                "开盘前（距 09:30 连续竞价尚未开始）：禁止写「市场已开盘」「今日实时行情」「今日开盘实况」"
                "「今开/最高/最低」「盘中上冲/回落」等。仅允许：① 对当日开盘/走势的**预测**；"
                "② 引用**上一交易日收盘**或工具明确标注的盘前静态价，并写明「昨收/数据日期」。"
                "用户若指出数据为上周五或昨收，必须采纳，不得再断言已开盘。"
            )
        elif status == "lunch_break":
            quote_narration_rule_cn = (
                "午休：上午已收市、下午未开盘。禁止编造下午盘中走势；勿将上午数据说成「当前盘中」。"
            )
        elif status == "after_close":
            quote_narration_rule_cn = (
                "收盘后：连续竞价已结束。禁止将收盘数据叙述为「当前盘中」；可复盘或预测次日。"
            )
        else:
            quote_narration_rule_cn = (
                "连续竞价时段：可使用盘中表述，但仍须标注数据时间与来源，并注意接口延迟。"
            )

        # 构建返回结果
        result = {
            "success": True,
            "data": {
                "status": status,
                "market_status_cn": market_status_cn,
                "is_trading_time": is_trading_time,
                "is_trading_day": is_trading_day_flag,
                "a_share_continuous_bidding_active": a_share_continuous_bidding_active,
                "allows_intraday_continuous_wording": a_share_continuous_bidding_active,
                "quote_narration_rule_cn": quote_narration_rule_cn,
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
