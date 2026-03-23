"""
风险评估
融合 Coze 插件 risk_assessment.py
OpenClaw 插件工具
"""

import sys
import os
from typing import Optional, Dict, Any
from datetime import datetime
import math

# 添加父目录到路径以导入read_cache_data
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, parent_dir)

try:
    from plugins.data_access.read_cache_data import read_cache_data
except ImportError:
    read_cache_data = None


def assess_risk(
    symbol: str = "510300",
    position_size: float = 10000,
    entry_price: float = 4.0,
    stop_loss: Optional[float] = None,
    account_value: float = 100000,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    风险评估（融合 Coze risk_assessment.py）
    
    Args:
        symbol: 标的代码（ETF代码）
        position_size: 持仓数量
        entry_price: 入场价格
        stop_loss: 止损价格（可选）
        account_value: 账户总值
        api_base_url: 原系统 API 基础地址
        api_key: API Key
    
    Returns:
        Dict: 包含风险评估结果的字典
    """
    try:
        # 验证ETF代码
        if not symbol or (not symbol.startswith("51") and not symbol.startswith("159")):
            return {
                'success': False,
                'message': 'symbol必须是ETF代码（上海ETF: 51xxxx，深圳ETF: 159xxx）',
                'data': None
            }
        
        # 计算日期范围
        from datetime import timedelta
        import pytz
        tz_shanghai = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz_shanghai)
        end_date = now.strftime('%Y%m%d')
        start_date = (now - timedelta(days=60)).strftime('%Y%m%d')
        
        # 读取缓存数据计算波动率
        if read_cache_data:
            data_type = "etf_daily"
            cache_result = read_cache_data(
                data_type=data_type,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                return_df=True,
            )
            
            if cache_result.get('success') and cache_result.get('df') is not None:
                df = cache_result['df']
                if not df.empty and 'close' in df.columns:
                    closes = df['close'].tolist()
                else:
                    closes = []
            else:
                closes = []
        else:
            closes = []
        
        # 计算波动率
        volatility = 0.0
        if len(closes) >= 20:
            returns = []
            for i in range(1, min(21, len(closes))):
                if closes[i-1] > 0:
                    ret = math.log(closes[i] / closes[i-1])
                    returns.append(ret)
            
            if len(returns) >= 10:
                mean_return = sum(returns) / len(returns)
                variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
                volatility = math.sqrt(variance) * math.sqrt(252)  # 年化波动率
        
        # 计算仓位比例
        position_value = position_size * entry_price
        position_ratio = position_value / account_value if account_value > 0 else 0
        
        # 计算止损（如果未提供）
        if stop_loss is None:
            if volatility > 0:
                stop_loss = entry_price * (1 - volatility * 1.5)
            else:
                stop_loss = entry_price * 0.97
        
        # 计算风险指标
        risk_amount = abs(entry_price - stop_loss) * position_size
        risk_ratio = risk_amount / account_value if account_value > 0 else 0
        
        # 凯利公式计算最优仓位（简化版）
        win_rate = 0.55  # 假设胜率
        avg_win = 0.02  # 假设平均盈利2%
        avg_loss = abs((entry_price - stop_loss) / entry_price)  # 平均亏损
        kelly_ratio = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win if avg_win > 0 else 0
        kelly_ratio = max(0, min(kelly_ratio, 0.25))  # 限制在0-25%
        
        # 风险评估等级
        if risk_ratio > 0.1:
            risk_level = "high"
        elif risk_ratio > 0.05:
            risk_level = "medium"
        else:
            risk_level = "low"
        
        # 生成建议
        recommendations = []
        if position_ratio > 0.3:
            recommendations.append("仓位比例较高，建议降低仓位")
        if risk_ratio > 0.1:
            recommendations.append("风险比例过高，建议设置更严格的止损")
        if volatility > 0.3:
            recommendations.append("波动率较高，建议谨慎操作")
        
        return {
            'success': True,
            'message': 'Successfully assessed risk',
            'data': {
                'symbol': symbol,
                'position_size': position_size,
                'entry_price': round(entry_price, 4),
                'stop_loss': round(stop_loss, 4),
                'position_value': round(position_value, 2),
                'position_ratio': round(position_ratio * 100, 2),
                'risk_amount': round(risk_amount, 2),
                'risk_ratio': round(risk_ratio * 100, 2),
                'volatility': round(volatility * 100, 2),
                'risk_level': risk_level,
                'kelly_optimal_position': round(kelly_ratio * 100, 2),
                'recommendations': recommendations,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


# OpenClaw 工具函数接口
def tool_assess_risk(
    symbol: str = "510300",
    position_size: float = 10000,
    entry_price: float = 4.0,
    stop_loss: Optional[float] = None,
    account_value: float = 100000
) -> Dict[str, Any]:
    """OpenClaw 工具：风险评估"""
    return assess_risk(
        symbol=symbol,
        position_size=position_size,
        entry_price=entry_price,
        stop_loss=stop_loss,
        account_value=account_value
    )
