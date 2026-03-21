"""
策略权重管理插件
根据策略评分动态调整策略权重
扩展原系统 volatility_weights.py
OpenClaw 插件工具
"""

import sys
import os
from typing import Dict, Any, Optional, List

# 添加父目录到路径以导入strategy_evaluator
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, parent_dir)

try:
    from plugins.analysis.strategy_evaluator import calculate_strategy_score
    STRATEGY_EVALUATOR_AVAILABLE = True
except ImportError:
    STRATEGY_EVALUATOR_AVAILABLE = False


def adjust_strategy_weights(
    current_weights: Dict[str, float],
    lookback_days: int = 60,
    adjustment_rate: float = 0.1,
    min_weight: float = 0.10,
    max_weight: float = 0.60
) -> Dict[str, Any]:
    """
    根据策略评分调整权重
    
    Args:
        current_weights: 当前权重 {strategy: weight}
        lookback_days: 回看天数
        adjustment_rate: 调整幅度（默认0.1，即10%）
        min_weight: 最小权重（默认0.10）
        max_weight: 最大权重（默认0.60）
    
    Returns:
        dict: {
            'adjusted_weights': dict,  # 调整后的权重
            'changes': dict,  # 权重变化
            'strategy_scores': dict  # 策略评分
        }
    """
    try:
        if not STRATEGY_EVALUATOR_AVAILABLE:
            return {
                'success': False,
                'message': '策略评分模块不可用',
                'data': None
            }
        
        # 1. 计算所有策略的评分
        strategy_scores = {}
        for strategy in current_weights.keys():
            score_result = calculate_strategy_score(strategy=strategy, lookback_days=lookback_days)
            if score_result.get('success') and score_result.get('data'):
                strategy_scores[strategy] = score_result['data'].get('score', 50.0)
            else:
                strategy_scores[strategy] = 50.0  # 默认中性评分
        
        # 2. 根据评分计算权重调整
        # 评分高的策略增加权重，评分低的策略降低权重
        total_score = sum(strategy_scores.values())
        if total_score == 0:
            # 如果所有评分都是0，保持原权重
            return {
                'success': True,
                'message': '所有策略评分均为0，保持原权重',
                'data': {
                    'adjusted_weights': current_weights.copy(),
                    'changes': {s: 0.0 for s in current_weights.keys()},
                    'strategy_scores': strategy_scores
                }
            }
        
        # 3. 根据评分比例计算新权重
        new_weights = {}
        for strategy, current_weight in current_weights.items():
            score = strategy_scores.get(strategy, 50.0)
            # 根据评分比例计算目标权重
            target_weight = (score / total_score) * sum(current_weights.values())
            
            # 限制权重范围
            target_weight = max(min_weight, min(max_weight, target_weight))
            
            # 平滑调整：每次调整不超过adjustment_rate
            weight_change = target_weight - current_weight
            if abs(weight_change) > adjustment_rate:
                weight_change = adjustment_rate if weight_change > 0 else -adjustment_rate
            
            new_weights[strategy] = current_weight + weight_change
        
        # 4. 归一化权重（确保总和为1）
        total_new_weight = sum(new_weights.values())
        if total_new_weight > 0:
            new_weights = {s: w / total_new_weight for s, w in new_weights.items()}
        else:
            # 如果归一化后为0，使用均等权重
            new_weights = {s: 1.0 / len(new_weights) for s in new_weights.keys()}
        
        # 5. 计算权重变化
        changes = {
            strategy: new_weights[strategy] - current_weights[strategy]
            for strategy in current_weights.keys()
        }
        
        return {
            'success': True,
            'message': '策略权重调整完成',
            'data': {
                'adjusted_weights': new_weights,
                'changes': changes,
                'strategy_scores': strategy_scores,
                'adjustment_rate': adjustment_rate
            }
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'调整策略权重失败: {str(e)}',
            'data': None
        }


def get_strategy_weights(
    strategies: Optional[List[str]] = None,
    default_weights: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    获取策略权重
    
    Args:
        strategies: 策略列表（可选）
        default_weights: 默认权重（可选）
    
    Returns:
        dict: 策略权重
    """
    try:
        if default_weights:
            return {
                'success': True,
                'data': default_weights
            }
        
        if strategies:
            # 均等分配
            weight = 1.0 / len(strategies)
            weights = {s: weight for s in strategies}
            return {
                'success': True,
                'data': weights
            }
        
        # 默认策略和权重
        default = {
            'trend_following': 0.35,
            'mean_reversion': 0.35,
            'breakout': 0.30
        }
        
        return {
            'success': True,
            'data': default
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'获取策略权重失败: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_adjust_strategy_weights(
    current_weights: Dict[str, float],
    lookback_days: int = 60,
    adjustment_rate: float = 0.1
) -> Dict[str, Any]:
    """OpenClaw 工具：调整策略权重"""
    return adjust_strategy_weights(
        current_weights=current_weights,
        lookback_days=lookback_days,
        adjustment_rate=adjustment_rate
    )


def tool_get_strategy_weights(
    strategies: Optional[List[str]] = None
) -> Dict[str, Any]:
    """OpenClaw 工具：获取策略权重"""
    return get_strategy_weights(strategies=strategies)
