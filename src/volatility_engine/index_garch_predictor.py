"""
指数GARCH区间预测器
复用GARCH引擎，用于预测指数价格区间（而非IV）
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
from datetime import datetime
import warnings

try:
    from arch import arch_model
    from statsmodels.tsa.arima.model import ARIMA
    ARCH_AVAILABLE = True
    ARIMA_AVAILABLE = True
except ImportError as e:
    ARCH_AVAILABLE = False
    ARIMA_AVAILABLE = False
    warnings.warn(f"arch或statsmodels库未安装，指数GARCH预测功能将不可用: {e}")

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


class IndexGARCHPredictor:
    """
    指数GARCH区间预测器
    使用GARCH模型预测指数价格波动率，结合ARIMA预测价格趋势，计算价格区间
    """
    
    def __init__(
        self,
        garch_p: int = 1,
        garch_q: int = 1,
        arima_order: tuple = (1, 1, 1),
        distribution: str = "normal",
        confidence_level: float = 0.95
    ):
        """
        初始化指数GARCH预测器
        
        Args:
            garch_p: GARCH模型的ARCH项阶数
            garch_q: GARCH模型的GARCH项阶数
            arima_order: ARIMA模型的阶数 (p, d, q)
            distribution: 残差分布类型 ("normal", "t", "skewt")
            confidence_level: 置信水平（默认0.95，即95%置信区间）
        """
        if not ARCH_AVAILABLE:
            raise ImportError("arch库未安装，无法使用GARCH功能")
        if not ARIMA_AVAILABLE:
            raise ImportError("statsmodels库未安装，无法使用ARIMA功能")
        
        self.garch_p = garch_p
        self.garch_q = garch_q
        self.arima_order = arima_order
        self.distribution = distribution
        self.confidence_level = confidence_level
        self.garch_model = None
        self.garch_fit = None
        self.arima_model = None
        self.arima_fit = None
        self.fitted = False
    
    def prepare_price_data(self, price_series: pd.Series) -> pd.Series:
        """
        准备价格数据用于GARCH建模（计算收益率）
        
        Args:
            price_series: 价格时间序列
        
        Returns:
            收益率序列
        """
        if len(price_series) < 20:
            raise ValueError(f"价格数据不足，至少需要20个数据点，当前只有{len(price_series)}个")
        
        # 计算对数收益率
        returns = np.diff(np.log(price_series.values + 1e-6))  # 加小值避免log(0)
        
        # 转换为Series
        returns_series = pd.Series(returns, index=price_series.index[1:])
        
        return returns_series
    
    def fit(self, price_series: pd.Series) -> Dict[str, Any]:
        """
        拟合GARCH和ARIMA模型
        
        Args:
            price_series: 价格时间序列
        
        Returns:
            拟合结果字典
        """
        if not ARCH_AVAILABLE or not ARIMA_AVAILABLE:
            raise ImportError("arch或statsmodels库未安装")
        
        try:
            # 1. 准备收益率数据用于GARCH
            returns = self.prepare_price_data(price_series)
            
            if len(returns) < max(self.garch_p, self.garch_q) + 10:
                raise ValueError(f"数据不足，无法拟合GARCH({self.garch_p},{self.garch_q})模型")
            
            # 2. 拟合GARCH模型（用于预测波动率）
            logger.debug(f"开始拟合GARCH({self.garch_p},{self.garch_q})模型，数据点: {len(returns)}")
            # 缩放数据以避免DataScaleWarning（将收益率乘以100转换为百分比，再乘以10以改善缩放）
            scaled_returns = returns * 1000  # 转换为千分比形式，改善缩放
            self.garch_model = arch_model(
                scaled_returns,
                vol='Garch',
                p=self.garch_p,
                q=self.garch_q,
                dist=self.distribution,
                rescale=False  # 我们已经手动缩放了
            )
            self.garch_fit = self.garch_model.fit(disp='off', show_warning=False)
            
            logger.debug(f"GARCH模型拟合成功: AIC={self.garch_fit.aic:.2f}, BIC={self.garch_fit.bic:.2f}")
            
            # 3. 拟合ARIMA模型（用于预测价格趋势）
            logger.debug(f"开始拟合ARIMA{self.arima_order}模型")
            self.arima_model = ARIMA(price_series, order=self.arima_order)
            self.arima_fit = self.arima_model.fit()
            
            logger.debug(f"ARIMA模型拟合成功: AIC={self.arima_fit.aic:.2f}, BIC={self.arima_fit.bic:.2f}")
            
            self.fitted = True
            
            return {
                'success': True,
                'garch_aic': self.garch_fit.aic,
                'garch_bic': self.garch_fit.bic,
                'arima_aic': self.arima_fit.aic,
                'arima_bic': self.arima_fit.bic
            }
            
        except Exception as e:
            logger.error(f"模型拟合失败: {e}", exc_info=True)
            self.fitted = False
            return {
                'success': False,
                'error': str(e)
            }
    
    def predict_price_range(
        self,
        current_price: float,
        price_series: pd.Series,
        horizon: int = 1,
        remaining_ratio: float = 1.0
    ) -> Dict[str, Any]:
        """
        预测指数价格区间（完整流程：拟合+预测）
        
        Args:
            current_price: 当前价格
            price_series: 历史价格时间序列
            horizon: 预测期数（向前看多少期）
            remaining_ratio: 剩余时间比例（用于缩放波动率，如0.5表示剩余50%交易时间）
        
        Returns:
            预测结果字典，包含：
                - predicted_price: 预测的价格（ARIMA预测）
                - upper: 价格上界
                - lower: 价格下界
                - volatility: 预测的波动率
        """
        try:
            # 1. 拟合模型
            fit_result = self.fit(price_series)
            if not fit_result['success']:
                return {
                    'success': False,
                    'error': fit_result.get('error', '模型拟合失败')
                }
            
            # 2. ARIMA预测价格趋势
            arima_forecast = self.arima_fit.forecast(steps=horizon)
            # 确保predicted_price是标量
            if hasattr(arima_forecast, 'iloc'):
                predicted_price = float(arima_forecast.iloc[-1])
            elif hasattr(arima_forecast, '__getitem__'):
                predicted_price = float(arima_forecast[-1])
            else:
                # 如果是numpy数组，取最后一个元素
                predicted_price = float(np.asarray(arima_forecast).flat[-1])
            
            # 3. GARCH预测波动率
            garch_forecast = self.garch_fit.forecast(horizon=horizon, reindex=False)
            variance_df = garch_forecast.variance
            
            # 提取方差值，确保是标量
            if horizon == 1:
                if len(variance_df.columns) > 0:
                    forecast_variance = variance_df.iloc[-1, 0]
                else:
                    forecast_variance = variance_df.iloc[-1, 0]
            else:
                forecast_variance = variance_df.iloc[-1, :].values[0]
            
            # 确保是标量
            if isinstance(forecast_variance, (np.ndarray, pd.Series)):
                forecast_variance = float(forecast_variance.flat[0] if hasattr(forecast_variance, 'flat') else forecast_variance.iloc[0] if hasattr(forecast_variance, 'iloc') else forecast_variance[0])
            else:
                forecast_variance = float(forecast_variance)
            
            # 计算预测的波动率（标准差，年化）
            # 注意：GARCH预测的是条件波动率，需要转换为年化
            # 由于我们输入时乘以了1000（千分比），预测的方差需要除以1000^2来还原
            # 对于分钟数据，需要根据数据频率调整
            # 假设是30分钟数据，一年约252个交易日，每天4个30分钟，共约1008个30分钟
            # 但为了简化，我们使用日波动率，然后根据剩余时间比例缩放
            # 还原缩放：除以1000（因为我们输入时乘以了1000）
            forecast_variance_scaled = forecast_variance / (1000 ** 2)
            predicted_vol_annual = np.sqrt(forecast_variance_scaled) * np.sqrt(252)  # 年化标准差
            predicted_vol_daily = predicted_vol_annual / np.sqrt(252)  # 日波动率
            
            # 根据剩余时间比例缩放波动率
            # remaining_ratio表示剩余交易时间的比例（如0.5表示剩余50%）
            scaled_vol = float(predicted_vol_daily * np.sqrt(remaining_ratio))
            
            # 4. 计算价格区间（基于ARIMA预测价格和GARCH预测波动率）
            from scipy import stats
            z_score = stats.norm.ppf((1 + self.confidence_level) / 2)
            
            # 价格区间 = 预测价格 ± z_score * 波动率 * 预测价格
            price_vol = predicted_price * scaled_vol
            upper = float(predicted_price + z_score * price_vol)
            lower = float(predicted_price - z_score * price_vol)
            
            # 确保下界非负且合理
            lower = max(lower, current_price * 0.8)  # 至少不低于当前价格的80%
            upper = max(upper, lower + current_price * 0.01)  # 至少比下界高1%
            
            logger.info(f"指数GARCH区间预测: 当前价格={current_price:.2f}, 预测价格={predicted_price:.2f}, "
                       f"区间=[{lower:.2f}, {upper:.2f}], 波动率={scaled_vol*100:.2f}%")
            
            return {
                'success': True,
                'current_price': current_price,
                'predicted_price': predicted_price,
                'upper': float(upper),
                'lower': float(lower),
                'volatility': float(scaled_vol * 100),  # 转换为百分比
                'confidence_level': self.confidence_level,
                'fit_info': {
                    'garch_aic': fit_result.get('garch_aic'),
                    'garch_bic': fit_result.get('garch_bic'),
                    'arima_aic': fit_result.get('arima_aic'),
                    'arima_bic': fit_result.get('arima_bic')
                }
            }
            
        except Exception as e:
            logger.error(f"指数GARCH区间预测失败: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
