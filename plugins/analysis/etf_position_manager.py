"""
ETF仓位管理插件
根据趋势强度分级仓位，支持多ETF仓位分配
融合原系统 etf_position_manager.py
OpenClaw 插件工具
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional

# 尝试将当前环境中的本地 src 根目录加入 Python 路径
selected_root: Optional[Path] = None
for parent in Path(__file__).resolve().parents:
    if (parent / "src").exists():
        selected_root = parent
        break
if selected_root is not None and str(selected_root) not in sys.path:
    sys.path.insert(0, str(selected_root))

try:
    # 导入原系统的仓位管理模块
    from src.etf_position_manager import (
        calculate_position_size as original_calculate_position_size,
        generate_position_adjustment_signal
    )
    from src.config_loader import load_system_config
    ORIGINAL_SYSTEM_AVAILABLE = True
except ImportError as e:
    ORIGINAL_SYSTEM_AVAILABLE = False
    IMPORT_ERROR = str(e)


def apply_hard_position_limit(
    recommended_size: float,
    account_value: float,
    etf_current_price: float,
    hard_limit_pct: Optional[float] = None
) -> float:
    """
    应用硬锁定限制（可选）
    
    Args:
        recommended_size: 建议仓位（0-1）
        account_value: 账户总值
        etf_current_price: ETF当前价格
        hard_limit_pct: 硬锁定百分比；传 None 表示不启用硬锁定
    
    Returns:
        float: 调整后的仓位大小（不超过硬锁定限制）
    """
    try:
        if hard_limit_pct is None:
            return recommended_size
        # 计算硬锁定限制的仓位价值
        max_position_value = account_value * hard_limit_pct
        
        # 计算硬锁定限制的仓位数量
        max_position_size = max_position_value / etf_current_price if etf_current_price > 0 else 0
        
        # 计算建议仓位的价值
        recommended_value = recommended_size * account_value
        
        # 如果建议仓位价值超过硬锁定限制，则限制为硬锁定限制
        if recommended_value > max_position_value:
            # 返回硬锁定限制对应的仓位比例
            return max_position_size / (account_value / etf_current_price) if (account_value / etf_current_price) > 0 else 0
        
        return recommended_size
    
    except Exception as e:
        # 如果计算失败，返回0（最保守）
        return 0.0


def calculate_position_size(
    trend_strength: float,
    signal_confidence: float,
    current_positions: Dict[str, float],
    account_value: float = 100000,
    etf_current_price: float = 4.0,
    apply_hard_limit: bool = False,
    hard_limit_pct: Optional[float] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    计算建议仓位（融合原系统逻辑，支持硬锁定）
    
    Args:
        trend_strength: 趋势强度 (0-1)
        signal_confidence: 信号置信度 (0-1)
        current_positions: 当前持仓 {etf_symbol: position_size}
        account_value: 账户总值，默认100000
        etf_current_price: ETF当前价格，默认4.0
        apply_hard_limit: 是否应用硬锁定，默认True
        hard_limit_pct: 硬锁定百分比；传 None 表示不启用硬锁定
        config: 系统配置
    
    Returns:
        dict: {
            'recommended_size': float,  # 建议仓位 (0-1)
            'adjustment': str,          # 'increase' | 'decrease' | 'hold'
            'reason': str,
            'max_position': float,      # 最大仓位限制
            'hard_limit_applied': bool  # 是否应用了硬锁定
        }
    """
    try:
        # 使用原系统的计算逻辑
        if ORIGINAL_SYSTEM_AVAILABLE:
            try:
                if config is None:
                    config = load_system_config(use_cache=True)
                
                result = original_calculate_position_size(
                    trend_strength=trend_strength,
                    signal_confidence=signal_confidence,
                    current_positions=current_positions,
                    config=config
                )
                
                recommended_size = result.get('recommended_size', 0.0)
                
                # 应用硬锁定限制
                hard_limit_applied = False
                if apply_hard_limit and hard_limit_pct is not None:
                    original_size = recommended_size
                    recommended_size = apply_hard_position_limit(
                        recommended_size=recommended_size,
                        account_value=account_value,
                        etf_current_price=etf_current_price,
                        hard_limit_pct=hard_limit_pct
                    )
                    
                    if recommended_size < original_size:
                        hard_limit_applied = True
                        result['reason'] = f"{result.get('reason', '')}，已应用硬锁定限制（{hard_limit_pct:.0%}）"
                
                result['recommended_size'] = recommended_size
                result['hard_limit_applied'] = hard_limit_applied
                result['hard_limit_pct'] = hard_limit_pct
                
                return result
            
            except Exception as e:
                return {
                    'success': False,
                    'recommended_size': 0.0,
                    'adjustment': 'hold',
                    'reason': f'计算失败: {str(e)}',
                    'max_position': hard_limit_pct if (apply_hard_limit and hard_limit_pct is not None) else 0.8,
                    'hard_limit_applied': False,
                    'error': str(e)
                }
        else:
            # 简化版计算（不依赖原系统）
            # 根据趋势强度确定仓位范围
            if trend_strength >= 0.7:
                base_range = [0.5, 0.8]
                reason_base = "趋势强"
            elif trend_strength >= 0.4:
                base_range = [0.3, 0.5]
                reason_base = "趋势中"
            else:
                base_range = [0.0, 0.2]
                reason_base = "趋势弱"
            
            # 在范围内根据置信度调整仓位
            min_position = base_range[0]
            max_position = base_range[1]
            recommended_size = min_position + (max_position - min_position) * signal_confidence
            recommended_size = max(0.0, min(1.0, recommended_size))
            
            # 应用硬锁定限制
            hard_limit_applied = False
            if apply_hard_limit and hard_limit_pct is not None:
                original_size = recommended_size
                recommended_size = apply_hard_position_limit(
                    recommended_size=recommended_size,
                    account_value=account_value,
                    etf_current_price=etf_current_price,
                    hard_limit_pct=hard_limit_pct
                )
                
                if recommended_size < original_size:
                    hard_limit_applied = True
                    reason_base = f"{reason_base}，已应用硬锁定限制（{hard_limit_pct:.0%}）"
            
            return {
                'recommended_size': recommended_size,
                'adjustment': 'hold',
                'reason': f"{reason_base}，建议仓位: {recommended_size:.2%}",
                'max_position': hard_limit_pct if (apply_hard_limit and hard_limit_pct is not None) else 0.8,
                'hard_limit_applied': hard_limit_applied,
                'hard_limit_pct': hard_limit_pct
            }
    
    except Exception as e:
        return {
            'success': False,
            'recommended_size': 0.0,
            'adjustment': 'hold',
            'reason': f'计算失败: {str(e)}',
            'max_position': hard_limit_pct if (apply_hard_limit and hard_limit_pct is not None) else 0.8,
            'hard_limit_applied': False,
            'error': str(e)
        }


def check_position_limit(
    current_position_value: float,
    account_value: float,
    hard_limit_pct: Optional[float] = None
) -> Dict[str, Any]:
    """
    检查仓位是否超过硬锁定限制
    
    Args:
        current_position_value: 当前仓位价值
        account_value: 账户总值
        hard_limit_pct: 硬锁定百分比；传 None 表示不检查硬锁定
    
    Returns:
        dict: {
            'within_limit': bool,  # 是否在限制内
            'current_pct': float,   # 当前仓位百分比
            'hard_limit_pct': float, # 硬锁定百分比
            'excess_value': float,  # 超出限制的价值（如果超出）
            'recommendation': str   # 建议
        }
    """
    try:
        if hard_limit_pct is None:
            current_pct = current_position_value / account_value if account_value > 0 else 0
            return {
                'within_limit': True,
                'current_pct': float(current_pct),
                'hard_limit_pct': None,
                'excess_value': 0.0,
                'recommendation': "未启用硬锁定检查"
            }
        current_pct = current_position_value / account_value if account_value > 0 else 0
        within_limit = current_pct <= hard_limit_pct
        
        excess_value = 0.0
        if not within_limit:
            excess_value = current_position_value - (account_value * hard_limit_pct)
        
        recommendation = "仓位在限制内" if within_limit else f"仓位超出硬锁定限制，建议减仓{excess_value:.2f}元"
        
        return {
            'within_limit': within_limit,
            'current_pct': float(current_pct),
            'hard_limit_pct': float(hard_limit_pct),
            'excess_value': float(excess_value),
            'recommendation': recommendation
        }
    
    except Exception as e:
        return {
            'within_limit': True,
            'current_pct': 0.0,
            'hard_limit_pct': float(hard_limit_pct) if hard_limit_pct is not None else None,
            'excess_value': 0.0,
            'recommendation': f'检查失败: {str(e)}',
            'error': str(e)
        }


# OpenClaw 工具函数接口
def tool_calculate_position_size(
    trend_strength: Optional[float] = None,
    signal_confidence: Optional[float] = None,
    account_value: float = 100000,
    etf_current_price: Optional[float] = None,
    apply_hard_limit: bool = False,
    hard_limit_pct: Optional[float] = None
) -> Dict[str, Any]:
    """
    OpenClaw 工具：计算建议仓位（含硬锁定）
    
    Args:
        trend_strength: 趋势强度 (0-1)，如果为None则使用默认值0.0
        signal_confidence: 信号置信度 (0-1)，如果为None则使用默认值0.0
        account_value: 账户总值，默认100000
        etf_current_price: ETF当前价格，如果为None则使用默认值4.0
        apply_hard_limit: 是否应用硬锁定，默认True
        hard_limit_pct: 硬锁定百分比；传 None 表示不启用硬锁定
    
    Returns:
        dict: 包含仓位计算结果的字典
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 处理 None 值：当没有信号时，使用默认值（最保守的仓位）
    if trend_strength is None:
        logger.warning("trend_strength 为 None，使用默认值 0.0（无趋势）")
        trend_strength = 0.0
    
    if signal_confidence is None:
        logger.warning("signal_confidence 为 None，使用默认值 0.0（无置信度）")
        signal_confidence = 0.0
    
    if etf_current_price is None:
        logger.warning("etf_current_price 为 None，使用默认值 4.0")
        etf_current_price = 4.0
    
    # 如果趋势强度和信号置信度都为0，说明没有有效信号，返回保守仓位
    if trend_strength == 0.0 and signal_confidence == 0.0:
        logger.info("趋势强度和信号置信度都为0，返回保守仓位（0%）")
        return {
            'success': True,
            'recommended_size': 0.0,
            'position_size': 0,
            'position_value': 0.0,
            'position_pct': 0.0,
            'adjustment': 'hold',
            'reason': '无有效信号，建议保持空仓',
            'max_position': hard_limit_pct if (apply_hard_limit and hard_limit_pct is not None) else 0.8,
            'hard_limit_applied': False,
            'hard_limit_pct': hard_limit_pct,
            'trend_strength': trend_strength,
            'signal_confidence': signal_confidence
        }
    
    try:
        result = calculate_position_size(
            trend_strength=trend_strength,
            signal_confidence=signal_confidence,
            current_positions={},
            account_value=account_value,
            etf_current_price=etf_current_price,
            apply_hard_limit=apply_hard_limit,
            hard_limit_pct=hard_limit_pct
        )
        
        # 确保返回格式统一
        if 'success' not in result:
            result['success'] = True
        
        # 计算实际仓位数量和价值
        recommended_size = result.get('recommended_size', 0.0)
        position_value = recommended_size * account_value
        position_size = int(position_value / etf_current_price) if etf_current_price > 0 else 0
        position_pct = recommended_size
        
        result['position_size'] = position_size
        result['position_value'] = position_value
        result['position_pct'] = position_pct
        
        return result
        
    except Exception as e:
        logger.error(f"计算建议仓位失败: {e}", exc_info=True)
        return {
            'success': False,
            'recommended_size': 0.0,
            'position_size': 0,
            'position_value': 0.0,
            'position_pct': 0.0,
            'adjustment': 'hold',
            'reason': f'计算失败: {str(e)}',
            'max_position': hard_limit_pct if apply_hard_limit else 0.8,
            'hard_limit_applied': False,
            'error': str(e)
        }


def tool_check_position_limit(
    current_position_value: float,
    account_value: float,
    hard_limit_pct: Optional[float] = None
) -> Dict[str, Any]:
    """OpenClaw 工具：检查仓位是否超限"""
    return check_position_limit(
        current_position_value=current_position_value,
        account_value=account_value,
        hard_limit_pct=hard_limit_pct
    )


def tool_apply_hard_limit(
    recommended_size: float,
    account_value: float,
    etf_current_price: float,
    hard_limit_pct: Optional[float] = None
) -> Dict[str, Any]:
    """OpenClaw 工具：应用硬锁定限制"""
    try:
        adjusted_size = apply_hard_position_limit(
            recommended_size=recommended_size,
            account_value=account_value,
            etf_current_price=etf_current_price,
            hard_limit_pct=hard_limit_pct
        )
        
        return {
            'success': True,
            'original_size': recommended_size,
            'adjusted_size': adjusted_size,
            'hard_limit_pct': hard_limit_pct,
            'applied': adjusted_size < recommended_size
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
