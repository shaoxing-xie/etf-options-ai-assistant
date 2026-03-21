"""
多GARCH模型集成模块
使用多个GARCH模型（不同参数）的预测结果进行集成
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from src.logger_config import get_module_logger
from src.volatility_engine.index_garch_predictor import IndexGARCHPredictor

logger = get_module_logger(__name__)

# 默认的GARCH模型参数组合（基于常见配置）
DEFAULT_GARCH_MODELS = [
    (1, 1, (1, 1, 1)),  # 标准GARCH(1,1) + ARIMA(1,1,1)
    (1, 1, (0, 1, 1)),  # GARCH(1,1) + ARIMA(0,1,1)
    (1, 1, (1, 1, 0)),  # GARCH(1,1) + ARIMA(1,1,0)
    (2, 1, (1, 1, 1)),  # GARCH(2,1) + ARIMA(1,1,1)
    (1, 2, (1, 1, 1)),  # GARCH(1,2) + ARIMA(1,1,1)
]


def ensemble_garch_predictions(
    price_series: pd.Series,
    current_price: float,
    remaining_ratio: float = 1.0,
    models: List[Tuple[int, int, Tuple[int, int, int]]] = None,
    weights: List[float] = None,
    confidence_level: float = 0.95
) -> Dict[str, Any]:
    """
    多个GARCH模型的集成预测
    
    Args:
        price_series: 价格序列
        current_price: 当前价格
        remaining_ratio: 剩余时间比例（用于缩放波动率）
        models: GARCH模型参数列表，格式：[(p1, q1, arima_order1), (p2, q2, arima_order2), ...]
        weights: 各模型的权重（如果为None，则使用等权重）
        confidence_level: 置信水平
    
    Returns:
        dict: 集成预测结果，包含upper, lower, confidence等
    """
    try:
        if models is None:
            models = DEFAULT_GARCH_MODELS
        
        if weights is None:
            # 使用等权重
            weights = [1.0 / len(models)] * len(models)
        else:
            # 确保权重归一化
            total_weight = sum(weights)
            if total_weight > 0:
                weights = [w / total_weight for w in weights]
            else:
                weights = [1.0 / len(models)] * len(models)
        
        predictions = []
        successful_models = []
        
        for i, (p, q, arima_order) in enumerate(models):
            try:
                # 创建GARCH预测器
                garch_predictor = IndexGARCHPredictor(
                    garch_p=p,
                    garch_q=q,
                    arima_order=arima_order,
                    confidence_level=confidence_level
                )
                
                # 预测价格区间
                garch_result = garch_predictor.predict_price_range(
                    current_price=current_price,
                    price_series=price_series,
                    horizon=1,
                    remaining_ratio=remaining_ratio
                )
                
                if garch_result.get('success', False):
                    predictions.append({
                        'upper': garch_result.get('upper'),
                        'lower': garch_result.get('lower'),
                        'predicted_price': garch_result.get('predicted_price'),
                        'volatility': garch_result.get('volatility'),
                        'model_params': (p, q, arima_order)
                    })
                    successful_models.append(i)
                else:
                    logger.debug(f"GARCH模型 ({p},{q},{arima_order}) 预测失败: {garch_result.get('error', '未知错误')}")
                    
            except Exception as e:
                logger.warning(f"GARCH模型 ({p},{q},{arima_order}) 预测异常: {e}")
                continue
        
        if not predictions:
            logger.warning("所有GARCH模型预测失败，返回None")
            return None
        
        # 使用成功模型的权重（重新归一化）
        if len(successful_models) < len(models):
            successful_weights = [weights[i] for i in successful_models]
            total_weight = sum(successful_weights)
            if total_weight > 0:
                successful_weights = [w / total_weight for w in successful_weights]
            else:
                successful_weights = [1.0 / len(predictions)] * len(predictions)
        else:
            successful_weights = weights[:len(predictions)]
        
        # 加权平均
        ensemble_upper = sum(
            p['upper'] * w 
            for p, w in zip(predictions, successful_weights)
        )
        
        ensemble_lower = sum(
            p['lower'] * w 
            for p, w in zip(predictions, successful_weights)
        )
        
        ensemble_predicted_price = sum(
            p['predicted_price'] * w 
            for p, w in zip(predictions, successful_weights)
        )
        
        ensemble_volatility = sum(
            p['volatility'] * w 
            for p, w in zip(predictions, successful_weights)
        )
        
        # 计算置信度（基于模型一致性）
        upper_values = [p['upper'] for p in predictions]
        lower_values = [p['lower'] for p in predictions]
        
        upper_std = np.std(upper_values)
        lower_std = np.std(lower_values)
        range_width = ensemble_upper - ensemble_lower
        
        if range_width > 0:
            consistency = 1.0 - min(1.0, (upper_std + lower_std) / range_width)
        else:
            consistency = 0.5
        
        # 一致性越高，置信度越高
        ensemble_confidence = confidence_level * (0.7 + 0.3 * consistency)
        
        logger.info(f"GARCH集成预测完成: {len(predictions)}/{len(models)} 个模型成功, "
                   f"区间=[{ensemble_lower:.2f}, {ensemble_upper:.2f}], "
                   f"一致性={consistency:.2f}, 置信度={ensemble_confidence:.2f}")
        
        return {
            'success': True,
            'upper': float(ensemble_upper),
            'lower': float(ensemble_lower),
            'predicted_price': float(ensemble_predicted_price),
            'volatility': float(ensemble_volatility),
            'confidence': float(ensemble_confidence),
            'method': 'GARCH集成',
            'num_models': len(predictions),
            'consistency': float(consistency),
            'model_predictions': predictions  # 保留各模型的预测结果，用于分析
        }
        
    except Exception as e:
        logger.error(f"GARCH集成预测失败: {e}", exc_info=True)
        return None


def get_ensemble_model_weights(
    model_performances: Dict[Tuple, Dict[str, Any]] = None,
    default_equal: bool = True
) -> List[float]:
    """
    根据历史表现计算各模型的权重
    
    Args:
        model_performances: {
            (p1, q1, arima_order1): {'hit_rate': 0.85, 'avg_width': 2.5, 'score': 0.8},
            ...
        }
        default_equal: 如果没有表现数据，是否使用等权重
    
    Returns:
        list: 各模型的权重列表
    """
    try:
        if not model_performances or default_equal:
            # 使用等权重
            return None
        
        # 计算综合得分
        scores = {}
        for model_params, perf in model_performances.items():
            hit_rate = perf.get('hit_rate', 0.5)
            avg_width = perf.get('avg_width', 3.0)
            
            # 宽度得分：2%为基准，越小越好
            width_score = 1.0 - (avg_width - 2.0) / 2.0
            width_score = max(0.0, min(1.0, width_score))
            
            # 综合得分
            scores[model_params] = hit_rate * 0.6 + width_score * 0.4
        
        # 归一化权重
        total_score = sum(scores.values())
        if total_score > 0:
            weights = [scores.get(model, 0.2) / total_score for model in DEFAULT_GARCH_MODELS]
        else:
            weights = None
        
        return weights
        
    except Exception as e:
        logger.warning(f"计算模型权重失败: {e}，使用等权重")
        return None
