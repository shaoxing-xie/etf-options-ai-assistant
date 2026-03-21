"""
ETF信号生成模块
整合多模型预测结果，生成ETF交易信号
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from src.logger_config import get_module_logger
from src.etf_models import (
    ProphetETFModel,
    predict_etf_trend_arima,
    generate_technical_signal
)
from src.indicator_calculator import calculate_ma, calculate_macd, calculate_volume_ma
from src.data_collector import fetch_etf_minute_data_with_fallback
from datetime import datetime
import pytz

logger = get_module_logger(__name__)


def generate_daily_etf_signals(
    etf_symbol: str,
    etf_daily_data: pd.DataFrame,
    etf_minute_30m: Optional[pd.DataFrame],
    etf_current_price: float,
    config: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    """
    生成日频ETF交易信号（主函数）
    
    Args:
        etf_symbol: ETF代码（如 "510300"）
        etf_daily_data: ETF日线数据
        etf_minute_30m: ETF 30分钟数据
        etf_current_price: ETF当前价格
        config: 系统配置
    
    Returns:
        list: 信号列表，每个信号包含：
            - signal_type: "买入" | "卖出" | "持有"
            - confidence: 置信度 (0-1)
            - position_size: 建议仓位 (0-1)
            - stop_loss: 止损价格
            - take_profit: 止盈价格
            - reason: 信号原因
            - etf_symbol: ETF代码
            - timestamp: 信号生成时间
    """
    try:
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        etf_config = config.get('etf_trading', {})
        model_weights = etf_config.get('model_weights', {
            'prophet': 0.35,
            'arima': 0.3,
            'technical': 0.35
        })
        voting_threshold = etf_config.get('voting_threshold', 0.6)
        min_agreements = etf_config.get('min_agreements', 2)  # 至少2个模型同意
        
        # 1. 多模型预测
        logger.info(f"开始生成ETF信号: {etf_symbol}")
        
        # Prophet模型预测
        try:
            prophet_model = ProphetETFModel()
            prophet_signal = prophet_model.predict_trend(etf_daily_data, forecast_days=5)
        except Exception as e:
            logger.warning(f"Prophet模型预测失败: {e}，使用中性信号")
            prophet_signal = {'direction': 'neutral', 'confidence': 0.5}
        
        # ARIMA模型预测
        try:
            arima_signal = predict_etf_trend_arima(etf_daily_data)
        except Exception as e:
            logger.warning(f"ARIMA模型预测失败: {e}，使用中性信号")
            arima_signal = {'direction': 'neutral', 'confidence': 0.5}
        
        # 技术指标模型预测
        try:
            technical_signal = generate_technical_signal(etf_daily_data, etf_minute_30m)
        except Exception as e:
            logger.warning(f"技术指标模型预测失败: {e}，使用中性信号")
            technical_signal = {'direction': 'neutral', 'confidence': 0.5}
        
        # GROK建议：添加调试日志，记录每个模型的原始输出
        logger.info(f"[DEBUG-VOTE] 模型原始输出 - Prophet: dir={prophet_signal.get('direction', 'none')}, conf={prophet_signal.get('confidence', 0):.3f}")
        logger.info(f"[DEBUG-VOTE] 模型原始输出 - ARIMA  : dir={arima_signal.get('direction', 'none')}, conf={arima_signal.get('confidence', 0):.3f}")
        logger.info(f"[DEBUG-VOTE] 模型原始输出 - Tech   : dir={technical_signal.get('direction', 'none')}, conf={technical_signal.get('confidence', 0):.3f}")
        
        # 2. 多模型投票
        voting_result = _multi_model_voting(
            prophet_signal=prophet_signal,
            arima_signal=arima_signal,
            technical_signal=technical_signal,
            weights=model_weights,
            threshold=voting_threshold,
            min_agreements=min_agreements
        )
        
        # 记录投票结果
        logger.info(f"多模型投票结果: 方向={voting_result.get('direction', 'neutral')}, "
                   f"置信度={voting_result.get('confidence', 0.5):.2f}, "
                   f"加权得分={voting_result.get('weighted_score', 0):.4f}, "
                   f"同意数={voting_result.get('agreements', 0)}, "
                   f"趋势强度={voting_result.get('trend_strength', 0.5):.2f}, "
                   f"信号类型={voting_result.get('signal_type', 'unknown')}")
        
        # 3. 短周期择时确认
        timing_result = None
        if etf_minute_30m is not None and not etf_minute_30m.empty:
            timing_result = _short_cycle_timing(
                etf_minute_30m=etf_minute_30m,
                etf_current_price=etf_current_price,
                config=config
            )
        
        # 4. 生成最终信号
        signals = []
        
        # 如果投票结果为中性，也生成"持有"信号并返回
        if voting_result['direction'] == 'neutral':
            logger.info(f"投票结果为中性，生成持有信号: 加权得分={voting_result.get('weighted_score', 0):.4f}, "
                       f"同意数={voting_result.get('agreements', 0)}")
            signals.append({
                'signal_type': '持有',
                'confidence': voting_result['confidence'],
                'position_size': 0.0,
                'stop_loss': None,
                'take_profit': None,
                'reason': voting_result.get('signal_meaning', '所有模型均为中性，建议持有'),
                'etf_symbol': etf_symbol,
                'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                'voting_result': voting_result,
                'timing_result': timing_result,
                'model_details': voting_result.get('model_details', {}),  # 各模型详细信息
                'weighted_score': voting_result.get('weighted_score', 0.0),  # 综合得分
                'signal_meaning': voting_result.get('signal_meaning', '所有模型均为中性，建议持有')  # 信号意义
            })
            return signals
        
        # 如果短周期择时未确认，降低信号强度
        if timing_result and not timing_result.get('confirmed', False):
            logger.info(f"短周期择时未确认，降低信号强度")
            voting_result['confidence'] *= 0.7  # 降低30%置信度
        
        # 确定信号类型
        if voting_result['direction'] == 'up':
            signal_type = '买入'
        elif voting_result['direction'] == 'down':
            signal_type = '卖出'
        else:
            signal_type = '持有'
        
        # GROK建议：震荡市买入过滤（震荡市买入胜率0%，应提前处理）
        if signal_type == '买入':
            try:
                from src.indicator_calculator import calculate_atr
                atr = calculate_atr(etf_daily_data, period=14)
                if atr is not None and not atr.empty and len(atr) >= 20:
                    atr_current = atr.iloc[-1]
                    atr_mean = atr.rolling(window=20, min_periods=20).mean().iloc[-1]
                    if atr_mean > 0 and atr_current < atr_mean * 0.85:  # 震荡市：当前ATR < 20日均ATR * 0.85
                        signal_type = '持有'
                        voting_result['signal_meaning'] = voting_result.get('signal_meaning', '') + " | 震荡市，买入信号降级为持有"
                        logger.info(f"[DEBUG-VOTE] 震荡市过滤: ATR当前={atr_current:.4f}, ATR均值={atr_mean:.4f}, 买入信号降级为持有")
            except Exception as e:
                logger.debug(f"震荡市过滤失败: {e}，继续使用原信号")
        
        # 计算建议仓位（根据置信度和趋势强度）
        from src.etf_position_manager import calculate_position_size
        position_result = calculate_position_size(
            trend_strength=voting_result.get('trend_strength', voting_result['confidence']),
            signal_confidence=voting_result['confidence'],
            current_positions={},  # 暂时不考虑当前持仓
            config=config
        )
        
        # 计算止盈止损
        from src.etf_risk_manager import calculate_stop_loss_take_profit
        risk_result = calculate_stop_loss_take_profit(
            entry_price=etf_current_price,
            current_price=etf_current_price,
            trend_direction=voting_result['direction'],
            config=config
        )
        
        # 生成信号
        signal = {
            'signal_type': signal_type,
            'confidence': voting_result['confidence'],
            'position_size': position_result.get('recommended_size', 0.5),
            'stop_loss': risk_result.get('stop_loss'),
            'take_profit': risk_result.get('take_profit'),
            'reason': voting_result.get('signal_meaning', f"多模型投票: {voting_result['direction']}, 置信度: {voting_result['confidence']:.2f}"),
            'etf_symbol': etf_symbol,
            'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
            'voting_result': voting_result,
            'timing_result': timing_result,
            'position_result': position_result,
            'risk_result': risk_result,
            'model_details': voting_result.get('model_details', {}),  # 各模型详细信息
            'weighted_score': voting_result.get('weighted_score', 0.0),  # 综合得分
            'signal_meaning': voting_result.get('signal_meaning', '')  # 信号意义
        }
        
        signals.append(signal)
        
        logger.info(f"ETF信号生成完成: {etf_symbol}, 信号类型: {signal_type}, 置信度: {voting_result['confidence']:.2f}")
        
        return signals
        
    except Exception as e:
        logger.error(f"生成ETF信号失败: {etf_symbol}, 错误: {e}", exc_info=True)
        return [{
            'signal_type': '持有',
            'confidence': 0.5,
            'position_size': 0.0,
            'stop_loss': None,
            'take_profit': None,
            'reason': f'信号生成失败: {str(e)}',
            'etf_symbol': etf_symbol,
            'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
            'error': str(e)
        }]


def _multi_model_voting(
    prophet_signal: Dict,
    arima_signal: Dict,
    technical_signal: Dict,
    weights: Dict[str, float],
    threshold: float = 0.6,
    min_agreements: int = 2
) -> Dict[str, Any]:
    """
    多模型投票机制
    
    Args:
        prophet_signal: Prophet模型信号 {'direction': 'up'|'down'|'neutral', 'confidence': float}
        arima_signal: ARIMA模型信号（同上）
        technical_signal: 技术指标信号（同上）
        weights: 模型权重 {'prophet': 0.35, 'arima': 0.3, 'technical': 0.35}
        threshold: 加权得分阈值（默认0.6）
    
    Returns:
        dict: 最终信号 {
            'direction': 'up' | 'down' | 'neutral',
            'confidence': float,
            'weighted_score': float,
            'trend_strength': float
        }
    
    投票规则：
    - 加权得分 = sum(模型信号得分 * 权重 * 置信度)
    - 加权得分 > threshold 才生成信号
    - 至少2个模型同意才生成信号
    """
    try:
        direction_scores = {'up': 1, 'down': -1, 'neutral': 0}
        
        # 记录每个模型的输入
        prophet_dir = prophet_signal.get('direction', 'neutral')
        prophet_conf = prophet_signal.get('confidence', 0.5)
        arima_dir = arima_signal.get('direction', 'neutral')
        arima_conf = arima_signal.get('confidence', 0.5)
        technical_dir = technical_signal.get('direction', 'neutral')
        technical_conf = technical_signal.get('confidence', 0.5)
        
        logger.debug(f"多模型投票输入: Prophet={prophet_dir}({prophet_conf:.2f}), "
                    f"ARIMA={arima_dir}({arima_conf:.2f}), "
                    f"Technical={technical_dir}({technical_conf:.2f}), "
                    f"threshold={threshold}")
        
        # 计算每个模型的得分
        prophet_score = direction_scores.get(prophet_dir, 0) * \
                       weights.get('prophet', 0.35) * \
                       prophet_conf
        
        arima_score = direction_scores.get(arima_dir, 0) * \
                     weights.get('arima', 0.3) * \
                     arima_conf
        
        technical_score = direction_scores.get(technical_dir, 0) * \
                         weights.get('technical', 0.35) * \
                         technical_conf
        
        weighted_score = prophet_score + arima_score + technical_score
        
        logger.debug(f"模型得分: Prophet={prophet_score:.4f}, ARIMA={arima_score:.4f}, "
                    f"Technical={technical_score:.4f}, 加权总分={weighted_score:.4f}")
        
        # 检查模型同意情况
        agreements = 0
        if prophet_dir == 'up' and weighted_score > 0:
            agreements += 1
        elif prophet_dir == 'down' and weighted_score < 0:
            agreements += 1
        
        if arima_dir == 'up' and weighted_score > 0:
            agreements += 1
        elif arima_dir == 'down' and weighted_score < 0:
            agreements += 1
        
        if technical_dir == 'up' and weighted_score > 0:
            agreements += 1
        elif technical_dir == 'down' and weighted_score < 0:
            agreements += 1
        
        logger.debug(f"模型同意数: {agreements}, 加权得分: {weighted_score:.4f}, 阈值: {threshold}")
        
        # GROK建议：添加详细调试日志
        logger.info(f"[DEBUG-VOTE] 加权得分={weighted_score:.4f}, 模型同意数={agreements}")
        logger.info(f"[DEBUG-VOTE] Prophet: dir={prophet_dir}, conf={prophet_conf:.3f}, score={prophet_score:.4f}")
        logger.info(f"[DEBUG-VOTE] ARIMA  : dir={arima_dir}, conf={arima_conf:.3f}, score={arima_score:.4f}")
        logger.info(f"[DEBUG-VOTE] Tech   : dir={technical_dir}, conf={technical_conf:.3f}, score={technical_score:.4f}")
        
        # 检查是否有高置信度单模型信号（置信度>0.7，允许1个模型同意）
        high_confidence_single_model = False
        single_model_direction = None
        single_model_name = None
        single_model_confidence = 0.0
        
        # 检查Prophet模型（GROK优化：差异化阈值，买入0.7，卖出0.72，上限控制以防覆盖率降）
        prophet_threshold = 0.72 if prophet_dir == 'down' else 0.7  # 卖出信号0.72，买入信号0.7（GROK建议：0.72更平衡，减少过滤力度）
        if prophet_conf > prophet_threshold and prophet_dir != 'neutral':
            # 如果其他模型都是neutral，或者Prophet置信度最高
            if (arima_dir == 'neutral' and technical_dir == 'neutral') or \
               (prophet_conf >= arima_conf and prophet_conf >= technical_conf):
                high_confidence_single_model = True
                single_model_direction = prophet_dir
                single_model_name = 'prophet'
                single_model_confidence = prophet_conf
                logger.info(f"检测到高置信度Prophet单模型信号: {prophet_dir}({prophet_conf:.2f}, 阈值={prophet_threshold})")
        
        # 检查ARIMA模型（优化：降低阈值从0.7降至0.65，增加ARIMA参与度）
        if not high_confidence_single_model:
            if arima_conf > 0.65 and arima_dir != 'neutral':
                if (prophet_dir == 'neutral' and technical_dir == 'neutral') or \
                   (arima_conf >= prophet_conf and arima_conf >= technical_conf):
                    high_confidence_single_model = True
                    single_model_direction = arima_dir
                    single_model_name = 'arima'
                    single_model_confidence = arima_conf
                    logger.info(f"检测到高置信度ARIMA单模型信号: {arima_dir}({arima_conf:.2f})")
        
        # 检查技术指标模型（优化：提高阈值从0.7至0.8，因为技术指标单模型信号胜率0%）
        if not high_confidence_single_model:
            if technical_conf > 0.8 and technical_dir != 'neutral':  # 优化：从0.7提升至0.8，提高信号质量
                if (prophet_dir == 'neutral' and arima_dir == 'neutral') or \
                   (technical_conf >= prophet_conf and technical_conf >= arima_conf):
                    high_confidence_single_model = True
                    single_model_direction = technical_dir
                    single_model_name = 'technical'
                    single_model_confidence = technical_conf
                    logger.info(f"检测到高置信度技术指标单模型信号: {technical_dir}({technical_conf:.2f}, 阈值=0.8)")
        
        # 检查是否有任何模型有信号（不是neutral）
        has_signal = (prophet_dir != 'neutral' or 
                      arima_dir != 'neutral' or 
                      technical_dir != 'neutral')
        
        # 生成详细的模型信息
        model_details = {
            'prophet': {
                'direction': prophet_dir,
                'confidence': prophet_conf,
                'weight': weights.get('prophet', 0.35),
                'score': prophet_score
            },
            'arima': {
                'direction': arima_dir,
                'confidence': arima_conf,
                'weight': weights.get('arima', 0.3),
                'score': arima_score
            },
            'technical': {
                'direction': technical_dir,
                'confidence': technical_conf,
                'weight': weights.get('technical', 0.35),
                'score': technical_score
            }
        }
        
        # 确定方向（优化后的投票逻辑）
        # 1. 只有当加权得分绝对值 > threshold 且至少min_agreements个模型同意时才生成信号
        # 2. 高置信度单模型信号（置信度>0.8）仍然允许直接通过
        
        # 初始化signal_type
        signal_type = 'neutral'
        
        if has_signal:
            # GROK建议：优先检查多模型一致信号（如果满足条件，质量更高，避免单模型信号抢占）
            # 根据方向选择阈值：买入信号使用较低阈值（0.45），卖出信号使用较高阈值（0.55）
            buy_threshold = 0.45  # 买入信号阈值（GROK优化：从0.50降至0.45，激活多模型投票）
            sell_threshold = 0.55  # 卖出信号阈值（GROK优化：从0.60降至0.55，激活多模型投票）
            
            # 优先检查多模型一致信号
            if weighted_score > buy_threshold and agreements >= min_agreements:
                direction = 'up'
                confidence = min(weighted_score, 1.0)
                signal_type = 'multi_model_agreement'
                logger.info(f"[DEBUG-VOTE] 多模型一致买入信号通过: 加权得分={weighted_score:.4f} (阈值={buy_threshold}), "
                           f"同意数={agreements}/{min_agreements}, "
                           f"Prophet={prophet_dir}({prophet_conf:.2f}), "
                           f"ARIMA={arima_dir}({arima_conf:.2f}), "
                           f"Technical={technical_dir}({technical_conf:.2f})")
            elif weighted_score < -sell_threshold and agreements >= min_agreements:
                direction = 'down'
                confidence = min(abs(weighted_score), 1.0)
                signal_type = 'multi_model_agreement'
                logger.info(f"[DEBUG-VOTE] 多模型一致卖出信号通过: 加权得分={weighted_score:.4f} (阈值={sell_threshold}), "
                           f"同意数={agreements}/{min_agreements}, "
                           f"Prophet={prophet_dir}({prophet_conf:.2f}), "
                           f"ARIMA={arima_dir}({arima_conf:.2f}), "
                           f"Technical={technical_dir}({technical_conf:.2f})")
            # 如果多模型不满足，再检查高置信度单模型信号
            elif high_confidence_single_model:
                direction = single_model_direction
                confidence = single_model_confidence
                signal_type = f'single_model_{single_model_name}'
                logger.info(f"[DEBUG-VOTE] 高置信度单模型信号通过: {direction}, 模型={single_model_name}, 置信度: {confidence:.2f}")
            else:
                # 不满足条件，返回中性
                direction = 'neutral'
                confidence = 0.5
                signal_type = 'neutral'
                used_threshold = buy_threshold if weighted_score > 0 else sell_threshold
                logger.info(f"[DEBUG-VOTE] 信号未通过: 加权得分={weighted_score:.4f} (阈值={used_threshold}), "
                           f"同意数={agreements}/{min_agreements}, "
                           f"Prophet={prophet_dir}({prophet_conf:.2f}), "
                           f"ARIMA={arima_dir}({arima_conf:.2f}), "
                           f"Technical={technical_dir}({technical_conf:.2f})")
        else:
            direction = 'neutral'
            confidence = 0.5
            signal_type = 'neutral'
            logger.debug(f"所有模型均为中性，建议持有")
        
        # 生成信号意义说明
        signal_meaning = _generate_signal_meaning(direction, model_details, weighted_score)
        
        # 计算趋势强度（基于加权得分的绝对值）
        trend_strength = min(abs(weighted_score), 1.0)
        
        # GROK建议：记录最终选择的信号类型和原因
        logger.info(f"[DEBUG-VOTE] 最终结果: direction={direction}, signal_type={signal_type}, confidence={confidence:.3f}")
        
        return {
            'direction': direction,
            'confidence': confidence,
            'weighted_score': weighted_score,
            'trend_strength': trend_strength,
            'agreements': agreements,
            'prophet_signal': prophet_signal,
            'arima_signal': arima_signal,
            'technical_signal': technical_signal,
            'model_details': model_details,
            'signal_meaning': signal_meaning,
            'signal_type': signal_type,  # 信号类型：single_model_prophet, single_model_arima, single_model_technical, multi_model_agreement, neutral
            'single_model_name': single_model_name if high_confidence_single_model else None
        }
        
    except Exception as e:
        logger.error(f"多模型投票失败: {e}", exc_info=True)
        return {
            'direction': 'neutral',
            'confidence': 0.5,
            'weighted_score': 0.0,
            'trend_strength': 0.5,
            'error': str(e)
        }


def _generate_signal_meaning(
    direction: str,
    model_details: Dict[str, Dict],
    weighted_score: float
) -> str:
    """
    生成信号意义说明
    
    Args:
        direction: 信号方向 ('up' | 'down' | 'neutral')
        model_details: 各模型详细信息
        weighted_score: 综合加权得分
    
    Returns:
        str: 信号意义说明
    """
    if direction == 'neutral':
        return "所有模型均为中性，建议持有"
    
    # 收集有信号的模型信息
    active_models = []
    for model_name, details in model_details.items():
        if details['direction'] != 'neutral':
            model_name_cn = {
                'prophet': 'Prophet模型',
                'arima': 'ARIMA模型',
                'technical': '技术指标模型'
            }.get(model_name, model_name)
            direction_cn = {
                'up': '上涨',
                'down': '下跌'
            }.get(details['direction'], details['direction'])
            active_models.append(
                f"{model_name_cn}预测{direction_cn}(置信度{details['confidence']:.2f}, 权重{details['weight']:.2f})"
            )
    
    if not active_models:
        return "所有模型均为中性，建议持有"
    
    # 生成信号意义说明
    direction_cn = '上涨' if direction == 'up' else '下跌'
    models_info = '、'.join(active_models)
    score_info = f"综合得分{weighted_score:.4f}"
    
    if direction == 'up':
        meaning = f"{models_info}，{score_info}。建议买入ETF或买入看涨期权(CALL)"
    else:
        meaning = f"{models_info}，{score_info}。建议卖出ETF（如有持仓）或买入看跌期权(PUT)"
    
    return meaning


def _short_cycle_timing(
    etf_minute_30m: pd.DataFrame,
    etf_current_price: float,
    config: Optional[Dict] = None
) -> Optional[Dict[str, Any]]:
    """
    短周期择时确认（30min MA金叉 + 成交放大）
    
    Args:
        etf_minute_30m: ETF 30分钟数据
        etf_current_price: ETF当前价格
        config: 系统配置
    
    Returns:
        dict: 择时信号 {
            'confirmed': bool,
            'ma_signal': str,  # 'golden_cross' | 'death_cross' | 'none'
            'volume_signal': str,  # 'amplified' | 'normal' | 'shrinking'
            'reason': str
        }
    
    规则：
    - MA10上穿MA30 → 买入信号
    - 成交量 > 10日均量 * 1.2 → 成交放大确认
    - 两个条件同时满足才确认
    """
    try:
        if etf_minute_30m is None or etf_minute_30m.empty:
            return {
                'confirmed': False,
                'ma_signal': 'none',
                'volume_signal': 'normal',
                'reason': '30分钟数据为空'
            }
        
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        etf_config = config.get('etf_trading', {})
        short_cycle_config = etf_config.get('short_cycle', {})
        ma_periods = short_cycle_config.get('ma_periods', [10, 30])
        volume_multiplier = short_cycle_config.get('volume_multiplier', 1.2)
        
        # 检查必要的列
        if '收盘' not in etf_minute_30m.columns:
            return {
                'confirmed': False,
                'ma_signal': 'none',
                'volume_signal': 'normal',
                'reason': '缺少收盘价列'
            }
        
        # 计算MA10和MA30
        ma10 = calculate_ma(etf_minute_30m, period=ma_periods[0], close_col='收盘')
        ma30 = calculate_ma(etf_minute_30m, period=ma_periods[1], close_col='收盘')
        
        if ma10 is None or ma10.empty or ma30 is None or ma30.empty:
            return {
                'confirmed': False,
                'ma_signal': 'none',
                'volume_signal': 'normal',
                'reason': 'MA计算失败'
            }
        
        # 检查MA金叉/死叉（最近两个数据点）
        if len(ma10) >= 2 and len(ma30) >= 2:
            ma10_prev = ma10.iloc[-2]
            ma10_curr = ma10.iloc[-1]
            ma30_prev = ma30.iloc[-2]
            ma30_curr = ma30.iloc[-1]
            
            # 金叉：MA10从下方穿越MA30
            if ma10_prev <= ma30_prev and ma10_curr > ma30_curr:
                ma_signal = 'golden_cross'
            # 死叉：MA10从上方穿越MA30
            elif ma10_prev >= ma30_prev and ma10_curr < ma30_curr:
                ma_signal = 'death_cross'
            else:
                ma_signal = 'none'
        else:
            ma_signal = 'none'
        
        # 检查成交量
        if '成交量' in etf_minute_30m.columns:
            from src.indicator_calculator import calculate_volume_ma
            volume_ma10 = calculate_volume_ma(etf_minute_30m, period=10, volume_col='成交量')
            
            if volume_ma10 is not None and not volume_ma10.empty:
                current_volume = etf_minute_30m['成交量'].iloc[-1]
                volume_ma10_value = volume_ma10.iloc[-1]
                
                if current_volume > volume_ma10_value * volume_multiplier:
                    volume_signal = 'amplified'
                elif current_volume < volume_ma10_value * 0.8:
                    volume_signal = 'shrinking'
                else:
                    volume_signal = 'normal'
            else:
                volume_signal = 'normal'
        else:
            volume_signal = 'normal'
        
        # 确认条件：MA金叉 + 成交放大
        confirmed = (ma_signal == 'golden_cross' and volume_signal == 'amplified')
        
        return {
            'confirmed': confirmed,
            'ma_signal': ma_signal,
            'volume_signal': volume_signal,
            'reason': f'MA信号: {ma_signal}, 成交量: {volume_signal}'
        }
        
    except Exception as e:
        logger.error(f"短周期择时确认失败: {e}", exc_info=True)
        return {
            'confirmed': False,
            'ma_signal': 'none',
            'volume_signal': 'normal',
            'reason': f'计算失败: {str(e)}'
        }
