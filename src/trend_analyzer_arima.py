"""
ARIMA趋势预测模块（GK优化 + ARIMA集成完善）
与现有MACD/RSI技术指标结合使用，提升趋势预测准确率

优化内容：
1. 自动选择ARIMA阶数（AIC优化）
2. 扩展数据窗口到180-250天
3. 改进置信度计算（残差分析 + Ljung-Box检验）
4. 动态趋势判断阈值（基于历史波动率ATR）
5. 支持成交量特征（可选）
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, Tuple
import warnings

# 抑制statsmodels ARIMA模型拟合时的常见警告（这些警告不影响功能）
warnings.filterwarnings('ignore', category=UserWarning, module='statsmodels.tsa.statespace.sarimax')
warnings.filterwarnings('ignore', message='Non-stationary starting autoregressive parameters')
warnings.filterwarnings('ignore', message='Non-invertible starting MA parameters')
warnings.filterwarnings('ignore', category=UserWarning, message='No frequency information was provided')
warnings.filterwarnings('ignore', message='.*inferred frequency.*')
# 抑制ARIMA模型优化收敛警告（ConvergenceWarning和RuntimeWarning）
warnings.filterwarnings('ignore', message='Maximum Likelihood optimization failed to converge')
warnings.filterwarnings('ignore', category=RuntimeWarning, message='Maximum Likelihood optimization failed to converge')
# 抑制statsmodels.base.model中的ConvergenceWarning
try:
    from statsmodels.tools.sm_exceptions import ConvergenceWarning
    warnings.filterwarnings('ignore', category=ConvergenceWarning)
except ImportError:
    pass

try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.stats.diagnostic import acorr_ljungbox
    ARIMA_AVAILABLE = True
except ImportError:
    ARIMA_AVAILABLE = False
    warnings.warn("statsmodels库未安装，ARIMA趋势预测功能将不可用。请运行: pip install statsmodels")

from src.logger_config import get_module_logger, log_error_with_context  # noqa: E402

logger = get_module_logger(__name__)


def _select_optimal_arima_order(
    price_series: pd.Series,
    max_p: int = 3,
    max_d: int = 2,
    max_q: int = 3,
    seasonal: bool = False
) -> Tuple[tuple, float]:
    """
    自动选择最优ARIMA阶数（基于AIC）
    
    Args:
        price_series: 价格序列
        max_p: 最大AR阶数
        max_d: 最大差分阶数
        max_q: 最大MA阶数
        seasonal: 是否考虑季节性（默认False）
    
    Returns:
        tuple: (最优阶数, 最小AIC值)
    """
    if not ARIMA_AVAILABLE:
        return (1, 1, 1), 0.0
    
    best_order = (1, 1, 1)
    best_aic = float('inf')
    
    # 常见ARIMA阶数组合
    orders_to_try = [
        (1, 1, 1), (2, 1, 1), (1, 1, 2), (2, 1, 2),
        (1, 1, 0), (0, 1, 1), (0, 1, 2), (2, 1, 0),
        (3, 1, 1), (1, 1, 3), (3, 1, 2), (2, 1, 3)
    ]
    
    # 限制在max_p, max_d, max_q范围内
    orders_to_try = [o for o in orders_to_try 
                     if o[0] <= max_p and o[1] <= max_d and o[2] <= max_q]
    
    logger.debug(f"尝试 {len(orders_to_try)} 个ARIMA阶数组合...")
    
    for order in orders_to_try:
        try:
            # 确保价格序列有正确的频率信息（避免频率警告）
            price_series_for_arima = price_series.copy()
            if isinstance(price_series_for_arima.index, pd.DatetimeIndex):
                # 如果是DatetimeIndex但没有频率，尝试推断
                if price_series_for_arima.index.freq is None:
                    # 尝试推断为日频率
                    try:
                        price_series_for_arima = price_series_for_arima.asfreq('D')
                    except Exception as e:
                        logger.debug(
                            f"ARIMA频率推断失败（仍继续使用原序列）: {e}",
                            exc_info=True,
                        )
            
            model = ARIMA(price_series_for_arima, order=order)
            fit_result = model.fit()
            aic = fit_result.aic
            
            if aic < best_aic:
                best_aic = aic
                best_order = order
                logger.debug(f"  阶数 {order}: AIC={aic:.2f} (当前最优)")
        except Exception as e:
            logger.debug(f"  阶数 {order} 拟合失败: {e}")
            continue
    
    logger.info(f"最优ARIMA阶数: {best_order}, AIC={best_aic:.2f}")
    return best_order, best_aic


def _calculate_atr(
    daily_df: pd.DataFrame,
    period: int = 20
) -> float:
    """
    计算平均真实波幅（ATR），用于动态阈值调整
    
    Args:
        daily_df: 日线数据（需包含'最高'、'最低'、'收盘'列）
        period: 计算周期（默认20天）
    
    Returns:
        float: ATR值（百分比）
    """
    try:
        if '最高' not in daily_df.columns or '最低' not in daily_df.columns or '收盘' not in daily_df.columns:
            return 1.0  # 默认阈值
        
        high = daily_df['最高'].dropna()
        low = daily_df['最低'].dropna()
        close = daily_df['收盘'].dropna()
        
        if len(high) < period or len(low) < period or len(close) < period:
            return 1.0
        
        # 计算TR（真实波幅）
        tr_list = []
        for i in range(1, min(len(high), len(low), len(close))):
            tr1 = high.iloc[i] - low.iloc[i]
            tr2 = abs(high.iloc[i] - close.iloc[i-1])
            tr3 = abs(low.iloc[i] - close.iloc[i-1])
            tr = max(tr1, tr2, tr3)
            tr_list.append(tr)
        
        if len(tr_list) < period:
            return 1.0
        
        # 计算ATR（最近period天的平均TR）
        recent_tr = tr_list[-period:]
        atr = np.mean(recent_tr)
        
        # 转换为百分比（相对于当前价格）
        current_price = close.iloc[-1]
        atr_pct = (atr / current_price) * 100
        
        return max(0.5, min(3.0, atr_pct))  # 限制在0.5%-3%之间
        
    except Exception as e:
        logger.debug(f"计算ATR失败: {e}，使用默认阈值1.0%")
        return 1.0


def _improve_confidence(
    fit_result: Any,
    residuals: np.ndarray
) -> float:
    """
    改进置信度计算（结合残差分析和Ljung-Box检验）
    
    Args:
        fit_result: ARIMA拟合结果
        residuals: 残差序列
    
    Returns:
        float: 置信度 (0-1)
    """
    try:
        confidence_factors = []
        
        # 1. 基于p值的置信度
        try:
            pvalues = fit_result.pvalues
            avg_pvalue = float(pvalues.mean())
            pvalue_confidence = max(0.5, min(0.95, 1.0 - avg_pvalue * 2))
            confidence_factors.append(pvalue_confidence)
        except Exception as e:
            logger.debug(f"基于p值的置信度计算失败: {e}", exc_info=True)
            pvalue_confidence = 0.7
            confidence_factors.append(pvalue_confidence)
        
        # 2. 基于AIC/BIC的置信度
        try:
            aic = fit_result.aic
            bic = fit_result.bic
            # AIC/BIC越小越好，归一化到0-1
            aic_normalized = max(0.5, min(0.95, 1.0 - (aic / 10000)))
            bic_normalized = max(0.5, min(0.95, 1.0 - (bic / 10000)))
            confidence_factors.append((aic_normalized + bic_normalized) / 2)
        except Exception as e:
            logger.debug(f"基于AIC/BIC的置信度计算失败: {e}", exc_info=True)
            confidence_factors.append(0.7)
        
        # 3. Ljung-Box检验（残差自相关检验）
        try:
            if len(residuals) > 10:
                lb_result = acorr_ljungbox(residuals, lags=min(10, len(residuals)//2), return_df=True)
                # p值越大，说明残差无自相关，模型越好
                lb_pvalue = float(lb_result['lb_pvalue'].iloc[-1])
                lb_confidence = max(0.5, min(0.95, lb_pvalue))
                confidence_factors.append(lb_confidence)
            else:
                confidence_factors.append(0.7)
        except Exception as e:
            logger.debug(f"Ljung-Box检验失败: {e}")
            confidence_factors.append(0.7)
        
        # 4. 残差方差（方差越小，模型越好）
        try:
            residual_var = np.var(residuals)
            # 归一化（假设方差在0-10000范围内）
            var_normalized = max(0.5, min(0.95, 1.0 - (residual_var / 10000)))
            confidence_factors.append(var_normalized)
        except Exception as e:
            logger.debug(f"基于残差方差的置信度计算失败: {e}", exc_info=True)
            confidence_factors.append(0.7)
        
        # 综合置信度（取平均值）
        final_confidence: float = float(np.mean(confidence_factors))
        return max(0.5, min(0.95, final_confidence))
        
    except Exception as e:
        logger.debug(f"置信度计算失败: {e}，使用默认值0.7")
        return 0.7


def predict_index_trend_arima(
    daily_df: pd.DataFrame,
    forecast_days: int = 3,
    arima_order: Optional[tuple] = None,
    auto_select_order: bool = True,
    data_window_days: int = 200,
    use_volume: bool = False,
    volume_df: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    """
    使用ARIMA模型预测指数趋势（3-5日）
    优化版本：支持自动阶数选择、扩展数据窗口、改进置信度、动态阈值
    
    Args:
        daily_df: 日线数据DataFrame（必须包含'收盘'列，可选'最高'、'最低'列用于ATR计算）
        forecast_days: 预测天数（默认3天）
        arima_order: ARIMA模型阶数 (p, d, q)，如果为None且auto_select_order=True则自动选择
        auto_select_order: 是否自动选择最优阶数（默认True）
        data_window_days: 数据窗口大小（默认200天，范围180-250天）
        use_volume: 是否使用成交量特征（默认False）
        volume_df: 成交量数据（如果use_volume=True且volume_df不为None）
    
    Returns:
        dict: {
            'direction': '上行' | '下行' | '震荡',
            'forecast_prices': 预测价格列表,
            'confidence': 置信度 (0-1),
            'trend_strength': 趋势强度 (0-1),
            'method': 'ARIMA',
            'arima_order': 使用的ARIMA阶数,
            'aic': AIC值,
            'bic': BIC值,
            'atr_pct': ATR百分比（用于动态阈值）,
            'dynamic_threshold': 动态阈值
        }
    """
    if not ARIMA_AVAILABLE:
        logger.warning("statsmodels库未安装，无法使用ARIMA预测")
        return {
            'direction': '震荡',
            'forecast_prices': [],
            'confidence': 0.5,
            'trend_strength': 0.5,
            'method': 'ARIMA',
            'error': 'statsmodels库未安装'
        }
    
    try:
        if daily_df is None or daily_df.empty:
            logger.warning("日线数据为空，无法进行ARIMA预测")
            return {
                'direction': '震荡',
                'forecast_prices': [],
                'confidence': 0.5,
                'trend_strength': 0.5,
                'method': 'ARIMA',
                'error': '数据为空'
            }
        
        if '收盘' not in daily_df.columns:
            logger.warning("日线数据中缺少'收盘'列")
            return {
                'direction': '震荡',
                'forecast_prices': [],
                'confidence': 0.5,
                'trend_strength': 0.5,
                'method': 'ARIMA',
                'error': '缺少收盘价数据'
            }
        
        # 准备价格序列（扩展数据窗口到180-250天）
        price_series = daily_df['收盘'].dropna()
        if len(price_series) < 30:
            logger.warning(f"数据不足（{len(price_series)}个），至少需要30个数据点进行ARIMA预测")
            return {
                'direction': '震荡',
                'forecast_prices': [],
                'confidence': 0.5,
                'trend_strength': 0.5,
                'method': 'ARIMA',
                'error': f'数据不足（需要30个，当前{len(price_series)}个）'
            }
        
        # 扩展数据窗口（180-250天，默认200天）
        window_days = max(90, min(250, data_window_days))  # 限制在90-250天
        if len(price_series) > window_days:
            price_series = price_series.iloc[-window_days:]
        
        current_price = float(price_series.iloc[-1])
        
        # 计算ATR（用于动态阈值）
        atr_pct = _calculate_atr(daily_df, period=20)
        # 动态阈值：震荡市（ATR<1%）用0.5%，趋势市（ATR>2%）用1.5%，其他用1.0%
        if atr_pct < 1.0:
            dynamic_threshold = 0.5  # 震荡市，阈值放宽
        elif atr_pct > 2.0:
            dynamic_threshold = 1.5  # 趋势市，阈值收紧
        else:
            dynamic_threshold = 1.0  # 正常市
        
        # 自动选择最优ARIMA阶数
        if auto_select_order and arima_order is None:
            arima_order, best_aic = _select_optimal_arima_order(price_series)
        elif arima_order is None:
            arima_order = (1, 1, 1)  # 默认阶数
        
        # 拟合ARIMA模型
        logger.debug(f"开始拟合ARIMA{arima_order}模型，数据点: {len(price_series)}, 窗口: {window_days}天")
        
        # 确保价格序列有正确的频率信息（避免频率警告）
        price_series_for_arima = price_series.copy()
        if isinstance(price_series_for_arima.index, pd.DatetimeIndex):
            # 如果是DatetimeIndex但没有频率，尝试推断
            if price_series_for_arima.index.freq is None:
                # 尝试推断为日频率
                try:
                    price_series_for_arima = price_series_for_arima.asfreq('D')
                except Exception as e:
                    logger.debug(f"推断 ARIMA 价格序列频率失败，忽略: {e}", exc_info=True)
        
        model = ARIMA(price_series_for_arima, order=arima_order)
        fit_result = model.fit()
        
        logger.debug(f"ARIMA模型拟合成功: AIC={fit_result.aic:.2f}, BIC={fit_result.bic:.2f}")
        
        # 获取残差（用于置信度计算）
        try:
            residuals = fit_result.resid.values
        except Exception:
            residuals = np.array([])
        
        # 预测未来价格
        forecast_result = fit_result.forecast(steps=forecast_days)
        forecast_prices = [float(x) for x in forecast_result]
        
        import json
        import os
        from pathlib import Path
        from datetime import datetime

        debug_log_path_str = os.environ.get("ETF_ASSISTANT_DEBUG_LOG_PATH", "").strip()
        debug_log_path = Path(debug_log_path_str) if debug_log_path_str else None

        def _append_debug(entry: Dict[str, Any]) -> None:
            if debug_log_path is None:
                return
            try:
                debug_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Debug log write failed: {e}")

        _append_debug(
            {
                "timestamp": datetime.now().timestamp() * 1000,
                "location": "trend_analyzer_arima.py:forecast",
                "message": "ARIMA预测结果",
                "data": {
                    "forecast_prices": forecast_prices,
                    "has_nan": any(np.isnan(p) for p in forecast_prices),
                    "current_price": current_price,
                    "forecast_days": forecast_days,
                },
            }
        )
        
        avg_forecast_price: float = float(np.mean(forecast_prices))
        
        # 如果预测结果为 nan，则使用当前价格作为预测均值
        if np.isnan(avg_forecast_price) or not np.isfinite(avg_forecast_price):
            _append_debug(
                {
                    "timestamp": datetime.now().timestamp() * 1000,
                    "location": "trend_analyzer_arima.py:avg_forecast_nan",
                    "message": "ARIMA预测均值为nan，使用当前价格",
                    "data": {"avg_forecast_price": avg_forecast_price, "current_price": current_price},
                }
            )
            avg_forecast_price = current_price  # 使用当前价格作为预测值
        
        # 动态趋势判断（基于ATR调整阈值）
        price_change_pct: float = float((avg_forecast_price - current_price) / current_price * 100)
        
        _append_debug(
            {
                "timestamp": datetime.now().timestamp() * 1000,
                "location": "trend_analyzer_arima.py:price_change",
                "message": "价格变化计算",
                "data": {
                    "avg_forecast_price": avg_forecast_price,
                    "current_price": current_price,
                    "price_change_pct": price_change_pct,
                    "is_nan": np.isnan(price_change_pct),
                },
            }
        )
        
        # 如果 price_change_pct 为 nan，则回退为震荡
        if np.isnan(price_change_pct) or not np.isfinite(price_change_pct):
            _append_debug(
                {
                    "timestamp": datetime.now().timestamp() * 1000,
                    "location": "trend_analyzer_arima.py:price_change_nan",
                    "message": "price_change_pct为nan，回退震荡",
                    "data": {"price_change_pct": price_change_pct, "dynamic_threshold": dynamic_threshold},
                }
            )
            direction = "震荡"
            trend_strength: float = 0.5
        elif price_change_pct > dynamic_threshold:  # 上涨超过动态阈值
            direction = "上行"
            trend_strength = float(min(1.0, abs(price_change_pct) / (dynamic_threshold * 3)))  # 强度基于涨幅
        elif price_change_pct < -dynamic_threshold:  # 下跌超过动态阈值
            direction = "下行"
            trend_strength = float(min(1.0, abs(price_change_pct) / (dynamic_threshold * 3)))
        else:
            direction = "震荡"
            trend_strength = float(
                max(0.2, 0.5 - abs(price_change_pct) / (dynamic_threshold * 2))
            )  # 震荡时强度较低
        
        # 改进置信度计算（结合残差分析和Ljung-Box检验）
        confidence = _improve_confidence(fit_result, residuals)
        
        _append_debug(
            {
                "timestamp": datetime.now().timestamp() * 1000,
                "location": "trend_analyzer_arima.py:final",
                "message": "ARIMA最终结果",
                "data": {
                    "direction": direction,
                    "trend_strength": trend_strength,
                    "confidence": confidence,
                    "avg_forecast_price": avg_forecast_price,
                    "current_price": current_price,
                    "price_change_pct": price_change_pct,
                },
            }
        )
        
        # 如果使用成交量特征，调整置信度和强度
        volume_adjustment = 1.0
        if use_volume and volume_df is not None:
            try:
                # 计算成交量变化率（最近5天 vs 前5天）
                if '成交量' in volume_df.columns and len(volume_df) >= 10:
                    recent_vol = volume_df['成交量'].iloc[-5:].mean()
                    prev_vol = volume_df['成交量'].iloc[-10:-5].mean()
                    if prev_vol > 0:
                        vol_change_ratio = recent_vol / prev_vol
                        # 成交量放大时，提高置信度
                        if vol_change_ratio > 1.2:  # 成交量放大20%以上
                            volume_adjustment = 1.1
                        elif vol_change_ratio < 0.8:  # 成交量萎缩20%以上
                            volume_adjustment = 0.9
            except Exception as e:
                logger.debug(f"成交量特征处理失败: {e}")
        
        confidence = min(0.95, confidence * volume_adjustment)
        
        logger.info(f"ARIMA趋势预测: 方向={direction}, 强度={trend_strength:.2f}, "
                   f"当前价格={current_price:.2f}, 预测平均价格={avg_forecast_price:.2f}, "
                   f"变化={price_change_pct:.2f}%, 置信度={confidence:.2f}, "
                   f"ATR={atr_pct:.2f}%, 动态阈值={dynamic_threshold:.2f}%")
        
        return {
            'direction': direction,
            'forecast_prices': forecast_prices,
            'current_price': current_price,
            'avg_forecast_price': avg_forecast_price,
            'price_change_pct': price_change_pct,
            'confidence': confidence,
            'trend_strength': trend_strength,
            'method': 'ARIMA',
            'arima_order': arima_order,
            'aic': float(fit_result.aic),
            'bic': float(fit_result.bic),
            'atr_pct': atr_pct,
            'dynamic_threshold': dynamic_threshold,
            'data_window_days': len(price_series),
            'auto_selected_order': auto_select_order and arima_order is not None,
            'volume_adjusted': use_volume and volume_df is not None
        }
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'predict_index_trend_arima', 'forecast_days': forecast_days},
            "ARIMA趋势预测失败"
        )
        return {
            'direction': '震荡',
            'forecast_prices': [],
            'confidence': 0.5,
            'trend_strength': 0.5,
            'method': 'ARIMA',
            'error': str(e)
        }


def combine_trend_analysis(
    arima_result: Dict[str, Any],
    technical_result: Tuple[str, float]
) -> Dict[str, Any]:
    """
    结合ARIMA预测和技术指标（MACD/RSI）的综合趋势分析
    
    Args:
        arima_result: ARIMA预测结果
        technical_result: 技术指标分析结果 (趋势方向, 趋势强度)
    
    Returns:
        dict: 综合趋势分析结果
    """
    try:
        technical_trend, technical_strength = technical_result
        
        # 如果ARIMA预测失败，直接使用技术指标结果
        if not arima_result.get('direction') or arima_result.get('error'):
            logger.debug("ARIMA预测失败，使用技术指标结果")
            return {
                'final_trend': technical_trend,
                'final_strength': technical_strength,
                'method': '技术指标',
                'arima_available': False,
                'technical_trend': technical_trend,
                'technical_strength': technical_strength
            }
        
        arima_direction = arima_result['direction']
        arima_strength = arima_result.get('trend_strength', 0.5)
        arima_confidence = arima_result.get('confidence', 0.5)
        
        # 权重分配：ARIMA 60%，技术指标 40%（ARIMA更关注短期趋势）
        arima_weight = 0.6
        technical_weight = 0.4
        
        # 趋势方向映射到数值
        trend_scores = {
            "强势": 1.0,
            "上行": 1.0,
            "震荡": 0.5,
            "弱势": 0.0,
            "下行": 0.0
        }
        
        arima_score = trend_scores.get(arima_direction, 0.5)
        technical_score = trend_scores.get(technical_trend, 0.5)
        
        # 综合得分
        combined_score = arima_score * arima_weight + technical_score * technical_weight
        
        # 综合强度（加权平均，但考虑置信度）
        # ARIMA的强度需要乘以置信度
        adjusted_arima_strength = arima_strength * arima_confidence
        combined_strength = adjusted_arima_strength * arima_weight + technical_strength * technical_weight
        
        # 判断最终趋势
        if combined_score >= 0.7:
            final_trend = "强势"
        elif combined_score <= 0.3:
            final_trend = "弱势"
        else:
            final_trend = "震荡"
        
        logger.info(f"综合趋势分析: ARIMA={arima_direction}(强度={arima_strength:.2f},置信度={arima_confidence:.2f}), "
                   f"技术指标={technical_trend}(强度={technical_strength:.2f}), "
                   f"综合={final_trend}(强度={combined_strength:.2f})")
        
        return {
            'final_trend': final_trend,
            'final_strength': combined_strength,
            'method': 'ARIMA+技术指标',
            'arima_available': True,
            'arima_trend': arima_direction,
            'arima_strength': arima_strength,
            'arima_confidence': arima_confidence,
            'technical_trend': technical_trend,
            'technical_strength': technical_strength,
            'combined_score': combined_score,
            'weights': {
                'arima': arima_weight,
                'technical': technical_weight
            }
        }
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'combine_trend_analysis'},
            "综合趋势分析失败"
        )
        # 回退到技术指标结果
        technical_trend, technical_strength = technical_result
        return {
            'final_trend': technical_trend,
            'final_strength': technical_strength,
            'method': '技术指标（回退）',
            'arima_available': False,
            'error': str(e)
        }
