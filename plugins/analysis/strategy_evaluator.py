"""
策略评分系统插件
评估策略表现，计算策略评分
参考原系统 volatility_weights.py 的逻辑
OpenClaw 插件工具
"""

import sys
import os
from typing import Dict, Any

# 添加父目录到路径以导入strategy_tracker
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, parent_dir)

try:
    from plugins.analysis.strategy_tracker import get_strategy_performance
    STRATEGY_TRACKER_AVAILABLE = True
except ImportError:
    STRATEGY_TRACKER_AVAILABLE = False


def calculate_strategy_score(
    strategy: str,
    lookback_days: int = 60,
    min_signals: int = 10
) -> Dict[str, Any]:
    """
    计算策略评分
    
    Args:
        strategy: 策略名称
        lookback_days: 回看天数
        min_signals: 最少信号数（低于此值无法评估）
    
    Returns:
        dict: {
            'score': float,  # 策略评分 (0-100)
            'win_rate': float,  # 胜率
            'avg_return': float,  # 平均收益率
            'sharpe_ratio': float,  # 夏普比率（简化版）
            'max_drawdown': float,  # 最大回撤
            'metrics': dict  # 各项指标详情
        }
    """
    try:
        if not STRATEGY_TRACKER_AVAILABLE:
            return {
                'success': False,
                'message': '策略跟踪模块不可用',
                'data': None
            }
        
        # 获取策略表现
        performance = get_strategy_performance(strategy=strategy, lookback_days=lookback_days)
        
        if not performance.get('success'):
            return {
                'success': False,
                'message': performance.get('error', '获取策略表现失败'),
                'data': None
            }
        
        # 检查是否有足够的信号
        total_signals = performance.get('total_signals', 0)
        closed_signals = performance.get('closed_signals', 0)
        
        if closed_signals < min_signals:
            return {
                'success': True,
                'message': f'信号数不足（{closed_signals} < {min_signals}），无法评估',
                'data': {
                    'score': 50.0,  # 默认中性评分
                    'win_rate': 0.0,
                    'avg_return': 0.0,
                    'sharpe_ratio': 0.0,
                    'max_drawdown': 0.0,
                    'total_signals': total_signals,
                    'closed_signals': closed_signals
                }
            }
        
        # 计算各项指标
        win_rate = performance.get('win_rate', 0.0)
        avg_return = performance.get('avg_return', 0.0)
        
        # 简化版夏普比率（假设无风险利率为0）
        # 实际应该计算收益率的标准差
        sharpe_ratio = avg_return * 10 if avg_return > 0 else 0.0  # 简化计算
        
        # 简化版最大回撤（实际需要计算历史回撤）
        max_drawdown = abs(min(0.0, avg_return * 0.5))  # 简化计算
        
        # 计算综合评分
        # 胜率权重30%，平均收益率权重40%，夏普比率权重20%，最大回撤权重10%
        score = (
            win_rate * 100 * 0.3 +  # 胜率（转换为0-100）
            min(max(avg_return * 1000, -50), 50) * 0.4 +  # 平均收益率（限制范围）
            min(max(sharpe_ratio * 10, 0), 20) * 0.2 +  # 夏普比率
            (1 - min(max_drawdown, 1.0)) * 100 * 0.1  # 最大回撤（越小越好）
        )
        
        # 限制评分范围
        score = max(0.0, min(100.0, score))
        
        return {
            'success': True,
            'message': '策略评分计算完成',
            'data': {
                'score': float(score),
                'win_rate': float(win_rate),
                'avg_return': float(avg_return),
                'sharpe_ratio': float(sharpe_ratio),
                'max_drawdown': float(max_drawdown),
                'total_signals': total_signals,
                'closed_signals': closed_signals,
                'lookback_days': lookback_days,
                'metrics': {
                    'win_rate_weight': 0.3,
                    'avg_return_weight': 0.4,
                    'sharpe_ratio_weight': 0.2,
                    'max_drawdown_weight': 0.1
                }
            }
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'计算策略评分失败: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_calculate_strategy_score(
    strategy: str,
    lookback_days: int = 60,
    min_signals: int = 10
) -> Dict[str, Any]:
    """OpenClaw 工具：计算策略评分"""
    return calculate_strategy_score(
        strategy=strategy,
        lookback_days=lookback_days,
        min_signals=min_signals
    )
