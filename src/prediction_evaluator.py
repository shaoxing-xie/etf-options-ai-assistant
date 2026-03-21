"""
预测评估指标计算模块
计算区间覆盖率、区间宽度、方向准确率、校准度等核心指标
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import pytz
import json
from pathlib import Path

from src.logger_config import get_module_logger
from src.prediction_recorder import PREDICTION_RECORDS_DIR

logger = get_module_logger(__name__)


def calculate_coverage_rate(
    predictions: List[Dict[str, Any]],
    min_predictions: int = 10
) -> Dict[str, Any]:
    """
    计算区间覆盖率
    
    Args:
        predictions: 预测记录列表（必须包含actual_range和hit字段）
        min_predictions: 最少预测次数
    
    Returns:
        dict: {
            'coverage_rate': 0.85,  # 覆盖率
            'total': 100,  # 总预测次数
            'hits': 85,  # 命中次数
            'misses': 15  # 未命中次数
        }
    """
    try:
        if not predictions or len(predictions) < min_predictions:
            return {
                'coverage_rate': None,
                'total': len(predictions) if predictions else 0,
                'hits': 0,
                'misses': 0,
                'insufficient_data': True
            }
        
        # 只统计已验证的预测
        verified_predictions = [p for p in predictions if p.get('verified', False)]
        
        if not verified_predictions:
            return {
                'coverage_rate': None,
                'total': len(predictions),
                'hits': 0,
                'misses': 0,
                'insufficient_data': True
            }
        
        hits = sum(1 for p in verified_predictions 
                  if p.get('actual_range', {}).get('hit', False))
        total = len(verified_predictions)
        misses = total - hits
        
        coverage_rate = hits / total if total > 0 else 0.0
        
        return {
            'coverage_rate': coverage_rate,
            'total': total,
            'hits': hits,
            'misses': misses,
            'insufficient_data': False
        }
        
    except Exception as e:
        logger.error(f"计算覆盖率失败: {e}", exc_info=True)
        return {
            'coverage_rate': None,
            'total': 0,
            'hits': 0,
            'misses': 0,
            'error': str(e)
        }


def calculate_average_width(
    predictions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    计算区间宽度
    
    Args:
        predictions: 预测记录列表
    
    Returns:
        dict: {
            'avg_width': 2.5,  # 平均宽度（百分比）
            'min_width': 1.5,  # 最小宽度
            'max_width': 5.0,  # 最大宽度
            'std_width': 0.8,  # 宽度标准差
            'total': 100
        }
    """
    try:
        if not predictions:
            return {
                'avg_width': None,
                'min_width': None,
                'max_width': None,
                'std_width': None,
                'total': 0
            }
        
        widths = []
        for p in predictions:
            range_pct = p.get('prediction', {}).get('range_pct')
            if range_pct is not None:
                widths.append(float(range_pct))
        
        if not widths:
            return {
                'avg_width': None,
                'min_width': None,
                'max_width': None,
                'std_width': None,
                'total': 0
            }
        
        widths_array = np.array(widths)
        
        return {
            'avg_width': float(np.mean(widths_array)),
            'min_width': float(np.min(widths_array)),
            'max_width': float(np.max(widths_array)),
            'std_width': float(np.std(widths_array)),
            'total': len(widths)
        }
        
    except Exception as e:
        logger.error(f"计算区间宽度失败: {e}", exc_info=True)
        return {
            'avg_width': None,
            'min_width': None,
            'max_width': None,
            'std_width': None,
            'total': 0,
            'error': str(e)
        }


def calculate_direction_accuracy(
    predictions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    计算方向准确率
    
    Args:
        predictions: 预测记录列表（需要包含趋势方向信息）
    
    Returns:
        dict: {
            'direction_accuracy': 0.65,  # 方向准确率
            'up_accuracy': 0.70,  # 向上预测准确率
            'down_accuracy': 0.60,  # 向下预测准确率
            'neutral_accuracy': 0.65,  # 横盘预测准确率
            'total': 100
        }
    """
    try:
        if not predictions:
            return {
                'direction_accuracy': None,
                'up_accuracy': None,
                'down_accuracy': None,
                'neutral_accuracy': None,
                'total': 0
            }
        
        # 只统计已验证的预测
        verified_predictions = [p for p in predictions if p.get('verified', False)]
        
        if not verified_predictions:
            return {
                'direction_accuracy': None,
                'up_accuracy': None,
                'down_accuracy': None,
                'neutral_accuracy': None,
                'total': len(predictions),
                'insufficient_data': True
            }
        
        # 计算实际方向（基于收盘价变化）
        direction_stats = {
            'up': {'correct': 0, 'total': 0},
            'down': {'correct': 0, 'total': 0},
            'neutral': {'correct': 0, 'total': 0}
        }
        
        for p in verified_predictions:
            actual_range = p.get('actual_range', {})
            prediction = p.get('prediction', {})
            
            actual_close = actual_range.get('actual_close')
            current_price = prediction.get('current_price')
            
            if actual_close is None or current_price is None:
                continue
            
            # 计算实际方向
            price_change = (actual_close - current_price) / current_price
            
            # 预测方向（从方法或其他字段推断，这里简化处理）
            # 实际应用中，需要从预测结果中提取趋势方向
            predicted_direction = 'neutral'  # 默认值
            
            # 判断实际方向
            if price_change > 0.005:  # 上涨超过0.5%
                actual_direction = 'up'
            elif price_change < -0.005:  # 下跌超过0.5%
                actual_direction = 'down'
            else:
                actual_direction = 'neutral'
            
            # 统计（这里简化处理，实际需要从预测中获取方向）
            # 暂时返回基础统计
        
        # 简化版本：返回基础结构
        total = len(verified_predictions)
        
        return {
            'direction_accuracy': None,  # 需要从预测中提取方向信息
            'up_accuracy': None,
            'down_accuracy': None,
            'neutral_accuracy': None,
            'total': total,
            'note': '方向准确率计算需要预测结果中包含趋势方向信息'
        }
        
    except Exception as e:
        logger.error(f"计算方向准确率失败: {e}", exc_info=True)
        return {
            'direction_accuracy': None,
            'up_accuracy': None,
            'down_accuracy': None,
            'neutral_accuracy': None,
            'total': 0,
            'error': str(e)
        }


def calculate_calibration(
    predictions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    计算校准度（预测区间宽度与实际波动范围的一致性）
    
    Args:
        predictions: 预测记录列表
    
    Returns:
        dict: {
            'calibration_score': 0.85,  # 校准度得分（0-1）
            'avg_predicted_width': 2.5,  # 平均预测宽度
            'avg_actual_width': 2.3,  # 平均实际波动宽度
            'width_ratio': 1.09,  # 预测宽度/实际宽度
            'total': 100
        }
    """
    try:
        if not predictions:
            return {
                'calibration_score': None,
                'avg_predicted_width': None,
                'avg_actual_width': None,
                'width_ratio': None,
                'total': 0
            }
        
        # 只统计已验证的预测
        verified_predictions = [p for p in predictions if p.get('verified', False)]
        
        if not verified_predictions:
            return {
                'calibration_score': None,
                'avg_predicted_width': None,
                'avg_actual_width': None,
                'width_ratio': None,
                'total': len(predictions),
                'insufficient_data': True
            }
        
        predicted_widths = []
        actual_widths = []
        
        for p in verified_predictions:
            prediction = p.get('prediction', {})
            actual_range = p.get('actual_range', {})
            
            current_price = prediction.get('current_price')
            upper = prediction.get('upper')
            lower = prediction.get('lower')
            
            actual_high = actual_range.get('actual_high')
            actual_low = actual_range.get('actual_low')
            
            if current_price and upper and lower:
                predicted_width = (upper - lower) / current_price * 100
                predicted_widths.append(predicted_width)
            
            if current_price and actual_high and actual_low:
                actual_width = (actual_high - actual_low) / current_price * 100
                actual_widths.append(actual_width)
        
        if not predicted_widths or not actual_widths:
            return {
                'calibration_score': None,
                'avg_predicted_width': None,
                'avg_actual_width': None,
                'width_ratio': None,
                'total': len(verified_predictions),
                'insufficient_data': True
            }
        
        avg_predicted_width = np.mean(predicted_widths)
        avg_actual_width = np.mean(actual_widths)
        
        width_ratio = avg_predicted_width / avg_actual_width if avg_actual_width > 0 else None
        
        # 校准度得分：越接近1越好
        if width_ratio:
            calibration_score = 1.0 - min(1.0, abs(width_ratio - 1.0))
        else:
            calibration_score = None
        
        return {
            'calibration_score': float(calibration_score) if calibration_score is not None else None,
            'avg_predicted_width': float(avg_predicted_width),
            'avg_actual_width': float(avg_actual_width),
            'width_ratio': float(width_ratio) if width_ratio else None,
            'total': len(verified_predictions)
        }
        
    except Exception as e:
        logger.error(f"计算校准度失败: {e}", exc_info=True)
        return {
            'calibration_score': None,
            'avg_predicted_width': None,
            'avg_actual_width': None,
            'width_ratio': None,
            'total': 0,
            'error': str(e)
        }


def calculate_method_performance(
    predictions: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    计算各方法的独立表现
    
    Args:
        predictions: 预测记录列表
    
    Returns:
        dict: {
            'GARCH集成': {
                'coverage_rate': 0.88,
                'avg_width': 2.3,
                'total': 50,
                'hits': 44
            },
            '综合方法': {
                'coverage_rate': 0.82,
                'avg_width': 2.5,
                'total': 50,
                'hits': 41
            },
            ...
        }
    """
    try:
        if not predictions:
            return {}
        
        # 按方法分组
        method_groups = {}
        
        for p in predictions:
            method = p.get('prediction', {}).get('method', '未知')
            if method not in method_groups:
                method_groups[method] = []
            method_groups[method].append(p)
        
        # 计算各方法的表现
        method_performance = {}
        
        for method, method_predictions in method_groups.items():
            coverage = calculate_coverage_rate(method_predictions, min_predictions=1)
            width = calculate_average_width(method_predictions)
            
            method_performance[method] = {
                'coverage_rate': coverage.get('coverage_rate'),
                'avg_width': width.get('avg_width'),
                'total': coverage.get('total', 0),
                'hits': coverage.get('hits', 0),
                'misses': coverage.get('misses', 0)
            }
        
        return method_performance
        
    except Exception as e:
        logger.error(f"计算方法表现失败: {e}", exc_info=True)
        return {}


def calculate_market_state_performance(
    predictions: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    计算不同市场状态下的表现
    
    Args:
        predictions: 预测记录列表
    
    Returns:
        dict: {
            'trend': {'coverage_rate': 0.90, 'avg_width': 2.8, ...},
            'range': {'coverage_rate': 0.85, 'avg_width': 2.2, ...},
            'high_volatility': {'coverage_rate': 0.80, 'avg_width': 3.5, ...}
        }
    """
    try:
        if not predictions:
            return {}
        
        # 按市场状态分组（需要从预测中提取市场状态信息）
        # 这里简化处理，实际需要从预测记录中获取市场状态
        
        # 暂时返回空结构，需要在实际预测时记录市场状态
        return {
            'trend': {},
            'range': {},
            'high_volatility': {}
        }
        
    except Exception as e:
        logger.error(f"计算市场状态表现失败: {e}", exc_info=True)
        return {}


def calculate_calibration_effectiveness(
    predictions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    计算实时校准效果（校准前后的覆盖率对比）
    
    Args:
        predictions: 预测记录列表
    
    Returns:
        dict: {
            'calibrated_coverage': 0.88,  # 校准后的覆盖率
            'uncalibrated_coverage': 0.82,  # 校准前的覆盖率
            'improvement': 0.06,  # 提升幅度
            'calibrated_count': 30,  # 校准次数
            'total_count': 100  # 总预测次数
        }
    """
    try:
        if not predictions:
            return {
                'calibrated_coverage': None,
                'uncalibrated_coverage': None,
                'improvement': None,
                'calibrated_count': 0,
                'total_count': 0
            }
        
        # 分离校准和未校准的预测
        calibrated_predictions = [p for p in predictions 
                                 if p.get('prediction', {}).get('calibration_applied', False)]
        uncalibrated_predictions = [p for p in predictions 
                                   if not p.get('prediction', {}).get('calibration_applied', False)]
        
        calibrated_coverage = calculate_coverage_rate(calibrated_predictions, min_predictions=1)
        uncalibrated_coverage = calculate_coverage_rate(uncalibrated_predictions, min_predictions=1)
        
        calibrated_rate = calibrated_coverage.get('coverage_rate')
        uncalibrated_rate = uncalibrated_coverage.get('coverage_rate')
        
        improvement = None
        if calibrated_rate is not None and uncalibrated_rate is not None:
            improvement = calibrated_rate - uncalibrated_rate
        
        return {
            'calibrated_coverage': calibrated_rate,
            'uncalibrated_coverage': uncalibrated_rate,
            'improvement': improvement,
            'calibrated_count': len(calibrated_predictions),
            'total_count': len(predictions)
        }
        
    except Exception as e:
        logger.error(f"计算校准效果失败: {e}", exc_info=True)
        return {
            'calibrated_coverage': None,
            'uncalibrated_coverage': None,
            'improvement': None,
            'calibrated_count': 0,
            'total_count': 0,
            'error': str(e)
        }


def load_predictions_from_date_range(
    start_date: str,
    end_date: str,
    prediction_type: Optional[str] = None,
    source: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    从日期范围加载预测记录
    
    Args:
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        prediction_type: 预测类型（可选）
        source: 预测来源（可选）
    
    Returns:
        list: 预测记录列表
    """
    try:
        all_predictions = []
        
        # 遍历日期范围
        start = datetime.strptime(start_date, '%Y%m%d')
        end = datetime.strptime(end_date, '%Y%m%d')
        
        current = start
        while current <= end:
            date_str = current.strftime('%Y%m%d')
            json_file = PREDICTION_RECORDS_DIR / f"predictions_{date_str}.json"
            
            if json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        day_predictions = json.load(f)
                    
                    # 过滤
                    for p in day_predictions:
                        if prediction_type and p.get('prediction_type') != prediction_type:
                            continue
                        if source and p.get('source') != source:
                            continue
                        all_predictions.append(p)
                        
                except Exception as e:
                    logger.debug(f"读取预测记录文件失败 {date_str}: {e}")
            
            current += timedelta(days=1)
        
        return all_predictions
        
    except Exception as e:
        logger.error(f"加载预测记录失败: {e}", exc_info=True)
        return []


def evaluate_predictions(
    start_date: str,
    end_date: str,
    prediction_type: Optional[str] = None,
    source: Optional[str] = None
) -> Dict[str, Any]:
    """
    综合评估预测结果
    
    Args:
        start_date: 开始日期（YYYYMMDD）
        end_date: 结束日期（YYYYMMDD）
        prediction_type: 预测类型（可选）
        source: 预测来源（可选）
    
    Returns:
        dict: 完整的评估结果
    """
    try:
        # 加载预测记录
        predictions = load_predictions_from_date_range(
            start_date, end_date, prediction_type, source
        )
        
        if not predictions:
            return {
                'error': '没有找到预测记录',
                'start_date': start_date,
                'end_date': end_date,
                'total': 0
            }
        
        # 计算核心指标
        coverage = calculate_coverage_rate(predictions)
        width = calculate_average_width(predictions)
        direction = calculate_direction_accuracy(predictions)
        calibration = calculate_calibration(predictions)
        
        # 计算辅助指标
        method_performance = calculate_method_performance(predictions)
        market_state_performance = calculate_market_state_performance(predictions)
        calibration_effectiveness = calculate_calibration_effectiveness(predictions)
        
        return {
            'start_date': start_date,
            'end_date': end_date,
            'prediction_type': prediction_type,
            'source': source,
            'total_predictions': len(predictions),
            'core_metrics': {
                'coverage_rate': coverage,
                'average_width': width,
                'direction_accuracy': direction,
                'calibration': calibration
            },
            'auxiliary_metrics': {
                'method_performance': method_performance,
                'market_state_performance': market_state_performance,
                'calibration_effectiveness': calibration_effectiveness
            }
        }
        
    except Exception as e:
        logger.error(f"评估预测结果失败: {e}", exc_info=True)
        return {
            'error': str(e),
            'start_date': start_date,
            'end_date': end_date
        }
