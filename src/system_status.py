"""
系统状态模块
判断交易时间、市场状态，处理系统启动时的错过任务
"""

import pytz
from datetime import datetime, time, timedelta
from typing import Dict, Optional, List
import calendar

from src.logger_config import get_module_logger, log_error_with_context
from src.config_loader import load_system_config, get_trading_hours_config

logger = get_module_logger(__name__)


def is_trading_day(date: Optional[datetime] = None, config: Optional[Dict] = None) -> bool:
    """
    判断是否是交易日（考虑周末和节假日）
    
    Args:
        date: 日期，如果为None则使用当前日期
        config: 系统配置，如果为None则自动加载
    
    Returns:
        bool: 是否是交易日
    """
    try:
        if date is None:
            date = datetime.now(pytz.timezone('Asia/Shanghai'))
        
        # 简单判断：周一到周五（0=Monday, 6=Sunday）
        weekday = date.weekday()
        weekday_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][weekday]
        is_weekday = weekday < 5
        
        if not is_weekday:
            logger.debug(f"日期判断: {date.strftime('%Y-%m-%d')} ({weekday_name}) 是周末，非交易日")
            return False
        
        # 检查是否是节假日
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        from src.config_loader import get_holidays_config
        holidays = get_holidays_config(config)
        
        date_str = date.strftime('%Y%m%d')
        if date_str in holidays:
            logger.debug(f"日期判断: {date.strftime('%Y-%m-%d')} ({weekday_name}) 是节假日，非交易日")
            return False
        
        logger.debug(f"日期判断: {date.strftime('%Y-%m-%d')} ({weekday_name}) 是交易日")
        return True
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'is_trading_day', 'date': date},
            "判断交易日失败"
        )
        # 默认返回True，避免影响系统运行
        return True


def get_current_market_status(config: Optional[Dict] = None) -> Dict[str, any]:
    """
    获取当前市场状态
    
    Args:
        config: 系统配置，如果为None则自动加载
    
    Returns:
        dict: {
            'status': 'before_open' | 'trading' | 'lunch_break' | 'after_close' | 'non_trading_day',
            'is_trading_time': bool,
            'current_time': str,
            'next_trading_time': str,
            'remaining_minutes': int
        }
    """
    try:
        if config is None:
            config = load_system_config()
        
        trading_hours = get_trading_hours_config(config)
        timezone_str = trading_hours.get('timezone', 'Asia/Shanghai')
        tz = pytz.timezone(timezone_str)
        
        now = datetime.now(tz)
        current_time = now.time()
        
        morning_start = time.fromisoformat(trading_hours.get('morning_start', '09:30'))
        morning_end = time.fromisoformat(trading_hours.get('morning_end', '11:30'))
        afternoon_start = time.fromisoformat(trading_hours.get('afternoon_start', '13:00'))
        afternoon_end = time.fromisoformat(trading_hours.get('afternoon_end', '15:00'))
        
        # 判断是否是交易日
        if not is_trading_day(now, config):
            return {
                'status': 'non_trading_day',
                'is_trading_time': False,
                'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'next_trading_time': None,
                'remaining_minutes': 0
            }
        
        # 判断市场状态
        if current_time < morning_start:
            # 开盘前
            next_time = tz.localize(datetime.combine(now.date(), morning_start))
            remaining = (next_time - now).total_seconds() / 60
            return {
                'status': 'before_open',
                'is_trading_time': False,
                'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'next_trading_time': next_time.strftime('%Y-%m-%d %H:%M:%S'),
                'remaining_minutes': int(remaining)
            }
        elif morning_start <= current_time <= morning_end:
            # 上午交易时间
            next_time = tz.localize(datetime.combine(now.date(), afternoon_start))
            remaining = (next_time - now).total_seconds() / 60
            return {
                'status': 'trading',
                'is_trading_time': True,
                'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'next_trading_time': next_time.strftime('%Y-%m-%d %H:%M:%S'),
                'remaining_minutes': int(remaining)
            }
        elif morning_end < current_time < afternoon_start:
            # 午休时间
            next_time = tz.localize(datetime.combine(now.date(), afternoon_start))
            remaining = (next_time - now).total_seconds() / 60
            return {
                'status': 'lunch_break',
                'is_trading_time': False,
                'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'next_trading_time': next_time.strftime('%Y-%m-%d %H:%M:%S'),
                'remaining_minutes': int(remaining)
            }
        elif afternoon_start <= current_time <= afternoon_end:
            # 下午交易时间
            next_time = tz.localize(datetime.combine(now.date(), afternoon_end))
            remaining = (next_time - now).total_seconds() / 60
            return {
                'status': 'trading',
                'is_trading_time': True,
                'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'next_trading_time': next_time.strftime('%Y-%m-%d %H:%M:%S'),
                'remaining_minutes': int(remaining)
            }
        else:
            # 收盘后
            # 计算下一个交易日的开盘时间
            next_trading_day = now
            while True:
                next_trading_day += timedelta(days=1)
                if is_trading_day(next_trading_day, config):
                    break
            next_time = tz.localize(datetime.combine(next_trading_day.date(), morning_start))
            remaining = (next_time - now).total_seconds() / 60
            return {
                'status': 'after_close',
                'is_trading_time': False,
                'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                'next_trading_time': next_time.strftime('%Y-%m-%d %H:%M:%S'),
                'remaining_minutes': int(remaining)
            }
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'get_current_market_status'},
            "获取市场状态失败"
        )
        # 返回默认状态
        return {
            'status': 'unknown',
            'is_trading_time': False,
            'current_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'next_trading_time': None,
            'remaining_minutes': 0
        }


def check_task_executed(task_name: str, date_str: str, config: Dict) -> bool:
    """
    检查任务是否已经执行过
    
    Args:
        task_name: 任务名称 ('after_close_analysis', 'before_open_analysis', 'first_intraday_analysis')
        date_str: 日期字符串 (YYYYMMDD)
        config: 系统配置
    
    Returns:
        bool: 是否已执行
    """
    try:
        from pathlib import Path
        from src.data_storage import get_data_storage_config
        
        data_storage_config = get_data_storage_config(config)
        data_dir = Path(data_storage_config.get('data_dir', 'data'))
        
        if task_name == 'after_close_analysis':
            # 检查盘后分析文件
            trend_dir = data_dir / 'trend_analysis' / 'after_close'
            file_path = trend_dir / f"{date_str}.json"
            if file_path.exists():
                logger.debug(f"盘后分析任务已执行: {file_path}")
                return True
        
        elif task_name == 'before_open_analysis':
            # 检查开盘前分析文件
            trend_dir = data_dir / 'trend_analysis' / 'before_open'
            file_path = trend_dir / f"{date_str}.json"
            if file_path.exists():
                logger.debug(f"开盘前分析任务已执行: {file_path}")
                return True
        
        elif task_name == 'opening_market_analysis':
            # 检查开盘分析文件
            opening_dir = data_dir / 'opening_analysis'
            file_path = opening_dir / f"{date_str}.json"
            if file_path.exists():
                logger.debug(f"开盘行情分析任务已执行: {file_path}")
                return True
        
        elif task_name == 'first_intraday_analysis':
            # 检查波动区间文件，看是否有9:35附近的数据
            volatility_dir = data_dir / 'volatility_ranges'
            file_path = volatility_dir / f"{date_str}.json"
            if file_path.exists():
                try:
                    import json
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # 检查是否有数据，并且第一个记录的时间戳是否在9:35附近（9:30-9:40）
                    if isinstance(data, list) and len(data) > 0:
                        first_record = data[0]
                        timestamp_str = first_record.get('timestamp', '')
                        if timestamp_str:
                            # 解析时间戳
                            record_time = datetime.strptime(timestamp_str.split(' ')[1], '%H:%M:%S').time()
                            target_time = time(9, 35)
                            # 允许前后5分钟的误差
                            time_diff = abs((datetime.combine(datetime.today(), record_time) - 
                                           datetime.combine(datetime.today(), target_time)).total_seconds() / 60)
                            if time_diff <= 5:
                                logger.debug(f"第一次日内趋势处理任务已执行: {file_path} (时间: {timestamp_str})")
                                return True
                    elif isinstance(data, dict):
                        # 单个记录格式
                        timestamp_str = data.get('timestamp', '')
                        if timestamp_str:
                            record_time = datetime.strptime(timestamp_str.split(' ')[1], '%H:%M:%S').time()
                            target_time = time(9, 35)
                            time_diff = abs((datetime.combine(datetime.today(), record_time) - 
                                           datetime.combine(datetime.today(), target_time)).total_seconds() / 60)
                            if time_diff <= 5:
                                logger.debug(f"第一次日内趋势处理任务已执行: {file_path} (时间: {timestamp_str})")
                                return True
                except Exception as e:
                    logger.debug(f"检查波动区间文件时出错: {str(e)}")
        
        return False
        
    except Exception as e:
        logger.debug(f"检查任务执行状态时出错: {str(e)}")
        return False


def check_and_execute_missed_tasks(config: Optional[Dict] = None) -> List[str]:
    """
    检查并执行错过的任务（系统启动时调用）
    会检查任务是否已经执行过，只返回未执行的任务
    
    Args:
        config: 系统配置，如果为None则自动加载
    
    Returns:
        list: 需要补执行的任务列表
    """
    try:
        if config is None:
            config = load_system_config()
        
        missed_tasks = []
        tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz)
        today_str = now.strftime("%Y%m%d")
        
        # 只处理交易日
        if not is_trading_day(now, config):
            logger.info("非交易日，跳过错过任务检查")
            return missed_tasks
        
        scheduler_config = config.get('system', {}).get('scheduler', {})
        
        # 检查9:15开盘前分析任务
        before_open_config = scheduler_config.get('before_open_analysis', {})
        if before_open_config.get('enabled', True):
            target_hour = before_open_config.get('hour', 9)
            target_minute = before_open_config.get('minute', 15)
            target_time = datetime.combine(now.date(), time(target_hour, target_minute))
            target_time = tz.localize(target_time)
            
            if now > target_time:
                # 已经过了目标时间，检查是否执行过
                if not check_task_executed('before_open_analysis', today_str, config):
                    logger.info(f"检测到错过任务: 开盘前分析 (目标时间: {target_time.strftime('%H:%M')}, 当前时间: {now.strftime('%H:%M')})")
                    missed_tasks.append('before_open_analysis')
                else:
                    logger.debug(f"开盘前分析任务已执行，跳过")
        
        # 检查9:28开盘行情分析
        opening_config = config.get('opening_analysis', {})
        opening_scheduler = opening_config.get('scheduler', {})
        if opening_scheduler.get('enabled', True):
            target_hour = opening_scheduler.get('hour', 9)
            target_minute = opening_scheduler.get('minute', 28)
            target_time = datetime.combine(now.date(), time(target_hour, target_minute))
            target_time = tz.localize(target_time)
            
            if now > target_time:
                # 已经过了目标时间，检查是否执行过
                if not check_task_executed('opening_market_analysis', today_str, config):
                    logger.info(f"检测到错过任务: 开盘行情分析 (目标时间: {target_time.strftime('%H:%M')}, 当前时间: {now.strftime('%H:%M')})")
                    missed_tasks.append('opening_market_analysis')
                else:
                    logger.debug(f"开盘行情分析任务已执行，跳过")
        
        # 检查9:35第一次日内趋势处理
        first_intraday_config = scheduler_config.get('first_intraday_analysis', {})
        if first_intraday_config.get('enabled', True):
            target_hour = first_intraday_config.get('hour', 9)
            target_minute = first_intraday_config.get('minute', 35)
            target_time = datetime.combine(now.date(), time(target_hour, target_minute))
            target_time = tz.localize(target_time)
            
            if now > target_time:
                # 已经过了目标时间，检查是否执行过
                if not check_task_executed('first_intraday_analysis', today_str, config):
                    logger.info(f"检测到错过任务: 第一次日内趋势处理 (目标时间: {target_time.strftime('%H:%M')}, 当前时间: {now.strftime('%H:%M')})")
                    missed_tasks.append('first_intraday_analysis')
                else:
                    logger.debug(f"第一次日内趋势处理任务已执行，跳过")
        
        # 检查15:30盘后分析（如果是当天）
        after_close_config = scheduler_config.get('after_close_analysis', {})
        if after_close_config.get('enabled', True):
            target_hour = after_close_config.get('hour', 15)
            target_minute = after_close_config.get('minute', 30)
            target_time = datetime.combine(now.date(), time(target_hour, target_minute))
            target_time = tz.localize(target_time)
            
            # 如果当前时间在15:30之后，但还在同一天，可能需要执行
            if now > target_time and now.date() == target_time.date():
                if not check_task_executed('after_close_analysis', today_str, config):
                    logger.info(f"检测到错过任务: 盘后分析 (目标时间: {target_time.strftime('%H:%M')}, 当前时间: {now.strftime('%H:%M')})")
                    missed_tasks.append('after_close_analysis')
                else:
                    logger.debug(f"盘后分析任务已执行，跳过")
        
        if missed_tasks:
            logger.info(f"发现 {len(missed_tasks)} 个需要补执行的任务: {', '.join(missed_tasks)}")
        else:
            logger.info("未发现需要补执行的任务（所有任务均已执行）")
        
        return missed_tasks
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'check_and_execute_missed_tasks'},
            "检查错过任务失败"
        )
        return []


def system_startup(config: Optional[Dict] = None) -> Dict[str, any]:
    """
    系统启动初始化逻辑
    
    Args:
        config: 系统配置，如果为None则自动加载
    
    Returns:
        dict: {
            'startup_time': str,
            'market_status': dict,
            'missed_tasks': list,
            'should_execute_immediate': bool
        }
    """
    try:
        logger.info("=" * 60)
        logger.info("系统启动初始化")
        logger.info("=" * 60)
        
        if config is None:
            config = load_system_config()
        
        tz = pytz.timezone('Asia/Shanghai')
        startup_time = datetime.now(tz)
        
        # 获取市场状态
        market_status = get_current_market_status(config)
        logger.info(f"当前市场状态: {market_status['status']}")
        logger.info(f"是否交易时间: {market_status['is_trading_time']}")
        
        # 检查错过任务
        missed_tasks = check_and_execute_missed_tasks(config)
        
        # 判断是否需要立即执行任务
        should_execute_immediate = False
        if market_status['is_trading_time']:
            # 如果在交易时间内，立即执行一次波动区间预测和信号生成
            should_execute_immediate = True
            logger.info("当前处于交易时间，将立即执行波动区间预测和信号生成")
        
        result = {
            'startup_time': startup_time.strftime('%Y-%m-%d %H:%M:%S'),
            'market_status': market_status,
            'missed_tasks': missed_tasks,
            'should_execute_immediate': should_execute_immediate
        }
        
        logger.info("系统启动初始化完成")
        logger.info("=" * 60)
        
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'system_startup'},
            "系统启动初始化失败"
        )
        return {
            'startup_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'market_status': {'status': 'unknown'},
            'missed_tasks': [],
            'should_execute_immediate': False
        }
