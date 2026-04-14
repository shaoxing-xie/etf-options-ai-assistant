"""
日内区间预测工具（轻量版）。

该模块用于补齐工作流依赖：tool_predict_intraday_range。
本工具在「主链路失败后的补算」路径上**仅使用分钟级数据**计算区间；**不使用日线数据做波动区间降级**。
若无法取得有效分钟数据或分钟模型无有效上下界，返回 success=False，并在 data 中带 error_code 供上层工作流/Agent 识别。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from src.underlying_resolver import resolve_volatility_underlying


def tool_predict_intraday_range(
    symbol: str = "510300",
    underlying: Optional[str] = None,
    lookback_days: int = 60,
    asset_type: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    预测标的当日剩余时间的价格区间（指数 / ETF / A 股）。

    Args:
        symbol: 默认 510300（ETF）
        underlying: 兼容参数，优先于 symbol
        lookback_days: 保留兼容（补算路径已不拉日线作区间降级，此参数当前未使用）
        asset_type: 可选，显式指定 index / etf / stock（小写），与输入中的「指数:」「ETF:」「股票:」前缀二选一
    """
    sym_raw = str(underlying or symbol or "510300")
    hint = str(asset_type).strip().lower() if asset_type else None
    if hint == "":
        hint = None
    try:
        from src.config_loader import load_system_config
        from src.on_demand_predictor import (
            predict_index_volatility_range_on_demand,
            predict_etf_volatility_range_on_demand,
            predict_stock_volatility_range_on_demand,
        )
        from src.data_collector import (
            fetch_etf_minute_data_with_fallback,
            fetch_stock_minute_data_with_fallback,
            get_stock_current_price,
        )
        from src.volatility_range import get_remaining_trading_time
        from src.volatility_range import calculate_etf_volatility_range_multi_period
        from src.logger_config import get_module_logger
        from src.prediction_recorder import record_prediction

        logger = get_module_logger(__name__)
        cfg = load_system_config(use_cache=True)

        resolved = resolve_volatility_underlying(sym_raw, hint)
        if not resolved.ok:
            return {
                "success": False,
                "message": resolved.error,
                "data": {"candidates": resolved.candidates} if resolved.candidates else None,
            }

        sym = resolved.code
        asset_type = resolved.asset_type

        # 指数与 ETF / 股票分别走对应预测链路，避免名称/类型误判导致价格尺度错乱
        if asset_type == "index":
            idx = predict_index_volatility_range_on_demand(symbol=sym, config=cfg)
            if not idx or idx.get("success") is False:
                return {"success": False, "message": idx.get("error", "Index prediction failed"), "data": None}
            payload = {
                "symbol": idx.get("symbol", sym),
                "current_price": float(idx.get("current_price", 0.0)),
                "lower_bound": float(idx.get("lower", 0.0)),
                "upper_bound": float(idx.get("upper", 0.0)),
                "predicted_range": f"{float(idx.get('lower', 0.0)):.4f} ~ {float(idx.get('upper', 0.0)):.4f}",
                "confidence": float(idx.get("confidence", 0.5)),
                "remaining_minutes": int(idx.get("remaining_minutes", 0)),
                "method": idx.get("method", "index_multi_period"),
                "timestamp": idx.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            }
            for k in ["iv_data_available", "iv_data_reason", "volume_factor", "garch_shadow", "data_quality", "ab_profile"]:
                if k in idx:
                    payload[k] = idx.get(k)
            return {"success": True, "message": "Intraday range predicted", "data": payload, "source": "index_multi_period"}

        if asset_type == "stock":
            stk = predict_stock_volatility_range_on_demand(symbol=sym, config=cfg)
            if stk and stk.get("success") is not False and "upper" in stk and "lower" in stk:
                payload = {
                    "symbol": stk.get("symbol", sym),
                    "current_price": float(stk.get("current_price", 0.0)),
                    "lower_bound": float(stk.get("lower", 0.0)),
                    "upper_bound": float(stk.get("upper", 0.0)),
                    "predicted_range": f"{float(stk.get('lower', 0.0)):.4f} ~ {float(stk.get('upper', 0.0)):.4f}",
                    "confidence": float(stk.get("confidence", 0.5)),
                    "remaining_minutes": int(stk.get("remaining_minutes", 0)),
                    "method": stk.get("method", "stock_multi_period"),
                    "timestamp": stk.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    "asset_type": "stock",
                }
                for k in ["volume_factor", "garch_shadow", "data_quality", "ab_profile"]:
                    if k in stk:
                        payload[k] = stk.get(k)
                return {"success": True, "message": "Intraday range predicted", "data": payload, "source": "stock_multi_period"}

        if asset_type == "etf":
            etf_try = predict_etf_volatility_range_on_demand(symbol=sym, config=cfg)
            if etf_try and etf_try.get("success") is not False and "upper" in etf_try and "lower" in etf_try:
                payload = {
                    "symbol": etf_try.get("symbol", sym),
                    "current_price": float(etf_try.get("current_price", 0.0)),
                    "lower_bound": float(etf_try.get("lower", 0.0)),
                    "upper_bound": float(etf_try.get("upper", 0.0)),
                    "predicted_range": f"{float(etf_try.get('lower', 0.0)):.4f} ~ {float(etf_try.get('upper', 0.0)):.4f}",
                    "confidence": float(etf_try.get("confidence", 0.5)),
                    "remaining_minutes": int(etf_try.get("remaining_minutes", 0)),
                    "method": etf_try.get("method", "etf_multi_period"),
                    "timestamp": etf_try.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                }
                for k in ["iv_data_available", "iv_data_reason", "volume_factor", "garch_shadow", "data_quality", "ab_profile"]:
                    if k in etf_try:
                        payload[k] = etf_try.get(k)
                return {"success": True, "message": "Intraday range predicted", "data": payload, "source": "etf_multi_period"}

        def _to_pct(x: float) -> float:
            # x<=1 视为比例；否则视为百分比
            return float(x) * 100.0 if x <= 1.0 else float(x)

        def _get_intraday_bounds_pct(_cfg) -> tuple[float, float]:
            # P0/P2：统一使用同一套上下限约束，避免任何链路绕过输出收敛
            min_intraday_pct = 0.015
            max_intraday_pct = 0.04
            try:
                vol_cfg = (
                    _cfg.get("signal_params", {})
                    .get("intraday_monitor_510300", {})
                    .get("volatility", {})
                )
                min_intraday_pct = vol_cfg.get("min_intraday_pct", min_intraday_pct)
                max_intraday_pct = vol_cfg.get("max_intraday_pct", max_intraday_pct)
            except Exception:
                pass
            return _to_pct(min_intraday_pct), _to_pct(max_intraday_pct)

        def _clamp_range(
            _current_price: float,
            _range_pct: float,
            _cfg: Dict[str, Any],
        ) -> tuple[float, float, float, bool]:
            if not _current_price or _current_price <= 0:
                return 0.0, 0.0, float(_range_pct), False
            min_pct, max_pct = _get_intraday_bounds_pct(_cfg)
            max_pct = max(max_pct, min_pct)
            clamped = float(min(max(_range_pct, min_pct), max_pct))
            clamp_applied = abs(clamped - _range_pct) > 1e-9
            half = _current_price * clamped / 200.0
            upper = _current_price + half
            lower = max(0.0, _current_price - half)
            real_range_pct = (upper - lower) / _current_price * 100.0
            return upper, lower, real_range_pct, clamp_applied

        # 1) 获取当前价格（ETF 用插件实时；股票用统一现价接口；不用日线收盘价兜底）
        current_price: Optional[float] = None
        if asset_type == "etf":
            try:
                from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_realtime

                rt = tool_fetch_etf_realtime(etf_code=sym, mode="test")
                if isinstance(rt, dict) and rt.get("success"):
                    d = rt.get("data", {})
                    if isinstance(d, dict) and "current_price" in d:
                        current_price = float(d.get("current_price"))
                    elif isinstance(d, dict) and "etf_data" in d and d["etf_data"]:
                        current_price = float(d["etf_data"][0].get("current_price"))
            except Exception:
                current_price = None
        else:
            current_price = get_stock_current_price(sym)

        if current_price is None:
            return {
                "success": False,
                "message": (
                    f"无法确定 {sym} 的当前价（日内区间工具不使用日线收盘价兜底）。"
                    "请检查实时行情接口或稍后重试。"
                ),
                "data": {
                    "error_code": "INTRADAY_SPOT_PRICE_UNAVAILABLE",
                    "symbol": sym,
                    "asset_type": asset_type,
                },
            }

        remaining_minutes = int(get_remaining_trading_time(cfg))

        # 2) 仅分钟级预测；无分钟数据或计算无效则报错（不使用日线降级）
        used_source = "minute_multi_period"
        method = None
        upper = None
        lower = None
        conf = None
        range_pct = None
        minute_rng: Dict[str, Any] = {}
        minute_exc: Optional[str] = None

        try:
            if asset_type == "etf":
                etf_minute_30m, etf_minute_15m = fetch_etf_minute_data_with_fallback(
                    underlying=sym,
                    lookback_days=10,
                    max_retries=2,
                    retry_delay=1.0,
                )
            else:
                etf_minute_30m, etf_minute_15m = fetch_stock_minute_data_with_fallback(
                    symbol=sym,
                    lookback_days=10,
                    max_retries=2,
                    retry_delay=1.0,
                )
            if etf_minute_30m is None or getattr(etf_minute_30m, "empty", True):
                return {
                    "success": False,
                    "message": (
                        f"{sym} 日内区间预测需要分钟K线数据，当前无法获取有效分钟序列；"
                        "已按策略不使用日线降级，请检查数据源或交易时段。"
                    ),
                    "data": {
                        "error_code": "INTRADAY_MINUTE_DATA_UNAVAILABLE",
                        "symbol": sym,
                        "asset_type": asset_type,
                    },
                }

            etf_minute_15m = etf_minute_15m if etf_minute_15m is not None and not etf_minute_15m.empty else etf_minute_30m
            minute_rng = calculate_etf_volatility_range_multi_period(
                etf_minute_30m=etf_minute_30m,
                etf_minute_15m=etf_minute_15m,
                etf_current_price=float(current_price),
                remaining_minutes=remaining_minutes,
                underlying=sym,
                config=cfg,
                use_option_iv=False,
            )
            _upper = minute_rng.get("upper")
            _lower = minute_rng.get("lower")
            _conf = minute_rng.get("confidence")
            if _upper is not None and _lower is not None:
                upper = float(_upper)
                lower = float(_lower)
                conf = float(_conf) if _conf is not None else float(0.5)
                range_pct = float(minute_rng.get("range_pct", (upper - lower) / current_price * 100.0))
                method = minute_rng.get("method", "minute_multi_period")
        except Exception as ex:
            minute_exc = str(ex)
            logger.warning("分钟级日内区间计算异常: %s", ex, exc_info=True)

        if upper is None or lower is None or conf is None or method is None:
            return {
                "success": False,
                "message": (
                    f"{sym} 分钟级波动区间计算未产生有效上下界；未使用日线降级。"
                    f"{' 异常: ' + minute_exc if minute_exc else ''}"
                ),
                "data": {
                    "error_code": "INTRADAY_MINUTE_CALC_INVALID",
                    "symbol": sym,
                    "asset_type": asset_type,
                    "exception": minute_exc,
                },
            }

        # P2：如果分钟路径包含 IV 校准字段，把影响字段可观测化（日志 + 输出/落库的附加字段）
        iv_debug_fields: Dict[str, Any] = {}
        try:
            iv_debug_fields = {
                k: minute_rng.get(k)
                for k in [
                    "iv_adjusted",
                    "iv_data_available",
                    "iv_data_reason",
                    "iv_ratio",
                    "option_iv",
                    "hist_vol_used",
                    "iv_adjustment",
                    "iv_hv_fusion",
                    "iv_hv_scaling_factor",
                    "iv_hv_sigma_eff",
                    "iv_hv_volume_factor",
                    "volume_factor",
                    "garch_shadow",
                    "data_quality",
                ]
                if minute_rng.get(k) is not None
            }
            if iv_debug_fields:
                logger.info("IV校准影响字段: %s", iv_debug_fields)
        except Exception:
            iv_debug_fields = {}

        # P0/P2：统一 clamp（确保任何链路都不绕过输出收敛）
        upper, lower, range_pct, _clamp_applied = _clamp_range(float(current_price), float(range_pct), cfg)

        logger.info("日内区间预测完成: %s, lower=%.4f, upper=%.4f, conf=%.2f, method=%s", sym, lower, upper, conf, method)

        # P0：预测落库，用于后续 P1 统计（收盘后回填 actual_range）
        try:
            record_prediction(
                prediction_type="etf" if asset_type == "etf" else "stock",
                symbol=sym,
                prediction={
                    "upper": upper,
                    "lower": lower,
                    "current_price": float(current_price),
                    "method": str(method),
                    "confidence": conf,
                    "range_pct": range_pct,
                    **iv_debug_fields,
                },
                source="scheduled",
                config=cfg,
            )
        except Exception as e:
            # 记录失败不影响工作流产出
            logger.warning(f"记录日内区间预测失败: {e}")

        return {
            "success": True,
            "message": "Intraday range predicted",
            "data": {
                "symbol": sym,
                "current_price": float(current_price),
                "lower_bound": lower,
                "upper_bound": upper,
                "predicted_range": f"{lower:.4f} ~ {upper:.4f}",
                "confidence": conf,
                "remaining_minutes": remaining_minutes,
                "method": method,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **iv_debug_fields,
            },
            "source": used_source,
        }
    except Exception as e:
        return {"success": False, "message": f"Error predicting intraday range: {e}", "data": None}

