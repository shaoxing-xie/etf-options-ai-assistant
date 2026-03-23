"""
Black-Scholes期权定价模型
用于将IV预测转换为期权价格区间
"""

import numpy as np
from scipy.stats import norm
from typing import Dict, Optional, Any
from datetime import datetime

from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


class BlackScholesPricer:
    """Black-Scholes期权定价器"""
    
    def __init__(self, risk_free_rate: float = 0.03):
        """
        初始化B-S定价器
        
        Args:
            risk_free_rate: 无风险利率（年化，默认3%）
        """
        self.risk_free_rate = risk_free_rate
    
    def calculate_d1_d2(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float
    ) -> tuple:
        """
        计算B-S模型中的d1和d2
        
        Args:
            S: 标的资产当前价格
            K: 行权价
            T: 到期时间（年）
            r: 无风险利率
            sigma: 波动率（年化）
        
        Returns:
            (d1, d2) 元组
        """
        if T <= 0:
            T = 1e-6  # 避免除零
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        return d1, d2
    
    def calculate_call_price(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float
    ) -> float:
        """
        计算Call期权价格
        
        Args:
            S: 标的资产当前价格
            K: 行权价
            T: 到期时间（年）
            r: 无风险利率
            sigma: 波动率（年化）
        
        Returns:
            Call期权理论价格
        """
        if T <= 0:
            return max(S - K, 0)  # 到期时的内在价值
        
        d1, d2 = self.calculate_d1_d2(S, K, T, r, sigma)
        
        call_price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        
        return max(call_price, 0)  # 确保非负
    
    def calculate_put_price(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float
    ) -> float:
        """
        计算Put期权价格
        
        Args:
            S: 标的资产当前价格
            K: 行权价
            T: 到期时间（年）
            r: 无风险利率
            sigma: 波动率（年化）
        
        Returns:
            Put期权理论价格
        """
        if T <= 0:
            return max(K - S, 0)  # 到期时的内在价值
        
        d1, d2 = self.calculate_d1_d2(S, K, T, r, sigma)
        
        put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        
        return max(put_price, 0)  # 确保非负
    
    def calculate_greeks(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = 'call'
    ) -> Dict[str, float]:
        """
        计算期权希腊字母
        
        Args:
            S: 标的资产当前价格
            K: 行权价
            T: 到期时间（年）
            r: 无风险利率
            sigma: 波动率（年化）
            option_type: 期权类型 ('call' 或 'put')
        
        Returns:
            希腊字母字典
        """
        if T <= 0:
            return {
                'delta': 1.0 if (option_type == 'call' and S > K) or (option_type == 'put' and S < K) else 0.0,
                'gamma': 0.0,
                'vega': 0.0,
                'theta': 0.0,
                'rho': 0.0
            }
        
        d1, d2 = self.calculate_d1_d2(S, K, T, r, sigma)
        
        # Delta
        if option_type == 'call':
            delta = norm.cdf(d1)
        else:
            delta = -norm.cdf(-d1)
        
        # Gamma（Call和Put相同）
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        # Vega（Call和Put相同）
        vega = S * norm.pdf(d1) * np.sqrt(T) / 100.0  # 除以100转换为每1%波动率变化
        
        # Theta
        if option_type == 'call':
            theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365.0
        else:
            theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365.0
        
        # Rho
        if option_type == 'call':
            rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100.0
        else:
            rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100.0
        
        return {
            'delta': delta,
            'gamma': gamma,
            'vega': vega,
            'theta': theta,
            'rho': rho
        }
    
    def calculate_price_range(
        self,
        S: float,
        K: float,
        T: float,
        iv_lower: float,
        iv_upper: float,
        iv_current: float,
        option_type: str = 'call',
        r: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        根据IV区间计算期权价格区间
        
        Args:
            S: 标的资产当前价格
            K: 行权价
            T: 到期时间（年）
            iv_lower: IV下界（百分比形式，如15.0表示15%）
            iv_upper: IV上界（百分比形式）
            iv_current: 当前IV（百分比形式）
            option_type: 期权类型 ('call' 或 'put')
            r: 无风险利率（可选，默认使用初始化时的值）
        
        Returns:
            价格区间字典
        """
        if r is None:
            r = self.risk_free_rate
        
        # 转换IV为小数形式（B-S模型需要）
        iv_lower_decimal = iv_lower / 100.0
        iv_upper_decimal = iv_upper / 100.0
        iv_current_decimal = iv_current / 100.0
        
        # 计算不同IV下的期权价格
        if option_type == 'call':
            price_lower = self.calculate_call_price(S, K, T, r, iv_lower_decimal)
            price_upper = self.calculate_call_price(S, K, T, r, iv_upper_decimal)
            price_current = self.calculate_call_price(S, K, T, r, iv_current_decimal)
        else:
            price_lower = self.calculate_put_price(S, K, T, r, iv_lower_decimal)
            price_upper = self.calculate_put_price(S, K, T, r, iv_upper_decimal)
            price_current = self.calculate_put_price(S, K, T, r, iv_current_decimal)
        
        # 调试：检查计算结果
        logger.debug(f"B-S定价计算: S={S:.4f}, K={K:.4f}, T={T:.6f}, "
                    f"IV=[{iv_lower_decimal:.4f}, {iv_upper_decimal:.4f}], "
                    f"价格=[{price_lower:.6f}, {price_upper:.6f}]")
        
        # 确保价格区间合理（下界 <= 上界）
        if price_lower > price_upper:
            price_lower, price_upper = price_upper, price_lower
        
        # 合理性检查：如果价格都为0或异常小，可能是T太小或IV太小
        if price_lower == 0 and price_upper == 0 and T < 0.01:
            logger.warning(f"B-S定价结果异常（价格全为0），可能是T太小（{T:.6f}年）或IV太小，"
                          f"建议检查到期时间计算")
        
        # 最小价格保护：如果下界过小（<当前价格的10%），使用当前价格的10%作为最小下界
        # 这可以防止虚值期权在低IV下界时出现不合理的极小价格
        # 使用10%而不是5%，因为虚值期权的时间价值可能很小，但不应低于当前价格的10%
        min_price_threshold = price_current * 0.10  # 当前价格的10%
        if price_lower < min_price_threshold and price_current > 0:
            logger.debug(f"B-S定价下界过小 ({price_lower:.6f} < {min_price_threshold:.6f})，"
                        f"使用最小价格保护: {min_price_threshold:.6f}")
            price_lower = min_price_threshold
        
        # 计算当前价格的Greeks
        greeks = self.calculate_greeks(S, K, T, r, iv_current_decimal, option_type)
        
        logger.debug(f"B-S定价: {option_type.upper()}期权, S={S:.4f}, K={K:.4f}, T={T:.4f}, "
                    f"IV=[{iv_lower:.2f}%, {iv_upper:.2f}%], "
                    f"价格区间=[{price_lower:.4f}, {price_upper:.4f}]")
        
        return {
            'current_price': price_current,
            'lower_price': price_lower,
            'upper_price': price_upper,
            'greeks': greeks,
            'iv_range': {
                'lower': iv_lower,
                'upper': iv_upper,
                'current': iv_current
            }
        }
    
    def time_to_expiry(
        self,
        expiry_date: datetime,
        current_date: Optional[datetime] = None
    ) -> float:
        """
        计算到期时间（年）
        
        Args:
            expiry_date: 到期日期
            current_date: 当前日期（可选，默认使用当前时间）
        
        Returns:
            到期时间（年）
        """
        if current_date is None:
            current_date = datetime.now()
        
        if expiry_date <= current_date:
            return 0.0
        
        # 计算交易日数量（简化：假设一年252个交易日）
        days_to_expiry = (expiry_date - current_date).days
        trading_days = days_to_expiry * 252 / 365.0  # 转换为交易日
        
        # 转换为年
        T = trading_days / 252.0
        
        return max(T, 1e-6)  # 避免除零
