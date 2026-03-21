"""
交易日判断工具
从config.yaml读取节假日配置，判断是否是交易日
"""

import os
import sys
import yaml
from typing import Optional, Set, Dict, Any
from datetime import datetime
import pytz
from pathlib import Path


def load_config_holidays(config_path: Optional[str] = None) -> Set[str]:
    """
    从config.yaml加载节假日配置
    
    Args:
        config_path: config.yaml路径，如果为None则自动查找
    
    Returns:
        Set[str]: 节假日日期集合（格式：YYYYMMDD字符串）
    """
    holidays_set = set()
    
    try:
        # 尝试多个可能的 config.yaml 路径（优先使用项目目录）
        if config_path is None:
            possible_paths = [
                os.path.join(os.path.dirname(__file__), "../../../config.yaml"),
                os.path.join(os.path.dirname(__file__), "../../../../config.yaml"),
                "config.yaml"
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    config_path = path
                    break
        
        if config_path is None or not os.path.exists(config_path):
            # 如果找不到配置文件，返回空集合
            return holidays_set
        
        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 获取节假日配置
        trading_hours = config.get('system', {}).get('trading_hours', {})
        holidays_config = trading_hours.get('holidays', {})
        
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
        
    except Exception as e:
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
