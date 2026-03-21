"""
IV百分位动态调整器
根据历史IV数据计算当前IV百分位，动态调整波动区间宽度
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import akshare as ak

from src.logger_config import get_module_logger, log_error_with_context
from src.data_collector import fetch_option_greeks_sina
from src.data_cache import get_cached_option_greeks
from src.config_loader import load_system_config

logger = get_module_logger(__name__)


class IVPercentileAdjuster:
    """IV百分位调整器"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化IV百分位调整器
        
        Args:
            config: 系统配置，包含：
                - lookback_days: 历史IV数据天数（默认30天）
                - high_percentile: 高百分位阈值（默认70）
                - low_percentile: 低百分位阈值（默认30）
                - high_compress: 高百分位压缩系数（默认0.85）
                - low_expand: 低百分位扩展系数（默认1.15）
        """
        if config is None:
            config = load_system_config()
        
        # 保存配置（用于访问缓存路径等）
        self.config = config
        
        volatility_config = config.get('volatility_engine', {})
        iv_config = volatility_config.get('iv_percentile_adjustment', {})
        
        self.enabled = iv_config.get('enabled', True)
        self.lookback_days = iv_config.get('lookback_days', 30)
        self.high_percentile = iv_config.get('high_percentile', 70)
        self.low_percentile = iv_config.get('low_percentile', 30)
        self.high_compress = iv_config.get('high_compress', 0.85)
        self.low_expand = iv_config.get('low_expand', 1.15)
        
        # IV数据缓存（避免重复获取）
        self._iv_cache: Dict[str, pd.Series] = {}
        self._cache_timestamp: Dict[str, datetime] = {}
        self._cache_ttl = 300  # 缓存5分钟
    
    def fetch_historical_iv(self, contract_code: str) -> Optional[pd.Series]:
        """
        获取历史IV数据（从缓存的Greeks数据中提取）
        
        Args:
            contract_code: 期权合约代码
        
        Returns:
            pd.Series: 历史IV数据（时间序列），如果失败返回None
        """
        try:
            # 检查内存缓存
            cache_key = contract_code
            if cache_key in self._iv_cache:
                cache_time = self._cache_timestamp.get(cache_key)
                if cache_time and (datetime.now() - cache_time).seconds < self._cache_ttl:
                    logger.debug(f"使用缓存的IV数据: {contract_code}")
                    return self._iv_cache[cache_key]
            
            logger.debug(f"获取历史IV数据: {contract_code}, lookback_days={self.lookback_days}")
            
            # 计算历史日期范围（排除周末）
            today = datetime.now()
            historical_ivs = {}
            
            # 从今天往前推，获取历史交易日
            current_date = today
            days_collected = 0
            max_attempts = self.lookback_days * 2  # 最多尝试2倍天数（考虑周末）
            attempts = 0
            
            while days_collected < self.lookback_days and attempts < max_attempts:
                attempts += 1
                # 跳过周末
                if current_date.weekday() >= 5:  # 周六=5, 周日=6
                    current_date = current_date - timedelta(days=1)
                    continue
                
                date_str = current_date.strftime('%Y%m%d')
                
                # 从缓存中获取该日期的Greeks数据
                greeks_data = get_cached_option_greeks(contract_code, date_str, config=self.config)
                
                if greeks_data is not None and not greeks_data.empty:
                    # 从Greeks数据中提取IV值
                    iv_value = None
                    for idx, row in greeks_data.iterrows():
                        field = str(row.get('字段', ''))
                        if '波动率' in field or 'IV' in field or '隐含波动率' in field or 'implied' in field.lower():
                            try:
                                iv_value = float(row.get('值', 0))
                                # 如果IV值过小（可能是小数形式），转换为百分比
                                if iv_value < 5.0:
                                    iv_value = iv_value * 100
                                # 合理性检查：IV应该在5%-50%之间
                                if 5.0 <= iv_value <= 50.0:
                                    break
                                else:
                                    iv_value = None
                            except (ValueError, TypeError):
                                continue
                    
                    if iv_value is not None:
                        # 使用日期作为索引（转换为datetime对象）
                        date_dt = datetime.strptime(date_str, '%Y%m%d')
                        historical_ivs[date_dt] = iv_value
                        days_collected += 1
                
                # 往前推一天
                current_date = current_date - timedelta(days=1)
            
            # 如果收集到的数据不足，尝试获取当前IV作为补充
            if days_collected < 5:  # 如果数据点少于5个，尝试获取当前IV
                logger.debug(f"历史IV数据不足（{days_collected}个），尝试获取当前IV")
                try:
                    greeks_data = fetch_option_greeks_sina(contract_code)
                    if greeks_data is not None and not greeks_data.empty:
                        current_iv = None
                        for idx, row in greeks_data.iterrows():
                            field = str(row.get('字段', ''))
                            if '波动率' in field or 'IV' in field or '隐含波动率' in field:
                                try:
                                    current_iv = float(row.get('值', 0))
                                    if current_iv < 5.0:
                                        current_iv = current_iv * 100
                                    if 5.0 <= current_iv <= 50.0:
                                        historical_ivs[datetime.now()] = current_iv
                                        days_collected += 1
                                        break
                                except (ValueError, TypeError):
                                    continue
                except Exception as e:
                    logger.debug(f"获取当前IV失败: {e}")
            
            # 如果仍然没有足够的数据，返回None
            if len(historical_ivs) == 0:
                logger.warning(f"无法获取历史IV数据: {contract_code}，缓存中可能没有Greeks数据")
                return None
            
            # 构建时间序列
            if len(historical_ivs) < 5:
                logger.warning(f"历史IV数据点不足（{len(historical_ivs)}个），建议至少5个数据点")
            
            # 转换为Series，按日期排序
            iv_series = pd.Series(historical_ivs)
            iv_series = iv_series.sort_index()
            
            # 缓存数据
            self._iv_cache[cache_key] = iv_series
            self._cache_timestamp[cache_key] = datetime.now()
            
            logger.info(f"从缓存获取到{len(iv_series)}天的真实IV数据: {contract_code}, "
                       f"日期范围: {iv_series.index.min().strftime('%Y-%m-%d')} ~ {iv_series.index.max().strftime('%Y-%m-%d')}, "
                       f"IV范围: {iv_series.min():.2f}% ~ {iv_series.max():.2f}%")
            
            return iv_series
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {'function': 'fetch_historical_iv', 'contract_code': contract_code},
                "获取历史IV数据失败"
            )
            return None
    
    def calculate_iv_percentile(self, current_iv: float, historical_ivs: pd.Series) -> float:
        """
        计算当前IV在历史分布中的百分位
        
        Args:
            current_iv: 当前IV值（百分比形式）
            historical_ivs: 历史IV数据序列
        
        Returns:
            float: IV百分位（0-100）
        """
        try:
            if historical_ivs is None or len(historical_ivs) == 0:
                logger.warning("历史IV数据为空，无法计算百分位")
                return 50.0  # 默认中位数
            
            # 确保当前IV在合理范围内
            if current_iv < 5.0:
                current_iv = current_iv * 100
            
            # 计算百分位
            percentile = (historical_ivs <= current_iv).sum() / len(historical_ivs) * 100
            
            logger.debug(f"IV百分位计算: 当前IV={current_iv:.2f}%, 百分位={percentile:.1f}%")
            
            return percentile
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {
                    'function': 'calculate_iv_percentile',
                    'current_iv': current_iv,
                    'historical_ivs_len': len(historical_ivs) if historical_ivs is not None else 0
                },
                "计算IV百分位失败"
            )
            return 50.0  # 默认中位数
    
    def calculate_adjustment_factor(
        self,
        current_iv: float,
        contract_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        计算IV调整系数
        
        Args:
            current_iv: 当前IV值（百分比形式）
            contract_code: 期权合约代码（可选，用于获取历史数据）
        
        Returns:
            dict: 调整结果，包含：
                - adjustment_factor: 调整系数（用于乘以区间宽度）
                - percentile: IV百分位
                - reason: 调整原因
        """
        try:
            if not self.enabled:
                return {
                    'adjustment_factor': 1.0,
                    'percentile': 50.0,
                    'reason': 'IV调整未启用'
                }
            
            # 如果提供了合约代码，获取历史IV数据
            historical_ivs = None
            if contract_code:
                historical_ivs = self.fetch_historical_iv(contract_code)
            
            # 如果无法获取历史数据，使用默认调整
            if historical_ivs is None or len(historical_ivs) == 0:
                logger.debug("无法获取历史IV数据，使用默认调整系数")
                return {
                    'adjustment_factor': 1.0,
                    'percentile': 50.0,
                    'reason': '无法获取历史IV数据'
                }
            
            # 计算IV百分位
            percentile = self.calculate_iv_percentile(current_iv, historical_ivs)
            
            # 根据百分位确定调整系数（非线性调整：极端百分位调整幅度更大）
            if percentile >= self.high_percentile:
                # IV高位，压缩区间（IV高位回落风险）
                # 非线性调整：百分位越高，压缩越多
                # 例如：70%百分位压缩到0.9，90%百分位压缩到0.85，95%百分位压缩到0.8
                compression_ratio = (percentile - self.high_percentile) / (100 - self.high_percentile)  # 0到1之间
                # 基础压缩系数 + 额外压缩（极端高位）
                adjustment_factor = self.high_compress * (1.0 - compression_ratio * 0.15)  # 最多额外压缩15%
                adjustment_factor = max(0.75, adjustment_factor)  # 最小压缩到0.75
                reason = f'IV高位（{percentile:.1f}%百分位），压缩区间（非线性）'
            elif percentile <= self.low_percentile:
                # IV低位，扩大区间（IV低位上涨潜力）
                # 非线性调整：百分位越低，扩大越多
                # 例如：30%百分位扩大到1.1，10%百分位扩大到1.15，5%百分位扩大到1.2
                expansion_ratio = (self.low_percentile - percentile) / self.low_percentile  # 0到1之间
                # 基础扩大系数 + 额外扩大（极端低位）
                adjustment_factor = self.low_expand * (1.0 + expansion_ratio * 0.15)  # 最多额外扩大15%
                adjustment_factor = min(1.25, adjustment_factor)  # 最大扩大到1.25
                reason = f'IV低位（{percentile:.1f}%百分位），扩大区间（非线性）'
            else:
                # IV中位，保持原区间（但根据距离中位的距离，轻微调整）
                # 距离50%越远，调整幅度越大（但幅度较小）
                distance_from_center = abs(percentile - 50.0) / 50.0  # 0到1之间
                # 轻微调整：最多±5%
                adjustment_factor = 1.0 + (distance_from_center - 0.5) * 0.1  # 在0.95到1.05之间
                adjustment_factor = max(0.95, min(1.05, adjustment_factor))
                reason = f'IV中位（{percentile:.1f}%百分位），轻微调整'
            
            result = {
                'adjustment_factor': adjustment_factor,
                'percentile': round(percentile, 1),
                'reason': reason
            }
            
            logger.debug(f"IV调整系数: {adjustment_factor:.2f}, 原因: {reason}")
            
            return result
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {
                    'function': 'calculate_adjustment_factor',
                    'current_iv': current_iv,
                    'contract_code': contract_code
                },
                "计算IV调整系数失败"
            )
            return {
                'adjustment_factor': 1.0,
                'percentile': 50.0,
                'reason': f'计算失败: {str(e)}'
            }
    
    def adjust_range(
        self,
        theoretical_range: List[float],
        current_iv: float,
        contract_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        调整波动区间（基于IV百分位）
        
        Args:
            theoretical_range: 理论波动区间 [lower, upper]
            current_iv: 当前IV值（百分比形式）
            contract_code: 期权合约代码（可选）
        
        Returns:
            dict: 调整后的区间和相关信息
        """
        try:
            theoretical_lower = theoretical_range[0]
            theoretical_upper = theoretical_range[1]
            
            if theoretical_lower >= theoretical_upper:
                logger.warning("理论区间无效，无法调整")
                return {
                    'adjusted_range': theoretical_range,
                    'adjustment_factor': 1.0,
                    'percentile': 50.0,
                    'reason': '理论区间无效'
                }
            
            # 计算调整系数
            adjustment_info = self.calculate_adjustment_factor(current_iv, contract_code)
            adjustment_factor = adjustment_info['adjustment_factor']
            
            # 如果调整系数为1.0，直接返回原区间
            if adjustment_factor == 1.0:
                return {
                    'adjusted_range': theoretical_range,
                    **adjustment_info
                }
            
            # 计算区间中心点和宽度
            range_center = (theoretical_lower + theoretical_upper) / 2.0
            range_width = theoretical_upper - theoretical_lower
            
            # 调整区间宽度
            adjusted_width = range_width * adjustment_factor
            
            # 计算调整后的区间
            adjusted_lower = range_center - adjusted_width / 2.0
            adjusted_upper = range_center + adjusted_width / 2.0
            
            # 确保下轨不为负
            adjusted_lower = max(0.001, adjusted_lower)
            
            result = {
                'adjusted_range': [round(adjusted_lower, 4), round(adjusted_upper, 4)],
                **adjustment_info
            }
            
            logger.debug(f"IV调整区间: 理论=[{theoretical_lower:.4f}, {theoretical_upper:.4f}], "
                        f"调整后=[{adjusted_lower:.4f}, {adjusted_upper:.4f}], "
                        f"系数={adjustment_factor:.2f}")
            
            return result
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {
                    'function': 'adjust_range',
                    'theoretical_range': theoretical_range,
                    'current_iv': current_iv
                },
                "调整波动区间失败"
            )
            return {
                'adjusted_range': theoretical_range,
                'adjustment_factor': 1.0,
                'percentile': 50.0,
                'reason': f'调整失败: {str(e)}'
            }
