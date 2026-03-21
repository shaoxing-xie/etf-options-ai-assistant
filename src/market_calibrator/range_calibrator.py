"""
区间校准器
根据市场盘口数据校准理论波动区间，确保区间可交易
"""

from typing import Dict, Any, List, Optional
from src.logger_config import get_module_logger, log_error_with_context

logger = get_module_logger(__name__)


class RangeCalibrator:
    """区间校准器"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化区间校准器
        
        Args:
            config: 系统配置，包含：
                - bid_adjustment: 买一价调整系数（默认0.98）
                - ask_adjustment: 卖一价调整系数（默认1.02）
                - max_deviation_pct: 理论区间与市场区间最大偏离百分比（默认20%）
        """
        if config is None:
            config = {}
        
        # 从配置中获取参数，或使用默认值
        volatility_config = config.get('volatility_engine', {})
        market_calibration = volatility_config.get('market_calibration', {})
        
        self.bid_adjustment = market_calibration.get('bid_adjustment', 0.98)
        self.ask_adjustment = market_calibration.get('ask_adjustment', 1.02)
        self.max_deviation_pct = market_calibration.get('max_deviation_pct', 20.0)
    
    def calibrate_range(
        self,
        theoretical_range: List[float],
        quotes: Dict[str, Any],
        liquidity_report: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        校准理论波动区间
        
        Args:
            theoretical_range: 理论波动区间 [lower, upper]
            quotes: 盘口数据，包含 bid_price, ask_price 等
            liquidity_report: 流动性评估报告
        
        Returns:
            dict: 校准结果，包含：
                - calibrated_range: 校准后的区间 [lower, upper]
                - status: 校准状态（success/fallback/adjusted）
                - confidence: 置信度（0-1）
                - deviation_pct: 理论区间与市场区间的偏离百分比
                - adjustment_info: 调整信息
        """
        try:
            theoretical_lower = theoretical_range[0]
            theoretical_upper = theoretical_range[1]
            
            if theoretical_lower >= theoretical_upper:
                logger.warning(f"理论区间异常: lower({theoretical_lower}) >= upper({theoretical_upper})")
                # 使用盘口中间价作为回退
                mid_price = quotes.get('mid_price', (quotes.get('bid_price', 0) + quotes.get('ask_price', 0)) / 2)
                if mid_price <= 0:
                    mid_price = quotes.get('last_price', 0.01)
                calibrated_lower = mid_price * 0.95
                calibrated_upper = mid_price * 1.05
                return {
                    'calibrated_range': [calibrated_lower, calibrated_upper],
                    'status': 'fallback',
                    'confidence': 0.5,
                    'deviation_pct': 0,
                    'adjustment_info': '理论区间异常，使用盘口中间价回退'
                }
            
            bid_price = quotes.get('bid_price', 0)
            ask_price = quotes.get('ask_price', 0)
            mid_price = quotes.get('mid_price', (bid_price + ask_price) / 2.0)
            is_estimated = quotes.get('is_estimated', False)
            
            if bid_price <= 0 or ask_price <= 0:
                logger.warning("盘口价格无效，无法校准")
                return {
                    'calibrated_range': theoretical_range,
                    'status': 'fallback',
                    'confidence': 0.5,
                    'deviation_pct': 0,
                    'adjustment_info': '盘口价格无效，使用理论区间'
                }
            
            # 如果是估算数据，降低置信度
            if is_estimated:
                logger.debug("使用估算盘口数据，将降低校准置信度")
            
            # 计算市场边界（考虑调整系数）
            market_lower = bid_price * self.bid_adjustment
            market_upper = ask_price * self.ask_adjustment
            
            # 如果流动性不足，使用更保守的区间
            if not liquidity_report.get('is_tradable', False):
                logger.debug("流动性不足，使用保守区间")
                market_lower = mid_price * 0.95
                market_upper = mid_price * 1.05
            
            # 校准区间：理论区间和市场边界的交集
            calibrated_lower = max(theoretical_lower, market_lower)
            calibrated_upper = min(theoretical_upper, market_upper)
            
            # 如果校准后区间无效（下轨>=上轨），使用保守回退
            if calibrated_lower >= calibrated_upper:
                logger.warning("校准后区间无效，使用保守回退")
                calibrated_lower = mid_price * 0.95
                calibrated_upper = mid_price * 1.05
                status = 'fallback'
                adjustment_info = '校准后区间无效，使用盘口中间价回退'
            else:
                status = 'success'
                adjustment_info = '成功校准'
            
            # 计算理论区间与市场区间的偏离度
            theoretical_mid = (theoretical_lower + theoretical_upper) / 2.0
            market_mid = (market_lower + market_upper) / 2.0
            if market_mid > 0:
                deviation_pct = abs((theoretical_mid - market_mid) / market_mid * 100)
            else:
                deviation_pct = 0
            
            # 计算置信度：偏离度越小，置信度越高
            if deviation_pct <= self.max_deviation_pct:
                confidence = 1.0 - (deviation_pct / self.max_deviation_pct * 0.3)  # 最大降低30%
            else:
                confidence = 0.7  # 偏离过大时，置信度降低
            
            # 如果是估算数据，进一步降低置信度（最多降低20%）
            if is_estimated:
                confidence = confidence * 0.8
                adjustment_info += '（使用估算盘口数据）'
            
            confidence = max(0.5, min(1.0, confidence))
            
            result = {
                'calibrated_range': [round(calibrated_lower, 4), round(calibrated_upper, 4)],
                'status': status,
                'confidence': round(confidence, 2),
                'deviation_pct': round(deviation_pct, 2),
                'adjustment_info': adjustment_info,
                'theoretical_range': [round(theoretical_lower, 4), round(theoretical_upper, 4)],
                'market_range': [round(market_lower, 4), round(market_upper, 4)]
            }
            
            logger.debug(f"区间校准: 理论区间=[{theoretical_lower:.4f}, {theoretical_upper:.4f}], "
                        f"校准后=[{calibrated_lower:.4f}, {calibrated_upper:.4f}], "
                        f"状态={status}, 置信度={confidence:.2f}, 偏离={deviation_pct:.2f}%")
            
            return result
            
        except Exception as e:
            log_error_with_context(
                logger, e,
                {
                    'function': 'calibrate_range',
                    'theoretical_range': theoretical_range,
                    'quotes': quotes
                },
                "校准波动区间失败"
            )
            # 回退到理论区间
            return {
                'calibrated_range': theoretical_range,
                'status': 'fallback',
                'confidence': 0.5,
                'deviation_pct': 0,
                'adjustment_info': f'校准失败: {str(e)}'
            }
