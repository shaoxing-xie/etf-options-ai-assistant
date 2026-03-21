"""
市场微观结构校准器（集成接口）
整合盘口数据获取、流动性评估和区间校准功能
"""

from typing import Dict, Any, Optional, List
from src.logger_config import get_module_logger

from .market_data_fetcher import OptionMarketDataFetcher
from .liquidity_assessor import LiquidityAssessor
from .range_calibrator import RangeCalibrator

logger = get_module_logger(__name__)


class MarketMicrostructureCalibrator:
    """市场微观结构校准器（主接口）"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化市场校准器
        
        Args:
            config: 系统配置
        """
        self.config = config or {}
        self.fetcher = OptionMarketDataFetcher()
        self.assessor = LiquidityAssessor()
        self.calibrator = RangeCalibrator(config)
        
        # 检查是否启用市场校准
        volatility_config = self.config.get('volatility_engine', {})
        self.enabled = volatility_config.get('market_calibration', {}).get('enabled', True)
    
    def calibrate_option_range(
        self,
        contract_code: str,
        theoretical_range: List[float],
        option_current_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        校准期权波动区间
        
        Args:
            contract_code: 期权合约代码
            theoretical_range: 理论波动区间 [lower, upper]
            option_current_price: 期权当前价格（可选，用于验证）
        
        Returns:
            dict: 校准结果，包含：
                - calibrated_range: 校准后的区间 [lower, upper]
                - liquidity_report: 流动性评估报告
                - metrics: 市场指标
                - calibration_info: 校准信息
                - status: 状态（success/fallback/disabled）
        """
        try:
            # 如果未启用市场校准，直接返回理论区间
            if not self.enabled:
                logger.debug("市场校准未启用，使用理论区间")
                return {
                    'calibrated_range': theoretical_range,
                    'liquidity_report': None,
                    'metrics': None,
                    'calibration_info': {'status': 'disabled'},
                    'status': 'disabled'
                }
            
            logger.info(f"开始校准期权波动区间: {contract_code}")
            
            # 1. 获取实时盘口数据
            quotes = self.fetcher.fetch_realtime_quotes(contract_code)
            if quotes is None:
                logger.warning(f"无法获取盘口数据: {contract_code}，使用理论区间")
                return {
                    'calibrated_range': theoretical_range,
                    'liquidity_report': None,
                    'metrics': None,
                    'calibration_info': {'status': 'fallback', 'reason': '无法获取盘口数据'},
                    'status': 'fallback'
                }
            
            # 2. 计算市场指标
            metrics = self.fetcher.calculate_market_metrics(quotes)
            
            # 3. 评估流动性（需要合并quotes和metrics用于评估）
            liquidity_input = {**quotes, **metrics}
            liquidity_report = self.assessor.assess_liquidity(metrics)
            
            # 4. 校准区间
            calibration_result = self.calibrator.calibrate_range(
                theoretical_range,
                liquidity_input,  # 合并quotes和metrics
                liquidity_report
            )
            
            # 5. 验证校准后的区间（如果提供了当前价格）
            if option_current_price is not None:
                calibrated_lower = calibration_result['calibrated_range'][0]
                calibrated_upper = calibration_result['calibrated_range'][1]
                
                # 确保当前价格在区间内（允许小幅超出）
                if option_current_price < calibrated_lower * 0.9:
                    logger.warning(f"当前价格({option_current_price:.4f})远低于校准下轨({calibrated_lower:.4f})")
                elif option_current_price > calibrated_upper * 1.1:
                    logger.warning(f"当前价格({option_current_price:.4f})远高于校准上轨({calibrated_upper:.4f})")
            
            result = {
                'calibrated_range': calibration_result['calibrated_range'],
                'liquidity_report': liquidity_report,
                'metrics': metrics,
                'calibration_info': {
                    'status': calibration_result['status'],
                    'confidence': calibration_result['confidence'],
                    'deviation_pct': calibration_result['deviation_pct'],
                    'adjustment_info': calibration_result['adjustment_info'],
                    'theoretical_range': calibration_result.get('theoretical_range', theoretical_range),
                    'market_range': calibration_result.get('market_range', None)
                },
                'status': calibration_result['status']
            }
            
            logger.info(f"期权波动区间校准完成: {contract_code}, "
                       f"校准区间=[{calibration_result['calibrated_range'][0]:.4f}, "
                       f"{calibration_result['calibrated_range'][1]:.4f}], "
                       f"流动性={liquidity_report.get('grade', 'unknown')}, "
                       f"置信度={calibration_result['confidence']:.2f}")
            
            return result
            
        except Exception as e:
            logger.error(f"校准期权波动区间失败: {contract_code}, 错误: {e}", exc_info=True)
            # 回退到理论区间
            return {
                'calibrated_range': theoretical_range,
                'liquidity_report': None,
                'metrics': None,
                'calibration_info': {'status': 'fallback', 'reason': str(e)},
                'status': 'fallback'
            }
