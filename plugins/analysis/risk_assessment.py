"""
风险评估
融合 Coze 插件 risk_assessment.py；支持 ETF / 指数 / A 股，缓存优先并无缓存时拉取日线。
OpenClaw 插件工具
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# 项目根（供插件独立加载）
_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

try:
    from plugins.data_access.read_cache_data import read_cache_data
except ImportError:
    read_cache_data = None


def _risk_cfg() -> Dict[str, Any]:
    try:
        from src.config_loader import load_system_config

        raw = load_system_config()
        return dict(raw.get("risk_assessment") or {})
    except Exception:
        return {}


def _normalize_symbol(symbol: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if symbol is None or not str(symbol).strip():
        return None, "symbol 为空"
    s = str(symbol).strip()
    u = s.upper().replace(" ", "")
    if "." in u:
        left, _, right = u.partition(".")
        if right in ("SH", "SZ") and left.isdigit() and len(left) == 6:
            return left, None
        if left in ("SH", "SZ") and right.isdigit() and len(right) == 6:
            return right, None
    low = s.lower()
    if (low.startswith("sh") or low.startswith("sz")) and len(low) >= 8:
        digits = low[2:8]
        if digits.isdigit():
            return digits, None
    if len(s) == 6 and s.isdigit():
        return s, None
    return None, f"无效标的代码: {symbol}，需 6 位数字（或 sh600000 / 600000.SH 形式）"


def _effective_asset_type(asset_type: Optional[str], rcfg: Dict[str, Any]) -> str:
    at = (asset_type or rcfg.get("default_asset_type") or "auto")
    return str(at).strip().lower()


def _effective_lookback(lookback_trading_days: Optional[int], rcfg: Dict[str, Any]) -> int:
    if lookback_trading_days is not None:
        return max(2, int(lookback_trading_days))
    return max(2, int(rcfg.get("default_lookback_trading_days", 60)))


def _min_bar_rows(lookback: int) -> int:
    return lookback + 2


def _load_daily_for_risk(
    symbol: str,
    asset_type: str,
    start_ymd: str,
    end_ymd: str,
    lookback: int,
) -> Tuple[Any, str, Optional[str]]:
    """
    返回 (df, price_data_source, error_message)。
    price_data_source: cache | network | cache_then_network
    """
    from plugins.analysis.underlying_historical_snapshot import (
        _fetch_daily_em_or_stock,
        _close_column,
        _normalize_daily_df,
    )

    min_rows = _min_bar_rows(lookback)
    at = asset_type.strip().lower()

    if at == "auto":
        df, err = _fetch_daily_em_or_stock(symbol, "auto", start_ymd, end_ymd)
        if err or df is None or getattr(df, "empty", True):
            return None, "network", err or "no_daily_data"
        df = _normalize_daily_df(df)
        return df, "network", None

    tried_cache = False

    if at == "etf" and read_cache_data:
        tried_cache = True
        res = read_cache_data(
            data_type="etf_daily",
            symbol=symbol,
            start_date=start_ymd,
            end_date=end_ymd,
            return_df=True,
            skip_online_refill=True,
        )
        df0 = res.get("df") if isinstance(res, dict) else None
        if df0 is not None and not getattr(df0, "empty", True):
            df0 = _normalize_daily_df(df0)
            cc = _close_column(df0)
            if cc and len(df0) >= min_rows:
                return df0, "cache", None

    if at == "index" and read_cache_data:
        tried_cache = True
        res = read_cache_data(
            data_type="index_daily",
            symbol=symbol,
            start_date=start_ymd,
            end_date=end_ymd,
            return_df=True,
            skip_online_refill=True,
        )
        df0 = res.get("df") if isinstance(res, dict) else None
        if df0 is not None and not getattr(df0, "empty", True):
            df0 = _normalize_daily_df(df0)
            cc = _close_column(df0)
            if cc and len(df0) >= min_rows:
                return df0, "cache", None

    if at == "stock":
        try:
            from src import data_cache

            df0, missing = data_cache.get_cached_stock_daily(symbol, start_ymd, end_ymd, config=None)
            if df0 is not None and not getattr(df0, "empty", True) and not missing:
                tried_cache = True
                df0 = _normalize_daily_df(df0)
                cc = _close_column(df0)
                if cc and len(df0) >= min_rows:
                    return df0, "cache", None
        except Exception:
            pass

    df, err = _fetch_daily_em_or_stock(symbol, at, start_ymd, end_ymd)
    if err or df is None or getattr(df, "empty", True):
        return None, "network", err or "no_daily_data_after_fetch"

    df = _normalize_daily_df(df)
    src = "cache_then_network" if tried_cache else "network"
    return df, src, None


def assess_risk(
    symbol: str = "510300",
    position_size: float = 10000,
    entry_price: float = 4.0,
    stop_loss: Optional[float] = None,
    account_value: float = 100000,
    asset_type: Optional[str] = None,
    lookback_trading_days: Optional[int] = None,
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    风险评估：ETF / 指数 / A 股；波动率与 historical_volatility / snapshot 同口径（realized_vol_windows，%%）。

    Args:
        symbol: 标的 6 位代码或 sh/sz/后缀形式
        asset_type: auto | stock | etf | index；缺省读 config risk_assessment.default_asset_type
        lookback_trading_days: 波动率窗口（交易日）；缺省读 config
        api_base_url / api_key: 保留兼容，未使用
    """
    del api_base_url, api_key  # 保留签名兼容

    try:
        rcfg = _risk_cfg()
        sym_clean, sym_err = _normalize_symbol(symbol)
        if sym_err:
            return {"success": False, "message": sym_err, "data": None}

        at_eff = _effective_asset_type(asset_type, rcfg)
        if at_eff not in ("auto", "stock", "etf", "index"):
            return {
                "success": False,
                "message": f"asset_type 无效: {at_eff}，应为 auto|stock|etf|index",
                "data": None,
            }

        lookback = _effective_lookback(lookback_trading_days, rcfg)
        stop_mult = float(rcfg.get("stop_loss_multiplier", 1.5))
        high_vol_pct = float(rcfg.get("high_volatility_pct", 30.0))
        pos_warn = float(rcfg.get("position_ratio_warn_pct", 30.0)) / 100.0
        risk_high = float(rcfg.get("risk_ratio_high_threshold", 0.1))
        risk_med = float(rcfg.get("risk_ratio_medium_threshold", 0.05))
        vol_model = str(rcfg.get("volatility_model", "realized_vol_windows"))

        kelly_block = rcfg.get("kelly") if isinstance(rcfg.get("kelly"), dict) else {}
        win_rate = float(kelly_block.get("default_win_rate", rcfg.get("kelly_default_win_rate", 0.55)))
        avg_win = float(kelly_block.get("default_avg_win", rcfg.get("kelly_default_avg_win", 0.02)))
        max_kelly = float(kelly_block.get("max_kelly_ratio", rcfg.get("kelly_max_ratio", 0.25)))

        try:
            import pytz

            tz_shanghai = pytz.timezone("Asia/Shanghai")
            now = datetime.now(tz_shanghai)
        except Exception:
            now = datetime.now()
        end_ymd = now.strftime("%Y%m%d")
        start_ymd = (now - timedelta(days=max(lookback * 3, 180))).strftime("%Y%m%d")

        from plugins.analysis.underlying_historical_snapshot import _close_column
        from src.realized_vol_panel import realized_vol_windows

        df, price_src, load_err = _load_daily_for_risk(sym_clean, at_eff, start_ymd, end_ymd, lookback)
        if df is None or load_err:
            return {
                "success": False,
                "message": f"无法获取日线数据（{load_err or 'unknown'}）",
                "data": {"symbol": sym_clean, "asset_type": at_eff, "price_data_source": price_src},
            }

        close_col = _close_column(df)
        if not close_col:
            return {
                "success": False,
                "message": "日线数据缺少收盘列（收盘/close）",
                "data": {"symbol": sym_clean, "asset_type": at_eff, "price_data_source": price_src},
            }

        hv_map = realized_vol_windows(df, [lookback], close_col=close_col, data_period="day")
        hv_pct = hv_map.get(str(lookback))
        if hv_pct is None or (isinstance(hv_pct, float) and hv_pct != hv_pct):  # NaN
            hv_pct = 0.0
        sigma = float(hv_pct) / 100.0

        position_value = position_size * entry_price
        position_ratio = position_value / account_value if account_value > 0 else 0

        if stop_loss is None:
            if sigma > 0 and entry_price > 0:
                stop_loss = entry_price * (1.0 - sigma * stop_mult)
            else:
                stop_loss = entry_price * 0.97

        risk_amount = abs(entry_price - stop_loss) * position_size
        risk_ratio = risk_amount / account_value if account_value > 0 else 0

        avg_loss = abs((entry_price - stop_loss) / entry_price) if entry_price > 0 else 0.0
        kelly_ratio = (win_rate * avg_win - (1.0 - win_rate) * avg_loss) / avg_win if avg_win > 0 else 0.0
        kelly_ratio = max(0.0, min(kelly_ratio, max_kelly))

        if risk_ratio > risk_high:
            risk_level = "high"
        elif risk_ratio > risk_med:
            risk_level = "medium"
        else:
            risk_level = "low"

        recommendations: List[str] = []
        if position_ratio > pos_warn:
            recommendations.append("仓位比例较高，建议降低仓位")
        if risk_ratio > risk_high:
            recommendations.append("风险比例过高，建议设置更严格的止损")
        if float(hv_pct) > high_vol_pct:
            recommendations.append("波动率较高，建议谨慎操作")

        return {
            "success": True,
            "message": "Successfully assessed risk",
            "data": {
                "symbol": sym_clean,
                "asset_type": at_eff,
                "price_data_source": price_src,
                "lookback_trading_days": lookback,
                "volatility_model": vol_model,
                "position_size": position_size,
                "entry_price": round(entry_price, 4),
                "stop_loss": round(float(stop_loss), 4),
                "position_value": round(position_value, 2),
                "position_ratio": round(position_ratio * 100, 2),
                "risk_amount": round(risk_amount, 2),
                "risk_ratio": round(risk_ratio * 100, 2),
                "volatility": round(float(hv_pct), 2),
                "risk_level": risk_level,
                "kelly_optimal_position": round(kelly_ratio * 100, 2),
                "recommendations": recommendations,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}", "data": None}


def tool_assess_risk(
    symbol: str = "510300",
    position_size: float = 10000,
    entry_price: float = 4.0,
    stop_loss: Optional[float] = None,
    account_value: float = 100000,
    asset_type: Optional[str] = None,
    lookback_trading_days: Optional[int] = None,
) -> Dict[str, Any]:
    """OpenClaw 工具：风险评估"""
    return assess_risk(
        symbol=symbol,
        position_size=position_size,
        entry_price=entry_price,
        stop_loss=stop_loss,
        account_value=account_value,
        asset_type=asset_type,
        lookback_trading_days=lookback_trading_days,
    )
