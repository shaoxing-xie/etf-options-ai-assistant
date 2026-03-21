"""
ETF风险控制模块
止盈止损规则，生成止盈止损信号提醒
"""

from typing import Dict, Any, Optional
from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


def calculate_stop_loss_take_profit(
    entry_price: float,
    current_price: float,
    trend_direction: str,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    计算止盈止损价格
    
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
    
    规则：
    - 固定止损：亏损超过5%止损
    - 固定止盈：盈利超过5%止盈
    - 跟踪止盈：盈利超过3%后，跟踪最高价，回撤3%止盈
    - 趋势转弱止盈：MACD死叉或跌破20日线止盈
    """
    try:
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        etf_config = config.get('etf_trading', {})
        risk_config = etf_config.get('risk_management', {})
        
        stop_loss_pct = risk_config.get('stop_loss_pct', 0.05)  # 默认5%
        take_profit_pct = risk_config.get('take_profit_pct', 0.05)  # 默认5%
        trailing_stop_pct = risk_config.get('trailing_stop_pct', 0.03)  # 默认3%
        
        if trend_direction == 'up':
            # 买入信号：做多
            stop_loss = entry_price * (1 - stop_loss_pct)  # 亏损5%止损
            take_profit = entry_price * (1 + take_profit_pct)  # 盈利5%止盈
        elif trend_direction == 'down':
            # 卖出信号：做空
            stop_loss = entry_price * (1 + stop_loss_pct)  # 亏损5%止损
            take_profit = entry_price * (1 - take_profit_pct)  # 盈利5%止盈
        else:
            # 中性信号：不设置止盈止损
            stop_loss = None
            take_profit = None
        
        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'stop_loss_pct': stop_loss_pct,
            'take_profit_pct': take_profit_pct,
            'trailing_stop_pct': trailing_stop_pct,
            'entry_price': entry_price,
            'current_price': current_price,
            'trend_direction': trend_direction
        }
        
    except Exception as e:
        logger.error(f"计算止盈止损失败: {e}", exc_info=True)
        return {
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
    highest_price: float,  # 持仓期间最高价
    trend_signals: Dict[str, Any],
    config: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    检查是否触发止盈止损，生成信号提醒
    
    Args:
        etf_symbol: ETF代码
        entry_price: 入场价格
        current_price: 当前价格
        highest_price: 持仓期间最高价
        trend_signals: 趋势信号（用于判断趋势转弱）
        config: 系统配置
    
    Returns:
        dict: {
            'signal_type': 'stop_loss' | 'take_profit',
            'trigger_price': float,
            'current_price': float,
            'profit_loss_pct': float,
            'reason': str
        } 或 None（如果未触发）
    
    触发条件：
    - 固定止损：当前价 <= 止损价
    - 固定止盈：当前价 >= 止盈价
    - 跟踪止盈：当前价 <= 最高价 * (1 - 0.03)
    - 趋势转弱：MACD死叉或跌破20日线
    """
    try:
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        etf_config = config.get('etf_trading', {})
        risk_config = etf_config.get('risk_management', {})
        
        stop_loss_pct = risk_config.get('stop_loss_pct', 0.05)
        take_profit_pct = risk_config.get('take_profit_pct', 0.05)
        trailing_stop_pct = risk_config.get('trailing_stop_pct', 0.03)
        
        # 判断是做多还是做空（根据入场价格和当前价格的关系）
        is_long = current_price >= entry_price  # 假设买入为做多
        
        # 1. 检查固定止损
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
        
        # 2. 检查固定止盈
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
        
        # 3. 检查跟踪止盈（盈利超过3%后）
        if is_long:
            profit_pct = (current_price - entry_price) / entry_price
            if profit_pct >= trailing_stop_pct:
                # 盈利超过3%，开始跟踪止盈
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
        
        # 4. 检查趋势转弱（需要从trend_signals中获取MACD和MA20信号）
        # 这里简化处理，实际应该从trend_signals中获取技术指标信号
        # 如果MACD死叉或跌破20日线，建议止盈
        if trend_signals:
            technical_signals = trend_signals.get('technical_signal', {})
            if technical_signals:
                signals = technical_signals.get('signals', {})
                if signals.get('macd') == 'death_cross' or signals.get('ma20') == 'below':
                    profit_loss_pct = (current_price - entry_price) / entry_price if is_long else (entry_price - current_price) / entry_price
                    return {
                        'signal_type': 'take_profit',
                        'trigger_price': current_price,
                        'current_price': current_price,
                        'profit_loss_pct': profit_loss_pct,
                        'reason': '趋势转弱（MACD死叉或跌破20日线），建议止盈',
                        'etf_symbol': etf_symbol
                    }
        
        # 未触发任何止盈止损
        return None
        
    except Exception as e:
        logger.error(f"检查止盈止损失败: {e}", exc_info=True)
        return None
