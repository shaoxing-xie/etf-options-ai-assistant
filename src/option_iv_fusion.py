"""
期权IV信息融合模块
使用期权市场隐含波动率信息校准ETF预测
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Any
from src.logger_config import get_module_logger
from src.data_collector import fetch_option_greeks_sina
from src.config_loader import get_underlyings

logger = get_module_logger(__name__)


def get_option_iv_data(
    underlying: str,
    config: Optional[Dict] = None
) -> Optional[Dict[str, float]]:
    """
    获取同标的期权的IV数据
    
    Args:
        underlying: ETF代码（如'510300'）
        config: 系统配置
    
    Returns:
        dict: {
            'avg_iv': 0.18,  # 平均IV
            'call_iv': 0.19,  # Call期权IV
            'put_iv': 0.17,  # Put期权IV
            'iv_percentile': 0.65,  # IV百分位（可选）
            'num_contracts': 4  # 使用的合约数量
        }
    """
    try:
        if config is None:
            from src.config_loader import load_system_config
            config = load_system_config()
        
        # 从配置中获取该标的物的期权合约
        option_contracts = config.get('option_contracts', {})
        underlyings_list = get_underlyings(option_contracts)
        
        # 找到对应的标的物配置
        underlying_config = None
        for cfg in underlyings_list:
            if cfg.get('underlying') == underlying:
                underlying_config = cfg
                break
        
        if not underlying_config:
            logger.debug(f"未找到标的物 {underlying} 的配置")
            return None
        
        # 获取Call和Put合约
        call_contracts = underlying_config.get('call_contracts', [])
        put_contracts = underlying_config.get('put_contracts', [])
        
        if not call_contracts and not put_contracts:
            logger.debug(f"标的物 {underlying} 没有配置期权合约")
            return None
        
        # 收集IV数据
        call_ivs = []
        put_ivs = []
        
        # 获取Call期权IV（取前3个合约）
        for contract in call_contracts[:3]:
            contract_code = contract.get('contract_code')
            if contract_code:
                try:
                    greeks = fetch_option_greeks_sina(str(contract_code), use_cache=True, config=config)
                    if greeks is not None and not greeks.empty:
                        if 'iv' in greeks.columns:
                            iv_value = greeks['iv'].iloc[0]
                            if pd.notna(iv_value) and iv_value > 0:
                                call_ivs.append(float(iv_value))
                except Exception as e:
                    logger.debug(f"获取Call期权 {contract_code} IV失败: {e}")
        
        # 获取Put期权IV（取前3个合约）
        for contract in put_contracts[:3]:
            contract_code = contract.get('contract_code')
            if contract_code:
                try:
                    greeks = fetch_option_greeks_sina(str(contract_code), use_cache=True, config=config)
                    if greeks is not None and not greeks.empty:
                        if 'iv' in greeks.columns:
                            iv_value = greeks['iv'].iloc[0]
                            if pd.notna(iv_value) and iv_value > 0:
                                put_ivs.append(float(iv_value))
                except Exception as e:
                    logger.debug(f"获取Put期权 {contract_code} IV失败: {e}")
        
        if not call_ivs and not put_ivs:
            logger.debug(f"无法获取标的物 {underlying} 的期权IV数据")
            return None
        
        # 计算统计值
        all_ivs = call_ivs + put_ivs
        avg_iv = np.mean(all_ivs) if all_ivs else None
        
        if avg_iv is None:
            return None
        
        # 保证 call_iv / put_iv 始终为 float，避免 Dict[str, float] 返回类型在 mypy 下被推断出 float|None
        call_iv: float = float(np.mean(call_ivs)) if call_ivs else float(avg_iv)
        put_iv: float = float(np.mean(put_ivs)) if put_ivs else float(avg_iv)
        
        logger.debug(f"获取期权IV数据成功: 标的物={underlying}, "
                    f"平均IV={avg_iv:.4f}, Call IV={call_iv:.4f}, "
                    f"Put IV={put_iv:.4f}, 合约数={len(all_ivs)}")
        
        return {
            'avg_iv': float(avg_iv),
            'call_iv': float(call_iv),
            'put_iv': float(put_iv),
            'num_contracts': len(all_ivs)
        }
        
    except Exception as e:
        logger.warning(f"获取期权IV数据失败: {e}")
        return None


def incorporate_option_iv(
    etf_prediction: Dict[str, Any],
    underlying: str,
    option_iv_data: Optional[Dict[str, float]] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    使用期权市场隐含波动率信息校准ETF预测
    
    Args:
        etf_prediction: ETF预测结果，必须包含upper, lower, current_price等
        underlying: ETF代码（如'510300'）
        option_iv_data: 期权IV数据（如果为None，则自动获取）
        config: 系统配置
    
    Returns:
        dict: 校准后的预测结果
    """
    try:
        # 如果没有提供IV数据，自动获取
        if option_iv_data is None:
            option_iv_data = get_option_iv_data(underlying, config)
        
        if option_iv_data is None:
            logger.debug(f"无法获取标的物 {underlying} 的期权IV数据，跳过IV校准")
            return etf_prediction
        
        avg_iv = option_iv_data.get('avg_iv')
        if avg_iv is None or avg_iv <= 0:
            return etf_prediction
        
        # 获取历史波动率（从预测结果中提取，如果没有则估算）
        hist_vol = etf_prediction.get('hist_vol')
        if hist_vol is None:
            # 如果没有历史波动率，从range_pct估算
            range_pct = etf_prediction.get('range_pct', 2.0)
            # 假设range_pct是日波动率，转换为年化（简化估算）
            hist_vol = range_pct / 100.0  # 转换为小数
        else:
            hist_vol = hist_vol / 100.0  # 转换为小数
        
        # 计算IV比率
        iv_ratio = avg_iv / hist_vol if hist_vol > 0 else 1.0
        
        current_price = etf_prediction.get('current_price')
        upper = etf_prediction.get('upper')
        lower = etf_prediction.get('lower')
        
        if upper is None or lower is None or current_price is None:
            logger.warning("ETF预测结果缺少必要字段，跳过IV校准")
            return etf_prediction
        
        calibration_applied = False
        adjustment = 0.0
        
        # 如果IV显著高于历史波动率，说明市场预期波动较大，扩大预测区间
        if iv_ratio > 1.15:  # IV比历史波动率高15%以上
            adjustment = min(0.3, (iv_ratio - 1.15) * 0.5)  # 最多扩大30%
            calibration_applied = True
            
            center = (upper + lower) / 2
            half_range = (upper - lower) / 2
            
            adjusted_upper = center + half_range * (1 + adjustment)
            adjusted_lower = center - half_range * (1 + adjustment)
            
            etf_prediction['upper'] = adjusted_upper
            etf_prediction['lower'] = adjusted_lower
            etf_prediction['range_pct'] = (adjusted_upper - adjusted_lower) / current_price * 100
        
        # 如果IV显著低于历史波动率，可以适当缩小区间（但要谨慎）
        elif iv_ratio < 0.85:
            adjustment = min(0.15, (0.85 - iv_ratio) * 0.3)  # 最多缩小15%
            calibration_applied = True
            
            center = (upper + lower) / 2
            half_range = (upper - lower) / 2
            
            adjusted_upper = center + half_range * (1 - adjustment)
            adjusted_lower = center - half_range * (1 - adjustment)
            
            etf_prediction['upper'] = adjusted_upper
            etf_prediction['lower'] = adjusted_lower
            etf_prediction['range_pct'] = (adjusted_upper - adjusted_lower) / current_price * 100
        
        if calibration_applied:
            etf_prediction['iv_adjusted'] = True
            etf_prediction['iv_ratio'] = iv_ratio
            etf_prediction['option_iv'] = avg_iv
            etf_prediction['hist_vol_used'] = hist_vol * 100  # 转换回百分比
            etf_prediction['iv_adjustment'] = adjustment
            
            logger.info(f"期权IV校准已应用: 标的物={underlying}, IV比率={iv_ratio:.2f}, "
                       f"调整幅度={adjustment*100:.1f}%, "
                       f"区间=[{etf_prediction['lower']:.4f}, {etf_prediction['upper']:.4f}]")
        
        return etf_prediction
        
    except Exception as e:
        logger.warning(f"期权IV融合失败: {e}，返回原始预测")
        return etf_prediction
