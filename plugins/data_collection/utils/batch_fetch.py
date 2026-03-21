"""
批量数据采集工具
使用并行处理提升批量数据获取性能
OpenClaw 插件工具
"""

import sys
import os
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime

# 导入重试工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.logging_utils import get_logger
    from plugins.utils.performance_monitor import measure_execution_time
    LOGGING_AVAILABLE = True
except ImportError:
    LOGGING_AVAILABLE = False
    import logging
    def get_logger(name):
        return logging.getLogger(name)
    def measure_execution_time(func):
        return func

logger = get_logger(__name__)


def batch_fetch_parallel(
    items: List[str],
    fetch_func: Callable[[str], Dict[str, Any]],
    max_workers: int = 5,
    timeout: Optional[float] = None
) -> Dict[str, Any]:
    """
    并行批量获取数据
    
    Args:
        items: 要获取的项目列表（如ETF代码列表、指数代码列表等）
        fetch_func: 单个项目的获取函数，接受一个item参数，返回Dict
        max_workers: 最大并发数
        timeout: 超时时间（秒），None表示不限制
    
    Returns:
        Dict: 包含所有结果的字典
        {
            'success': bool,
            'total': int,
            'success_count': int,
            'failed_count': int,
            'results': Dict[str, Dict],  # {item: result}
            'errors': Dict[str, str],    # {item: error_message}
            'execution_time': float
        }
    """
    start_time = time.time()
    results = {}
    errors = {}
    success_count = 0
    failed_count = 0
    
    if not items:
        return {
            'success': False,
            'message': '未提供要获取的项目列表',
            'total': 0,
            'success_count': 0,
            'failed_count': 0,
            'results': {},
            'errors': {},
            'execution_time': 0.0
        }
    
    logger.info(f"开始并行批量获取 {len(items)} 个项目，最大并发数: {max_workers}")
    
    # 使用ThreadPoolExecutor并行执行
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_item = {
            executor.submit(fetch_func, item): item
            for item in items
        }
        
        # 收集结果（整体等待时间由 as_completed 的 timeout 控制，
        # 单个任务的阻塞时间使用 per_item_timeout 控制）
        for future in as_completed(future_to_item, timeout=timeout):
            item = future_to_item[future]
            try:
                per_item_timeout = timeout or 30.0
                result = future.result(timeout=per_item_timeout)
                if result and result.get('success', False):
                    results[item] = result
                    success_count += 1
                else:
                    error_msg = result.get('message', '获取失败') if result else '获取失败'
                    errors[item] = error_msg
                    failed_count += 1
                    logger.warning(f"获取 {item} 失败: {error_msg}")
            except Exception as e:
                error_msg = str(e)
                errors[item] = error_msg
                failed_count += 1
                logger.error(f"获取 {item} 时发生异常: {error_msg}", exc_info=True)
    
    execution_time = time.time() - start_time
    
    logger.info(f"批量获取完成: 成功 {success_count}/{len(items)}, 失败 {failed_count}/{len(items)}, 耗时 {execution_time:.2f}秒")
    
    return {
        'success': success_count > 0,
        'total': len(items),
        'success_count': success_count,
        'failed_count': failed_count,
        'results': results,
        'errors': errors,
        'execution_time': execution_time
    }


@measure_execution_time
def tool_fetch_multiple_etf_realtime(
    etf_codes: List[str],
    max_workers: int = 5,
    timeout: Optional[float] = 30.0
) -> Dict[str, Any]:
    """
    OpenClaw工具：批量获取多个ETF的实时数据（并行）
    
    Args:
        etf_codes: ETF代码列表，如 ["510300", "510050", "510500"]
        max_workers: 最大并发数（默认5）
        timeout: 超时时间（秒，默认30秒）
    
    Returns:
        Dict: 包含所有ETF实时数据的字典
    """
    try:
        from plugins.data_collection.etf.fetch_realtime import fetch_etf_realtime
        
        # 定义单个ETF的获取函数
        def fetch_single_etf(etf_code: str) -> Dict[str, Any]:
            return fetch_etf_realtime(etf_code=etf_code)
        
        # 并行批量获取
        batch_result = batch_fetch_parallel(
            items=etf_codes,
            fetch_func=fetch_single_etf,
            max_workers=max_workers,
            timeout=timeout
        )
        
        # 格式化返回结果
        formatted_results = {}
        for etf_code, result in batch_result['results'].items():
            if result and result.get('data'):
                formatted_results[etf_code] = result['data']
        
        return {
            'success': batch_result['success'],
            'message': f"批量获取完成: 成功 {batch_result['success_count']}/{batch_result['total']}",
            'data': formatted_results,
            'statistics': {
                'total': batch_result['total'],
                'success_count': batch_result['success_count'],
                'failed_count': batch_result['failed_count'],
                'execution_time': batch_result['execution_time']
            },
            'errors': batch_result['errors'] if batch_result['errors'] else None
        }
        
    except Exception as e:
        logger.error(f"批量获取ETF实时数据失败: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': f'批量获取失败: {str(e)}',
            'data': None
        }


@measure_execution_time
def tool_fetch_multiple_index_realtime(
    index_codes: List[str],
    max_workers: int = 5,
    timeout: Optional[float] = 30.0
) -> Dict[str, Any]:
    """
    OpenClaw工具：批量获取多个指数的实时数据（并行）
    
    Args:
        index_codes: 指数代码列表，如 ["000300", "000001", "399001"]
        max_workers: 最大并发数（默认5）
        timeout: 超时时间（秒，默认30秒）
    
    Returns:
        Dict: 包含所有指数实时数据的字典
    """
    try:
        from plugins.data_collection.index.fetch_realtime import fetch_index_realtime
        
        # 定义单个指数的获取函数
        def fetch_single_index(index_code: str) -> Dict[str, Any]:
            return fetch_index_realtime(index_code=index_code)
        
        # 并行批量获取
        batch_result = batch_fetch_parallel(
            items=index_codes,
            fetch_func=fetch_single_index,
            max_workers=max_workers,
            timeout=timeout
        )
        
        # 格式化返回结果
        formatted_results = {}
        for index_code, result in batch_result['results'].items():
            if result and result.get('data'):
                formatted_results[index_code] = result['data']
        
        return {
            'success': batch_result['success'],
            'message': f"批量获取完成: 成功 {batch_result['success_count']}/{batch_result['total']}",
            'data': formatted_results,
            'statistics': {
                'total': batch_result['total'],
                'success_count': batch_result['success_count'],
                'failed_count': batch_result['failed_count'],
                'execution_time': batch_result['execution_time']
            },
            'errors': batch_result['errors'] if batch_result['errors'] else None
        }
        
    except Exception as e:
        logger.error(f"批量获取指数实时数据失败: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': f'批量获取失败: {str(e)}',
            'data': None
        }


@measure_execution_time
def tool_fetch_multiple_option_realtime(
    contract_codes: List[str],
    max_workers: int = 5,
    timeout: Optional[float] = 30.0
) -> Dict[str, Any]:
    """
    OpenClaw工具：批量获取多个期权合约的实时数据（并行）
    
    Args:
        contract_codes: 期权合约代码列表，如 ["10010891", "10010892"]
        max_workers: 最大并发数（默认5）
        timeout: 超时时间（秒，默认30秒）
    
    Returns:
        Dict: 包含所有期权实时数据的字典
    """
    try:
        from plugins.data_collection.option.fetch_realtime import fetch_option_realtime
        
        # 定义单个期权的获取函数
        def fetch_single_option(contract_code: str) -> Dict[str, Any]:
            return fetch_option_realtime(contract_code=contract_code)
        
        # 并行批量获取
        batch_result = batch_fetch_parallel(
            items=contract_codes,
            fetch_func=fetch_single_option,
            max_workers=max_workers,
            timeout=timeout
        )
        
        # 格式化返回结果
        formatted_results = {}
        for contract_code, result in batch_result['results'].items():
            if result and result.get('data'):
                formatted_results[contract_code] = result['data']
        
        return {
            'success': batch_result['success'],
            'message': f"批量获取完成: 成功 {batch_result['success_count']}/{batch_result['total']}",
            'data': formatted_results,
            'statistics': {
                'total': batch_result['total'],
                'success_count': batch_result['success_count'],
                'failed_count': batch_result['failed_count'],
                'execution_time': batch_result['execution_time']
            },
            'errors': batch_result['errors'] if batch_result['errors'] else None
        }
        
    except Exception as e:
        logger.error(f"批量获取期权实时数据失败: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': f'批量获取失败: {str(e)}',
            'data': None
        }


@measure_execution_time
def tool_fetch_multiple_option_greeks(
    contract_codes: List[str],
    max_workers: int = 5,
    timeout: Optional[float] = 30.0
) -> Dict[str, Any]:
    """
    OpenClaw工具：批量获取多个期权合约的Greeks数据（并行）
    
    Args:
        contract_codes: 期权合约代码列表，如 ["10010891", "10010892"]
        max_workers: 最大并发数（默认5）
        timeout: 超时时间（秒，默认30秒）
    
    Returns:
        Dict: 包含所有期权Greeks数据的字典
    """
    try:
        from plugins.data_collection.option.fetch_greeks import fetch_option_greeks
        
        # 定义单个期权的获取函数
        def fetch_single_greeks(contract_code: str) -> Dict[str, Any]:
            return fetch_option_greeks(contract_code=contract_code)
        
        # 并行批量获取
        batch_result = batch_fetch_parallel(
            items=contract_codes,
            fetch_func=fetch_single_greeks,
            max_workers=max_workers,
            timeout=timeout
        )
        
        # 格式化返回结果
        formatted_results = {}
        for contract_code, result in batch_result['results'].items():
            if result and result.get('data'):
                formatted_results[contract_code] = result['data']
        
        return {
            'success': batch_result['success'],
            'message': f"批量获取完成: 成功 {batch_result['success_count']}/{batch_result['total']}",
            'data': formatted_results,
            'statistics': {
                'total': batch_result['total'],
                'success_count': batch_result['success_count'],
                'failed_count': batch_result['failed_count'],
                'execution_time': batch_result['execution_time']
            },
            'errors': batch_result['errors'] if batch_result['errors'] else None
        }
        
    except Exception as e:
        logger.error(f"批量获取期权Greeks数据失败: {str(e)}", exc_info=True)
        return {
            'success': False,
            'message': f'批量获取失败: {str(e)}',
            'data': None
        }
