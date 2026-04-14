"""
组合风险快照：历史模拟 VaR、最大回撤、当前回撤、仓位相对阈值。

依赖：本地 ETF 日线缓存（tool_read_market_data / etf_daily）、config/portfolio_weights.json（可选）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_live_positions(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    尝试加载“真实持仓/账户快照”。

    约定（优先级）：
    - 显式 path
    - env: OPENCLAW_POSITIONS_JSON
    - 默认：~/.openclaw/workspaces/etf-options-ai-assistant/memory/positions.json
    """
    candidates: List[Path] = []
    if path:
        candidates.append(Path(path).expanduser())
    env_p = os.environ.get("OPENCLAW_POSITIONS_JSON", "").strip()
    if env_p:
        candidates.append(Path(env_p).expanduser())
    candidates.append(
        Path(os.path.expanduser("~/.openclaw/workspaces/etf-options-ai-assistant/memory/positions.json"))
    )
    for p in candidates:
        if not p.is_file():
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def _positions_to_weights(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    将持仓快照归一为 cfg 结构：weights/current_position_pct/cash_pct。

    支持常见形态：
    - {"positions":[{"symbol":"510300","market_value":12345,"asset_type":"etf"},...], "cash": 1000, "total_assets": 20000}
    - {"data":{"positions":[...]}, ...}
    - 直接 positions 列表
    """
    if not snapshot:
        return None
    blob: Any = snapshot
    if isinstance(blob, dict) and isinstance(blob.get("data"), dict):
        blob = blob["data"]
    positions: Any = None
    cash: Optional[float] = None
    total_assets: Optional[float] = None
    if isinstance(blob, dict):
        positions = blob.get("positions") or blob.get("holdings") or blob.get("items")
        cash = blob.get("cash") if blob.get("cash") is not None else blob.get("cash_available")
        total_assets = blob.get("total_assets") or blob.get("equity") or blob.get("net_asset")
    elif isinstance(blob, list):
        positions = blob

    if not isinstance(positions, list) or not positions:
        return None

    mv_by_sym: Dict[str, float] = {}
    total_mv = 0.0
    for it in positions:
        if not isinstance(it, dict):
            continue
        sym = (
            it.get("symbol")
            or it.get("code")
            or it.get("asset_code")
            or it.get("underlying")
        )
        if not sym:
            continue
        sym_s = str(sym).strip()
        if not sym_s:
            continue
        # 仅取 ETF/指数这类“可用日线缓存”的标的；否则跳过
        asset_type = (it.get("asset_type") or it.get("type") or "").strip().lower()
        if asset_type and asset_type not in ("etf", "index"):
            continue

        mv = it.get("market_value") or it.get("marketValue") or it.get("value")
        if mv is None:
            qty = it.get("quantity") or it.get("qty") or it.get("position") or 0
            px = it.get("price") or it.get("last") or it.get("current_price") or 0
            try:
                mv = float(qty) * float(px)
            except Exception:
                mv = 0.0
        try:
            mv_f = float(mv)
        except Exception:
            mv_f = 0.0
        if mv_f <= 0:
            continue
        mv_by_sym[sym_s] = mv_by_sym.get(sym_s, 0.0) + mv_f
        total_mv += mv_f

    if total_mv <= 0:
        return None

    weights = {k: v / total_mv for k, v in mv_by_sym.items()}

    cash_f: float = 0.0
    if cash is not None:
        try:
            cash_f = float(cash)
        except Exception:
            cash_f = 0.0
    if total_assets is None:
        total_assets = total_mv + cash_f
    try:
        total_assets_f = float(total_assets)
    except Exception:
        total_assets_f = total_mv + cash_f

    pos_pct = (total_mv / total_assets_f * 100.0) if total_assets_f > 0 else 100.0
    cash_pct = max(0.0, 100.0 - pos_pct)

    return {
        "schema_version": 1,
        "weights": weights,
        "current_position_pct": pos_pct,
        "cash_pct": cash_pct,
        "source": "live_positions",
    }


def _load_portfolio_config(path: Optional[str]) -> Dict[str, Any]:
    root = _project_root()
    candidates = []
    if path:
        candidates.append(Path(path).expanduser())
    candidates.append(root / "config" / "portfolio_weights.json")
    candidates.append(root / "config" / "portfolio_weights.example.json")
    for p in candidates:
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {
        "schema_version": 1,
        "weights": {"510300": 0.34, "510500": 0.33, "159915": 0.33},
        "current_position_pct": 50.0,
        "cash_pct": 50.0,
    }


def _load_thresholds(path: Optional[str]) -> Dict[str, float]:
    root = _project_root()
    p = Path(path).expanduser() if path else root / "config" / "risk_thresholds.yaml"
    if not p.is_file():
        p = root / "config" / "risk_thresholds.example.yaml"
    out = {
        "var_confidence": 0.95,
        "drawdown_warn_pct": 10.0,
        "drawdown_alert_pct": 15.0,
        "position_warn_pct": 80.0,
        "position_alert_pct": 90.0,
    }
    if not p.is_file():
        return out
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for k in out:
            if k in data and data[k] is not None:
                out[k] = float(data[k])
    except Exception:
        pass
    return out


def _date_key(rec: dict) -> Optional[str]:
    for k in ("date", "trade_date", "cal_date", "datetime", "日期", "交易日期"):
        v = rec.get(k)
        if v is None:
            continue
        s = str(v).replace("-", "")[:8]
        if len(s) >= 8 and s.isdigit():
            return s[:8]
    return None


def _close_px(rec: dict) -> Optional[float]:
    for k in ("close", "Close", "adj_close", "adjclose", "收盘", "收盘价"):
        v = rec.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _records_to_series(records: List[dict]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for r in records:
        d = _date_key(r)
        c = _close_px(r)
        if d and c is not None and c > 0:
            out[d] = c
    return out


def _aligned_returns(
    series_by_symbol: Dict[str, Dict[str, float]],
    weights: Dict[str, float],
) -> Tuple[Optional[np.ndarray], List[str]]:
    common: Optional[set] = None
    for sym, px in series_by_symbol.items():
        if sym not in weights or weights[sym] <= 0:
            continue
        dates = set(px.keys())
        common = dates if common is None else common & dates
    if not common:
        return None, []
    ordered = sorted(common)
    rets: List[float] = []
    syms = [s for s in weights if weights[s] > 0 and s in series_by_symbol]
    for i in range(1, len(ordered)):
        d0, d1 = ordered[i - 1], ordered[i]
        daily: List[float] = []
        ok = True
        for s in syms:
            p0 = series_by_symbol[s].get(d0)
            p1 = series_by_symbol[s].get(d1)
            if not p0 or not p1 or p0 <= 0:
                ok = False
                break
            daily.append(p1 / p0 - 1.0)
        if not ok or len(daily) != len(syms):
            continue
        w = np.array([weights[s] for s in syms], dtype=float)
        w = w / w.sum()
        pr = float(np.dot(w, np.array(daily, dtype=float)))
        rets.append(pr)
    if len(rets) < 5:
        return None, syms
    return np.array(rets, dtype=float), syms


def tool_portfolio_risk_snapshot(
    lookback_days: int = 120,
    portfolio_config_path: Optional[str] = None,
    positions_path: Optional[str] = None,
    risk_thresholds_path: Optional[str] = None,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """
    读取组合权重与 ETF 日线缓存，估算历史模拟 VaR、最大/当前回撤、仓位标志。
    """
    try:
        cfg = None
        live = _load_live_positions(positions_path)
        if isinstance(live, (dict, list)):
            live_cfg = _positions_to_weights(live if isinstance(live, dict) else {"positions": live})
            if live_cfg:
                cfg = live_cfg
        if cfg is None:
            cfg = _load_portfolio_config(portfolio_config_path)
        thr = _load_thresholds(risk_thresholds_path)
        weights: Dict[str, float] = {str(k): float(v) for k, v in (cfg.get("weights") or {}).items()}
        if not weights:
            return {"success": False, "message": "weights 为空", "data": None}
        wsum = sum(weights.values())
        if wsum <= 0:
            return {"success": False, "message": "权重和无效", "data": None}
        weights = {k: v / wsum for k, v in weights.items()}

        # 日线缓存通常只到上一交易日；盘中用“今天”会造成 cache miss
        end = datetime.now() - timedelta(days=1)
        start = end - timedelta(days=max(lookback_days, 30) + 45)
        start_date = start.strftime("%Y%m%d")
        end_date = end.strftime("%Y%m%d")

        series_by_symbol: Dict[str, Dict[str, float]] = {}
        missing_symbols: List[Dict[str, Any]] = []
        for sym in weights:
            if weights[sym] <= 0:
                continue
            df = None
            try:
                # 优先走 data_collector：允许缓存部分覆盖（不要求 start_date~end_date 全覆盖）
                from src.data_collector import fetch_etf_daily_em  # type: ignore

                df = fetch_etf_daily_em(symbol=sym, start_date=start_date, end_date=end_date)  # type: ignore
            except Exception:
                df = None

            recs: List[dict] = []
            if df is not None:
                try:
                    import pandas as pd  # type: ignore

                    if isinstance(df, pd.DataFrame) and not df.empty:
                        # 标准化列名到 records（保留中文列；_records_to_series 会自适配 close/收盘）
                        recs = df.to_dict(orient="records")  # type: ignore[assignment]
                except Exception:
                    recs = []

            if not recs:
                # 最后尝试：读缓存工具（可能返回 records 或 partial）
                from merged.read_market_data import tool_read_market_data

                raw = tool_read_market_data(
                    data_type="etf_daily",
                    symbol=sym,
                    start_date=start_date,
                    end_date=end_date,
                )
                recs = (raw.get("data") or {}).get("records") or []
                if not recs:
                    missing_symbols.append(
                        {"symbol": sym, "reason": raw.get("message", "cache miss"), "raw": raw}
                    )
                    continue

            series_by_symbol[sym] = _records_to_series(recs)
            if len(series_by_symbol[sym]) < 5:
                missing_symbols.append({"symbol": sym, "reason": "有效日线不足（缓存条数过少）"})
                series_by_symbol.pop(sym, None)
                continue

        if not series_by_symbol:
            return {
                "success": False,
                "message": "无可用日线数据（无法计算组合风险）",
                "data": {"missing_symbols": missing_symbols},
            }

        rets, syms_used = _aligned_returns(series_by_symbol, weights)
        if rets is None or len(rets) < 3:
            return {"success": False, "message": "无法对齐多标的收益序列", "data": None}

        alpha = 1.0 - confidence
        var_pct = float(-np.percentile(rets, alpha * 100)) * 100.0

        nav = np.cumprod(1.0 + rets)
        peak = np.maximum.accumulate(nav)
        dd = (nav - peak) / peak
        max_dd_pct = float(dd.min()) * 100.0
        current_dd_pct = float(dd[-1]) * 100.0

        pos_pct = float(cfg.get("current_position_pct") or 0.0)
        pos_flag = "ok"
        if pos_pct >= thr["position_alert_pct"]:
            pos_flag = "alert"
        elif pos_pct >= thr["position_warn_pct"]:
            pos_flag = "warning"

        dd_flag = "ok"
        if current_dd_pct <= -thr["drawdown_alert_pct"]:
            dd_flag = "alert"
        elif current_dd_pct <= -thr["drawdown_warn_pct"]:
            dd_flag = "warning"

        data = {
            "symbols_used": syms_used,
            "missing_symbols": missing_symbols,
            "lookback_trading_days": len(rets),
            "confidence": confidence,
            "var_historical_pct": round(var_pct, 4),
            "max_drawdown_pct": round(max_dd_pct, 4),
            "current_drawdown_pct": round(current_dd_pct, 4),
            "current_position_pct": round(pos_pct, 2),
            "cash_pct": round(float(cfg.get("cash_pct") or max(0.0, 100.0 - pos_pct)), 2),
            "position_risk_flag": pos_flag,
            "drawdown_risk_flag": dd_flag,
            "thresholds": thr,
            "portfolio_source": cfg.get("source") or ("config_file" if portfolio_config_path else "default_weights"),
        }
        return {"success": True, "message": "portfolio risk snapshot", "data": data}
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}

