"""
流动性评估器
评估期权合约的流动性等级，判断是否可交易
"""

from typing import Dict, Any, Optional
from src.logger_config import get_module_logger

logger = get_module_logger(__name__)


class LiquidityAssessor:
    """流动性评估器"""
    
    # 流动性等级阈值（优化后：放宽阈值，更符合实际市场情况，提升信号可用性）
    THRESHOLDS = {
        'excellent': {
            'max_spread_pct': 0.5,
            'min_depth': 100
        },
        'good': {
            'max_spread_pct': 1.5,  # 从1.0提高到1.5，放宽good等级标准
            'min_depth': 50
        },
        'fair': {
            'max_spread_pct': 4.0,  # 从3.0提高到4.0，进一步放宽fair等级标准
            'min_depth': 15  # 从20降到15，降低深度要求
        },
        'poor': {
            'max_spread_pct': 8.0,  # 从6.0提高到8.0，放宽poor等级标准
            'min_depth': 8  # 从10降到8，降低深度要求
        },
        'critical': {
            'max_spread_pct': 10.0,
            'min_depth': 5
        }
    }
    
    def __init__(self, custom_thresholds: Optional[Dict[str, Dict[str, float]]] = None):
        """
        初始化流动性评估器
        
        Args:
            custom_thresholds: 自定义阈值，如果提供则覆盖默认阈值
        """
        if custom_thresholds:
            self.THRESHOLDS = custom_thresholds
        else:
            self.THRESHOLDS = LiquidityAssessor.THRESHOLDS.copy()
    
    def assess_liquidity(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        评估流动性
        
        Args:
            metrics: 市场指标，包含：
                - spread_pct: 买卖价差百分比
                - total_depth: 总深度（买卖量之和）
                - depth_imbalance: 深度不平衡度
                - is_estimated: 是否为估算数据（bool，可选）
        
        Returns:
            dict: 流动性评估结果，包含：
                - grade: 流动性等级（excellent/good/fair/poor/critical）
                - is_tradable: 是否可交易（bool）
                - warnings: 警告信息列表
                - score: 流动性评分（0-100，100最好）
        """
        try:
            spread_pct = metrics.get('spread_pct', 0)
            total_depth = metrics.get('total_depth', 0)
            depth_imbalance = metrics.get('depth_imbalance', 0.5)
            is_estimated = metrics.get('is_estimated', False)
            
            # 从高到低检查流动性等级
            grade = 'critical'
            for g in ['excellent', 'good', 'fair', 'poor', 'critical']:
                thresh = self.THRESHOLDS[g]
                if spread_pct <= thresh['max_spread_pct'] and total_depth >= thresh['min_depth']:
                    grade = g
                    break
            
            # 判断是否可交易（excellent/good/fair/poor为可交易，critical不可交易）
            # 优化：将poor也纳入可交易，提升信号可用性，但会添加警告提示风险
            is_tradable = grade in ['excellent', 'good', 'fair', 'poor']
            
            # 计算流动性评分（0-100）
            # 价差越小、深度越大、不平衡度越小，评分越高
            spread_score = max(0, 100 - spread_pct * 10)  # 价差每1%扣10分
            depth_score = min(100, total_depth / 2)  # 深度每2手加1分，最高100分
            imbalance_score = (1 - depth_imbalance) * 100  # 不平衡度越小，评分越高
            
            # 综合评分（价差40%，深度40%，不平衡度20%）
            score = (spread_score * 0.4 + depth_score * 0.4 + imbalance_score * 0.2)
            score = max(0, min(100, round(score, 1)))
            
            # 生成警告信息
            warnings = []
            
            # 如果是估算数据，添加警告并降低评分
            if is_estimated:
                warnings.append("⚠️ 盘口数据为估算值，实际流动性可能不同")
                # 降低评分（估算数据最多50分）
                score = min(50, score)
            
            # 根据流动性等级生成警告（优化：更细致的警告分级）
            if grade == 'poor':
                warnings.append("⚠️ 流动性较差（poor），价差较大，成交成本较高，建议谨慎交易")
            elif grade == 'critical':
                warnings.append("⚠️ 流动性严重不足（critical），成交困难，不建议交易")
            
            if spread_pct > 8.0:
                warnings.append("⚠️ 价差过大（>8%），成交成本很高")
            elif spread_pct > 4.0:
                warnings.append("⚠️ 价差较大（>4%），注意成交成本")
            elif spread_pct > 1.5:
                warnings.append("⚠️ 价差适中，注意成交成本")
            
            if total_depth < 10:
                warnings.append("⚠️ 深度严重不足（<10），可能影响成交")
            elif total_depth < 20:
                warnings.append("⚠️ 深度不足（<20），可能影响成交")
            
            if depth_imbalance > 0.7:
                warnings.append("⚠️ 深度严重不平衡，可能影响成交价格")
            
            if not is_tradable:
                warnings.append("⚠️ 流动性严重不足（critical），成交困难，不建议交易")
            
            result = {
                'grade': grade,
                'is_tradable': is_tradable,
                'warnings': warnings,
                'score': score,
                'spread_pct': round(spread_pct, 2),
                'total_depth': total_depth,
                'depth_imbalance': round(depth_imbalance, 3)
            }
            
            logger.debug(f"流动性评估: 等级={grade}, 可交易={is_tradable}, 评分={score}, "
                        f"价差={spread_pct:.2f}%, 深度={total_depth}")
            
            return result
            
        except Exception as e:
            logger.error(f"评估流动性失败: {e}", exc_info=True)
            return {
                'grade': 'critical',
                'is_tradable': False,
                'warnings': ["⚠️ 流动性评估失败"],
                'score': 0,
                'spread_pct': 0,
                'total_depth': 0,
                'depth_imbalance': 0.5
            }
