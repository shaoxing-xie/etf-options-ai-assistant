"""
波动区间计算模块
计算指数、ETF、期权的波动区间预测
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Dict, Optional, Any
import pytz

from src.logger_config import get_module_logger, log_error_with_context
from src.indicator_calculator import (
    calculate_atr, calculate_bollinger_bands, calculate_historical_volatility
)
from src.system_status import get_trading_hours_config
from src.config_loader import load_system_config

logger = get_module_logger(__name__)

# 阶段1优化：导入市场校准器和IV调整器
try:
    from src.market_calibrator import MarketMicrostructureCalibrator
    from src.volatility_engine import IVPercentileAdjuster
    MARKET_CALIBRATION_AVAILABLE = True
except ImportError as e:
    logger.warning(f"市场校准模块导入失败: {e}，将使用原有方法")
    MARKET_CALIBRATION_AVAILABLE = False

# GROK优化：突破概率和Greeks贡献拆解辅助函数
def calculate_breakthrough_probability(
    current_price: float,
    upper: float,
    lower: float,
    confidence: float,
    remaining_minutes: int
) -> Dict[str, float]:
    """
    计算区间突破概率（GROK优化建议）
    
    基于GARCH置信区间 + 当前位置 + 剩余时间因子计算突破概率
    
    Args:
        current_price: 当前价格
        upper: 预测上轨
        lower: 预测下轨
        confidence: 置信度（0-1）
        remaining_minutes: 剩余交易时间（分钟）
    
    Returns:
        dict: 包含突破概率信息
            - upper_breakthrough_prob: 上轨突破概率（0-1）
            - lower_breakthrough_prob: 下轨突破概率（0-1）
            - time_factor: 剩余时间因子（0-1）
            - position: 当前位置（0-1，0为下轨，1为上轨）
    """
    try:
        range_width = upper - lower
        if range_width <= 0:
            return {
                "upper_breakthrough_prob": 0.0,
                "lower_breakthrough_prob": 0.0,
                "time_factor": 0.0,
                "position": 0.5,
            }

        # 当前位置（0-1，0为下轨，1为上轨）
        position = (current_price - lower) / range_width
        position = max(0.0, min(1.0, position))

        # 剩余时间因子（非线性衰减：越接近收盘，衰减越快）
        # 全天 240 分钟，使用开平方形式，让中段时间的因子更平滑
        total_minutes = 240.0
        if remaining_minutes <= 0:
            time_factor = 0.0
        else:
            ratio = max(0.0, min(1.0, remaining_minutes / total_minutes))
            time_factor = ratio ** 0.5  # 非线性：中段偏高，尾盘快速衰减

        # 基础突破概率（尚未乘置信度）
        base_upper = (1.0 - position) * time_factor
        base_lower = position * time_factor

        # 应用置信度折扣：置信度越低，突破概率整体打折
        upper_prob = base_upper * max(0.0, min(1.0, confidence))
        lower_prob = base_lower * max(0.0, min(1.0, confidence))

        return {
            "upper_breakthrough_prob": round(upper_prob, 4),
            "lower_breakthrough_prob": round(lower_prob, 4),
            "time_factor": round(time_factor, 4),
            "position": round(position, 4),
        }
    except Exception as e:
        logger.debug(f"计算突破概率失败: {e}")
        return {
            "upper_breakthrough_prob": 0.0,
            "lower_breakthrough_prob": 0.0,
            "time_factor": 0.0,
            "position": 0.5,
        }


def calculate_greeks_contribution(
    delta: float,
    gamma: float,
    vega: Optional[float],
    etf_change_up_pct: float,
    etf_change_down_pct: float,
    iv_change_pct: Optional[float] = None
) -> Dict[str, float]:
    """
    计算各Greeks对期权价格变动的贡献度（GROK优化建议）
    
    量化Delta、Gamma、Vega各自对区间宽度的贡献百分比
    
    Args:
        delta: Delta值
        gamma: Gamma值
        vega: Vega值（可选）
        etf_change_up_pct: ETF上涨变动百分比（0-1）
        etf_change_down_pct: ETF下跌变动百分比（0-1）
        iv_change_pct: IV变动百分比（可选，0-1）
    
    Returns:
        dict: 包含Greeks贡献信息
            - delta_contribution_pct: Delta贡献百分比
            - gamma_contribution_pct: Gamma贡献百分比
            - vega_contribution_pct: Vega贡献百分比
            - total_change_pct: 总变动百分比
    """
    try:
        # Delta贡献（线性项）
        delta_contribution = abs(delta * (etf_change_up_pct + etf_change_down_pct) / 2.0)
        
        # Gamma贡献（二次项，加速效应）
        gamma_contribution = abs(0.5 * gamma * ((etf_change_up_pct ** 2) + (etf_change_down_pct ** 2)) / 2.0)
        
        # Vega贡献（IV变动）
        vega_contribution = 0.0
        if vega is not None and iv_change_pct is not None:
            vega_contribution = abs(vega * iv_change_pct)
        
        total_contribution = delta_contribution + gamma_contribution + vega_contribution
        
        if total_contribution <= 0:
            return {
                'delta_contribution_pct': 0.0,
                'gamma_contribution_pct': 0.0,
                'vega_contribution_pct': 0.0,
                'total_change_pct': 0.0
            }
        
        # 计算各Greeks的贡献百分比
        return {
            'delta_contribution_pct': round(delta_contribution / total_contribution * 100.0, 1),
            'gamma_contribution_pct': round(gamma_contribution / total_contribution * 100.0, 1),
            'vega_contribution_pct': round(vega_contribution / total_contribution * 100.0, 1),
            'total_change_pct': round(total_contribution * 100.0, 1)
        }
    except Exception as e:
        logger.debug(f"计算Greeks贡献失败: {e}")
        return {
            'delta_contribution_pct': 0.0,
            'gamma_contribution_pct': 0.0,
            'vega_contribution_pct': 0.0,
            'total_change_pct': 0.0
        }

# 阶段2优化：导入GARCH-IV引擎
GARCHIVEngineCls: Optional[Any] = None
try:
    from src.volatility_engine import GARCHIVEngine as _GARCHIVEngine, GARCH_AVAILABLE
    GARCHIVEngineCls = _GARCHIVEngine
    GARCH_IV_AVAILABLE = GARCH_AVAILABLE
except ImportError as e:
    logger.debug(f"GARCH-IV引擎导入失败: {e}，将使用阶段1方法")
    GARCH_IV_AVAILABLE = False

# GK优化：导入指数GARCH预测器
IndexGARCHPredictorCls: Optional[Any] = None
try:
    from src.volatility_engine.index_garch_predictor import IndexGARCHPredictor as _IndexGARCHPredictor
    IndexGARCHPredictorCls = _IndexGARCHPredictor
    INDEX_GARCH_AVAILABLE = True
except ImportError as e:
    logger.debug(f"指数GARCH预测器导入失败: {e}，将使用原有方法")
    INDEX_GARCH_AVAILABLE = False


def get_remaining_trading_time(config: Optional[Dict] = None) -> int:
    """
    计算当天剩余交易时间（分钟）
    
    Args:
        config: 系统配置
    
    Returns:
        int: 剩余交易时间（分钟）
    """
    try:
        if config is None:
            config = load_system_config()
        
        trading_hours = get_trading_hours_config(config)
        timezone_str = trading_hours.get('timezone', 'Asia/Shanghai')
        tz = pytz.timezone(timezone_str)
        
        now = datetime.now(tz)
        current_time = now.time()
        
        morning_start = time.fromisoformat(trading_hours.get('morning_start', '09:30'))
        morning_end = time.fromisoformat(trading_hours.get('morning_end', '11:30'))
        afternoon_start = time.fromisoformat(trading_hours.get('afternoon_start', '13:00'))
        afternoon_end = time.fromisoformat(trading_hours.get('afternoon_end', '15:00'))
        
        # 总交易时间：240分钟（上午120分钟 + 下午120分钟）
        if current_time < morning_start:
            return 240
        elif morning_start <= current_time <= morning_end:
            # 上午交易时间
            remaining_morning = (morning_end.hour * 60 + morning_end.minute) - (current_time.hour * 60 + current_time.minute)
            return remaining_morning + 120  # 加上下午时间
        elif morning_end < current_time < afternoon_start:
            # 午休时间
            return 120
        elif afternoon_start <= current_time <= afternoon_end:
            # 下午交易时间
            remaining_afternoon = (afternoon_end.hour * 60 + afternoon_end.minute) - (current_time.hour * 60 + current_time.minute)
            return remaining_afternoon
        else:
            return 0  # 收盘后
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'get_remaining_trading_time'},
            "计算剩余交易时间失败"
        )
        return 0


def calculate_index_volatility_range(
    index_minute: pd.DataFrame,
    current_price: float,
    remaining_minutes: int,
    period_label: str = "",
    is_etf_data: bool = False,
    price_ratio: float = 1.0  # ETF价格转指数价格的比率（index_price / etf_price）
) -> Dict[str, Any]:
    """
    计算指数波动区间（单周期）
    支持使用ETF分钟数据替代指数数据（通过price_ratio转换）
    
    Args:
        index_minute: 指数分钟数据（或ETF分钟数据）
        current_price: 当前价格（指数价格或ETF价格）
        remaining_minutes: 剩余交易时间（分钟）
        period_label: 周期标签（用于日志，如"30分钟"、"15分钟"）
        is_etf_data: 是否为ETF数据（默认False）
        price_ratio: ETF价格转指数价格的比率（默认1.0，即不使用转换）
    
    Returns:
        dict: 波动区间信息
    """
    try:
        if index_minute is None or index_minute.empty:
            logger.warning(f"指数分钟数据为空{period_label}")
            return {
                'upper': current_price * 1.02,
                'lower': current_price * 0.98,
                'range_pct': 2.0,
                'method': '默认',
                'confidence': 0.5
            }
        
        # 验证必需的列名（ETF和指数数据格式应该相同）
        required_columns = ['收盘', '开盘', '最高', '最低']
        missing_columns = [col for col in required_columns if col not in index_minute.columns]
        if missing_columns:
            data_type = "ETF" if is_etf_data else "指数"
            logger.error(f"{data_type}分钟数据缺少必需列: {missing_columns}, 可用列: {index_minute.columns.tolist()}")
            raise ValueError(f"{data_type}分钟数据格式不正确，缺少列: {missing_columns}")
        
        # 优先尝试使用GARCH模型集成（阶段3优化）
        garch_min_data_points = 30  # GARCH需要至少30个数据点
        if INDEX_GARCH_AVAILABLE and len(index_minute) >= garch_min_data_points:
            try:
                # 提取价格序列
                price_series = index_minute['收盘'].copy()
                
                # 如果是ETF数据，记录原始价格范围（用于调试）
                if is_etf_data:
                    logger.debug(f"ETF数据价格范围: {price_series.min():.4f} - {price_series.max():.4f}")
                
                # 如果是ETF数据，转换为指数价格
                if is_etf_data and price_ratio != 1.0:
                    price_series = price_series * price_ratio
                    logger.debug(f"ETF数据转换为指数价格: 使用比率 {price_ratio:.6f}")
                
                # 计算剩余时间比例
                remaining_ratio = remaining_minutes / 240.0 if remaining_minutes > 0 else 1.0
                
                # 尝试使用GARCH模型集成（阶段3优化）
                try:
                    from src.garch_ensemble import ensemble_garch_predictions
                    
                    ensemble_result = ensemble_garch_predictions(
                        price_series=price_series,
                        current_price=current_price,
                        remaining_ratio=remaining_ratio,
                        # ensemble_garch_predictions 的类型标注要求 list，这里保留 None 以使用函数内部默认行为
                        models=None,  # type: ignore[arg-type]
                        weights=None,  # type: ignore[arg-type]
                        confidence_level=0.95
                    )
                    
                    if ensemble_result and ensemble_result.get('success', False):
                        upper = ensemble_result.get('upper', current_price * 1.02)
                        lower = ensemble_result.get('lower', current_price * 0.98)
                        range_pct = (upper - lower) / current_price * 100
                        
                        logger.info(f"GARCH集成预测成功{period_label}: {lower:.2f} - {upper:.2f}, "
                                   f"范围: {range_pct:.2f}%, 模型数: {ensemble_result.get('num_models', 0)}")
                        return {
                            'symbol': '000300',
                            'current_price': current_price,
                            'upper': round(upper, 2),
                            'lower': round(lower, 2),
                            'range_pct': round(range_pct, 3),
                            'method': 'GARCH集成',
                            'confidence': ensemble_result.get('confidence', 0.85),
                            'period': period_label,
                            'garch_info': {
                                'predicted_volatility': ensemble_result.get('volatility'),
                                'predicted_price': ensemble_result.get('predicted_price'),
                                'num_models': ensemble_result.get('num_models'),
                                'consistency': ensemble_result.get('consistency')
                            }
                        }
                    else:
                        logger.debug(f"GARCH集成预测失败{period_label}，尝试单模型")
                except Exception as e:
                    logger.debug(f"GARCH集成预测异常{period_label}: {str(e)}，尝试单模型")
                
                # 回退到单GARCH模型（使用优化后的参数）
                try:
                    from src.garch_optimizer import optimize_garch_parameters
                    optimal_params = optimize_garch_parameters(
                        price_series=price_series,
                        use_cache=True,
                        symbol='000300'
                    )
                    garch_p = optimal_params.get('garch_p', 1)
                    garch_q = optimal_params.get('garch_q', 1)
                    arima_order = optimal_params.get('arima_order', (1, 1, 1))
                    logger.debug(f"使用优化后的GARCH参数: p={garch_p}, q={garch_q}, arima={arima_order}")
                except Exception as e:
                    logger.debug(f"GARCH参数优化失败: {e}，使用默认参数")
                    garch_p = 1
                    garch_q = 1
                    arima_order = (1, 1, 1)
                
                assert IndexGARCHPredictorCls is not None
                garch_predictor = IndexGARCHPredictorCls(
                    garch_p=garch_p,
                    garch_q=garch_q,
                    arima_order=arima_order,
                    confidence_level=0.95
                )
                
                # 预测指数区间
                garch_result = garch_predictor.predict_price_range(
                    current_price=current_price,
                    price_series=price_series,
                    horizon=1,
                    remaining_ratio=remaining_ratio
                )
                
                if garch_result.get('success', False):
                    upper = garch_result.get('upper', current_price * 1.02)
                    lower = garch_result.get('lower', current_price * 0.98)
                    range_pct = (upper - lower) / current_price * 100
                    
                    logger.info(f"GARCH预测成功{period_label}: {lower:.2f} - {upper:.2f}, 范围: {range_pct:.2f}%")
                    result = {
                        'symbol': '000300',
                        'current_price': current_price,
                        'upper': round(upper, 2),
                        'lower': round(lower, 2),
                        'range_pct': round(range_pct, 3),
                        'method': 'GARCH+ARIMA',
                        'confidence': 0.85,  # GARCH方法置信度较高
                        'period': period_label,
                        'garch_info': {
                            'predicted_volatility': garch_result.get('volatility'),
                            'predicted_price': garch_result.get('predicted_price'),
                            'fit_info': garch_result.get('fit_info', {})
                        }
                    }
                    # GROK优化：添加突破概率计算
                    breakthrough_prob = calculate_breakthrough_probability(
                        current_price=current_price,
                        upper=upper,
                        lower=lower,
                        confidence=0.85,
                        remaining_minutes=remaining_minutes
                    )
                    result['breakthrough_probability'] = breakthrough_prob
                    return result
                else:
                    logger.debug(f"GARCH预测失败{period_label}: {garch_result.get('error', '未知错误')}，回退到综合方法")
            except Exception as e:
                logger.debug(f"GARCH预测异常{period_label}: {str(e)}，回退到综合方法")
        
        # 回退到传统综合方法
        # 1. 计算ATR
        atr = calculate_atr(index_minute, high_col='最高', low_col='最低', close_col='收盘')
        atr_value = atr.iloc[-1] if atr is not None and not atr.empty else current_price * 0.01
        
        # 2. 计算布林带
        bb = calculate_bollinger_bands(index_minute, close_col='收盘')
        bb_upper = bb['upper'].iloc[-1] if bb is not None else current_price * 1.02
        bb_lower = bb['lower'].iloc[-1] if bb is not None else current_price * 0.98
        
        # 3. 计算历史波动率
        hist_vol = calculate_historical_volatility(index_minute, close_col='收盘')
        hist_vol = hist_vol if hist_vol is not None else 1.5  # 默认1.5%
        
        # 4. 计算日内波动率（当天已交易数据）
        if len(index_minute) > 1:
            price_changes = index_minute['收盘'].pct_change().dropna()
            intraday_vol = price_changes.std() * 100  # 转换为百分比
        else:
            intraday_vol = 1.0
        
        # 5. 综合计算波动区间（加权平均）
        # 方法1：基于ATR
        atr_range_upper = current_price + atr_value * 2
        atr_range_lower = current_price - atr_value * 2
        
        # 方法2：基于历史波动率（年化转日内）
        remaining_ratio = remaining_minutes / 240.0 if remaining_minutes > 0 else 0
        hist_vol_range = current_price * (hist_vol / 100) * np.sqrt(remaining_ratio)
        hist_vol_upper = current_price + hist_vol_range
        hist_vol_lower = current_price - hist_vol_range
        
        # 方法3：基于布林带
        bb_range_upper = bb_upper
        bb_range_lower = bb_lower
        
        # 方法4：基于日内波动率
        intraday_vol_range = current_price * (intraday_vol / 100) * np.sqrt(remaining_ratio)
        intraday_vol_upper = current_price + intraday_vol_range
        intraday_vol_lower = current_price - intraday_vol_range
        
        # 综合方法（加权平均）- 使用市场状态自适应权重
        try:
            from src.volatility_weights import get_market_state_weights, determine_market_state, calculate_dynamic_weights
            
            # 判断市场状态（需要日线数据，如果没有则使用分钟数据）
            market_state = 'range'  # 默认
            try:
                # 尝试从分钟数据判断市场状态
                market_state = determine_market_state(minute_data=index_minute)
            except Exception as e:
                logger.debug(f"判断市场状态失败: {e}，使用默认值")
                market_state = 'range'
            
            # 获取市场状态自适应权重
            state_weights = get_market_state_weights(market_state)
            
            # 尝试获取动态权重（基于历史表现）
            try:
                dynamic_weights = calculate_dynamic_weights({}, lookback_days=30)
                # 结合市场状态权重和动态权重（各50%）
                final_weights = {
                    'atr': (state_weights['atr'] + dynamic_weights.get('atr', 0.3)) / 2,
                    'hist_vol': (state_weights['hist_vol'] + dynamic_weights.get('hist_vol', 0.3)) / 2,
                    'bb': (state_weights['bb'] + dynamic_weights.get('bb', 0.2)) / 2,
                    'intraday_vol': (state_weights['intraday_vol'] + dynamic_weights.get('intraday_vol', 0.2)) / 2
                }
                # 归一化
                total = sum(final_weights.values())
                final_weights = {k: v / total for k, v in final_weights.items()}
            except Exception as e:
                logger.debug(f"获取动态权重失败: {e}，仅使用市场状态权重")
                final_weights = state_weights
            
            # 应用权重
            atr_weight = final_weights.get('atr', 0.3)
            hist_vol_weight = final_weights.get('hist_vol', 0.3)
            bb_weight = final_weights.get('bb', 0.2)
            intraday_vol_weight = final_weights.get('intraday_vol', 0.2)
            
            logger.debug(f"市场状态: {market_state}, 权重: {final_weights}")
        except Exception as e:
            logger.debug(f"权重优化失败: {e}，使用默认权重")
            atr_weight = 0.3
            hist_vol_weight = 0.3
            bb_weight = 0.2
            intraday_vol_weight = 0.2
        
        upper = (atr_range_upper * atr_weight + hist_vol_upper * hist_vol_weight + 
                 bb_range_upper * bb_weight + intraday_vol_upper * intraday_vol_weight)
        lower = (atr_range_lower * atr_weight + hist_vol_lower * hist_vol_weight + 
                 bb_range_lower * bb_weight + intraday_vol_lower * intraday_vol_weight)
        
        range_pct = (upper - lower) / current_price * 100
        
        # 计算置信度（基于数据量）
        confidence = min(0.9, 0.5 + len(index_minute) / 100.0)
        
        result = {
            'symbol': '000300',
            'current_price': current_price,
            'upper': round(upper, 2),
            'lower': round(lower, 2),
            'range_pct': round(range_pct, 3),  # 改为3位小数，保留更多精度
            'method': '综合方法',
            'confidence': round(confidence, 2),
            'period': period_label
        }
        
        # GROK优化：添加突破概率计算
        breakthrough_prob = calculate_breakthrough_probability(
            current_price=current_price,
            upper=upper,
            lower=lower,
            confidence=confidence,
            remaining_minutes=remaining_minutes
        )
        result['breakthrough_probability'] = breakthrough_prob
        
        if period_label:
            logger.info(f"指数波动区间{period_label}: {lower:.2f} - {upper:.2f}, 范围: {range_pct:.2f}%")
        else:
            logger.info(f"指数波动区间: {lower:.2f} - {upper:.2f}, 范围: {range_pct:.2f}%")
        logger.debug(f"突破概率: 上轨={breakthrough_prob['upper_breakthrough_prob']:.2%}, 下轨={breakthrough_prob['lower_breakthrough_prob']:.2%}")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_index_volatility_range', 'current_price': current_price, 'period': period_label},
            "计算指数波动区间失败"
        )
        return {
            'symbol': '000300',
            'current_price': current_price,
            'upper': current_price * 1.02,
            'lower': current_price * 0.98,
            'range_pct': 2.0,
            'method': '默认',
            'confidence': 0.5,
            'period': period_label
        }


def calculate_index_volatility_range_multi_period(
    index_minute_30m: pd.DataFrame,
    index_minute_15m: pd.DataFrame,
    current_price: float,
    remaining_minutes: int,
    primary_weight: float = 0.7,
    secondary_weight: float = 0.3,
    is_etf_data: bool = False,
    price_ratio: float = 1.0  # ETF价格转指数价格的比率
) -> Dict[str, Any]:
    """
    计算指数波动区间（双周期综合：30分钟为主，15分钟为辅）
    支持使用ETF分钟数据替代指数数据
    
    Args:
        index_minute_30m: 30分钟周期指数数据（主周期）或ETF数据
        index_minute_15m: 15分钟周期指数数据（辅助周期）或ETF数据
        current_price: 当前价格（指数价格或ETF价格）
        remaining_minutes: 剩余交易时间（分钟）
        primary_weight: 主周期权重（默认0.7，即30分钟周期）
        secondary_weight: 辅助周期权重（默认0.3，即15分钟周期）
        is_etf_data: 是否为ETF数据（默认False）
        price_ratio: ETF价格转指数价格的比率（默认1.0）
    
    Returns:
        dict: 波动区间信息（综合结果）
"""
    try:
        logger.info("开始双周期波动区间计算（30分钟为主，15分钟为辅）...")
        
        # 1. 使用30分钟周期计算主要波动区间
        primary_range = calculate_index_volatility_range(
            index_minute_30m,
            current_price,
            remaining_minutes,
            period_label="(30分钟周期)",
            is_etf_data=is_etf_data,
            price_ratio=price_ratio
        )
        
        # 2. 使用15分钟周期计算辅助波动区间
        secondary_range = calculate_index_volatility_range(
            index_minute_15m,
            current_price,
            remaining_minutes,
            period_label="(15分钟周期)",
            is_etf_data=is_etf_data,
            price_ratio=price_ratio
        )
        
        # 3. 综合两种周期的结果（加权平均）
        upper = primary_range['upper'] * primary_weight + secondary_range['upper'] * secondary_weight
        lower = primary_range['lower'] * primary_weight + secondary_range['lower'] * secondary_weight
        range_pct = (upper - lower) / current_price * 100
        
        # 综合置信度（取两者平均值，但偏向主周期）
        confidence = primary_range['confidence'] * primary_weight + secondary_range['confidence'] * secondary_weight
        
        result = {
            'symbol': '000300',
            'current_price': current_price,
            'upper': round(upper, 2),
            'lower': round(lower, 2),
            'range_pct': round(range_pct, 3),  # 改为3位小数，保留更多精度
            'method': '双周期综合（30分钟主+15分钟辅）',
            'confidence': round(confidence, 2),
            'primary_range': primary_range,
            'secondary_range': secondary_range,
            'weights': {
                'primary': primary_weight,
                'secondary': secondary_weight
            }
        }
        
        # GROK优化：添加突破概率计算
        breakthrough_prob = calculate_breakthrough_probability(
            current_price=current_price,
            upper=upper,
            lower=lower,
            confidence=confidence,
            remaining_minutes=remaining_minutes
        )
        result['breakthrough_probability'] = breakthrough_prob
        
        logger.info(f"指数波动区间（综合）: {lower:.2f} - {upper:.2f}, 范围: {range_pct:.2f}% (30分钟{primary_weight*100:.0f}% + 15分钟{secondary_weight*100:.0f}%)")
        logger.debug(f"突破概率: 上轨={breakthrough_prob['upper_breakthrough_prob']:.2%}, 下轨={breakthrough_prob['lower_breakthrough_prob']:.2%}")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'calculate_index_volatility_range_multi_period',
                'current_price': current_price,
                'primary_weight': primary_weight,
                'secondary_weight': secondary_weight
            },
            "计算双周期波动区间失败"
        )
        # 如果双周期计算失败，回退到单周期（30分钟）
        if index_minute_30m is not None and not index_minute_30m.empty:
            logger.warning("双周期计算失败，回退到30分钟单周期计算")
            return calculate_index_volatility_range(
                index_minute_30m,
                current_price,
                remaining_minutes,
                period_label="(30分钟周期，回退)"
            )
        else:
            return {
                'symbol': '000300',
                'current_price': current_price,
                'upper': current_price * 1.02,
                'lower': current_price * 0.98,
                'range_pct': 2.0,
                'method': '默认',
                'confidence': 0.5
            }


def calculate_etf_volatility_range(
    etf_minute: pd.DataFrame,
    etf_current_price: float,
    remaining_minutes: int,
    period_label: str = ""
) -> Dict[str, Any]:
    """
    计算ETF波动区间（单周期）- 用ETF数据独立计算
    
    Args:
        etf_minute: ETF分钟数据
        etf_current_price: ETF当前价格
        remaining_minutes: 剩余交易时间（分钟）
        period_label: 周期标签（用于日志，如"30分钟"、"15分钟"）
    
    Returns:
        dict: ETF波动区间信息
    """
    try:
        if etf_minute is None or etf_minute.empty:
            logger.warning(f"ETF分钟数据为空{period_label}")
            return {
                'symbol': '510300',
                'current_price': etf_current_price,
                'upper': etf_current_price * 1.02,
                'lower': max(0, etf_current_price * 0.98),
                'range_pct': 2.0,
                'method': '默认',
                'confidence': 0.5,
                'period': period_label
            }
        
        # 验证必需的列名
        required_columns = ['收盘', '开盘', '最高', '最低']
        missing_columns = [col for col in required_columns if col not in etf_minute.columns]
        if missing_columns:
            logger.error(f"ETF分钟数据缺少必需列: {missing_columns}, 可用列: {etf_minute.columns.tolist()}")
            raise ValueError(f"ETF分钟数据格式不正确，缺少列: {missing_columns}")
        
        # 优先尝试使用GARCH模型（GK优化）
        garch_min_data_points = 30  # GARCH需要至少30个数据点
        if INDEX_GARCH_AVAILABLE and len(etf_minute) >= garch_min_data_points:
            try:
                # 提取价格序列（ETF价格，不需要转换）
                price_series = etf_minute['收盘'].copy()
                logger.debug(f"ETF数据价格范围: {price_series.min():.4f} - {price_series.max():.4f}")
                
                # 计算剩余时间比例
                remaining_ratio = remaining_minutes / 240.0 if remaining_minutes > 0 else 1.0
                
                # 初始化GARCH预测器
                assert IndexGARCHPredictorCls is not None
                garch_predictor = IndexGARCHPredictorCls(
                    garch_p=1,
                    garch_q=1,
                    arima_order=(1, 1, 1),
                    confidence_level=0.95
                )
                
                # 预测ETF区间（使用ETF价格）
                garch_result = garch_predictor.predict_price_range(
                    current_price=etf_current_price,
                    price_series=price_series,
                    horizon=1,
                    remaining_ratio=remaining_ratio
                )
                
                if garch_result.get('success', False):
                    upper = garch_result.get('upper', etf_current_price * 1.02)
                    lower = garch_result.get('lower', etf_current_price * 0.98)
                    range_pct = (upper - lower) / etf_current_price * 100
                    
                    logger.info(f"GARCH预测成功（ETF）{period_label}: {lower:.4f} - {upper:.4f}, 范围: {range_pct:.2f}%")
                    result = {
                        'symbol': '510300',
                        'current_price': etf_current_price,
                        'upper': round(upper, 4),
                        'lower': round(lower, 4),
                        'range_pct': round(range_pct, 3),
                        'method': 'GARCH+ARIMA',
                        'confidence': 0.85,
                        'period': period_label,
                        'garch_info': {
                            'predicted_volatility': garch_result.get('volatility'),
                            'predicted_price': garch_result.get('predicted_price'),
                            'fit_info': garch_result.get('fit_info', {})
                        }
                    }
                    # GROK优化：添加突破概率计算
                    breakthrough_prob = calculate_breakthrough_probability(
                        current_price=etf_current_price,
                        upper=upper,
                        lower=lower,
                        confidence=0.85,
                        remaining_minutes=remaining_minutes
                    )
                    result['breakthrough_probability'] = breakthrough_prob
                    return result
                else:
                    logger.debug(f"GARCH预测失败（ETF）{period_label}: {garch_result.get('error', '未知错误')}，回退到综合方法")
            except Exception as e:
                logger.debug(f"GARCH预测异常（ETF）{period_label}: {str(e)}，回退到综合方法")
        
        # 回退到传统综合方法（使用ETF数据）
        # 1. 计算ATR
        atr = calculate_atr(etf_minute, high_col='最高', low_col='最低', close_col='收盘')
        atr_value = atr.iloc[-1] if atr is not None and not atr.empty else etf_current_price * 0.01
        
        # 2. 计算布林带
        bb = calculate_bollinger_bands(etf_minute, close_col='收盘')
        bb_upper = bb['upper'].iloc[-1] if bb is not None else etf_current_price * 1.02
        bb_lower = bb['lower'].iloc[-1] if bb is not None else etf_current_price * 0.98
        
        # 3. 计算历史波动率
        hist_vol = calculate_historical_volatility(etf_minute, close_col='收盘')
        hist_vol = hist_vol if hist_vol is not None else 1.5  # 默认1.5%
        
        # 4. 计算日内波动率（当天已交易数据）
        if len(etf_minute) > 1:
            price_changes = etf_minute['收盘'].pct_change().dropna()
            intraday_vol = price_changes.std() * 100  # 转换为百分比
        else:
            intraday_vol = 1.0
        
        # 5. 综合计算波动区间（加权平均）
        # 方法1：基于ATR
        atr_range_upper = etf_current_price + atr_value * 2
        atr_range_lower = etf_current_price - atr_value * 2
        
        # 方法2：基于历史波动率（年化转日内）
        remaining_ratio = remaining_minutes / 240.0 if remaining_minutes > 0 else 0
        hist_vol_range = etf_current_price * (hist_vol / 100) * np.sqrt(remaining_ratio)
        hist_vol_upper = etf_current_price + hist_vol_range
        hist_vol_lower = etf_current_price - hist_vol_range
        
        # 方法3：基于布林带
        bb_range_upper = bb_upper
        bb_range_lower = bb_lower
        
        # 方法4：基于日内波动率
        intraday_vol_range = etf_current_price * (intraday_vol / 100) * np.sqrt(remaining_ratio)
        intraday_vol_upper = etf_current_price + intraday_vol_range
        intraday_vol_lower = etf_current_price - intraday_vol_range
        
        # 综合方法（加权平均）
        upper = (atr_range_upper * 0.3 + hist_vol_upper * 0.3 + bb_range_upper * 0.2 + intraday_vol_upper * 0.2)
        lower = (atr_range_lower * 0.3 + hist_vol_lower * 0.3 + bb_range_lower * 0.2 + intraday_vol_lower * 0.2)
        
        range_pct = (upper - lower) / etf_current_price * 100
        
        # 计算置信度（基于数据量）
        confidence = min(0.9, 0.5 + len(etf_minute) / 100.0)
        
        result = {
            'symbol': '510300',
            'current_price': etf_current_price,
            'upper': round(upper, 4),
            'lower': round(lower, 4),
            'range_pct': round(range_pct, 3),
            'method': '综合方法',
            'confidence': round(confidence, 2),
            'period': period_label,
            'hist_vol': hist_vol  # 保存历史波动率，用于IV融合
        }
        
        # 阶段3优化：尝试使用期权IV信息融合（如果可用）
        # 注意：单周期函数需要从调用方传入underlying，这里暂时跳过IV融合
        # IV融合主要在multi_period函数中应用
        
        # GROK优化：添加突破概率计算
        breakthrough_prob = calculate_breakthrough_probability(
            current_price=etf_current_price,
            upper=result['upper'],
            lower=result['lower'],
            confidence=result['confidence'],
            remaining_minutes=remaining_minutes
        )
        result['breakthrough_probability'] = breakthrough_prob
        
        if period_label:
            logger.info(f"ETF波动区间{period_label}: {result['lower']:.4f} - {result['upper']:.4f}, 范围: {result['range_pct']:.2f}%")
        else:
            logger.info(f"ETF波动区间: {result['lower']:.4f} - {result['upper']:.4f}, 范围: {result['range_pct']:.2f}%")
        logger.debug(f"突破概率: 上轨={breakthrough_prob['upper_breakthrough_prob']:.2%}, 下轨={breakthrough_prob['lower_breakthrough_prob']:.2%}")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_etf_volatility_range', 'etf_current_price': etf_current_price, 'period': period_label},
            "计算ETF波动区间失败"
        )
        return {
            'symbol': '510300',
            'current_price': etf_current_price,
            'upper': etf_current_price * 1.02,
            'lower': max(0, etf_current_price * 0.98),
            'range_pct': 2.0,
            'method': '默认',
            'confidence': 0.5,
            'period': period_label
        }


def calculate_etf_volatility_range_multi_period(
    etf_minute_30m: pd.DataFrame,
    etf_minute_15m: pd.DataFrame,
    etf_current_price: float,
    remaining_minutes: int,
    primary_weight: float = 0.7,
    secondary_weight: float = 0.3,
    underlying: str = '510300',  # ETF代码，用于IV融合
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    计算ETF波动区间（双周期综合：30分钟为主，15分钟为辅）
    用ETF数据独立计算，不依赖指数数据
    
    Args:
        etf_minute_30m: 30分钟周期ETF数据（主周期）
        etf_minute_15m: 15分钟周期ETF数据（辅助周期）
        etf_current_price: ETF当前价格
        remaining_minutes: 剩余交易时间（分钟）
        primary_weight: 主周期权重（默认0.7，即30分钟周期）
        secondary_weight: 辅助周期权重（默认0.3，即15分钟周期）
    
    Returns:
        dict: ETF波动区间信息（综合结果）
    """
    try:
        logger.info("开始双周期ETF波动区间计算（30分钟为主，15分钟为辅）...")
        
        # 1. 使用30分钟周期计算主要波动区间
        primary_range = calculate_etf_volatility_range(
            etf_minute_30m,
            etf_current_price,
            remaining_minutes,
            period_label="(30分钟周期)"
        )
        
        # 2. 使用15分钟周期计算辅助波动区间
        secondary_range = calculate_etf_volatility_range(
            etf_minute_15m,
            etf_current_price,
            remaining_minutes,
            period_label="(15分钟周期)"
        )
        
        # 3. 综合两种周期的结果（加权平均）
        upper = primary_range['upper'] * primary_weight + secondary_range['upper'] * secondary_weight
        lower = primary_range['lower'] * primary_weight + secondary_range['lower'] * secondary_weight
        range_pct = (upper - lower) / etf_current_price * 100
        
        # 综合置信度（取两者平均值，但偏向主周期）
        confidence = primary_range['confidence'] * primary_weight + secondary_range['confidence'] * secondary_weight
        
        result = {
            'symbol': '510300',
            'current_price': etf_current_price,
            'upper': round(upper, 4),
            'lower': round(lower, 4),
            'range_pct': round(range_pct, 3),
            'method': '双周期综合（30分钟主+15分钟辅）',
            'confidence': round(confidence, 2),
            'primary_range': primary_range,
            'secondary_range': secondary_range,
            'weights': {
                'primary': primary_weight,
                'secondary': secondary_weight
            },
            'hist_vol': primary_range.get('hist_vol') or (primary_range.get('range_pct', 2.0))  # 保存历史波动率
        }
        
        # 阶段3优化：尝试使用期权IV信息融合（如果可用）
        try:
            from src.option_iv_fusion import incorporate_option_iv
            if config is None:
                config = load_system_config()
            
            # 尝试应用IV融合
            result = incorporate_option_iv(
                etf_prediction=result,
                underlying=underlying,
                option_iv_data=None,  # 自动获取
                config=config
            )
        except Exception as e:
            logger.debug(f"期权IV融合失败（双周期）: {e}，使用原始预测")
        
        # GROK优化：添加突破概率计算
        breakthrough_prob = calculate_breakthrough_probability(
            current_price=etf_current_price,
            upper=result['upper'],
            lower=result['lower'],
            confidence=result['confidence'],
            remaining_minutes=remaining_minutes
        )
        result['breakthrough_probability'] = breakthrough_prob
        
        logger.info(f"ETF波动区间（综合）: {result['lower']:.4f} - {result['upper']:.4f}, 范围: {result['range_pct']:.2f}% (30分钟{primary_weight*100:.0f}% + 15分钟{secondary_weight*100:.0f}%)")
        logger.debug(f"突破概率: 上轨={breakthrough_prob['upper_breakthrough_prob']:.2%}, 下轨={breakthrough_prob['lower_breakthrough_prob']:.2%}")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {
                'function': 'calculate_etf_volatility_range_multi_period',
                'etf_current_price': etf_current_price,
                'primary_weight': primary_weight,
                'secondary_weight': secondary_weight
            },
            "计算双周期ETF波动区间失败"
        )
        # 如果双周期计算失败，回退到单周期（30分钟）
        if etf_minute_30m is not None and not etf_minute_30m.empty:
            logger.warning("双周期计算失败，回退到30分钟单周期计算")
            return calculate_etf_volatility_range(
                etf_minute_30m,
                etf_current_price,
                remaining_minutes,
                period_label="(30分钟周期，回退)"
            )
        else:
            return {
                'symbol': '510300',
                'current_price': etf_current_price,
                'upper': etf_current_price * 1.02,
                'lower': max(0, etf_current_price * 0.98),
                'range_pct': 2.0,
                'method': '默认',
                'confidence': 0.5
            }


def extract_greeks_from_data(greeks_df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """
    从Greeks数据中提取所有Greeks值
    
    Args:
        greeks_df: Greeks数据DataFrame
    
    Returns:
        dict: 包含Delta、Gamma、Theta、Vega、IV的字典
    """
    result: Dict[str, Optional[float]] = {
        'delta': None,
        'gamma': None,
        'theta': None,
        'vega': None,
        'iv': None
    }
    
    if greeks_df is None or greeks_df.empty:
        return result
    
    try:
        for idx, row in greeks_df.iterrows():
            field = str(row.get('字段', ''))
            value = row.get('值', '')
            
            try:
                if 'Delta' in field or 'delta' in field.lower():
                    result['delta'] = float(value)
                elif 'Gamma' in field or 'gamma' in field.lower():
                    result['gamma'] = abs(float(value))  # Gamma始终为正值
                elif 'Theta' in field or 'theta' in field.lower():
                    result['theta'] = float(value)
                elif 'Vega' in field or 'vega' in field.lower():
                    result['vega'] = abs(float(value))  # Vega通常为正值
                elif '波动率' in field or 'IV' in field or 'implied' in field.lower() or 'iv' in field.lower():
                    result['iv'] = float(value)
            except (ValueError, TypeError):
                continue
    except Exception as e:
        logger.debug(f"提取Greeks数据失败: {str(e)}")
    
    return result


def calculate_option_volatility_range(
    option_type: str,
    option_current_price: float,
    etf_range: Dict[str, Any],
    option_greeks: Optional[pd.DataFrame] = None,
    strike_price: Optional[float] = None,
    remaining_minutes: Optional[int] = None,
    config: Optional[Dict] = None,
    contract_code: Optional[str] = None,
    garch_engine: Optional[Any] = None,  # 可选：传入已创建的GARCHIVEngine实例（用于回测优化）
    option_minute_data: Optional[pd.DataFrame] = None  # 新增：期权分钟K线数据，用于计算历史波动率和技术指标
) -> Dict[str, Any]:
    """
    计算期权波动区间（改进版：考虑Delta、Gamma、Vega和IV，集成期权分钟数据）
    
    Args:
        option_type: "call" 或 "put"
        option_current_price: 期权当前价格
        etf_range: ETF波动区间
        option_greeks: 期权Greeks数据
        strike_price: 行权价
        remaining_minutes: 剩余交易时间（分钟），如果为None则自动计算
        config: 系统配置
        contract_code: 合约代码（可选）
        garch_engine: GARCH引擎实例（可选）
        option_minute_data: 期权分钟K线数据（可选），用于计算历史波动率和技术指标
    
    Returns:
        dict: 期权波动区间信息
    """
    try:
        etf_current = etf_range['current_price']
        etf_upper = etf_range['upper']
        etf_lower = etf_range['lower']
        
        # 计算剩余交易时间
        if remaining_minutes is None:
            remaining_minutes = get_remaining_trading_time(config)
        
        # 提取Greeks数据
        greeks = extract_greeks_from_data(option_greeks)
        
        # ========== 新增：使用期权分钟数据计算历史波动率和技术指标 ==========
        option_historical_volatility = None
        option_trend = None
        option_atr = None
        
        if option_minute_data is not None and not option_minute_data.empty:
            try:
                from src.indicator_calculator import (
                    calculate_historical_volatility, 
                    calculate_option_atr
                )
                
                # 确定价格列名（兼容不同的数据格式）
                price_col = None
                for col in ['收盘', 'close', '收盘价', '价格']:
                    if col in option_minute_data.columns:
                        price_col = col
                        break
                
                if price_col:
                    # 计算期权历史波动率（基于分钟K线）
                    option_historical_volatility = calculate_historical_volatility(
                        option_minute_data,
                        period=20,  # 使用20个周期
                        close_col=price_col,
                        data_period='minute'  # 分钟数据
                    )
                    
                    # 计算期权ATR（真实波动幅度）- 使用适配期权数据格式的函数
                    atr_series = calculate_option_atr(
                        option_minute_data,
                        period=14,  # 14周期ATR
                        price_col=price_col
                    )
                    if atr_series is not None and not atr_series.empty:
                        option_atr = float(atr_series.iloc[-1])  # 取最新ATR值
                    else:
                        option_atr = None
                    
                    # 分析期权价格趋势（简单方法：最近N个周期的价格变化）
                    if len(option_minute_data) >= 5:
                        recent_prices = option_minute_data[price_col].tail(5)
                        price_change_pct = (recent_prices.iloc[-1] - recent_prices.iloc[0]) / recent_prices.iloc[0] * 100
                        if price_change_pct > 1.0:
                            option_trend = '上升'
                        elif price_change_pct < -1.0:
                            option_trend = '下降'
                        else:
                            option_trend = '震荡'
                        
                        option_vol_str = f"{option_historical_volatility:.2f}%" if option_historical_volatility is not None else "N/A"
                        option_atr_str = f"{option_atr:.4f}" if option_atr is not None else "N/A"
                        logger.debug(f"期权分钟数据分析: 历史波动率={option_vol_str}, "
                                   f"ATR={option_atr_str}, 趋势={option_trend}")
                    else:
                        logger.debug(f"期权分钟数据不足（{len(option_minute_data)}条），无法计算趋势")
            except Exception as e:
                logger.debug(f"使用期权分钟数据计算指标失败（不影响主流程）: {e}")
        
        # ========== 期权分钟数据处理结束 ==========
        
        # 获取Delta、Gamma、Vega、IV（使用默认值如果未找到）
        delta = greeks.get('delta')
        gamma = greeks.get('gamma')
        vega = greeks.get('vega')
        iv = greeks.get('iv')
        
        # 保存原始IV值用于日志显示
        iv_original = iv
        
        # 设置默认值（基于期权类型和是否为虚值）
        if delta is None:
            # 虚值期权的Delta通常较小（0.1-0.3）
            # 如果行权价已知，可以更精确估计
            if strike_price is not None:
                # 估算Delta：虚值程度越大，Delta越小
                moneyness = etf_current / strike_price if strike_price > 0 else 1.0
                if option_type == 'call':
                    # Call期权：行权价越高（虚值程度越大），Delta越小
                    if moneyness < 0.95:  # 深度虚值
                        delta = 0.1
                    elif moneyness < 0.98:  # 虚值
                        delta = 0.2
                    else:  # 接近平值
                        delta = 0.3
                else:  # put
                    # Put期权：行权价越低（虚值程度越大），Delta越小（绝对值）
                    if moneyness > 1.05:  # 深度虚值
                        delta = -0.1
                    elif moneyness > 1.02:  # 虚值
                        delta = -0.2
                    else:  # 接近平值
                        delta = -0.3
            else:
                # 无行权价信息，使用保守估计
                delta = 0.2 if option_type == 'call' else -0.2
        
        if gamma is None:
            # 虚值期权的Gamma通常较大（0.01-0.05）
            gamma = 0.02  # 默认值
        
        if vega is None:
            # Vega默认值（通常为正值，单位：价格变动/IV变动1%）
            vega = 0.001  # 默认值，表示IV变动1%，期权价格变动0.001
        
        # 计算ETF价格变动（百分比）
        etf_change_up_pct = (etf_upper - etf_current) / etf_current if etf_current > 0 else 0
        etf_change_down_pct = (etf_current - etf_lower) / etf_current if etf_current > 0 else 0
        etf_range_pct = (etf_upper - etf_lower) / etf_current * 100 if etf_current > 0 else 0
        
        # 方法1：Delta + Gamma（基于ETF价格变动）
        if option_type == 'call':
            # Call期权：ETF上涨时，期权价格上涨
            delta_gamma_change_up = delta * etf_change_up_pct + 0.5 * gamma * (etf_change_up_pct ** 2)
            # ETF下跌时，期权价格下跌
            delta_gamma_change_down = delta * (-etf_change_down_pct) + 0.5 * gamma * (etf_change_down_pct ** 2)
        else:  # put
            # Put期权：ETF下跌时，期权价格上涨（Delta为负，所以用绝对值）
            delta_gamma_change_up = abs(delta) * etf_change_down_pct + 0.5 * gamma * (etf_change_down_pct ** 2)
            # ETF上涨时，期权价格下跌
            delta_gamma_change_down = abs(delta) * etf_change_up_pct + 0.5 * gamma * (etf_change_up_pct ** 2)
        
        # 方法2：IV驱动的预期移动（如果IV可用且合理）
        iv_based_change = None
        # IV合理性检查：正常IV应该在5%-50%之间
        if iv is not None and iv > 0:
            # 如果IV < 5%，可能是小数形式（如0.18表示18%），需要乘以100
            if iv < 5.0:
                iv = iv * 100
                logger.debug(f"IV值过小，转换为百分比形式: {iv:.2f}%")
            
            # 再次检查IV合理性
            if 5.0 <= iv <= 50.0:
                # 年化交易时间（分钟）：240分钟/天 × 250交易日/年
                annual_trading_minutes = 240 * 250
                
                # IV驱动的预期移动（ETF价格）
                iv_expected_move = etf_current * (iv / 100) * np.sqrt(remaining_minutes / annual_trading_minutes)
                
                # 期权价格预期变动（考虑Delta）
                iv_based_change = abs(delta) * (iv_expected_move / etf_current)
                
                logger.debug(f"IV驱动的预期移动: ETF={iv_expected_move:.4f}, 期权变动={iv_based_change*100:.2f}%")
            else:
                logger.warning(f"IV值不合理: {iv:.2f}%，忽略IV方法")
                iv = None  # 标记为无效
        
        # 方法3：Vega影响（如果IV可能变化）
        vega_impact = 0.0
        if vega is not None and vega > 0:
            # 假设IV可能变化（基于ETF波动区间，IV可能变化1-3%）
            # 保守估计：IV变化 = ETF波动区间的一半，但不超过5%
            iv_change_expected = min(etf_range_pct / 2.0, 5.0)  # IV可能变化（%），最大5%
            # Vega影响 = Vega值 × IV变化（%）/ 100，转换为期权价格变动百分比
            # Vega通常表示：IV变化1%，期权价格变化多少
            # 所以：期权价格变动% = Vega × IV变化% / 100
            vega_impact = (vega * iv_change_expected) / 100.0
            # 限制Vega影响不超过期权价格的20%
            vega_impact = min(vega_impact, 0.20)
            logger.debug(f"Vega影响: IV预期变化={iv_change_expected:.2f}%, Vega影响={vega_impact*100:.2f}%")
        
        # 方法4：基于期权杠杆效应的波动区间估算（主要方法）
        # 期权价格变动百分比 = Delta × ETF价格变动百分比 × 杠杆系数
        # 杠杆系数 = ETF价格 / 期权价格（但需要限制在合理范围内）
        if option_current_price > 0 and etf_current > 0:
            # 计算杠杆系数
            leverage_ratio = etf_current / option_current_price
            
            # 基于ETF波动区间和Delta估算期权波动区间
            # 期权价格变动% = Delta × ETF价格变动% × 杠杆系数
            # 对于虚值期权，虽然Delta小，但杠杆系数大，所以总体变动应该合理
            leverage_based_change = abs(delta) * (etf_range_pct / 100.0) * leverage_ratio
            
            # 限制基于杠杆的变动在合理范围内
            # 对于虚值期权，波动区间应该在ETF波动区间的6-10倍之间（更符合实际）
            min_change = etf_range_pct / 100.0 * 4.0  # 至少是ETF波动区间的4倍
            max_change = etf_range_pct / 100.0 * 10.0  # 最多是ETF波动区间的10倍
            leverage_based_change = max(min_change, min(leverage_based_change, max_change))
            
            logger.debug(f"期权杠杆系数: {leverage_ratio:.2f}, Delta={delta:.3f}, ETF波动={etf_range_pct:.2f}%, 基于杠杆的变动: {leverage_based_change*100:.2f}%")
        else:
            leverage_based_change = None
        
        # 综合计算期权价格变动
        # 优先使用杠杆效应方法（最符合实际），然后结合其他方法
        if leverage_based_change is not None and leverage_based_change > 0:
            # 使用杠杆效应作为主要方法
            base_change = leverage_based_change
            
            # 如果IV可用，取杠杆效应和IV预期移动的较大值
            if iv_based_change is not None:
                base_change = max(base_change, iv_based_change)
            
            # 加上Delta+Gamma的贡献（作为调整项）
            delta_gamma_up = min(abs(delta_gamma_change_up), 0.15)  # 限制为15%，作为调整项
            delta_gamma_down = min(abs(delta_gamma_change_down), 0.15)
            
            # 加上Vega影响（增加Vega影响，因为IV变化对期权价格影响大）
            option_change_up = base_change + delta_gamma_up + vega_impact * 1.5
            option_change_down = base_change + delta_gamma_down + vega_impact * 1.5
            method = '基于杠杆效应+Delta+Gamma+IV+Vega'
        elif iv_based_change is not None:
            # 使用IV预期移动和Delta+Gamma的较大值，然后加上Vega影响
            delta_gamma_up = min(abs(delta_gamma_change_up), 0.30)  # 限制Delta+Gamma影响不超过30%
            delta_gamma_down = min(abs(delta_gamma_change_down), 0.30)
            iv_change = min(iv_based_change, 0.30)  # 限制IV影响不超过30%
            
            option_change_up = max(delta_gamma_up, iv_change) + vega_impact
            option_change_down = max(delta_gamma_down, iv_change) + vega_impact
            method = '基于Delta+Gamma+IV+Vega'
        else:
            # 仅使用Delta+Gamma，但增加Vega影响
            delta_gamma_up = min(abs(delta_gamma_change_up), 0.30)  # 限制Delta+Gamma影响不超过30%
            delta_gamma_down = min(abs(delta_gamma_change_down), 0.30)
            
            option_change_up = delta_gamma_up + vega_impact
            option_change_down = delta_gamma_down + vega_impact
            method = '基于Delta+Gamma+Vega'
        
        # ========== 新增：使用期权历史波动率调整波动区间 ==========
        if option_historical_volatility is not None and option_historical_volatility > 0:
            # 记录调整前的区间值
            before_adjustment_up = option_change_up
            before_adjustment_down = option_change_down
            
            # 如果期权历史波动率可用，用它来调整波动区间
            # 历史波动率越高，波动区间应该越大
            # 将历史波动率转换为剩余时间内的预期波动
            annual_trading_minutes = 240 * 250
            volatility_adjustment = option_historical_volatility / 100.0 * np.sqrt(remaining_minutes / annual_trading_minutes)
            
            # 调整系数：如果历史波动率较高，增加波动区间；如果较低，减少波动区间
            # 基准：假设历史波动率与ETF波动率相当
            if volatility_adjustment > 0:
                # 计算调整系数（相对于当前计算的波动区间）
                current_avg_change = (option_change_up + option_change_down) / 2
                if current_avg_change > 0:
                    adjustment_ratio = volatility_adjustment / current_avg_change
                    # 优化：放宽调整阈值范围，从 0.8-1.2 改为 0.7-1.5
                    # 优化：增加调整幅度，从最多1.3倍改为最多1.5倍
                    if adjustment_ratio > 1.3:  # 从1.2改为1.3，但允许更大的调整
                        adjustment_factor = min(1.5, adjustment_ratio)  # 从1.3改为1.5
                        option_change_up *= adjustment_factor
                        option_change_down *= adjustment_factor
                        method += f'+历史波动率调整({adjustment_factor:.2f}倍)'
                        logger.info(f"期权历史波动率调整: 历史波动率={option_historical_volatility:.2f}%, "
                                   f"调整系数={adjustment_factor:.2f}, "
                                   f"调整前区间=[{before_adjustment_up*100:.2f}%, {before_adjustment_down*100:.2f}%], "
                                   f"调整后区间=[{option_change_up*100:.2f}%, {option_change_down*100:.2f}%]")
                    elif adjustment_ratio < 0.7:  # 从0.8改为0.7
                        adjustment_factor = max(0.7, adjustment_ratio)  # 从0.8改为0.7
                        option_change_up *= adjustment_factor
                        option_change_down *= adjustment_factor
                        method += f'+历史波动率调整({adjustment_factor:.2f}倍)'
                        logger.info(f"期权历史波动率调整: 历史波动率={option_historical_volatility:.2f}%, "
                                   f"调整系数={adjustment_factor:.2f}, "
                                   f"调整前区间=[{before_adjustment_up*100:.2f}%, {before_adjustment_down*100:.2f}%], "
                                   f"调整后区间=[{option_change_up*100:.2f}%, {option_change_down*100:.2f}%]")
                    else:
                        # 在0.7-1.3范围内，也进行小幅调整（平滑过渡）
                        if adjustment_ratio > 1.0:
                            adjustment_factor = 1.0 + (adjustment_ratio - 1.0) * 0.5  # 平滑调整
                            option_change_up *= adjustment_factor
                            option_change_down *= adjustment_factor
                            method += f'+历史波动率微调({adjustment_factor:.2f}倍)'
                            logger.debug(f"期权历史波动率微调: 历史波动率={option_historical_volatility:.2f}%, "
                                       f"调整系数={adjustment_factor:.2f}")
                        elif adjustment_ratio < 1.0:
                            adjustment_factor = 1.0 - (1.0 - adjustment_ratio) * 0.5  # 平滑调整
                            option_change_up *= adjustment_factor
                            option_change_down *= adjustment_factor
                            method += f'+历史波动率微调({adjustment_factor:.2f}倍)'
                            logger.debug(f"期权历史波动率微调: 历史波动率={option_historical_volatility:.2f}%, "
                                       f"调整系数={adjustment_factor:.2f}")
        
        # 如果期权趋势可用，根据趋势调整波动区间
        if option_trend == '上升':
            # 记录调整前的区间值
            before_trend_up = option_change_up
            before_trend_down = option_change_down
            # 上升趋势：上波动区间略增，下波动区间略减
            option_change_up *= 1.1
            option_change_down *= 0.9
            method += '+趋势调整(上升)'
            logger.info(f"期权趋势调整: 上升趋势，上波动区间+10%，下波动区间-10%, "
                       f"调整前=[{before_trend_up*100:.2f}%, {before_trend_down*100:.2f}%], "
                       f"调整后=[{option_change_up*100:.2f}%, {option_change_down*100:.2f}%]")
        elif option_trend == '下降':
            # 记录调整前的区间值
            before_trend_up = option_change_up
            before_trend_down = option_change_down
            # 下降趋势：上波动区间略减，下波动区间略增
            option_change_up *= 0.9
            option_change_down *= 1.1
            method += '+趋势调整(下降)'
            logger.info(f"期权趋势调整: 下降趋势，上波动区间-10%，下波动区间+10%, "
                       f"调整前=[{before_trend_up*100:.2f}%, {before_trend_down*100:.2f}%], "
                       f"调整后=[{option_change_up*100:.2f}%, {option_change_down*100:.2f}%]")
        # ========== 期权历史波动率调整结束 ==========
        
        # 对于虚值期权，如果Delta很小，应该适度放大波动区间
        # 因为虚值期权虽然Delta小，但IV变化和Gamma效应会放大价格波动
        if abs(delta) < 0.3:  # 虚值期权
            # 放大系数：Delta越小，放大越多，最大放大到1.5倍
            amplification_factor = 1.0 + (0.3 - abs(delta)) * 1.5  # 最大放大到1.5倍
            option_change_up *= amplification_factor
            option_change_down *= amplification_factor
            method += f'（虚值放大{amplification_factor:.2f}倍）'
            logger.debug(f"虚值期权放大: Delta={delta:.3f}, 放大系数={amplification_factor:.2f}")
        
        # 合理性检查：期权价格变动限制
        # 对于虚值期权，允许更大的波动（最大60%）
        max_change = 0.60 if abs(delta) < 0.3 else 0.50  # 虚值期权最大60%，其他50%
        if option_change_up > max_change:
            logger.debug(f"期权价格上变动: {option_change_up*100:.2f}%，限制为{max_change*100:.2f}%")
            option_change_up = max_change
        if option_change_down > max_change:
            logger.debug(f"期权价格下变动: {option_change_down*100:.2f}%，限制为{max_change*100:.2f}%")
            option_change_down = max_change
        
        # 计算理论期权波动区间
        theoretical_upper = option_current_price * (1 + option_change_up)
        theoretical_lower = max(0.001, option_current_price * (1 - option_change_down))  # 期权价格不能为负，最小0.001
        
        # 确保上轨大于下轨
        if theoretical_upper <= theoretical_lower:
            logger.warning(f"期权波动区间异常: 上轨({theoretical_upper:.4f}) <= 下轨({theoretical_lower:.4f})，调整下轨")
            theoretical_lower = max(0.001, theoretical_upper * 0.95)  # 下轨设为上轨的95%
        
        theoretical_range = [theoretical_lower, theoretical_upper]
        
        # 阶段2优化：尝试使用GARCH-IV引擎（如果启用）
        garch_iv_used = False
        garch_iv_info = None
        
        if GARCH_IV_AVAILABLE and config is not None:
            try:
                garch_config = config.get('volatility_engine', {}).get('garch_iv', {})
                if garch_config.get('enabled', False):
                    # 获取必要的参数
                    etf_current = etf_range.get('current_price', 0)
                    if etf_current > 0 and iv is not None and iv > 0 and contract_code:
                        # 尝试获取到期日期（用于准确计算到期时间T）
                        # 优先级：配置文件 > API获取 > remaining_minutes > 默认值
                        expiry_date = None
                        try:
                            # 优先级1：从配置文件读取
                            from src.config_loader import get_contract_expiry_date
                            expiry_date = get_contract_expiry_date(config, option_type)
                            if expiry_date is not None:
                                logger.debug(f"从配置获取到期日期: {contract_code} -> {expiry_date.strftime('%Y-%m-%d')}")
                        except Exception as e:
                            logger.debug(f"从配置获取到期日期失败: {e}")
                        
                        # 优先级2：从API获取（如果配置中没有）
                        if expiry_date is None:
                            try:
                                from src.data_collector import fetch_option_expiry_date
                                expiry_date = fetch_option_expiry_date(contract_code)
                                if expiry_date is not None:
                                    logger.debug(f"从API获取到期日期成功: {contract_code} -> {expiry_date.strftime('%Y-%m-%d')}")
                            except Exception as e:
                                logger.debug(f"从API获取到期日期失败: {e}，将使用remaining_minutes或默认值")
                        
                        # 如果未传入引擎实例，创建新实例（实时系统）
                        # 如果传入了引擎实例，复用该实例（回测优化，利用缓存）
                        if garch_engine is None:
                            assert GARCHIVEngineCls is not None
                            garch_engine = GARCHIVEngineCls(config)
                        
                        # 尝试使用GARCH-IV预测
                        garch_result = garch_engine.predict_option_range(
                            contract_code=contract_code,
                            option_type=option_type,
                            current_price=option_current_price,
                            strike_price=strike_price if strike_price else 0,
                            underlying_price=etf_current,
                            current_iv=iv,
                            expiry_date=expiry_date,  # 优先使用实际到期日期
                            remaining_minutes=remaining_minutes  # 备用
                        )
                        
                        if garch_result.get('success', False):
                            # GARCH-IV预测成功，使用预测结果
                            final_upper = garch_result['upper_price']
                            final_lower = garch_result['lower_price']
                            
                            # 最小价格保护：如果下界过小（<当前价格的10%），使用当前价格的10%作为最小下界
                            # 这可以防止虚值期权在低IV下界时出现不合理的极小价格
                            # 使用10%而不是5%，因为虚值期权的时间价值可能很小，但不应低于当前价格的10%
                            if option_current_price and option_current_price > 0:
                                min_price_threshold = option_current_price * 0.10  # 当前价格的10%
                                if final_lower < min_price_threshold:
                                    logger.debug(f"GARCH-IV下界过小 ({final_lower:.6f} < {min_price_threshold:.6f})，"
                                                f"使用最小价格保护: {min_price_threshold:.6f}")
                                    final_lower = min_price_threshold
                            
                            garch_iv_used = True
                            garch_iv_info = {
                                'method': 'GARCH-IV + B-S',
                                'iv_prediction': garch_result.get('iv_prediction', {}),
                                'performance': garch_result.get('performance', {}),
                                'greeks': garch_result.get('greeks', {})
                            }
                            method = 'GARCH-IV + B-S定价'
                            
                            logger.info(f"GARCH-IV预测成功: {option_type.upper()}期权 {contract_code}, "
                                      f"价格区间=[{final_lower:.4f}, {final_upper:.4f}], "
                                      f"耗时={garch_result.get('performance', {}).get('total_time', 0):.2f}秒")
                        else:
                            # GARCH-IV预测失败，回退到阶段1方法
                            logger.debug(f"GARCH-IV预测失败: {garch_result.get('error', 'unknown')}，回退到阶段1方法")
                    else:
                        logger.debug("GARCH-IV所需参数不完整，跳过GARCH-IV预测")
            except Exception as e:
                logger.warning(f"GARCH-IV引擎调用失败: {e}，回退到阶段1方法", exc_info=True)
        
        # 阶段1优化：应用IV百分位调整和市场校准（如果GARCH-IV未使用）
        if not garch_iv_used:
            final_upper = theoretical_upper
            final_lower = theoretical_lower
        
        calibration_info = None
        liquidity_info = None
        iv_adjustment_info = None
        
        if not garch_iv_used and MARKET_CALIBRATION_AVAILABLE and config is not None:
            try:
                # 1. IV百分位调整
                if iv is not None and iv > 0:
                    iv_adjuster = IVPercentileAdjuster(config)
                    # 获取合约代码（优先使用传入的contract_code，否则从配置获取）
                    iv_contract_code = contract_code
                    if not iv_contract_code and config:
                        contract_config = config.get('option_contracts', {})
                        if option_type == 'call':
                            call_contract = contract_config.get('call_contract', {})
                            iv_contract_code = call_contract.get('contract_code')
                        else:
                            put_contract = contract_config.get('put_contract', {})
                            iv_contract_code = put_contract.get('contract_code')
                    
                    iv_adjustment_result = iv_adjuster.adjust_range(
                        theoretical_range,
                        iv,
                        iv_contract_code
                    )
                    
                    if iv_adjustment_result.get('adjustment_factor', 1.0) != 1.0:
                        # IV调整生效，使用调整后的区间
                        adjusted_range = iv_adjustment_result['adjusted_range']
                        final_lower = adjusted_range[0]
                        final_upper = adjusted_range[1]
                        iv_adjustment_info = {
                            'adjustment_factor': iv_adjustment_result['adjustment_factor'],
                            'percentile': iv_adjustment_result['percentile'],
                            'reason': iv_adjustment_result['reason']
                        }
                        logger.info(f"IV百分位调整: {iv_adjustment_result['reason']}, 调整系数={iv_adjustment_result['adjustment_factor']:.2f}")
                
                # 2. 市场校准
                market_calibrator = MarketMicrostructureCalibrator(config)
                # 获取合约代码（优先使用传入的contract_code，否则从配置获取）
                if not contract_code and config:
                    contract_config = config.get('option_contracts', {})
                    if option_type == 'call':
                        call_contract = contract_config.get('call_contract', {})
                        contract_code = call_contract.get('contract_code')
                    else:
                        put_contract = contract_config.get('put_contract', {})
                        contract_code = put_contract.get('contract_code')
                
                if contract_code:
                    calibration_result = market_calibrator.calibrate_option_range(
                        contract_code,
                        [final_lower, final_upper],  # 使用IV调整后的区间
                        option_current_price
                    )
                    
                    if calibration_result.get('status') == 'success':
                        # 校准成功，使用校准后的区间
                        calibrated_range = calibration_result['calibrated_range']
                        final_lower = calibrated_range[0]
                        final_upper = calibrated_range[1]
                        calibration_info = calibration_result['calibration_info']
                        liquidity_info = calibration_result.get('liquidity_report')
                        
                        # 更新方法说明
                        if iv_adjustment_info:
                            method += f"+IV调整({iv_adjustment_info['adjustment_factor']:.2f})"
                        method += "+市场校准"
                        
                        logger.info(f"市场校准成功: 理论区间=[{theoretical_lower:.4f}, {theoretical_upper:.4f}], "
                                  f"校准后=[{final_lower:.4f}, {final_upper:.4f}], "
                                  f"流动性={liquidity_info.get('grade', 'unknown') if liquidity_info else 'unknown'}")
                    else:
                        # 校准失败，使用理论区间（或IV调整后的区间）
                        logger.warning(f"市场校准失败: {calibration_result.get('calibration_info', {}).get('adjustment_info', 'unknown')}，使用理论区间")
                else:
                    logger.debug("合约代码未提供，跳过市场校准")
                    
            except Exception as e:
                logger.warning(f"市场校准或IV调整失败: {e}，使用理论区间", exc_info=True)
                # 回退到理论区间
                final_upper = theoretical_upper
                final_lower = theoretical_lower
        
        # 最终合理性检查：波动区间范围限制（根据剩余时间动态调整）
        range_pct = (final_upper - final_lower) / option_current_price * 100 if option_current_price > 0 else 0
        
        # 根据剩余交易时间动态调整最大区间宽度
        # 剩余时间越少，区间宽度应该越小（时间衰减效应）
        if remaining_minutes is not None and remaining_minutes > 0:
            # 时间衰减系数：剩余时间越少，系数越小（最小0.6，最大1.0）
            time_decay_factor = max(0.6, min(1.0, remaining_minutes / 240.0))
            # 基础最大区间宽度
            base_max_range_pct = 70.0 if abs(delta) < 0.3 else 50.0
            # 应用时间衰减
            max_range_pct = base_max_range_pct * time_decay_factor
            logger.debug(f"剩余时间={remaining_minutes}分钟, 时间衰减系数={time_decay_factor:.2f}, 最大区间宽度={max_range_pct:.2f}%")
        else:
            max_range_pct = 70.0 if abs(delta) < 0.3 else 50.0
        
        if range_pct > max_range_pct:
            logger.debug(f"期权波动区间范围: {range_pct:.3f}%，限制为{max_range_pct:.3f}%")
            # 重新计算，使范围不超过限制
            mid_price = (final_upper + final_lower) / 2
            range_ratio = max_range_pct / 100.0 / 2.0
            final_upper = mid_price * (1 + range_ratio)
            final_lower = mid_price * (1 - range_ratio)
            range_pct = max_range_pct
        
        # 基础结果
        result = {
            "option_type": option_type,
            "current_price": option_current_price,
            "upper": round(final_upper, 4),
            "lower": round(final_lower, 4),
            "range_pct": round(range_pct, 3),  # 改为3位小数，保留更多精度
            "method": method,
            "confidence": etf_range.get("confidence", 0.5) * 0.8,  # 期权预测置信度略低
            "delta": round(delta, 4) if delta is not None else None,
            "gamma": round(gamma, 6) if gamma is not None else None,
            "vega": round(vega, 6) if vega is not None else None,
            "iv": round(iv, 2) if iv is not None else None,  # 使用处理后的IV值
            "option_historical_volatility": round(option_historical_volatility, 2)
            if option_historical_volatility is not None
            else None,  # 新增：期权历史波动率
            "option_trend": option_trend,  # 新增：期权趋势
            "option_atr": round(option_atr, 4) if option_atr is not None else None,  # 新增：期权ATR
        }

        # 虚值期权特有风险提示（Theta衰减 + Gamma 加速）
        risk_warnings: list[str] = []
        try:
            if remaining_minutes is not None and remaining_minutes < 120 and abs(delta) < 0.3:
                risk_warnings.append(
                    f"剩余时间较短（{remaining_minutes} 分钟），虚值期权 Theta 衰减加速，区间下沿可能快速收窄"
                )
            if gamma is not None and gamma > 0.03:
                risk_warnings.append(
                    "Gamma 较高，若突破方向相反，价格可能出现快速反向放大，需控制仓位与止损"
                )
        except Exception as e:
            # 风险提示失败不影响主流程，但记录一下，便于追踪潜在数据问题
            logger.debug(f"生成 risk_warnings 失败，忽略: {e}", exc_info=True)
        if risk_warnings:
            result["risk_warnings"] = risk_warnings
        
        # 添加阶段2优化信息（GARCH-IV）
        if garch_iv_info:
            result['garch_iv_info'] = garch_iv_info
        
        # 添加阶段1优化信息
        if calibration_info:
            result['calibration_info'] = calibration_info
        if liquidity_info:
            result['liquidity_info'] = liquidity_info
        if iv_adjustment_info:
            result['iv_adjustment_info'] = iv_adjustment_info
        
        # GROK优化：添加突破概率计算
        breakthrough_prob = calculate_breakthrough_probability(
            current_price=option_current_price,
            upper=final_upper,
            lower=final_lower,
            confidence=result['confidence'],
            remaining_minutes=remaining_minutes
        )
        result['breakthrough_probability'] = breakthrough_prob
        
        # GROK优化：添加Greeks贡献拆解
        etf_current = etf_range.get('current_price', 0)
        etf_upper = etf_range.get('upper', etf_current)
        etf_lower = etf_range.get('lower', etf_current)
        if etf_current > 0:
            etf_change_up_pct = (etf_upper - etf_current) / etf_current
            etf_change_down_pct = (etf_current - etf_lower) / etf_current
            # 计算IV变动百分比（如果有历史IV数据）
            iv_change_pct = None
            if iv is not None and iv > 0:
                # 简单估算：假设IV变动与ETF波动率相关
                # 这里可以后续优化，使用实际的历史IV数据
                iv_change_pct = (etf_change_up_pct + etf_change_down_pct) / 2.0
            
            greeks_contribution = calculate_greeks_contribution(
                delta=delta if delta is not None else 0.0,
                gamma=gamma if gamma is not None else 0.0,
                vega=vega,
                etf_change_up_pct=etf_change_up_pct,
                etf_change_down_pct=etf_change_down_pct,
                iv_change_pct=iv_change_pct
            )
            result['greeks_contribution'] = greeks_contribution
        
        # GROK优化：格式化IV Percentile上下文显示
        if iv_adjustment_info:
            percentile = iv_adjustment_info.get('percentile', None)
            adjustment_factor = iv_adjustment_info.get('adjustment_factor', 1.0)
            reason = iv_adjustment_info.get('reason', '')
            
            if percentile is not None:
                if percentile >= 70:
                    percentile_desc = f"高位（{percentile:.0f}%分位）"
                    risk_hint = "高位压缩风险"
                elif percentile <= 30:
                    percentile_desc = f"低位（{percentile:.0f}%分位）"
                    risk_hint = "低位扩展机会"
                else:
                    percentile_desc = f"中位（{percentile:.0f}%分位）"
                    risk_hint = "正常范围"
                
                result['iv_percentile_context'] = {
                    'percentile': percentile,
                    'percentile_desc': percentile_desc,
                    'adjustment_factor': adjustment_factor,
                    'reason': reason,
                    'risk_hint': risk_hint,
                    'display': f"IV Percentile: {percentile_desc}，{reason}（调整系数{adjustment_factor:.2f}）"
                }
        
        # 添加行权价（如果提供）
        if strike_price is not None:
            result['strike_price'] = strike_price
        
        # 格式化Delta和IV显示
        delta_str = f"{delta:.3f}" if delta is not None else "N/A"
        # 使用处理后的IV值（如果转换过，已经是百分比形式）
        iv_display = iv if iv is not None else iv_original
        iv_str = f"{iv_display:.1f}%" if iv_display is not None else "N/A"
        
        # 添加流动性信息到日志
        liquidity_str = ""
        if liquidity_info:
            liquidity_str = f", 流动性={liquidity_info.get('grade', 'unknown')}"
            if liquidity_info.get('warnings'):
                liquidity_str += f" ({', '.join(liquidity_info['warnings'])})"
        
        logger.info(f"{option_type.upper()}期权波动区间: {final_lower:.4f} - {final_upper:.4f}, 范围: {range_pct:.2f}% (Delta={delta_str}, IV={iv_str}{liquidity_str})")
        logger.debug(f"突破概率: 上轨={breakthrough_prob['upper_breakthrough_prob']:.2%}, 下轨={breakthrough_prob['lower_breakthrough_prob']:.2%}")
        if 'greeks_contribution' in result:
            greeks_contrib = result['greeks_contribution']
            logger.debug(f"Greeks贡献: Delta={greeks_contrib['delta_contribution_pct']:.1f}%, "
                        f"Gamma={greeks_contrib['gamma_contribution_pct']:.1f}%, "
                        f"Vega={greeks_contrib['vega_contribution_pct']:.1f}%")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_option_volatility_range', 'option_type': option_type},
            "计算期权波动区间失败"
        )
        return {
            'option_type': option_type,
            'current_price': option_current_price,
            'upper': option_current_price * 1.05,
            'lower': max(0, option_current_price * 0.95),
            'range_pct': 5.0,
            'method': '默认',
            'confidence': 0.5
        }


def calculate_volatility_ranges(
    index_minute: pd.DataFrame = None,
    index_minute_30m: pd.DataFrame = None,
    index_minute_15m: pd.DataFrame = None,
    etf_minute_30m: pd.DataFrame = None,  # 新增：ETF分钟数据
    etf_minute_15m: pd.DataFrame = None,  # 新增：ETF分钟数据
    etf_current_price: Optional[float] = None,
    call_option_price: Optional[float] = None,
    put_option_price: Optional[float] = None,
    call_option_greeks: Optional[pd.DataFrame] = None,
    put_option_greeks: Optional[pd.DataFrame] = None,
    config: Optional[Dict] = None,
    call_contract_code: Optional[str] = None,
    put_contract_code: Optional[str] = None,
    use_multi_period: bool = True,
    garch_engine: Optional[Any] = None  # 可选：传入已创建的GARCHIVEngine实例（用于回测优化）
) -> Dict[str, Any]:
    """
    计算所有波动区间（指数、ETF、期权）
    指数和ETF数据独立计算，不互相依赖
    
    Args:
        index_minute: 指数分钟数据（5分钟周期，兼容旧接口）
        index_minute_30m: 30分钟周期指数数据（主周期）
        index_minute_15m: 15分钟周期指数数据（辅助周期）
        etf_minute_30m: 30分钟周期ETF数据（主周期）- 新增
        etf_minute_15m: 15分钟周期ETF数据（辅助周期）- 新增
        etf_current_price: ETF当前价格
        call_option_price: Call期权当前价格
        put_option_price: Put期权当前价格
        call_option_greeks: Call期权Greeks数据
        put_option_greeks: Put期权Greeks数据
        config: 系统配置
        call_contract_code: Call期权合约代码（可选，如果未提供则从配置加载）
        put_contract_code: Put期权合约代码（可选，如果未提供则从配置加载）
        use_multi_period: 是否使用双周期计算（默认True，30分钟+15分钟）
    
    Returns:
        dict: 所有波动区间信息，包含：
            - index_range: 指数波动区间（用于用户展示）
            - etf_range: ETF波动区间（用于内部预测）
            - call_ranges: Call期权波动区间列表（多合约格式）
            - put_ranges: Put期权波动区间列表（多合约格式）
    """
    try:
        logger.info("开始计算波动区间（指数和ETF独立计算）...")
        
        # 计算剩余交易时间
        remaining_minutes = get_remaining_trading_time(config)
        
        # ========== 1. 计算指数波动区间（用指数数据） ==========
        if use_multi_period and index_minute_30m is not None and index_minute_15m is not None:
            # 使用双周期计算（30分钟+15分钟）
            logger.info("使用双周期计算指数波动区间（30分钟为主，15分钟为辅）")
            
            # 获取指数当前价格
            if index_minute_30m is not None and not index_minute_30m.empty:
                index_current_price = index_minute_30m['收盘'].iloc[-1]
            elif index_minute_15m is not None and not index_minute_15m.empty:
                index_current_price = index_minute_15m['收盘'].iloc[-1]
            else:
                logger.warning("指数分钟数据都为空，使用默认值")
                index_current_price = 4000.0
            
            # 计算指数波动区间（用指数数据，不需要转换）
            index_range = calculate_index_volatility_range_multi_period(
                index_minute_30m,
                index_minute_15m,
                index_current_price,
                remaining_minutes,
                is_etf_data=False,  # 明确指定为指数数据
                price_ratio=1.0  # 不需要转换
            )
        else:
            # 使用单周期计算（兼容旧接口，使用5分钟数据）
            logger.info("使用单周期计算指数波动区间（5分钟周期）")
            
            if index_minute is None:
                logger.warning("未提供指数分钟数据，使用默认值")
                index_current_price = 4000.0
                index_range = {
                    'symbol': '000300',
                    'current_price': index_current_price,
                    'upper': index_current_price * 1.02,
                    'lower': index_current_price * 0.98,
                    'range_pct': 2.0,
                    'method': '默认',
                    'confidence': 0.5
                }
            else:
                index_current_price = index_minute['收盘'].iloc[-1]
                # 计算指数波动区间（单周期）
                index_range = calculate_index_volatility_range(
                    index_minute,
                    index_current_price,
                    remaining_minutes,
                    is_etf_data=False,
                    price_ratio=1.0
                )
        
        # ========== 2. 计算ETF波动区间（用ETF数据，独立计算） ==========
        # 如果ETF价格为0或None，使用默认值
        if etf_current_price is None or etf_current_price <= 0:
            logger.warning(f"ETF当前价格无效: {etf_current_price}，尝试重新获取...")
            from src.data_collector import get_etf_current_price
            etf_current_price = get_etf_current_price()
            if etf_current_price is None or etf_current_price <= 0:
                logger.warning("重新获取ETF价格失败，使用默认价格4.8")
                etf_current_price = 4.8  # 使用默认价格（510300的典型价格）
        
        # 使用ETF数据独立计算ETF波动区间
        if use_multi_period and etf_minute_30m is not None and etf_minute_15m is not None:
            # 使用双周期计算（30分钟+15分钟）
            logger.info("使用双周期计算ETF波动区间（30分钟为主，15分钟为辅）")
            etf_range = calculate_etf_volatility_range_multi_period(
                etf_minute_30m,
                etf_minute_15m,
                etf_current_price,
                remaining_minutes
            )
        else:
            # 使用单周期计算（如果没有提供30分钟和15分钟数据，使用默认值）
            logger.warning("未提供ETF分钟数据，使用默认ETF波动区间")
            etf_range = {
                'symbol': '510300',
                'current_price': etf_current_price,
                'upper': etf_current_price * 1.02,
                'lower': max(0, etf_current_price * 0.98),
                'range_pct': 2.0,
                'method': '默认',
                'confidence': 0.5
            }
        
        # 3. 获取合约配置（支持多个合约）
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        from src.config_loader import get_contract_codes
        call_contracts_config = get_contract_codes(config, 'call', verify_strike=False) if call_contract_code is None else None
        put_contracts_config = get_contract_codes(config, 'put', verify_strike=False) if put_contract_code is None else None
        
        # 向后兼容：如果使用旧的单个合约参数，转换为列表格式
        if call_contract_code is not None:
            call_contracts_config = [{'contract_code': call_contract_code, 'strike_price': None, 'expiry_date': None, 'name': call_contract_code}]
        elif not call_contracts_config:
            # 如果新格式也没有，尝试使用旧的get_contract_code（向后兼容）
            from src.config_loader import get_contract_code
            old_call_code = get_contract_code(config, 'call', verify_strike=False)
            if old_call_code:
                call_contracts_config = [{'contract_code': old_call_code, 'strike_price': None, 'expiry_date': None, 'name': old_call_code}]
        
        if put_contract_code is not None:
            put_contracts_config = [{'contract_code': put_contract_code, 'strike_price': None, 'expiry_date': None, 'name': put_contract_code}]
        elif not put_contracts_config:
            # 如果新格式也没有，尝试使用旧的get_contract_code（向后兼容）
            from src.config_loader import get_contract_code
            old_put_code = get_contract_code(config, 'put', verify_strike=False)
            if old_put_code:
                put_contracts_config = [{'contract_code': old_put_code, 'strike_price': None, 'expiry_date': None, 'name': old_put_code}]
        
        # 4. 计算多个Call期权波动区间
        call_ranges = []
        if call_contracts_config:
            # 如果传入了单个call_option_price和call_option_greeks，只用于第一个合约（向后兼容）
            if call_option_price is not None and call_option_greeks is not None:
                # 向后兼容：使用传入的单个价格和Greeks
                call_strike_price = None
                if call_option_greeks is not None and not call_option_greeks.empty:
                    for idx, row in call_option_greeks.iterrows():
                        field = str(row.get('字段', ''))
                        if '行权价' in field or 'strike' in field.lower():
                            try:
                                call_strike_price = float(row.get('值', 0))
                                break
                            except (ValueError, TypeError):
                                pass
                
                if call_contracts_config:
                    first_call = call_contracts_config[0]
                    contract_code = first_call.get('contract_code')
                    strike_price = call_strike_price or first_call.get('strike_price')
                    
                    call_range = calculate_option_volatility_range(
                        'call',
                        call_option_price,
                        etf_range,
                        call_option_greeks,
                        strike_price=strike_price,
                        remaining_minutes=remaining_minutes,
                        config=config,
                        contract_code=contract_code,
                        garch_engine=garch_engine
                    )
                    if call_range:
                        call_range['contract_code'] = contract_code
                        call_range['name'] = first_call.get('name', contract_code)
                        if strike_price:
                            call_range['strike_price'] = strike_price
                        if first_call.get('expiry_date'):
                            call_range['expiry_date'] = first_call.get('expiry_date')
                        call_ranges.append(call_range)
            else:
                # 新格式：为每个合约计算波动区间（需要从外部传入每个合约的价格和Greeks）
                # 注意：此情况下需要外部循环调用，这里只处理已传入的数据
                pass
        
        
        # 5. 计算多个Put期权波动区间
        put_ranges = []
        if put_contracts_config:
            # 如果传入了单个put_option_price和put_option_greeks，只用于第一个合约（向后兼容）
            if put_option_price is not None and put_option_greeks is not None:
                # 向后兼容：使用传入的单个价格和Greeks
                put_strike_price = None
                if put_option_greeks is not None and not put_option_greeks.empty:
                    for idx, row in put_option_greeks.iterrows():
                        field = str(row.get('字段', ''))
                        if '行权价' in field or 'strike' in field.lower():
                            try:
                                put_strike_price = float(row.get('值', 0))
                                break
                            except (ValueError, TypeError):
                                pass
                
                if put_contracts_config:
                    first_put = put_contracts_config[0]
                    contract_code = first_put.get('contract_code')
                    strike_price = put_strike_price or first_put.get('strike_price')
                    
                    put_range = calculate_option_volatility_range(
                        'put',
                        put_option_price,
                        etf_range,
                        put_option_greeks,
                        strike_price=strike_price,
                        remaining_minutes=remaining_minutes,
                        config=config,
                        contract_code=contract_code,
                        garch_engine=garch_engine
                    )
                    if put_range:
                        put_range['contract_code'] = contract_code
                        put_range['name'] = first_put.get('name', contract_code)
                        if strike_price:
                            put_range['strike_price'] = strike_price
                        if first_put.get('expiry_date'):
                            put_range['expiry_date'] = first_put.get('expiry_date')
                        put_ranges.append(put_range)
            else:
                # 新格式：为每个合约计算波动区间（需要从外部传入每个合约的价格和Greeks）
                # 注意：此情况下需要外部循环调用，这里只处理已传入的数据
                pass
        
        
        # 7. 计算市场状态（如果指数分钟数据可用）
        market_status = {}
        try:
            from src.indicator_calculator import calculate_rsi, calculate_atr
            from src.data_storage import load_trend_analysis
            
            # 获取开盘策略（用于整体趋势）
            opening_strategy = load_trend_analysis(analysis_type='before_open', config=config) if config else None
            overall_trend = opening_strategy.get('final_trend', '震荡') if opening_strategy else '震荡'
            trend_strength = opening_strategy.get('final_strength', 0.5) if opening_strategy else 0.5
            
            # 计算日内RSI和ATR
            intraday_rsi = None
            atr_value = None
            if index_minute is not None and not index_minute.empty:
                rsi_series = calculate_rsi(index_minute, close_col='收盘')
                if rsi_series is not None and not rsi_series.empty:
                    intraday_rsi = round(float(rsi_series.iloc[-1]), 2)
                
                atr_series = calculate_atr(index_minute, high_col='最高', low_col='最低', close_col='收盘')
                if atr_series is not None and not atr_series.empty:
                    atr_value = round(float(atr_series.iloc[-1]), 2)
            
            # 判断波动状态
            volatility_status = "正常波动"
            if index_minute is not None and len(index_minute) > 1:
                price_changes = index_minute['收盘'].pct_change().dropna()
                intraday_vol = price_changes.std() * 100
                if intraday_vol > 1.5:
                    volatility_status = "高波动"
                elif intraday_vol < 0.5:
                    volatility_status = "低波动"
            
            market_status = {
                'overall_trend': overall_trend,
                'trend_strength': round(trend_strength, 2),
                'intraday_rsi': intraday_rsi,
                'atr': atr_value,
                'volatility_status': volatility_status
            }
        except Exception as e:
            logger.debug(f"计算市场状态失败: {str(e)}")
            market_status = {
                'overall_trend': '未知',
                'trend_strength': 0.5,
                'intraday_rsi': None,
                'atr': None,
                'volatility_status': '未知'
            }
        
        # 8. 生成操作建议
        trading_suggestions = {}
        try:
            if etf_range:
                etf_current = etf_range.get('current_price', etf_current_price)
                etf_upper = etf_range.get('upper')
                etf_lower = etf_range.get('lower')
                
                if etf_upper and etf_lower and etf_upper > etf_lower:
                    etf_position = (etf_current - etf_lower) / (etf_upper - etf_lower)
                    
                    if etf_position < 0.3:
                        etf_suggestion = f"当前价格({etf_current:.3f})接近下轨({etf_lower:.3f})，如果整体趋势强势，可能反弹"
                    elif etf_position > 0.7:
                        etf_suggestion = f"当前价格({etf_current:.3f})接近上轨({etf_upper:.3f})，如果整体趋势弱势，可能回调"
                    else:
                        etf_suggestion = f"当前价格({etf_current:.3f})在波动区间中部，等待突破方向"
                    
                    trading_suggestions['etf'] = {
                        'support': round(etf_lower, 3),
                        'resistance': round(etf_upper, 3),
                        'suggestion': etf_suggestion
                    }
            
            if call_ranges:
                call_range = call_ranges[0]  # 使用第一个合约
                call_upper = call_range.get('upper')
                call_lower = call_range.get('lower')
                if call_upper and etf_range and etf_range.get('upper'):
                    call_suggestion = f"如果ETF上涨至{etf_range['upper']:.3f}，Call期权可能上涨至{call_upper:.3f}"
                    trading_suggestions['call_option'] = {
                        'support': round(call_lower, 4) if call_lower else None,
                        'resistance': round(call_upper, 4) if call_upper else None,
                        'suggestion': call_suggestion
                    }
            
            if put_ranges:
                put_range = put_ranges[0]  # 使用第一个合约
                put_upper = put_range.get('upper')
                put_lower = put_range.get('lower')
                if put_upper and etf_range and etf_range.get('lower'):
                    put_suggestion = f"如果ETF下跌至{etf_range['lower']:.3f}，Put期权可能上涨至{put_upper:.3f}"
                    trading_suggestions['put_option'] = {
                        'support': round(put_lower, 4) if put_lower else None,
                        'resistance': round(put_upper, 4) if put_upper else None,
                        'suggestion': put_suggestion
                    }
        except Exception as e:
            logger.debug(f"生成操作建议失败: {str(e)}")
        
        result = {
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),
            'remaining_time_minutes': remaining_minutes,
            'index_range': index_range,
            'etf_range': etf_range,
            # 新格式：多个合约列表
            'call_ranges': call_ranges,  # 所有Call合约的波动区间列表
            'put_ranges': put_ranges,  # 所有Put合约的波动区间列表
            'market_status': market_status,  # 符合STRATEGY.md规范
            'trading_suggestions': trading_suggestions  # 符合STRATEGY.md规范
        }
        
        logger.info("波动区间计算完成")
        return result
        
    except Exception as e:
        log_error_with_context(
            logger, e,
            {'function': 'calculate_volatility_ranges'},
            "计算波动区间失败"
        )
        return {
            'timestamp': datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),
            'remaining_time_minutes': 0,
            'index_range': None,
            'etf_range': None,
            'call_ranges': [],
            'put_ranges': [],
            'market_status': None,
            'trading_suggestions': {}
        }
