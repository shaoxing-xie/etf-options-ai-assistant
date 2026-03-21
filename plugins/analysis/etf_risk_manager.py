"""
ETF风险管理插件
止盈止损规则，生成止盈止损信号提醒
融合原系统 etf_risk_manager.py
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
    # 导入原系统的风险管理模块
    from src.etf_risk_manager import (
        calculate_stop_loss_take_profit as original_calculate_stop_loss_take_profit,
        check_stop_loss_take_profit as original_check_stop_loss_take_profit
    )
    from src.config_loader import load_system_config
    ORIGINAL_SYSTEM_AVAILABLE = True
except ImportError as e:
    ORIGINAL_SYSTEM_AVAILABLE = False
    IMPORT_ERROR = str(e)


def calculate_stop_loss_take_profit(
    entry_price: float,
    current_price: float,
    trend_direction: str,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    计算止盈止损价格（融合原系统逻辑）
    
    Args:
        entry_price: 入场价格
        current_price: 当前价格
        trend_direction: 趋势方向 'up' | 'down'
        config: 系统配置
    
    Returns:
        dict: {
            'stop_loss': float,      # 止损价格
            'take_profit': float,    # 止盈价格
            'stop_loss_pct': float,  # 止损比例（默认5%）
            'take_profit_pct': float # 止盈比例（默认5%）
        }
    """
    try:
        if ORIGINAL_SYSTEM_AVAILABLE:
            try:
                if config is None:
                    config = load_system_config(use_cache=True)
                
                return original_calculate_stop_loss_take_profit(
                    entry_price=entry_price,
                    current_price=current_price,
                    trend_direction=trend_direction,
                    config=config
                )
            except Exception as e:
                return {
                    'success': False,
                    'stop_loss': None,
                    'take_profit': None,
                    'stop_loss_pct': 0.05,
                    'take_profit_pct': 0.05,
                    'error': str(e)
                }
        else:
            # 简化版计算（不依赖原系统）
            stop_loss_pct = 0.05  # 默认5%
            take_profit_pct = 0.05  # 默认5%
            
            if trend_direction == 'up':
                stop_loss = entry_price * (1 - stop_loss_pct)
                take_profit = entry_price * (1 + take_profit_pct)
            elif trend_direction == 'down':
                stop_loss = entry_price * (1 + stop_loss_pct)
                take_profit = entry_price * (1 - take_profit_pct)
            else:
                stop_loss = None
                take_profit = None
            
            return {
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'stop_loss_pct': stop_loss_pct,
                'take_profit_pct': take_profit_pct,
                'entry_price': entry_price,
                'current_price': current_price,
                'trend_direction': trend_direction
            }
    
    except Exception as e:
        return {
            'success': False,
            'stop_loss': None,
            'take_profit': None,
            'stop_loss_pct': 0.05,
            'take_profit_pct': 0.05,
            'error': str(e)
        }


def check_stop_loss_take_profit(
    etf_symbol: str,
    entry_price: float,
    current_price: float,
    highest_price: float,
    trend_signals: Optional[Dict[str, Any]] = None,
    config: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    检查是否触发止盈止损，生成信号提醒（融合原系统逻辑）
    
    Args:
        etf_symbol: ETF代码
        entry_price: 入场价格
        current_price: 当前价格
        highest_price: 持仓期间最高价
        trend_signals: 趋势信号（用于判断趋势转弱）
        config: 系统配置
    
    Returns:
        dict: 止盈止损信号或None
    """
    try:
        if ORIGINAL_SYSTEM_AVAILABLE:
            try:
                if config is None:
                    config = load_system_config(use_cache=True)
                
                return original_check_stop_loss_take_profit(
                    etf_symbol=etf_symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    highest_price=highest_price,
                    trend_signals=trend_signals or {},
                    config=config
                )
            except Exception as e:
                return None
        else:
            # 简化版检查（不依赖原系统）
            stop_loss_pct = 0.05
            take_profit_pct = 0.05
            trailing_stop_pct = 0.03
            
            # 判断是做多还是做空
            is_long = current_price >= entry_price
            
            # 检查固定止损
            if is_long:
                stop_loss_price = entry_price * (1 - stop_loss_pct)
                if current_price <= stop_loss_price:
                    profit_loss_pct = (current_price - entry_price) / entry_price
                    return {
                        'signal_type': 'stop_loss',
                        'trigger_price': stop_loss_price,
                        'current_price': current_price,
                        'profit_loss_pct': profit_loss_pct,
                        'reason': f'触发固定止损，亏损{abs(profit_loss_pct):.2%}',
                        'etf_symbol': etf_symbol
                    }
            else:
                stop_loss_price = entry_price * (1 + stop_loss_pct)
                if current_price >= stop_loss_price:
                    profit_loss_pct = (current_price - entry_price) / entry_price
                    return {
                        'signal_type': 'stop_loss',
                        'trigger_price': stop_loss_price,
                        'current_price': current_price,
                        'profit_loss_pct': profit_loss_pct,
                        'reason': f'触发固定止损，亏损{abs(profit_loss_pct):.2%}',
                        'etf_symbol': etf_symbol
                    }
            
            # 检查固定止盈
            if is_long:
                take_profit_price = entry_price * (1 + take_profit_pct)
                if current_price >= take_profit_price:
                    profit_loss_pct = (current_price - entry_price) / entry_price
                    return {
                        'signal_type': 'take_profit',
                        'trigger_price': take_profit_price,
                        'current_price': current_price,
                        'profit_loss_pct': profit_loss_pct,
                        'reason': f'触发固定止盈，盈利{profit_loss_pct:.2%}',
                        'etf_symbol': etf_symbol
                    }
            else:
                take_profit_price = entry_price * (1 - take_profit_pct)
                if current_price <= take_profit_price:
                    profit_loss_pct = (current_price - entry_price) / entry_price
                    return {
                        'signal_type': 'take_profit',
                        'trigger_price': take_profit_price,
                        'current_price': current_price,
                        'profit_loss_pct': profit_loss_pct,
                        'reason': f'触发固定止盈，盈利{abs(profit_loss_pct):.2%}',
                        'etf_symbol': etf_symbol
                    }
            
            # 检查跟踪止盈
            if is_long:
                profit_pct = (current_price - entry_price) / entry_price
                if profit_pct >= trailing_stop_pct:
                    trailing_stop_price = highest_price * (1 - trailing_stop_pct)
                    if current_price <= trailing_stop_price:
                        profit_loss_pct = (current_price - entry_price) / entry_price
                        return {
                            'signal_type': 'take_profit',
                            'trigger_price': trailing_stop_price,
                            'current_price': current_price,
                            'profit_loss_pct': profit_loss_pct,
                            'reason': f'触发跟踪止盈，从最高价{highest_price:.2f}回撤{trailing_stop_pct:.0%}',
                            'etf_symbol': etf_symbol
                        }
            
            return None
    
    except Exception as e:
        return None


# OpenClaw 工具函数接口
def tool_calculate_stop_loss_take_profit(
    entry_price: float,
    current_price: float,
    trend_direction: str
) -> Dict[str, Any]:
    """OpenClaw 工具：计算止盈止损价格"""
    return calculate_stop_loss_take_profit(
        entry_price=entry_price,
        current_price=current_price,
        trend_direction=trend_direction
    )


def tool_check_stop_loss_take_profit(
    etf_symbol: str,
    entry_price: float,
    current_price: float,
    highest_price: float
) -> Dict[str, Any]:
    """OpenClaw 工具：检查是否触发止盈止损"""
    result = check_stop_loss_take_profit(
        etf_symbol=etf_symbol,
        entry_price=entry_price,
        current_price=current_price,
        highest_price=highest_price
    )
    
    if result:
        return {
            'success': True,
            'triggered': True,
            'data': result
        }
    else:
        return {
            'success': True,
            'triggered': False,
            'data': None
        }
