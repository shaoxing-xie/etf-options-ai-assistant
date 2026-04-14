"""
交易日判断工具
从分层系统配置（load_system_config）读取节假日，判断是否是交易日。
"""

import os
import yaml
from typing import Optional, Set, Dict, Any
from datetime import datetime
import pytz


def load_config_holidays(config_path: Optional[str] = None) -> Set[str]:
    """
    加载节假日配置（YYYYMMDD 字符串集合）。

    Args:
        config_path: 若为 None，使用 ``load_system_config``；否则从该 YAML 文件读取（测试或自定义路径）。

    Returns:
        Set[str]: 节假日日期集合（格式：YYYYMMDD字符串）
    """
    holidays_set = set()

    try:
        if config_path is None:
            from src.config_loader import get_holidays_config, load_system_config

            return get_holidays_config(load_system_config(use_cache=True))

        if not os.path.exists(config_path):
            return holidays_set

        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            return holidays_set

        trading_hours = config.get("system", {}).get("trading_hours", {})
        holidays_config = trading_hours.get("holidays", {})
        
        # 支持按年份组织：holidays: {2026: [...]}
        if isinstance(holidays_config, dict):
            for year, dates in holidays_config.items():
                if isinstance(dates, list):
                    for date in dates:
                        if isinstance(date, str) and len(date) == 8 and date.isdigit():
                            holidays_set.add(date)
        
        # 也支持扁平列表：holidays: [...]
        elif isinstance(holidays_config, list):
            for date in holidays_config:
                if isinstance(date, str) and len(date) == 8 and date.isdigit():
                    holidays_set.add(date)
        
    except Exception:
        # 读取失败，返回空集合
        pass
    
    return holidays_set


def is_trading_day(date: Optional[datetime] = None, config_path: Optional[str] = None) -> bool:
    """
    判断是否是交易日（考虑周末和节假日）
    
    Args:
        date: 日期，如果为None则使用当前日期
        config_path: config.yaml路径，如果为None则自动查找
    
    Returns:
        bool: 是否是交易日
    """
    try:
        if date is None:
            date = datetime.now(pytz.timezone('Asia/Shanghai'))
        
        # 判断是否是工作日（周一到周五）
        weekday = date.weekday()  # 0=Monday, 6=Sunday
        is_weekday = weekday < 5
        
        if not is_weekday:
            return False
        
        # 检查是否是节假日
        holidays = load_config_holidays(config_path)
        date_str = date.strftime('%Y%m%d')
        
        if date_str in holidays:
            return False
        
        return True
        
    except Exception:
        # 异常情况下，默认返回True，避免影响系统运行
        return True


def check_trading_day_before_operation(operation_name: str = "操作", config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    在执行操作前检查是否是交易日
    
    Args:
        operation_name: 操作名称，用于错误提示
        config_path: config.yaml路径
    
    Returns:
        Optional[Dict]: 如果是非交易日，返回错误信息；如果是交易日，返回None
    """
    try:
        now = datetime.now(pytz.timezone('Asia/Shanghai'))
        date_str = now.strftime('%Y-%m-%d')
        
        if not is_trading_day(now, config_path):
            # 判断是周末还是节假日
            weekday = now.weekday()
            weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            weekday_name = weekday_names[weekday]
            
            holidays = load_config_holidays(config_path)
            is_holiday = date_str.replace('-', '') in holidays
            
            if is_holiday:
                reason = "节假日"
            else:
                reason = "周末"
            
            return {
                'success': False,
                'message': f'{operation_name}失败：{date_str} ({weekday_name}) 是{reason}，非交易日',
                'data': None,
                'is_trading_day': False,
                'date': date_str,
                'reason': reason
            }
        
        return None
        
    except Exception:
        # 异常情况下，不阻止操作
        return None
