"""
日内区间预测工具（轻量版）。

该模块用于补齐工作流依赖：tool_predict_intraday_range。
实现采用 src.volatility_range_fallback 的日线降级方案，保证在多数环境可运行。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def tool_predict_intraday_range(
    symbol: str = "510300",
    underlying: Optional[str] = None,
    lookback_days: int = 60,
    **_: Any,
) -> Dict[str, Any]:
    """
    预测标的（ETF）当日剩余时间的价格区间。

    Args:
        symbol: ETF 代码（默认 510300）
        underlying: 兼容参数，优先于 symbol
        lookback_days: 用于获取日线窗口（默认 60）
    """
    sym = str(underlying or symbol or "510300")
    try:
        from src.config_loader import load_system_config
        from src.data_collector import fetch_etf_daily_em
        from src.data_collector import fetch_etf_minute_data_with_fallback
        from src.volatility_range import get_remaining_trading_time
        from src.volatility_range import calculate_etf_volatility_range_multi_period
        from src.volatility_range_fallback import calculate_etf_volatility_range_fallback
        from src.logger_config import get_module_logger
        from src.prediction_recorder import record_prediction

        logger = get_module_logger(__name__)
        cfg = load_system_config(use_cache=True)

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

        def _dynamic_confidence_from_move(_conf: float, _current_price: float, _daily_close: float) -> float:
            # P0：用“日内当前价 vs 日线最后收盘价”的偏离幅度降权，避免极端日置信度偏乐观
            if not _daily_close or _daily_close <= 0:
                return float(min(0.6, _conf))
            price_change_pct = (_current_price - _daily_close) / _daily_close * 100.0
            move_abs = abs(price_change_pct)
            move_factor = max(0.0, min(1.0, 1.0 - move_abs / 5.0))
            target_conf = 0.3 + 0.3 * move_factor
            # 不让置信度超过原预测太多，同时保证不会超过0.6
            return float(min(0.6, _conf, target_conf))

        # 1) 获取当前价格（优先用插件实时工具；失败则用日线最后收盘兜底）
        current_price: Optional[float] = None
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

        # 2) 获取日线数据（内部含缓存逻辑）
        now = datetime.now()
        end_ymd = now.strftime("%Y%m%d")
        start_ymd = (now - timedelta(days=max(int(lookback_days) * 2, 90))).strftime("%Y%m%d")
        daily_df = fetch_etf_daily_em(symbol=sym, period="daily", start_date=start_ymd, end_date=end_ymd)
        if daily_df is None or getattr(daily_df, "empty", True):
            return {"success": False, "message": f"Failed to fetch daily data for {sym}", "data": None}

        # 用于动态置信度：日线最后收盘价（如果 realtime 成功，偏离幅度就反映极端日）
        close_col = "收盘" if "收盘" in daily_df.columns else ("close" if "close" in daily_df.columns else None)
        daily_close = float(daily_df[close_col].iloc[-1]) if close_col else float("nan")

        if current_price is None:
            # 尝试用最后收盘价兜底
            if close_col:
                try:
                    current_price = float(daily_df[close_col].iloc[-1])
                except Exception:
                    current_price = None

        if current_price is None:
            return {"success": False, "message": f"Failed to determine current price for {sym}", "data": None}

        remaining_minutes = int(get_remaining_trading_time(cfg))

        # 3) P2：优先分钟级预测；失败则回退日线降级
        used_source = "fallback_daily"
        method = None
        upper = None
        lower = None
        conf = None
        range_pct = None

        try:
            etf_minute_30m, etf_minute_15m = fetch_etf_minute_data_with_fallback(
                underlying=sym,
                lookback_days=10,
                max_retries=2,
                retry_delay=1.0,
            )
            if etf_minute_30m is not None and not etf_minute_30m.empty:
                etf_minute_15m = etf_minute_15m if etf_minute_15m is not None and not etf_minute_15m.empty else etf_minute_30m
                minute_rng = calculate_etf_volatility_range_multi_period(
                    etf_minute_30m=etf_minute_30m,
                    etf_minute_15m=etf_minute_15m,
                    etf_current_price=float(current_price),
                    remaining_minutes=remaining_minutes,
                    underlying=sym,
                    config=cfg,
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
                    used_source = "minute_multi_period"
        except Exception:
            used_source = "fallback_daily"

        if upper is None or lower is None or conf is None or method is None:
            # 回退：日线降级
            rng = calculate_etf_volatility_range_fallback(
                daily_df,
                float(current_price),
                remaining_minutes,
                opening_strategy=None,
                previous_volatility_ranges=None,
                config=cfg,
            )
            upper = float(rng.get("upper", current_price * 1.02))
            lower = float(rng.get("lower", current_price * 0.98))
            conf = float(rng.get("confidence", 0.3))
            range_pct = float(rng.get("range_pct", (upper - lower) / current_price * 100.0 if current_price > 0 else 2.0))
            method = rng.get("method", "fallback_daily")

        # P2：如果分钟路径包含 IV 校准字段，把影响字段可观测化（日志 + 输出/落库的附加字段）
        iv_debug_fields: Dict[str, Any] = {}
        try:
            if used_source == "minute_multi_period":
                # minute_rng 作用域在 try 块内，这里用最小侵入方式从局部变量抓取
                iv_debug_fields = {
                    k: locals().get("minute_rng", {}).get(k)
                    for k in ["iv_adjusted", "iv_ratio", "option_iv", "hist_vol_used", "iv_adjustment"]
                    if locals().get("minute_rng", {}).get(k) is not None
                }
                if iv_debug_fields:
                    logger.info("IV校准影响字段: %s", iv_debug_fields)
        except Exception:
            iv_debug_fields = {}

        # P0/P2：统一动态置信度降权（避免极端日过度自信）
        # NaN daily_close 时自动退化为 min(0.6, conf)
        try:
            if str(daily_close) != "nan":
                conf = _dynamic_confidence_from_move(conf, float(current_price), float(daily_close))
        except Exception:
            conf = float(min(0.6, conf))

        # P0/P2：统一 clamp（确保任何链路都不绕过输出收敛）
        upper, lower, range_pct, _clamp_applied = _clamp_range(float(current_price), float(range_pct), cfg)

        logger.info("日内区间预测完成: %s, lower=%.4f, upper=%.4f, conf=%.2f, method=%s", sym, lower, upper, conf, method)

        # P0：预测落库，用于后续 P1 统计（收盘后回填 actual_range）
        try:
            record_prediction(
                prediction_type="etf",
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

