"""
间接指导逻辑模块（GK优化）
结合指数趋势+区间+期权希腊/IV，生成间接交易建议
"""

from typing import Dict, Optional, Any, Union
from datetime import datetime
import pytz
import pandas as pd

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


def generate_indirect_guidance(
    index_trend: Dict[str, Any],
    index_range: Dict[str, Any],
    etf_current_price: float,
    call_option_price: Optional[float] = None,
    put_option_price: Optional[float] = None,
    call_iv: Optional[float] = None,
    put_iv: Optional[float] = None,
    call_greeks: Optional[Union[Dict[str, float], pd.DataFrame]] = None,
    put_greeks: Optional[Union[Dict[str, float], pd.DataFrame]] = None,
    etf_range: Optional[Dict[str, Any]] = None,
    index_current_price: Optional[float] = None
) -> Dict[str, Any]:
    """
    生成间接交易指导建议（GK优化）
    结合指数趋势+区间+期权希腊/IV，输出间接建议而非直接指令
    
    Args:
        index_trend: 指数趋势分析结果（包含direction, strength等）
        index_range: 指数波动区间（包含upper, lower等）
        etf_current_price: ETF当前价格
        call_option_price: Call期权当前价格
        put_option_price: Put期权当前价格
        call_iv: Call期权IV（百分比，如15.5表示15.5%）
        put_iv: Put期权IV（百分比）
        call_greeks: Call期权Greeks（包含delta, gamma, theta, vega等）
        put_greeks: Put期权Greeks
    
    Returns:
        dict: 间接指导建议
    """
    try:
        direction = index_trend.get('direction', '震荡')
        trend_strength = index_trend.get('strength', 0.5)
        index_upper = index_range.get('upper')
        index_lower = index_range.get('lower')
        
        # 判断价格在区间中的位置
        # 优先使用ETF区间，如果没有则使用指数区间（需要指数当前价格）
        price_position = 0.5  # 默认值
        current_price_for_position = None
        range_upper = None
        range_lower = None
        
        if etf_range and etf_range.get('upper') and etf_range.get('lower'):
            # 使用ETF区间
            range_upper = etf_range.get('upper')
            range_lower = etf_range.get('lower')
            current_price_for_position = etf_current_price
        elif index_upper and index_lower and index_current_price:
            # 使用指数区间（需要指数当前价格）
            range_upper = index_upper
            range_lower = index_lower
            current_price_for_position = index_current_price
        elif index_upper and index_lower:
            # 如果没有指数当前价格，尝试从指数区间数据中获取
            index_current = index_range.get('current_price')
            if index_current:
                range_upper = index_upper
                range_lower = index_lower
                current_price_for_position = index_current
        
        # 计算位置
        if range_upper and range_lower and current_price_for_position:
            range_width = range_upper - range_lower
            if range_width > 0:
                price_position = (current_price_for_position - range_lower) / range_width
                # 限制在0-1之间
                price_position = max(0.0, min(1.0, price_position))
            else:
                price_position = 0.5
        
        # 构建基础建议
        # 确定显示哪个区间（优先ETF区间）
        display_range = etf_range if etf_range and etf_range.get('upper') and etf_range.get('lower') else index_range
        display_current = etf_current_price if (etf_range and etf_range.get('upper')) else (index_current_price or index_range.get('current_price', etf_current_price))
        
        guidance = {
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),
            'index_trend': direction,
            'trend_strength': round(trend_strength, 2),
            'index_range': {
                'upper': round(display_range.get('upper', 0), 2) if display_range else round(index_upper or 0, 2),
                'lower': round(display_range.get('lower', 0), 2) if display_range else round(index_lower or 0, 2),
                'current': round(display_current, 2),
                'position': round(price_position, 4)  # 0-1，0为下轨，1为上轨，保留4位小数避免显示问题
            },
            'suggestions': [],
            'risk_warning': '设置5%止损，仅参考，不构成投资建议'
        }
        
        # 根据趋势和区间位置生成建议
        suggestions: list[Dict[str, Any]] = []
        
        # 获取用于显示的价格和区间
        display_upper = display_range.get('upper') if display_range else index_upper
        display_lower = display_range.get('lower') if display_range else index_lower
        
        # 1. 趋势判断建议
        if direction == "上行" or direction == "强势":
            if price_position > 0.8:  # 接近上轨
                suggestions.append({
                    'type': 'call_observation',
                    'message': f"指数{direction}趋势，当前价格({display_current:.2f})接近区间上轨({display_upper:.2f})。若突破上轨，可考虑观察Call期权机会。",
                    'condition': '突破上轨',
                    'action': '观察Call期权'
                })
            elif price_position < 0.3:  # 接近下轨
                suggestions.append({
                    'type': 'call_opportunity',
                    'message': f"指数{direction}趋势，当前价格({display_current:.2f})接近区间下轨({display_lower:.2f})，上行空间较大。可考虑观察Call期权。",
                    'condition': '接近下轨，上行空间大',
                    'action': '观察Call期权'
                })
            else:
                suggestions.append({
                    'type': 'call_hold',
                    'message': f"指数{direction}趋势，当前价格在区间中部，建议持有或观察，等待突破信号。",
                    'condition': '区间中部',
                    'action': '持有或观察'
                })
        
        elif direction == "下行" or direction == "弱势":
            if price_position < 0.2:  # 接近下轨
                suggestions.append({
                    'type': 'put_observation',
                    'message': f"指数{direction}趋势，当前价格({display_current:.2f})接近区间下轨({display_lower:.2f})。若突破下轨，可考虑观察Put期权机会。",
                    'condition': '突破下轨',
                    'action': '观察Put期权'
                })
            elif price_position > 0.7:  # 接近上轨
                suggestions.append({
                    'type': 'put_opportunity',
                    'message': f"指数{direction}趋势，当前价格({display_current:.2f})接近区间上轨({display_upper:.2f})，下行空间较大。可考虑观察Put期权。",
                    'condition': '接近上轨，下行空间大',
                    'action': '观察Put期权'
                })
            else:
                suggestions.append({
                    'type': 'put_hold',
                    'message': f"指数{direction}趋势，当前价格在区间中部，建议持有或观察，等待突破信号。",
                    'condition': '区间中部',
                    'action': '持有或观察'
                })
        
        else:  # 震荡
            suggestions.append({
                'type': 'straddle_observation',
                'message': f"指数震荡市，当前价格在区间[{display_lower:.2f}, {display_upper:.2f}]内。建议观察straddle策略或等待明确方向。",
                'condition': '震荡市',
                'action': '观察straddle或等待方向'
            })
        
        # 2. IV分析建议
        if call_iv is not None:
            # IV水平判断（简单阈值，可根据历史数据优化）
            if call_iv < 10:
                iv_level = "低位"
                iv_suggestion = "IV低位，Call期权价格相对便宜，但需注意时间价值衰减。"
            elif call_iv > 30:
                iv_level = "高位"
                iv_suggestion = "IV高位，Call期权价格较贵，需警惕IV回落风险。"
            else:
                iv_level = "中位"
                iv_suggestion = "IV中位，价格相对合理。"
            
            suggestions.append({
                'type': 'iv_analysis',
                'message': f"Call期权IV: {call_iv:.2f}% ({iv_level})。{iv_suggestion}",
                'iv': round(call_iv, 2),
                'iv_level': iv_level
            })
        
        if put_iv is not None:
            if put_iv < 10:
                iv_level = "低位"
                iv_suggestion = "IV低位，Put期权价格相对便宜，但需注意时间价值衰减。"
            elif put_iv > 30:
                iv_level = "高位"
                iv_suggestion = "IV高位，Put期权价格较贵，需警惕IV回落风险。"
            else:
                iv_level = "中位"
                iv_suggestion = "IV中位，价格相对合理。"
            
            suggestions.append({
                'type': 'iv_analysis',
                'message': f"Put期权IV: {put_iv:.2f}% ({iv_level})。{iv_suggestion}",
                'iv': round(put_iv, 2),
                'iv_level': iv_level
            })
        
        # 3. Greeks分析建议（如果可用）
        # 处理 call_greeks（可能是 DataFrame 或字典）
        if call_greeks is not None:
            # 如果是 DataFrame，转换为字典
            if isinstance(call_greeks, pd.DataFrame):
                if call_greeks.empty:
                    call_greeks = None
                else:
                    # 从 DataFrame 中提取 Greeks 值
                    call_greeks_dict: Dict[str, Any] = {}
                    for idx, row in call_greeks.iterrows():
                        field = str(row.get('字段', '')).lower()
                        value = row.get('值', '')
                        try:
                            if 'delta' in field:
                                call_greeks_dict['delta'] = float(value) if value else 0
                            elif 'gamma' in field:
                                call_greeks_dict['gamma'] = abs(float(value)) if value else 0
                            elif 'theta' in field:
                                call_greeks_dict['theta'] = float(value) if value else 0
                            elif 'vega' in field:
                                call_greeks_dict['vega'] = abs(float(value)) if value else 0
                            elif 'iv' in field or '波动率' in field or 'implied' in field:
                                call_greeks_dict['iv'] = float(value) if value else None
                        except (ValueError, TypeError):
                            continue
                    call_greeks = call_greeks_dict if call_greeks_dict else None
            
            # 如果是字典，直接使用
            if isinstance(call_greeks, dict):
                delta = call_greeks.get('delta', 0) or 0
                gamma = call_greeks.get('gamma', 0) or 0
                theta = call_greeks.get('theta', 0) or 0
                vega = call_greeks.get('vega', 0) or 0
                
                greeks_suggestion = []
                if delta is not None and abs(delta) > 0.5:
                    greeks_suggestion.append(f"Delta较高({delta:.2f})，对价格变化敏感")
                if gamma is not None and abs(gamma) > 0.1:
                    greeks_suggestion.append(f"Gamma较高({gamma:.2f})，Delta变化快")
                if theta is not None and abs(theta) > 0.01:
                    greeks_suggestion.append(f"Theta较高({theta:.2f})，时间价值衰减快")
                if vega is not None and abs(vega) > 0.1:
                    greeks_suggestion.append(f"Vega较高({vega:.2f})，对IV变化敏感")
                
                if greeks_suggestion:
                    suggestions.append({
                        'type': 'greeks_analysis',
                        'message': f"Call期权Greeks: {', '.join(greeks_suggestion)}。",
                        'greeks': call_greeks
                    })
        
        # 处理 put_greeks（可能是 DataFrame 或字典）
        if put_greeks is not None:
            # 如果是 DataFrame，转换为字典
            if isinstance(put_greeks, pd.DataFrame):
                if put_greeks.empty:
                    put_greeks = None
                else:
                    # 从 DataFrame 中提取 Greeks 值
                    put_greeks_dict: Dict[str, Any] = {}
                    for idx, row in put_greeks.iterrows():
                        field = str(row.get('字段', '')).lower()
                        value = row.get('值', '')
                        try:
                            if 'delta' in field:
                                put_greeks_dict['delta'] = float(value) if value else 0
                            elif 'gamma' in field:
                                put_greeks_dict['gamma'] = abs(float(value)) if value else 0
                            elif 'theta' in field:
                                put_greeks_dict['theta'] = float(value) if value else 0
                            elif 'vega' in field:
                                put_greeks_dict['vega'] = abs(float(value)) if value else 0
                            elif 'iv' in field or '波动率' in field or 'implied' in field:
                                put_greeks_dict['iv'] = float(value) if value else None
                        except (ValueError, TypeError):
                            continue
                    put_greeks = put_greeks_dict if put_greeks_dict else None
            
            # 如果是字典，直接使用
            if isinstance(put_greeks, dict):
                delta = put_greeks.get('delta', 0) or 0
                gamma = put_greeks.get('gamma', 0) or 0
                theta = put_greeks.get('theta', 0) or 0
                vega = put_greeks.get('vega', 0) or 0
                
                greeks_suggestion = []
                if delta is not None and delta < -0.5:
                    greeks_suggestion.append(f"Delta较低({delta:.2f})，对价格下跌敏感")
                if gamma is not None and abs(gamma) > 0.1:
                    greeks_suggestion.append(f"Gamma较高({gamma:.2f})，Delta变化快")
                if theta is not None and abs(theta) > 0.01:
                    greeks_suggestion.append(f"Theta较高({theta:.2f})，时间价值衰减快")
                if vega is not None and abs(vega) > 0.1:
                    greeks_suggestion.append(f"Vega较高({vega:.2f})，对IV变化敏感")
                
                if greeks_suggestion:
                    suggestions.append({
                        'type': 'greeks_analysis',
                        'message': f"Put期权Greeks: {', '.join(greeks_suggestion)}。",
                        'greeks': put_greeks
                    })
        
        guidance['suggestions'] = suggestions
        
        # 生成综合建议文本
        summary_parts = []
        summary_parts.append(f"指数{direction}趋势（强度{trend_strength:.2f}），波动区间[{display_lower:.2f}, {display_upper:.2f}]。")
        
        for suggestion in suggestions[:3]:  # 只取前3个最重要的建议
            # 包含所有趋势判断相关的建议类型
            if suggestion['type'] in ['call_observation', 'call_opportunity', 'call_hold', 
                                     'put_observation', 'put_opportunity', 'put_hold', 
                                     'straddle_observation']:
                summary_parts.append(suggestion['message'])
        
        guidance['summary'] = ' '.join(summary_parts)
        guidance['summary'] += f" {guidance['risk_warning']}"
        
        logger.info(f"生成间接指导: {guidance['summary'][:100]}...")
        
        return guidance
        
    except Exception as e:
        logger.error(f"生成间接指导失败: {e}", exc_info=True)
        return {
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e),
            'summary': '间接指导生成失败，请参考其他信号'
        }
