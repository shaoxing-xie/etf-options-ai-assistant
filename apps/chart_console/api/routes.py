from __future__ import annotations

from urllib.parse import parse_qs

import pandas as pd

from .services import ApiServices


class ApiRoutes:
    def __init__(self, services: ApiServices) -> None:
        self.svc = services

    def handle_get(self, path: str, query: dict[str, list[str]]):
        if path == "/api/health":
            return {"success": True, "message": "ok"}, 200
        if path == "/api/alerts/config":
            return self.svc.get_alerts_config_text(), 200
        if path == "/api/config/market_data":
            return self.svc.get_market_data_config_text(), 200
        if path == "/api/config/analytics":
            return self.svc.get_analytics_config_text(), 200
        if path == "/api/ohlcv":
            symbol = (query.get("symbol") or ["510300"])[0]
            lookback_days = int((query.get("lookback_days") or ["180"])[0])
            resp = self.svc.get_ohlcv(symbol=symbol, lookback_days=lookback_days)
            df = resp.get("data")
            rows = df.to_dict("records") if df is not None else []
            return {
                "success": bool(resp.get("success")),
                "message": resp.get("message", ""),
                "data": rows,
                "cache_status": resp.get("cache_status", {}),
            }, 200
        if path == "/api/indicators":
            symbol = (query.get("symbol") or ["510300"])[0]
            lookback_days = int((query.get("lookback_days") or ["180"])[0])
            timeframe_raw = (query.get("timeframe_minutes") or ["30"])[0]
            timeframe = None if timeframe_raw == "None" else int(timeframe_raw)
            ma = (query.get("ma_periods") or ["5,10,20,60"])[0]
            ma_periods = [int(x.strip()) for x in ma.split(",") if x.strip()]
            resp = self.svc.get_indicators(
                symbol=symbol,
                lookback_days=lookback_days,
                timeframe_minutes=timeframe,
                ma_periods=ma_periods,
            )
            if not resp.get("success"):
                fallback = self.svc.get_ohlcv(symbol=symbol, lookback_days=lookback_days)
                rows = []
                if fallback.get("success"):
                    df = fallback.get("data")
                    if df is not None:
                        rows = df.to_dict("records")
                close = pd.to_numeric(pd.DataFrame(rows).get("close", pd.Series(dtype=float)), errors="coerce").ffill()
                out = close.rolling(14, min_periods=1).mean().fillna(0.0).tolist()
                resp = {
                    "success": True,
                    "message": f"fallback indicators: {resp.get('message', 'indicator failed')}",
                    "data": {"indicators": {"rsi": {"values": out}}},
                }
            return resp, 200
        if path == "/api/backtest":
            symbol = (query.get("symbol") or ["510300"])[0]
            lookback_days = int((query.get("lookback_days") or ["240"])[0])
            fast_ma = int((query.get("fast_ma") or ["10"])[0])
            slow_ma = int((query.get("slow_ma") or ["30"])[0])
            fee_bps = float((query.get("fee_bps") or ["3"])[0])
            slippage_bps = float((query.get("slippage_bps") or ["2"])[0])
            resp = self.svc.get_backtest(
                symbol=symbol,
                lookback_days=lookback_days,
                fast_ma=fast_ma,
                slow_ma=slow_ma,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            if resp.get("success"):
                resp["data"]["series"] = resp["data"]["series"].to_dict("records")
            return resp, 200
        if path == "/api/alerts/replay":
            return self.svc.get_alert_replay(), 200
        if path == "/api/workspaces":
            return {"success": True, "data": self.svc.workspace.list_workspaces()}, 200
        if path == "/api/workspace_templates":
            return {"success": True, "data": self.svc.workspace.list_templates()}, 200
        if path == "/api/screening/summary":
            return self.svc.get_screening_summary(), 200
        if path == "/api/screening/history":
            return self.svc.get_screening_history(), 200
        if path == "/api/screening/by-date":
            date_key = (query.get("date") or [""])[0]
            payload, code = self.svc.get_screening_by_date(str(date_key))
            return payload, code
        return {"success": False, "message": "not found"}, 404

    def handle_post(self, path: str, body: dict):
        if path == "/api/alerts/config/save":
            text = body.get("text")
            if not isinstance(text, str):
                return {"success": False, "message": "missing text"}, 400
            resp = self.svc.save_alerts_config_text(text)
            return resp, 200 if resp.get("success") else 400
        if path == "/api/config/market_data/save":
            text = body.get("text")
            if not isinstance(text, str):
                return {"success": False, "message": "missing text"}, 400
            resp = self.svc.save_market_data_config_text(text)
            return resp, 200 if resp.get("success") else 400
        if path == "/api/config/analytics/save":
            text = body.get("text")
            if not isinstance(text, str):
                return {"success": False, "message": "missing text"}, 400
            resp = self.svc.save_analytics_config_text(text)
            return resp, 200 if resp.get("success") else 400
        if path == "/api/workspaces/save":
            name = str(body.get("name", "")).strip()
            state = body.get("state")
            if not isinstance(state, dict):
                return {"success": False, "message": "state must be object"}, 400
            saved = self.svc.workspace.save_workspace(name, state)
            return {"success": True, "data": saved}, 200
        if path == "/api/workspaces/delete":
            name = str(body.get("name", "")).strip()
            return {"success": self.svc.workspace.delete_workspace(name)}, 200
        if path == "/api/workspace_templates/save":
            name = str(body.get("name", "")).strip()
            template = body.get("template")
            if not isinstance(template, dict):
                return {"success": False, "message": "template must be object"}, 400
            saved = self.svc.workspace.save_template(name, template)
            return {"success": True, "data": saved}, 200
        return {"success": False, "message": "not found"}, 404
