"""
ETF仓位管理模块
根据趋势强度分级仓位，支持多ETF仓位分配
"""

from typing import Dict, Any, Optional
from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


def calculate_position_size(
    trend_strength: float,
    signal_confidence: float,
    current_positions: Dict[str, float],
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    计算建议仓位
    
    Args:
        trend_strength: 趋势强度 (0-1)
        signal_confidence: 信号置信度 (0-1)
        current_positions: 当前持仓 {etf_symbol: position_size}
        config: 系统配置
    
    Returns:
        dict: {
            'recommended_size': float,  # 建议仓位 (0-1)
            'adjustment': str,          # 'increase' | 'decrease' | 'hold'
            'reason': str,
            'max_position': float       # 最大仓位限制
        }
    
    仓位规则：
    - 趋势强（strength >= 0.7）：50-80%
    - 趋势中（0.4 <= strength < 0.7）：30-50%
    - 趋势弱（strength < 0.4）：0-20%
    - 单ETF最大仓位：80%
    - 多ETF总仓位：不超过100%
    """
    try:
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        etf_config = config.get('etf_trading', {})
        position_config = etf_config.get('position_management', {})
        
        strong_trend_range = position_config.get('strong_trend', [0.5, 0.8])
        medium_trend_range = position_config.get('medium_trend', [0.3, 0.5])
        weak_trend_range = position_config.get('weak_trend', [0.0, 0.2])
        max_single_position = position_config.get('max_single_position', 0.8)
        max_total_position = position_config.get('max_total_position', 1.0)
        
        # 根据趋势强度确定仓位范围
        if trend_strength >= 0.7:
            # 趋势强：50-80%
            base_range = strong_trend_range
            reason_base = "趋势强"
        elif trend_strength >= 0.4:
            # 趋势中：30-50%
            base_range = medium_trend_range
            reason_base = "趋势中"
        else:
            # 趋势弱：0-20%
            base_range = weak_trend_range
            reason_base = "趋势弱"
        
        # 在范围内根据置信度调整仓位
        min_position = base_range[0]
        max_position = min(base_range[1], max_single_position)  # 不超过单ETF最大仓位
        
        # 仓位 = 最小仓位 + (最大仓位 - 最小仓位) * 置信度
        recommended_size = min_position + (max_position - min_position) * signal_confidence
        
        # 限制在0-1范围内
        recommended_size = max(0.0, min(1.0, recommended_size))
        
        # 检查总仓位限制
        total_current_position = sum(current_positions.values())
        if total_current_position + recommended_size > max_total_position:
            # 如果超过总仓位限制，按比例缩减
            available_position = max(0.0, max_total_position - total_current_position)
            recommended_size = min(recommended_size, available_position)
            reason = f"{reason_base}，但受总仓位限制，建议仓位: {recommended_size:.2%}"
        else:
            reason = f"{reason_base}，建议仓位: {recommended_size:.2%}"
        
        return {
            'recommended_size': recommended_size,
            'adjustment': 'hold',  # 暂时不判断调整方向，由外部逻辑判断
            'reason': reason,
            'max_position': max_single_position,
            'max_total_position': max_total_position,
            'trend_strength': trend_strength,
            'signal_confidence': signal_confidence
        }
        
    except Exception as e:
        logger.error(f"计算建议仓位失败: {e}", exc_info=True)
        return {
            'recommended_size': 0.0,
            'adjustment': 'hold',
            'reason': f'计算失败: {str(e)}',
            'max_position': 0.8,
            'max_total_position': 1.0,
            'error': str(e)
        }


def generate_position_adjustment_signal(
    etf_symbol: str,
    current_position: float,
    recommended_position: float,
    trend_strength: float,
    trend_change: str  # 'strengthen' | 'weaken' | 'stable'
) -> Optional[Dict[str, Any]]:
    """
    生成仓位调整信号提醒
    
    Args:
        etf_symbol: ETF代码
        current_position: 当前仓位 (0-1)
        recommended_position: 建议仓位 (0-1)
        trend_strength: 趋势强度 (0-1)
        trend_change: 趋势变化 'strengthen' | 'weaken' | 'stable'
    
    Returns:
        dict: {
            'signal_type': 'position_adjustment',
            'action': 'increase' | 'decrease' | 'hold',
            'current_size': float,
            'recommended_size': float,
            'adjustment_pct': float,  # 调整幅度
            'reason': str
        } 或 None（如果不需要调整）
    
    触发条件：
    - 趋势转弱：逐步减仓（每天减仓20%）
    - 趋势转强：逐步加仓（每次加仓30%）
    - 仓位偏差>20%：生成调整信号
    """
    try:
        # 计算仓位偏差
        position_diff = abs(recommended_position - current_position)
        position_diff_pct = position_diff / max(current_position, 0.01)  # 避免除零
        
        # 如果仓位偏差<5%，不需要调整
        if position_diff_pct < 0.05:
            return None
        
        # 确定调整方向
        if recommended_position > current_position:
            action = 'increase'
            adjustment_pct = min(0.3, (recommended_position - current_position))  # 每次最多加仓30%
        elif recommended_position < current_position:
            action = 'decrease'
            adjustment_pct = -min(0.2, (current_position - recommended_position))  # 每次最多减仓20%
        else:
            action = 'hold'
            adjustment_pct = 0.0
        
        # 根据趋势变化调整
        if trend_change == 'weaken':
            # 趋势转弱：逐步减仓
            action = 'decrease'
            adjustment_pct = -0.2  # 每天减仓20%
            reason = "趋势转弱，建议减仓20%"
        elif trend_change == 'strengthen':
            # 趋势转强：逐步加仓
            action = 'increase'
            adjustment_pct = min(0.3, (recommended_position - current_position))  # 每次加仓30%
            reason = f"趋势转强，建议加仓{adjustment_pct:.0%}"
        else:
            # 趋势稳定，根据仓位偏差调整
            if position_diff_pct > 0.2:
                reason = f"仓位偏差{position_diff_pct:.0%}，建议调整至{recommended_position:.0%}"
            else:
                return None  # 偏差不大，不需要调整
        
        return {
            'signal_type': 'position_adjustment',
            'action': action,
            'current_size': current_position,
            'recommended_size': recommended_position,
            'adjustment_pct': adjustment_pct,
            'reason': reason,
            'etf_symbol': etf_symbol,
            'trend_strength': trend_strength,
            'trend_change': trend_change
        }
        
    except Exception as e:
        logger.error(f"生成仓位调整信号失败: {e}", exc_info=True)
        return None
