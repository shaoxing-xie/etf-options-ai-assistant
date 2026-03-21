"""
数据存储模块
保存波动区间、趋势分析、信号等数据到文件
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any, List

from src.logger_config import get_module_logger, log_error_with_context
from src.config_loader import load_system_config, get_data_storage_config

logger = get_module_logger(__name__)


def save_volatility_ranges(
    volatility_ranges: Dict[str, Any],
    config: Optional[Dict] = None
) -> bool:
    """
    保存波动区间数据到文件
    
    Args:
        volatility_ranges: 波动区间数据
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if config is None:
            config = load_system_config()
        
        storage_config = get_data_storage_config(config)
        volatility_config = storage_config.get('volatility_ranges', {})
        
        if not volatility_config.get('enabled', True):
            logger.debug("波动区间存储已禁用")
            return False
        
        # 获取存储目录
        volatility_dir = volatility_config.get('dir', 'volatility_ranges')
        # 如果 volatility_dir 已经包含 data/ 前缀，直接使用；否则拼接 data_dir
        if volatility_dir.startswith('data/'):
            storage_path = Path(volatility_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / volatility_dir
        storage_path.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名（按日期）
        today = datetime.now().strftime('%Y%m%d')
        file_format = volatility_config.get('file_format', 'json')
        
        if file_format == 'json':
            file_path = storage_path / f"{today}.json"
            
            # 读取现有数据（如果存在）
            existing_data = []
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except Exception as e:
                    logger.warning(f"读取现有波动区间数据失败: {file_path} | 错误: {str(e)}")
            
            # 确保数据包含时间戳和日期（如果缺失）
            if 'timestamp' not in volatility_ranges:
                volatility_ranges['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if 'date' not in volatility_ranges:
                volatility_ranges['date'] = today
            
            # 提取并保存关键信息用于后续分析
            # 支持多个合约格式（新格式）和单个合约格式（向后兼容）
            enhanced_data = volatility_ranges.copy()
            
            # 支持多标的物格式
            underlyings_data = volatility_ranges.get('underlyings', {})
            
            if underlyings_data:
                # 新格式：多标的物
                enhanced_data['underlyings'] = {}
                for underlying, underlying_data in underlyings_data.items():
                    enhanced_data['underlyings'][underlying] = {
                        'etf_range': underlying_data.get('etf_range'),
                        'call_ranges': underlying_data.get('call_ranges', []),
                        'put_ranges': underlying_data.get('put_ranges', []),
                    }
            
            # 向后兼容：单个标的物格式
            # 新格式：多个合约列表
            call_ranges = volatility_ranges.get('call_ranges', [])
            put_ranges = volatility_ranges.get('put_ranges', [])
            
            
            # 提取所有Call合约的关键信息
            if call_ranges:
                enhanced_data['call_contracts'] = []
                for i, call_range in enumerate(call_ranges):
                    contract_info = {
                        'contract_code': call_range.get('contract_code'),
                        'underlying': call_range.get('underlying'),
                        'name': call_range.get('name', call_range.get('contract_code', f'Call{i+1}')),
                        'current_price': call_range.get('current_price'),
                        'iv': call_range.get('iv'),
                        'strike_price': call_range.get('strike_price'),
                        'expiry_date': call_range.get('expiry_date'),
                        'upper': call_range.get('upper'),
                        'lower': call_range.get('lower'),
                        'range_pct': call_range.get('range_pct')
                    }
                    enhanced_data['call_contracts'].append(contract_info)
                
                # 向后兼容：第一个合约的字段
                first_call = call_ranges[0]
                enhanced_data['call_current_price'] = first_call.get('current_price')
                enhanced_data['call_iv'] = first_call.get('iv')
                enhanced_data['call_strike'] = first_call.get('strike_price')
                enhanced_data['call_contract_code'] = first_call.get('contract_code')
            
            # 提取所有Put合约的关键信息
            if put_ranges:
                enhanced_data['put_contracts'] = []
                for i, put_range in enumerate(put_ranges):
                    contract_info = {
                        'contract_code': put_range.get('contract_code'),
                        'underlying': put_range.get('underlying'),
                        'name': put_range.get('name', put_range.get('contract_code', f'Put{i+1}')),
                        'current_price': put_range.get('current_price'),
                        'iv': put_range.get('iv'),
                        'strike_price': put_range.get('strike_price'),
                        'expiry_date': put_range.get('expiry_date'),
                        'upper': put_range.get('upper'),
                        'lower': put_range.get('lower'),
                        'range_pct': put_range.get('range_pct')
                    }
                    enhanced_data['put_contracts'].append(contract_info)
                
                # 向后兼容：第一个合约的字段
                first_put = put_ranges[0]
                enhanced_data['put_current_price'] = first_put.get('current_price')
                enhanced_data['put_iv'] = first_put.get('iv')
                enhanced_data['put_strike'] = first_put.get('strike_price')
                enhanced_data['put_contract_code'] = first_put.get('contract_code')
            
            # 提取ETF价格
            etf_range = volatility_ranges.get('etf_range')
            if etf_range:
                enhanced_data['etf_price'] = etf_range.get('current_price')
            
            # 添加新数据
            existing_data.append(enhanced_data)
            
            # 保存
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"波动区间数据已保存: {file_path} (共 {len(existing_data)} 条记录)")
            return True
        else:
            logger.warning(f"不支持的文件格式: {file_format}")
            return False
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_volatility_ranges'},
            "保存波动区间数据失败"
        )
        return False


def load_volatility_ranges(
    date: Optional[str] = None,
    config: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    """
    加载波动区间数据
    
    Args:
        date: 日期 YYYYMMDD，如果为None则使用今天
        config: 系统配置
    
    Returns:
        list: 波动区间数据列表
    """
    try:
        if config is None:
            config = load_system_config()
        
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        
        storage_config = get_data_storage_config(config)
        volatility_config = storage_config.get('volatility_ranges', {})
        volatility_dir = volatility_config.get('dir', 'volatility_ranges')
        # 如果 volatility_dir 已经包含 data/ 前缀，直接使用；否则拼接 data_dir
        if volatility_dir.startswith('data/'):
            storage_path = Path(volatility_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / volatility_dir
        
        file_path = storage_path / f"{date}.json"
        
        if not file_path.exists():
            logger.debug(f"波动区间数据文件不存在: {file_path}")
            return []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 只在DEBUG级别输出，避免重复日志（回测时会加载大量数据）
        logger.debug(f"加载波动区间数据: {file_path}, 共 {len(data)} 条记录")
        
        return data
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'load_volatility_ranges', 'date': date},
            "加载波动区间数据失败"
        )
        return []


def save_trend_analysis(
    analysis_data: Dict[str, Any],
    analysis_type: str = 'after_close',
    config: Optional[Dict] = None
) -> bool:
    """
    保存趋势分析数据
    
    Args:
        analysis_data: 分析数据
        analysis_type: 'after_close' 或 'before_open'
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if config is None:
            config = load_system_config()
        
        storage_config = get_data_storage_config(config)
        trend_config = storage_config.get('trend_analysis', {})
        
        if not trend_config.get('enabled', True):
            logger.debug("趋势分析存储已禁用")
            return False
        
        # 获取存储目录
        if analysis_type == 'after_close':
            trend_dir = trend_config.get('after_close_dir', 'trend_analysis/after_close')
        else:
            trend_dir = trend_config.get('before_open_dir', 'trend_analysis/before_open')
        
        # 如果 trend_dir 已经包含 data/ 前缀，直接使用；否则拼接 data_dir
        if trend_dir.startswith('data/'):
            storage_path = Path(trend_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / trend_dir
        storage_path.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名（按日期）
        date = analysis_data.get('date', datetime.now().strftime('%Y%m%d'))
        file_path = storage_path / f"{date}.json"
        
        # 保存
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"趋势分析数据已保存: {file_path}")
        return True
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_trend_analysis', 'analysis_type': analysis_type},
            "保存趋势分析数据失败"
        )
        return False


def load_trend_analysis(
    date: Optional[str] = None,
    analysis_type: str = 'after_close',
    config: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    加载趋势分析数据
    
    Args:
        date: 日期 YYYYMMDD，如果为None则使用今天
        analysis_type: 'after_close' 或 'before_open'
        config: 系统配置
    
    Returns:
        dict: 分析数据，如果不存在返回None
    """
    try:
        if config is None:
            config = load_system_config()
        
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        
        storage_config = get_data_storage_config(config)
        trend_config = storage_config.get('trend_analysis', {})
        
        if analysis_type == 'after_close':
            trend_dir = trend_config.get('after_close_dir', 'trend_analysis/after_close')
        else:
            trend_dir = trend_config.get('before_open_dir', 'trend_analysis/before_open')
        
        # 如果 trend_dir 已经包含 data/ 前缀，直接使用；否则拼接 data_dir
        if trend_dir.startswith('data/'):
            storage_path = Path(trend_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / trend_dir
        file_path = storage_path / f"{date}.json"
        
        if not file_path.exists():
            logger.debug(f"趋势分析数据文件不存在: {file_path}")
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"加载趋势分析数据: {file_path}")
        return data
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'load_trend_analysis', 'date': date, 'analysis_type': analysis_type},
            "加载趋势分析数据失败"
        )
        return None


def save_signal(
    signal: Dict[str, Any],
    config: Optional[Dict] = None
) -> bool:
    """
    保存信号数据
    
    Args:
        signal: 信号数据
        config: 系统配置
    
    Returns:
        bool: 是否保存成功
    """
    try:
        if config is None:
            config = load_system_config()
        
        storage_config = get_data_storage_config(config)
        signals_config = storage_config.get('signals', {})
        
        if not signals_config.get('enabled', True):
            logger.debug("信号存储已禁用")
            return False
        
        # 获取存储目录
        signals_dir = signals_config.get('dir', 'signals')
        # 如果 signals_dir 已经包含 data/ 前缀，直接使用；否则拼接 data_dir
        if signals_dir.startswith('data/'):
            storage_path = Path(signals_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / signals_dir
        storage_path.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名（按日期）
        today = datetime.now().strftime('%Y%m%d')
        file_path = storage_path / f"{today}.json"
        
        # 读取现有数据（如果存在）
        existing_data = []
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except Exception as e:
                logger.warning(f"读取现有信号数据失败: {file_path} | 错误: {str(e)}")
        
        # 添加新信号
        existing_data.append(signal)
        
        # 保存
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"信号数据已保存: {file_path}")
        return True
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_signal'},
            "保存信号数据失败"
        )
        return False


def load_signals(
    date: Optional[str] = None,
    config: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    """
    加载信号数据
    
    Args:
        date: 日期 YYYYMMDD，如果为None则使用今天
        config: 系统配置
    
    Returns:
        list: 信号数据列表
    """
    try:
        if config is None:
            config = load_system_config()
        
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        
        storage_config = get_data_storage_config(config)
        signals_config = storage_config.get('signals', {})
        signals_dir = signals_config.get('dir', 'signals')
        # 如果 signals_dir 已经包含 data/ 前缀，直接使用；否则拼接 data_dir
        if signals_dir.startswith('data/'):
            storage_path = Path(signals_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / signals_dir
        
        file_path = storage_path / f"{date}.json"
        
        if not file_path.exists():
            logger.debug(f"信号数据文件不存在: {file_path}")
            return []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"加载信号数据: {file_path}, 共 {len(data)} 条记录")
        return data
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'load_signals', 'date': date},
            "加载信号数据失败"
        )
        return []


def save_opening_analysis(
    analysis_result: Dict[str, Any],
    config: Optional[Dict] = None
) -> str:
    """
    保存开盘分析结果
    
    Args:
        analysis_result: 完整的分析结果（包含opening_data、analysis、trend_prediction）
        config: 系统配置
    
    Returns:
        str: 保存的文件路径
    """
    try:
        if config is None:
            config = load_system_config()
        
        storage_config = get_data_storage_config(config)
        trend_config = storage_config.get('trend_analysis', {})
        
        if not trend_config.get('enabled', True):
            logger.debug("趋势分析存储已禁用")
            return ""
        
        # 获取存储目录（使用trend_analysis目录）
        trend_dir = trend_config.get('dir', 'data/trend_analysis')
        if trend_dir.startswith('data/'):
            storage_path = Path(trend_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / trend_dir
        
        # 创建目录
        storage_path.mkdir(parents=True, exist_ok=True)
        
        # 从analysis_result中提取日期
        date_str = analysis_result.get('date')
        if not date_str:
            # 如果没有日期，使用当前日期
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # 生成文件名
        filename = f"opening_analysis_{date_str.replace('-', '')}.json"
        file_path = storage_path / filename
        
        # 保存数据
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"开盘分析结果已保存: {file_path}")
        return str(file_path)
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'save_opening_analysis'},
            "保存开盘分析结果失败"
        )
        return ""


def load_opening_analysis(
    date: Optional[str] = None,
    config: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    加载开盘分析结果
    
    Args:
        date: 日期字符串（格式：YYYY-MM-DD 或 YYYYMMDD），如果为None则使用当前日期
        config: 系统配置
    
    Returns:
        dict: 开盘分析结果，如果失败返回None
    """
    try:
        if config is None:
            config = load_system_config()
        
        storage_config = get_data_storage_config(config)
        trend_config = storage_config.get('trend_analysis', {})
        
        if not trend_config.get('enabled', True):
            logger.debug("趋势分析存储已禁用")
            return None
        
        # 获取存储目录
        trend_dir = trend_config.get('dir', 'data/trend_analysis')
        if trend_dir.startswith('data/'):
            storage_path = Path(trend_dir)
        else:
            data_dir = storage_config.get('data_dir', 'data')
            storage_path = Path(data_dir) / trend_dir
        
        # 处理日期
        if date is None:
            # 使用当前日期，格式为YYYYMMDD（与保存时一致）
            date_str = datetime.now().strftime("%Y%m%d")
        else:
            # 统一转换为YYYYMMDD格式（去掉横线）
            if '-' in date:
                date_str = date.replace('-', '')
            elif len(date) == 10 and date.count('-') == 2:
                # YYYY-MM-DD格式
                date_str = date.replace('-', '')
            else:
                # 已经是YYYYMMDD格式
                date_str = date
        
        # 生成文件名
        filename = f"opening_analysis_{date_str}.json"
        file_path = storage_path / filename
        
        if not file_path.exists():
            logger.warning(f"开盘分析文件不存在: {file_path}")
            return None
        
        # 加载数据
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"加载开盘分析结果: {file_path}")
        return data
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'load_opening_analysis', 'date': date},
            "加载开盘分析结果失败"
        )
        return None
