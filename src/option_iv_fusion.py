"""
期权IV信息融合模块
使用期权市场隐含波动率信息校准ETF预测
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Any, Tuple, List
from src.logger_config import get_module_logger
from src.data_collector import fetch_option_greeks_sina
from src.config_loader import get_underlyings

logger = get_module_logger(__name__)


def _normalize_vol_value_to_decimal(vol_value: float, *, kind: str) -> Tuple[float, str]:
    """
    将输入的波动率值归一到“年化波动率小数”语义。

    约定：
    - 如果值 > 1.5：认为是“百分数形式”（如 51.67 表示 51.67%），转换为 /100
    - 否则：认为已经是“小数形式”（如 0.5167 表示 51.67%），保持不变
    """
    if vol_value is None:
        raise ValueError(f"{kind} is None")
    v = float(vol_value)
    if v <= 0:
        raise ValueError(f"{kind} must be > 0, got {v}")

    if v > 1.5:
        return v / 100.0, f"{kind}_converted_from_percent"
    return v, f"{kind}_assumed_decimal"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def blend_sigma(iv_annual: float, hv_annual: float, w_iv: float, w_hv: float) -> float:
    """显式 IV-HV 融合，输入/输出均为年化小数波动率。"""
    ws = w_iv + w_hv
    if ws <= 0:
        return hv_annual
    wi = w_iv / ws
    wh = w_hv / ws
    return wi * iv_annual + wh * hv_annual


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
        bad_delta = 0
        bad_vega_zero = 0
        total_contracts = 0
        
        # 获取Call期权IV（取前3个合约）
        for contract in call_contracts[:3]:
            contract_code = contract.get('contract_code')
            if contract_code:
                total_contracts += 1
                try:
                    greeks = fetch_option_greeks_sina(str(contract_code), use_cache=True, config=config)
                    if greeks is not None and not greeks.empty and 'iv' in greeks.columns:
                        row = greeks.iloc[0]
                        iv_value = row.get('iv')
                        if pd.isna(iv_value) or iv_value is None or iv_value <= 0:
                            continue
                        # 质量门禁：过滤掉 Delta 明显异常或 Vega≈0 的合约
                        delta_val = row.get('delta') if 'delta' in greeks.columns else None
                        vega_val = row.get('vega') if 'vega' in greeks.columns else None
                        if delta_val is not None:
                            try:
                                if abs(float(delta_val)) > 1.5:
                                    bad_delta += 1
                                    continue
                            except Exception:
                                bad_delta += 1
                                continue
                        if vega_val is not None:
                            try:
                                if abs(float(vega_val)) < 1e-8:
                                    bad_vega_zero += 1
                                    continue
                            except Exception:
                                bad_vega_zero += 1
                                continue
                        call_ivs.append(float(iv_value))
                except Exception as e:
                    logger.debug(f"获取Call期权 {contract_code} IV失败: {e}")
        
        # 获取Put期权IV（取前3个合约）
        for contract in put_contracts[:3]:
            contract_code = contract.get('contract_code')
            if contract_code:
                total_contracts += 1
                try:
                    greeks = fetch_option_greeks_sina(str(contract_code), use_cache=True, config=config)
                    if greeks is not None and not greeks.empty and 'iv' in greeks.columns:
                        row = greeks.iloc[0]
                        iv_value = row.get('iv')
                        if pd.isna(iv_value) or iv_value is None or iv_value <= 0:
                            continue
                        delta_val = row.get('delta') if 'delta' in greeks.columns else None
                        vega_val = row.get('vega') if 'vega' in greeks.columns else None
                        if delta_val is not None:
                            try:
                                if abs(float(delta_val)) > 1.5:
                                    bad_delta += 1
                                    continue
                            except Exception:
                                bad_delta += 1
                                continue
                        if vega_val is not None:
                            try:
                                if abs(float(vega_val)) < 1e-8:
                                    bad_vega_zero += 1
                                    continue
                            except Exception:
                                bad_vega_zero += 1
                                continue
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
        
        logger.debug(
            "获取期权IV数据成功: 标的物=%s, 平均IV=%.4f, Call IV=%.4f, Put IV=%.4f, 合约数=%d, bad_delta=%d, bad_vega_zero=%d, total=%d",
            underlying,
            avg_iv,
            call_iv,
            put_iv,
            len(all_ivs),
            bad_delta,
            bad_vega_zero,
            total_contracts,
        )
        
        return {
            'avg_iv': float(avg_iv),
            'call_iv': float(call_iv),
            'put_iv': float(put_iv),
            'num_contracts': len(all_ivs),
            'quality': {
                'total_contracts': total_contracts,
                'used_contracts': len(all_ivs),
                'bad_delta': bad_delta,
                'bad_vega_zero': bad_vega_zero,
            },
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
        # 默认先打可观测标记，任何失败分支都会带原因返回
        etf_prediction["iv_data_available"] = False
        etf_prediction["iv_data_reason"] = "iv_not_checked"

        config = config or {}
        vol_engine_cfg = (config.get("volatility_engine") or {}) if isinstance(config, dict) else {}
        fusion_cfg = vol_engine_cfg.get("iv_hv_fusion") or {}
        fusion_enabled = bool(fusion_cfg.get("enabled", False))

        weight_iv = float(fusion_cfg.get("weight_iv", 0.5))
        weight_hv = float(fusion_cfg.get("weight_hv", 1.0 - weight_iv))
        w_sum = weight_iv + weight_hv
        if w_sum > 0:
            weight_iv /= w_sum
            weight_hv /= w_sum

        min_scale = float(fusion_cfg.get("min_scale", 0.7))
        max_scale = float(fusion_cfg.get("max_scale", 1.3))
        min_scale = min(min_scale, max_scale)

        # 如果没有提供IV数据，自动获取
        if option_iv_data is None:
            option_iv_data = get_option_iv_data(underlying, config)
        
        if option_iv_data is None:
            etf_prediction["iv_data_available"] = False
            etf_prediction["iv_data_reason"] = "option_iv_data_unavailable"
            logger.debug(f"无法获取标的物 {underlying} 的期权IV数据，跳过IV校准")
            return etf_prediction
        
        avg_iv = option_iv_data.get('avg_iv')
        if avg_iv is None or avg_iv <= 0:
            etf_prediction["iv_data_available"] = False
            etf_prediction["iv_data_reason"] = "avg_iv_invalid_or_empty"
            return etf_prediction

        etf_prediction["iv_data_available"] = True
        etf_prediction["iv_data_reason"] = "iv_data_ready"

        unit_warnings: List[str] = []

        # 1) 归一化 IV 到“年化小数”
        iv_decimal, iv_unit_status = _normalize_vol_value_to_decimal(
            float(avg_iv), kind="iv"
        )
        if iv_unit_status != "iv_assumed_decimal":
            unit_warnings.append(f"IV单位已转换：{iv_unit_status}")

        # 2) 归一化 HV 到“年化小数”
        hist_vol_raw = etf_prediction.get('hist_vol')
        if hist_vol_raw is None:
            range_pct = float(etf_prediction.get('range_pct', 2.0) or 2.0)
            hist_vol_raw = range_pct

        hv_decimal, hv_unit_status = _normalize_vol_value_to_decimal(
            float(hist_vol_raw), kind="hist_vol"
        )
        if hv_unit_status != "hist_vol_assumed_decimal":
            unit_warnings.append(f"HV单位已转换：{hv_unit_status}")

        if hv_decimal <= 0:
            etf_prediction["iv_data_reason"] = "hist_vol_invalid"
            return etf_prediction

        # 计算IV比率（用于诊断与旧逻辑）
        iv_ratio = iv_decimal / hv_decimal
        
        current_price = etf_prediction.get('current_price')
        upper = etf_prediction.get('upper')
        lower = etf_prediction.get('lower')
        
        if upper is None or lower is None or current_price is None:
            etf_prediction["iv_data_reason"] = "prediction_fields_missing"
            logger.warning("ETF预测结果缺少必要字段，跳过IV校准")
            return etf_prediction
        
        calibration_applied = False
        adjustment = 0.0

        if fusion_enabled:
            # 显式 IV–HV σ 融合：通过缩放区间半宽来反映 sigma_eff 变化
            sigma_eff = blend_sigma(iv_decimal, hv_decimal, weight_iv, weight_hv)
            # 成交量因子：在 sigma 融合阶段注入，而非 clamp 阶段
            volume_factor = float(etf_prediction.get("volume_factor") or 1.0)
            sigma_eff *= volume_factor
            scaling_factor = sigma_eff / hv_decimal if hv_decimal > 0 else 1.0
            scaling_factor = _clamp(scaling_factor, min_scale, max_scale)

            if abs(scaling_factor - 1.0) > 1e-9:
                center = (upper + lower) / 2.0
                half_range = (upper - lower) / 2.0
                adjusted_upper = center + half_range * scaling_factor
                adjusted_lower = center - half_range * scaling_factor
                adjusted_lower = max(0.0, adjusted_lower)

                etf_prediction['upper'] = adjusted_upper
                etf_prediction['lower'] = adjusted_lower
                etf_prediction['range_pct'] = (adjusted_upper - adjusted_lower) / current_price * 100

                calibration_applied = True
                adjustment = float(scaling_factor - 1.0)

                etf_prediction['iv_hv_fusion'] = True
                etf_prediction['iv_hv_sigma_eff'] = float(sigma_eff)
                etf_prediction['iv_hv_weights'] = {
                    'weight_iv': float(weight_iv),
                    'weight_hv': float(weight_hv),
                }
                etf_prediction['iv_hv_scaling_factor'] = float(scaling_factor)
                etf_prediction['iv_hv_volume_factor'] = float(volume_factor)
        else:
            # 旧阈值逻辑（基于已归一化的 iv_decimal / hv_decimal）
            if iv_ratio > 1.15:  # IV比历史波动率高15%以上
                adjustment = min(0.3, (iv_ratio - 1.15) * 0.5)  # 最多扩大30%
                calibration_applied = True
                
                center = (upper + lower) / 2.0
                half_range = (upper - lower) / 2.0
                
                adjusted_upper = center + half_range * (1 + adjustment)
                adjusted_lower = center - half_range * (1 + adjustment)
                
                etf_prediction['upper'] = adjusted_upper
                etf_prediction['lower'] = adjusted_lower
                etf_prediction['range_pct'] = (adjusted_upper - adjusted_lower) / current_price * 100
            
            elif iv_ratio < 0.85:
                adjustment = min(0.15, (0.85 - iv_ratio) * 0.3)  # 最多缩小15%
                calibration_applied = True
                
                center = (upper + lower) / 2.0
                half_range = (upper - lower) / 2.0
                
                adjusted_upper = center + half_range * (1 - adjustment)
                adjusted_lower = center - half_range * (1 - adjustment)
                
                etf_prediction['upper'] = adjusted_upper
                etf_prediction['lower'] = adjusted_lower
                etf_prediction['range_pct'] = (adjusted_upper - adjusted_lower) / current_price * 100
        
        if calibration_applied:
            etf_prediction['iv_adjusted'] = True
            etf_prediction['iv_ratio'] = iv_ratio
            # option_iv：保留为“年化小数”（如 0.5167）
            etf_prediction['option_iv'] = float(iv_decimal)
            # hist_vol_used：保留为“年化百分比”（如 15.43）
            etf_prediction['hist_vol_used'] = float(hv_decimal * 100.0)
            etf_prediction['iv_adjustment'] = adjustment

            # 聚合单位与合约池质量告警
            dq_warnings: List[str] = []
            dq_warnings.extend(unit_warnings)
            quality_info = option_iv_data.get('quality') if isinstance(option_iv_data, dict) else None
            if quality_info:
                used = quality_info.get('used_contracts')
                total = quality_info.get('total_contracts')
                bad_delta = quality_info.get('bad_delta')
                bad_vega_zero = quality_info.get('bad_vega_zero')
                if total:
                    dq_warnings.append(
                        f"IV合约池: 使用 {used}/{total} 条, bad_delta={bad_delta}, bad_vega_zero={bad_vega_zero}"
                    )

            if dq_warnings:
                etf_prediction.setdefault('data_quality', {})
                dq = etf_prediction['data_quality']
                existing = dq.get('warnings') or []
                dq['warnings'] = list(existing) + dq_warnings
            
            logger.info(
                "期权IV校准已应用: 标的物=%s, IV比率=%.2f, 调整幅度=%.1f%%, 区间=[%.4f, %.4f]",
                underlying,
                iv_ratio,
                adjustment * 100.0,
                etf_prediction['lower'],
                etf_prediction['upper'],
            )
            etf_prediction["iv_data_reason"] = "iv_fusion_applied"
        else:
            etf_prediction["iv_data_reason"] = "iv_data_ready_but_no_adjustment"
        
        return etf_prediction
        
    except Exception as e:
        etf_prediction["iv_data_available"] = False
        etf_prediction["iv_data_reason"] = f"iv_fusion_error:{type(e).__name__}"
        logger.warning(f"期权IV融合失败: {e}，返回原始预测")
        return etf_prediction
