"""
GARCH-IV引擎
集成GARCH模型和Black-Scholes定价，用于预测期权价格区间
"""

import pandas as pd
from typing import Dict, Optional, Any
from datetime import datetime
import time
import hashlib

from src.logger_config import get_module_logger
from .garch_model import GARCHIVPredictor, ARCH_AVAILABLE
from .option_pricer import BlackScholesPricer

logger = get_module_logger(__name__)


class GARCHIVEngine:
    """GARCH-IV预测引擎"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化GARCH-IV引擎
        
        Args:
            config: 系统配置字典
        """
        self.config = config or {}
        
        # 从配置读取GARCH参数
        garch_config = self.config.get('volatility_engine', {}).get('garch_iv', {})
        self.enabled = garch_config.get('enabled', False)
        self.lookback_days = garch_config.get('lookback_days', 30)
        garch_order = garch_config.get('garch_order', [1, 1])
        self.p = garch_order[0] if len(garch_order) > 0 else 1
        self.q = garch_order[1] if len(garch_order) > 1 else 1
        self.distribution = garch_config.get('distribution', 'normal')
        self.confidence_level = garch_config.get('confidence_level', 0.95)
        
        # 初始化组件
        self.garch_predictor = None
        self.bs_pricer = BlackScholesPricer()
        
        # 模型缓存（方案2：避免重复拟合）
        # 键：合约代码，值：已拟合的预测器和数据哈希
        self._cached_predictors: Dict[str, GARCHIVPredictor] = {}
        self._cached_iv_hashes: Dict[str, str] = {}
        
        # 性能监控
        self.last_fit_time = 0.0
        self.last_forecast_time = 0.0
        self.cache_hits = 0  # 缓存命中次数
        self.cache_misses = 0  # 缓存未命中次数
    
    def is_available(self) -> bool:
        """检查GARCH功能是否可用"""
        return ARCH_AVAILABLE and self.enabled
    
    def fetch_historical_iv(
        self,
        contract_code: str,
        lookback_days: Optional[int] = None
    ) -> Optional[pd.Series]:
        """
        获取历史IV数据
        
        Args:
            contract_code: 期权合约代码
            lookback_days: 回看天数（可选，默认使用配置值）
        
        Returns:
            IV时间序列（百分比形式）
        """
        if lookback_days is None:
            lookback_days = self.lookback_days
        
        try:
            
            # 获取历史IV数据
            # 注意：这里简化处理，实际应该获取多天的历史数据
            # 当前实现使用IV百分位调整器的数据获取逻辑
            from .iv_percentile_adjuster import IVPercentileAdjuster
            iv_adjuster = IVPercentileAdjuster(self.config)
            historical_ivs = iv_adjuster.fetch_historical_iv(contract_code)
            
            if historical_ivs is None or len(historical_ivs) < 20:
                logger.warning(f"历史IV数据不足（需要至少20个数据点，当前{len(historical_ivs) if historical_ivs is not None else 0}个）")
                return None
            
            return historical_ivs
            
        except Exception as e:
            logger.error(f"获取历史IV数据失败: {e}", exc_info=True)
            return None
    
    def predict_option_range(
        self,
        contract_code: str,
        option_type: str,
        current_price: float,
        strike_price: float,
        underlying_price: float,
        current_iv: float,
        expiry_date: Optional[datetime] = None,
        remaining_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        预测期权价格区间（使用GARCH-IV模型）
        
        Args:
            contract_code: 期权合约代码
            option_type: 期权类型 ('call' 或 'put')
            current_price: 期权当前价格
            strike_price: 行权价
            underlying_price: 标的资产当前价格（ETF价格）
            current_iv: 当前IV（百分比形式）
            expiry_date: 到期日期（可选）
            remaining_minutes: 剩余交易时间（分钟，可选）
        
        Returns:
            预测结果字典
        """
        if not self.is_available():
            return {
                'success': False,
                'error': 'GARCH-IV引擎未启用或arch库未安装',
                'fallback': True
            }
        
        start_time = time.time()
        
        try:
            # 1. 获取历史IV数据
            historical_ivs = self.fetch_historical_iv(contract_code)
            if historical_ivs is None or len(historical_ivs) < 20:
                return {
                    'success': False,
                    'error': '历史IV数据不足',
                    'fallback': True
                }
            
            # 2. 检查模型缓存（方案2：避免重复拟合）
            # 计算历史IV数据的哈希值，用于判断数据是否变化
            iv_hash = self._compute_iv_hash(historical_ivs)
            
            # 检查是否有缓存的预测器且数据未变化
            cached_predictor = self._cached_predictors.get(contract_code)
            cached_hash = self._cached_iv_hashes.get(contract_code)
            
            if cached_predictor is not None and cached_hash == iv_hash:
                # 缓存命中：复用已拟合的模型
                logger.debug(f"GARCH模型缓存命中: {contract_code}，复用已拟合模型")
                self.cache_hits += 1
                predictor = cached_predictor
                # 注意：即使使用缓存，predict_iv_range内部仍会调用fit，但我们可以优化
                # 这里先使用缓存，如果predict_iv_range支持复用已拟合模型，可以进一步优化
            else:
                # 缓存未命中：创建新的预测器并拟合
                logger.debug(f"GARCH模型缓存未命中: {contract_code}，创建新模型并拟合")
                self.cache_misses += 1
                predictor = GARCHIVPredictor(
                    p=self.p,
                    q=self.q,
                    distribution=self.distribution,
                    lookback_days=self.lookback_days
                )
                # 预先拟合模型（这样predict_iv_range可以复用）
                fit_result = predictor.fit(historical_ivs)
                if fit_result.get('success', False):
                    # 缓存预测器和数据哈希
                    self._cached_predictors[contract_code] = predictor
                    self._cached_iv_hashes[contract_code] = iv_hash
                    logger.debug(f"GARCH模型已缓存: {contract_code}")
                else:
                    logger.warning(f"GARCH模型拟合失败，无法缓存: {fit_result.get('error', 'unknown')}")
            
            # 3. 使用GARCH预测IV区间
            fit_start = time.time()
            # 如果使用缓存的预测器，跳过拟合步骤（模型已拟合）
            skip_fit = (cached_predictor is not None and cached_hash == iv_hash)
            iv_prediction = predictor.predict_iv_range(
                current_iv=current_iv,
                iv_series=historical_ivs,
                horizon=1,
                confidence_level=self.confidence_level,
                skip_fit_if_fitted=skip_fit
            )
            # 如果跳过了拟合，拟合时间为0（实际拟合时间已在缓存时记录）
            if skip_fit:
                self.last_fit_time = 0.0  # 使用缓存，拟合时间为0
            else:
                self.last_fit_time = time.time() - fit_start
            
            if not iv_prediction['success']:
                logger.warning(f"GARCH-IV预测失败: {iv_prediction.get('error')}，将回退到阶段1方法")
                return {
                    'success': False,
                    'error': iv_prediction.get('error', 'GARCH预测失败'),
                    'fallback': True
                }
            
            # 4. 计算到期时间（优先使用实际到期日期）
            T = None
            
            # 优先级1：使用传入的到期日期（最准确）
            if expiry_date is not None:
                T = self.bs_pricer.time_to_expiry(expiry_date)
                logger.debug(f"使用传入的到期日期计算T: {expiry_date.strftime('%Y-%m-%d')} -> T={T:.6f}年")
            
            # 优先级2：从合约数据中获取到期日期
            if T is None or T <= 0:
                from src.data_collector import fetch_option_expiry_date
                fetched_expiry_date = fetch_option_expiry_date(contract_code)
                if fetched_expiry_date is not None:
                    T = self.bs_pricer.time_to_expiry(fetched_expiry_date)
                    logger.debug(f"从合约数据获取到期日期: {fetched_expiry_date.strftime('%Y-%m-%d')} -> T={T:.6f}年")
            
            # 优先级3：使用remaining_minutes（如果只是当天剩余时间，需要加上到期前的天数）
            if T is None or T <= 0:
                if remaining_minutes is not None:
                    # 从剩余分钟数计算年化时间
                    # 注意：remaining_minutes可能只是当天剩余时间，需要加上到期前的天数
                    # 这里先尝试使用remaining_minutes，如果太小则使用默认值
                    T = remaining_minutes / (252 * 240)  # 假设一年252个交易日，每天240分钟
                    if T < 0.01:
                        logger.warning(f"从remaining_minutes计算的T={T:.6f}年过小，可能只是当天剩余时间，尝试使用默认值")
                        # 如果T太小，可能是当天剩余时间，尝试加上一个月的交易日
                        # 假设还有1个月到期（约21个交易日）
                        T = (remaining_minutes + 21 * 240) / (252 * 240)
                        if T < 0.01:
                            T = 0.01  # 最小值
                        logger.debug(f"调整后的T={T:.6f}年（假设还有约1个月到期）")
            
            # 优先级4：使用默认值（假设还有1个月到期）
            if T is None or T <= 0:
                T = 30 / 365.0
                logger.warning(f"无法获取到期日期，使用默认值T={T:.6f}年（假设还有1个月到期）")
            
            logger.debug(f"最终到期时间: T={T:.6f}年 (remaining_minutes={remaining_minutes}, expiry_date={expiry_date})")
            
            # 5. 使用B-S模型计算期权价格区间
            forecast_start = time.time()
            price_range = self.bs_pricer.calculate_price_range(
                S=underlying_price,
                K=strike_price,
                T=T,
                iv_lower=iv_prediction['lower_iv'],
                iv_upper=iv_prediction['upper_iv'],
                iv_current=current_iv,
                option_type=option_type
            )
            self.last_forecast_time = time.time() - forecast_start
            
            total_time = time.time() - start_time
            
            logger.info(f"GARCH-IV预测完成: {option_type.upper()}期权 {contract_code}, "
                       f"IV区间=[{iv_prediction['lower_iv']:.2f}%, {iv_prediction['upper_iv']:.2f}%], "
                       f"价格区间=[{price_range['lower_price']:.4f}, {price_range['upper_price']:.4f}], "
                       f"耗时={total_time:.2f}秒")
            
            return {
                'success': True,
                'lower_price': price_range['lower_price'],
                'upper_price': price_range['upper_price'],
                'current_price_bs': price_range['current_price'],
                'iv_prediction': {
                    'current_iv': iv_prediction['current_iv'],
                    'predicted_iv': iv_prediction['predicted_iv'],
                    'lower_iv': iv_prediction['lower_iv'],
                    'upper_iv': iv_prediction['upper_iv']
                },
                'greeks': price_range['greeks'],
                'performance': {
                    'fit_time': self.last_fit_time,
                    'forecast_time': self.last_forecast_time,
                    'total_time': total_time
                },
                'method': 'GARCH-IV + B-S'
            }
            
        except Exception as e:
            logger.error(f"GARCH-IV引擎预测失败: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'fallback': True
            }
    
    def _compute_iv_hash(self, iv_series: pd.Series) -> str:
        """
        计算IV序列的哈希值，用于缓存判断
        
        Args:
            iv_series: IV时间序列
        
        Returns:
            str: 哈希值
        """
        try:
            # 使用最后N个数据点的值和索引计算哈希（避免整个序列变化导致频繁重新拟合）
            # 取最后10个数据点，如果数据变化不大，哈希应该相同
            n_points = min(10, len(iv_series))
            if n_points > 0:
                recent_values = iv_series.tail(n_points).values
                recent_index = iv_series.tail(n_points).index.strftime('%Y-%m-%d').values
                # 组合值和索引计算哈希
                hash_input = f"{recent_values.tobytes()}{''.join(recent_index)}"
            else:
                hash_input = str(iv_series.values.tobytes())
            
            # 使用 SHA-256：用于缓存校验，无需密码学弱哈希
            return hashlib.sha256(hash_input.encode()).hexdigest()
        except Exception as e:
            logger.debug(f"计算IV哈希失败: {e}，使用简单哈希")
            return hashlib.sha256(str(iv_series.values).encode()).hexdigest()
    
    def preheat(self, contract_codes: list, current_ivs: Optional[Dict[str, float]] = None, min_data_points: int = 5) -> Dict[str, Any]:
        """
        预热GARCH模型（方案1：系统启动时预热）
        
        Args:
            contract_codes: 合约代码列表，如 ['10010466', '10010474']
            current_ivs: 当前IV值字典，格式 {contract_code: iv_value}，可选
            min_data_points: 最小数据点要求（默认5，预热时可以放宽要求）
        
        Returns:
            dict: 预热结果，包含成功/失败的合约
        """
        if not self.is_available():
            return {
                'success': False,
                'error': 'GARCH-IV引擎未启用或arch库未安装',
                'preheated': []
            }
        
        # 用更宽的类型标注 results，避免 mypy 把其中列表/字典推断成 object
        results: Dict[str, Any] = {
            'success': True,
            'preheated': [],
            'failed': [],
            'skipped': [],  # 数据不足但跳过（不视为失败）
            'errors': {}
        }
        
        logger.info(f"开始预热GARCH模型，合约数量: {len(contract_codes)}, 最小数据点要求: {min_data_points}")
        
        for contract_code in contract_codes:
            try:
                # 获取历史IV数据
                historical_ivs = self.fetch_historical_iv(contract_code)
                
                # 检查数据是否足够（预热时可以使用更少的数据点）
                if historical_ivs is None or len(historical_ivs) < min_data_points:
                    data_count = len(historical_ivs) if historical_ivs is not None else 0
                    # 如果数据少于最小要求，跳过但不视为失败（数据还在积累中）
                    if data_count > 0:
                        logger.debug(f"预热跳过 {contract_code}: 历史IV数据不足（当前{data_count}个，需要至少{min_data_points}个），"
                                   f"数据正在积累中，后续会自动预热")
                    else:
                        logger.debug(f"预热跳过 {contract_code}: 无法获取历史IV数据，数据正在积累中")
                    results['skipped'].append(contract_code)
                    continue
                
                # 如果数据点少于GARCH推荐值（20），记录警告但继续尝试
                if len(historical_ivs) < 20:
                    logger.warning(f"预热 {contract_code}: 历史IV数据点较少（{len(historical_ivs)}个，推荐至少20个），"
                                 f"拟合效果可能不佳，但会尝试预热")
                
                # 检查GARCH模型的最小数据要求（p+q+10）
                min_garch_points = max(self.p, self.q) + 10
                if len(historical_ivs) < min_garch_points:
                    error_msg = f"历史IV数据不足（当前{len(historical_ivs)}个，GARCH模型需要至少{min_garch_points}个数据点）"
                    results['failed'].append(contract_code)
                    results['errors'][contract_code] = error_msg
                    logger.warning(f"预热失败 {contract_code}: {error_msg}")
                    continue
                
                # 计算数据哈希
                iv_hash = self._compute_iv_hash(historical_ivs)
                
                # 检查是否已缓存
                if contract_code in self._cached_predictors and \
                   self._cached_iv_hashes.get(contract_code) == iv_hash:
                    logger.debug(f"合约 {contract_code} 已预热，跳过")
                    results['preheated'].append(contract_code)
                    continue
                
                # 创建预测器并拟合
                predictor = GARCHIVPredictor(
                    p=self.p,
                    q=self.q,
                    distribution=self.distribution,
                    lookback_days=self.lookback_days
                )
                
                fit_start = time.time()
                fit_result = predictor.fit(historical_ivs)
                fit_time = time.time() - fit_start
                
                if fit_result.get('success', False):
                    # 缓存预测器
                    self._cached_predictors[contract_code] = predictor
                    self._cached_iv_hashes[contract_code] = iv_hash
                    results['preheated'].append(contract_code)
                    logger.info(f"预热成功: {contract_code}, 拟合耗时={fit_time:.2f}秒, "
                              f"AIC={fit_result.get('aic', 0):.2f}, 数据点={len(historical_ivs)}个")
                else:
                    error_msg = fit_result.get('error', '拟合失败')
                    results['failed'].append(contract_code)
                    results['errors'][contract_code] = error_msg
                    logger.warning(f"预热失败 {contract_code}: {error_msg}")
                    
            except Exception as e:
                error_msg = str(e)
                results['failed'].append(contract_code)
                results['errors'][contract_code] = error_msg
                logger.error(f"预热异常 {contract_code}: {error_msg}", exc_info=True)
        
        logger.info(f"GARCH预热完成: 成功 {len(results['preheated'])} 个, "
                   f"失败 {len(results['failed'])} 个, "
                   f"跳过 {len(results['skipped'])} 个（数据积累中）")
        
        # 如果有跳过的合约，说明数据还在积累，这是正常的
        if results['skipped']:
            logger.info(f"提示: {len(results['skipped'])} 个合约因历史数据不足而跳过预热，"
                       f"随着数据积累，后续预测时会自动预热")
        
        return results
    
    def clear_cache(self, contract_code: Optional[str] = None):
        """
        清除模型缓存
        
        Args:
            contract_code: 合约代码，如果为None则清除所有缓存
        """
        if contract_code is None:
            self._cached_predictors.clear()
            self._cached_iv_hashes.clear()
            logger.info("已清除所有GARCH模型缓存")
        else:
            if contract_code in self._cached_predictors:
                del self._cached_predictors[contract_code]
            if contract_code in self._cached_iv_hashes:
                del self._cached_iv_hashes[contract_code]
            logger.info(f"已清除合约 {contract_code} 的GARCH模型缓存")
    
    def get_performance_stats(self) -> Dict[str, float]:
        """获取性能统计"""
        return {
            'last_fit_time': self.last_fit_time,
            'last_forecast_time': self.last_forecast_time,
            'total_time': self.last_fit_time + self.last_forecast_time,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': self.cache_hits / (self.cache_hits + self.cache_misses) if (self.cache_hits + self.cache_misses) > 0 else 0.0
        }
