"""
GARCH模型实现
用于预测隐含波动率(IV)的动态变化
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
import warnings

try:
    from arch import arch_model
    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False
    warnings.warn("arch库未安装，GARCH功能将不可用。请运行: pip install arch")

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


class GARCHIVPredictor:
    """GARCH-IV预测器"""
    
    def __init__(
        self,
        p: int = 1,
        q: int = 1,
        distribution: str = "normal",
        lookback_days: int = 30
    ):
        """
        初始化GARCH模型
        
        Args:
            p: GARCH模型的ARCH项阶数
            q: GARCH模型的GARCH项阶数
            distribution: 残差分布类型 ("normal", "t", "skewt")
            lookback_days: 历史数据回看天数
        """
        if not ARCH_AVAILABLE:
            raise ImportError("arch库未安装，无法使用GARCH功能")
        
        self.p = p
        self.q = q
        self.distribution = distribution
        self.lookback_days = lookback_days
        # arch 的返回类型类型标注较宽，这里用 Any 收敛 mypy
        self.model: Any = None
        self.fit_result: Any = None  # 保存拟合结果，用于预测
        self.fitted = False
        
    def prepare_data(self, iv_series: pd.Series) -> pd.Series:
        """
        准备IV数据用于GARCH建模
        
        Args:
            iv_series: IV时间序列（百分比形式，如15.5表示15.5%）
        
        Returns:
            处理后的收益率序列
        """
        if len(iv_series) < 20:
            raise ValueError(f"IV数据不足，至少需要20个数据点，当前只有{len(iv_series)}个")
        
        # 转换为收益率（对数收益率）
        # 如果IV已经是百分比形式（如15.5），先除以100
        iv_values = iv_series.values
        if iv_values.max() > 1:
            iv_values = iv_values / 100.0
        
        # 计算对数收益率
        returns = np.diff(np.log(iv_values + 1e-6))  # 加小值避免log(0)
        
        # 转换为Series
        returns_series = pd.Series(returns, index=iv_series.index[1:])
        
        return returns_series
    
    def fit(self, iv_series: pd.Series) -> Dict[str, Any]:
        """
        拟合GARCH模型
        
        Args:
            iv_series: IV时间序列
        
        Returns:
            拟合结果字典
        """
        if not ARCH_AVAILABLE:
            raise ImportError("arch库未安装，无法使用GARCH功能")
        
        try:
            # 准备数据
            returns = self.prepare_data(iv_series)
            
            if len(returns) < max(self.p, self.q) + 10:
                raise ValueError(f"数据不足，无法拟合GARCH({self.p},{self.q})模型")
            
            # 创建GARCH模型
            self.model = arch_model(
                returns * 100,  # 转换为百分比形式
                vol='GARCH',
                p=self.p,
                q=self.q,
                dist=self.distribution,  # type: ignore[arg-type]
            )
            
            # 拟合模型
            logger.debug(f"开始拟合GARCH({self.p},{self.q})模型，数据点: {len(returns)}")
            self.fit_result = self.model.fit(disp='off', show_warning=False)
            
            self.fitted = True
            
            logger.info(f"GARCH模型拟合成功: AIC={self.fit_result.aic:.2f}, BIC={self.fit_result.bic:.2f}")
            
            return {
                'success': True,
                'aic': self.fit_result.aic,
                'bic': self.fit_result.bic,
                'params': self.fit_result.params.to_dict(),
                'residuals': self.fit_result.resid,
                'conditional_volatility': self.fit_result.conditional_volatility
            }
            
        except Exception as e:
            logger.error(f"GARCH模型拟合失败: {e}", exc_info=True)
            self.fitted = False
            return {
                'success': False,
                'error': str(e)
            }
    
    def forecast(
        self,
        horizon: int = 1,
        confidence_level: float = 0.95
    ) -> Dict[str, Any]:
        """
        预测未来IV波动率
        
        Args:
            horizon: 预测期数（向前看多少期）
            confidence_level: 置信水平（如0.95表示95%置信区间）
        
        Returns:
            预测结果字典
        """
        if not self.fitted or self.fit_result is None:
            raise ValueError("模型尚未拟合，请先调用fit()方法")
        
        try:
            # 使用拟合结果进行预测（arch库的正确用法）
            forecast_result = self.fit_result.forecast(horizon=horizon, reindex=False)
            
            # 获取预测的方差（arch库返回的variance是DataFrame）
            # forecast_result.variance 是预测的方差DataFrame，列名为'h.1', 'h.2', ...等
            variance_df = forecast_result.variance
            
            # 获取最后一期的方差（horizon=1时取第一列，horizon>1时取对应列）
            if horizon == 1:
                # 取第一列（h.1）的最后一个值
                forecast_variance = variance_df.iloc[-1, 0] if len(variance_df.columns) > 0 else variance_df.iloc[-1, 0]
            else:
                # 取所有预测期的方差
                forecast_variance = variance_df.iloc[-1, :].values
            
            # 转换为numpy数组（如果是标量，转换为数组）
            if np.isscalar(forecast_variance):
                forecast_variance = np.array([forecast_variance])
            
            # 计算置信区间
            from scipy import stats
            z_score = stats.norm.ppf((1 + confidence_level) / 2)
            
            # 预测的波动率（标准差，年化）
            # forecast_variance是方差，需要开方得到标准差
            # 注意：这里预测的是条件波动率，需要转换为年化
            predicted_std = np.sqrt(forecast_variance) * np.sqrt(252)  # 年化标准差
            
            # 置信区间（基于标准差）
            std_error = np.sqrt(forecast_variance) * np.sqrt(252)  # 标准误差
            lower_bound = predicted_std - z_score * std_error
            upper_bound = predicted_std + z_score * std_error
            
            # 确保非负
            lower_bound = np.maximum(lower_bound, 0)
            
            # 提取标量值（如果horizon=1）
            if horizon == 1:
                predicted_std = float(predicted_std[0]) if len(predicted_std) > 0 else float(predicted_std)
                lower_bound = float(lower_bound[0]) if len(lower_bound) > 0 else float(lower_bound)
                upper_bound = float(upper_bound[0]) if len(upper_bound) > 0 else float(upper_bound)
            
            logger.debug(f"GARCH预测: 波动率={predicted_std:.4f}, 置信区间=[{lower_bound:.4f}, {upper_bound:.4f}]")
            
            return {
                'success': True,
                'predicted_volatility': predicted_std,
                'lower_bound': lower_bound,
                'upper_bound': upper_bound,
                'confidence_level': confidence_level
            }
            
        except Exception as e:
            logger.error(f"GARCH预测失败: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
    
    def predict_iv_range(
        self,
        current_iv: float,
        iv_series: pd.Series,
        horizon: int = 1,
        confidence_level: float = 0.95,
        skip_fit_if_fitted: bool = True
    ) -> Dict[str, Any]:
        """
        预测IV区间（完整流程：拟合+预测）
        
        Args:
            current_iv: 当前IV值（百分比形式，如15.5表示15.5%）
            iv_series: 历史IV时间序列
            horizon: 预测期数
            confidence_level: 置信水平
            skip_fit_if_fitted: 如果模型已拟合，跳过拟合步骤（用于缓存优化）
        
        Returns:
            预测结果字典，包含：
                - predicted_iv: 预测的IV值
                - lower_iv: IV下界
                - upper_iv: IV上界
        """
        try:
            # 如果模型已拟合且skip_fit_if_fitted=True，跳过拟合步骤
            if skip_fit_if_fitted and self.fitted and self.fit_result is not None:
                logger.debug("模型已拟合，跳过拟合步骤，直接进行预测")
                fit_result = {
                    'success': True,
                    'aic': self.fit_result.aic,
                    'bic': self.fit_result.bic
                }
            else:
                # 拟合模型
                fit_result = self.fit(iv_series)
                if not fit_result['success']:
                    return {
                        'success': False,
                        'error': fit_result.get('error', '模型拟合失败')
                    }
            
            # 进行预测
            forecast_result = self.forecast(horizon=horizon, confidence_level=confidence_level)
            if not forecast_result['success']:
                return {
                    'success': False,
                    'error': forecast_result.get('error', '预测失败')
                }
            
            # 将预测的波动率转换为IV区间
            # GARCH模型预测的是IV对数收益率的条件波动率（年化）
            # 我们需要基于这个波动率来估计IV的变化范围
            
            # 确保current_iv是百分比形式
            if current_iv > 1:
                current_iv_pct = current_iv / 100.0
            else:
                current_iv_pct = current_iv
            
            # 预测的波动率是年化的标准差（已经乘以sqrt(252)）
            # 我们需要将其转换为日波动率，然后用于计算IV的变化范围
            predicted_vol_annual = forecast_result['predicted_volatility']  # 年化波动率
            predicted_vol_daily = predicted_vol_annual / np.sqrt(252)  # 日波动率
            
            # 使用预测的波动率来估计IV的变化范围
            # 假设IV的对数收益率服从正态分布，均值为0，标准差为predicted_vol_daily
            # 对于1期预测，IV的预期变化为0（均值），但波动率是predicted_vol_daily
            from scipy import stats
            z_score = stats.norm.ppf((1 + confidence_level) / 2)
            
            # IV的对数收益率的变化范围（基于预测的波动率）
            # 使用对数正态分布：IV_t+1 = IV_t * exp(return)
            # return ~ N(0, predicted_vol_daily^2)
            # 所以 IV_t+1 的置信区间为 [IV_t * exp(-z*vol), IV_t * exp(z*vol)]
            vol_multiplier_lower = np.exp(-z_score * predicted_vol_daily)
            vol_multiplier_upper = np.exp(z_score * predicted_vol_daily)
            
            # 计算IV区间
            lower_iv = current_iv_pct * vol_multiplier_lower
            upper_iv = current_iv_pct * vol_multiplier_upper
            predicted_iv = current_iv_pct  # 预测IV等于当前IV（均值）
            
            # 合理性检查：IV区间应该在合理范围内
            # 限制IV变化在±50%以内（避免极端预测）
            max_change = 0.5
            lower_iv = max(lower_iv, current_iv_pct * (1 - max_change))
            upper_iv = min(upper_iv, current_iv_pct * (1 + max_change))
            
            # 确保非负且下界小于上界
            lower_iv = max(lower_iv, 0.01)  # 最小1%
            upper_iv = max(upper_iv, lower_iv + 0.01)
            
            # 转换回百分比形式
            predicted_iv_pct = predicted_iv * 100
            lower_iv_pct = lower_iv * 100
            upper_iv_pct = upper_iv * 100
            
            logger.info(f"GARCH-IV预测: 当前IV={current_iv:.2f}%, 预测IV={predicted_iv_pct:.2f}%, 区间=[{lower_iv_pct:.2f}%, {upper_iv_pct:.2f}%]")
            
            return {
                'success': True,
                'current_iv': current_iv,
                'predicted_iv': predicted_iv_pct,
                'lower_iv': lower_iv_pct,
                'upper_iv': upper_iv_pct,
                'confidence_level': confidence_level,
                'fit_info': {
                    'aic': fit_result.get('aic'),
                    'bic': fit_result.get('bic')
                }
            }
            
        except Exception as e:
            logger.error(f"GARCH-IV预测失败: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
