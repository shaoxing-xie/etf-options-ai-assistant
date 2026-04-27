from __future__ import annotations

from apps.chart_console.api.routes import CHART_CONSOLE_ROUTES_TAG, ApiRoutes


class _Svc:
    def get_semantic_research_metrics(self, trade_date: str, window: int):
        return {"success": True, "data": {"trade_date": trade_date, "window": window}}

    def get_semantic_research_diagnostics(self, trade_date: str, window: int):
        return {"success": True, "data": {"trade_date": trade_date, "window": window}}

    def get_semantic_factor_diagnostics(self, trade_date: str, period: str):
        return {"success": True, "data": {"trade_date": trade_date, "period": period}}

    def get_semantic_strategy_attribution(self, trade_date: str):
        return {"success": True, "data": {"trade_date": trade_date}}

    def get_semantic_orchestration_timeline(self, trade_date: str):
        return {"success": True, "data": {"trade_date": trade_date, "events": []}}

    def get_semantic_task_dependency_health(self, trade_date: str):
        return {"success": True, "data": {"trade_date": trade_date, "health_metrics": {}}}

    def record_fallback_event(self, primary_url: str, fallback_url: str, reason: str):
        return {"success": True, "data": {"primary_url": primary_url, "fallback_url": fallback_url, "reason": reason}}


def test_routes_semantic_analysis_endpoints() -> None:
    routes = ApiRoutes(_Svc())
    payload, code, _ = routes.handle_get("/api/semantic/research_metrics", {"trade_date": ["2026-04-22"], "window": ["5"]})
    assert code == 200
    assert payload["success"] is True
    assert payload["data"]["window"] == 5

    payload, code, _ = routes.handle_get("/api/semantic/research_diagnostics", {"trade_date": ["2026-04-22"], "window": ["3"]})
    assert code == 200
    assert payload["data"]["window"] == 3

    payload, code, _ = routes.handle_get("/api/semantic/factor_diagnostics", {"trade_date": ["2026-04-22"], "period": ["week"]})
    assert code == 200
    assert payload["data"]["period"] == "week"

    payload, code, _ = routes.handle_get("/api/semantic/strategy_attribution", {"trade_date": ["2026-04-22"]})
    assert code == 200
    assert payload["data"]["trade_date"] == "2026-04-22"

    payload, code, _ = routes.handle_get("/api/semantic/orchestration_timeline", {"trade_date": ["2026-04-22"]})
    assert code == 200
    assert payload["data"]["trade_date"] == "2026-04-22"

    payload, code, _ = routes.handle_get("/api/semantic/task_dependency_health", {"trade_date": ["2026-04-22"]})
    assert code == 200
    assert payload["data"]["trade_date"] == "2026-04-22"


def test_health_includes_routes_tag() -> None:
    routes = ApiRoutes(_Svc())
    out = routes.handle_get("/api/health", {})
    assert len(out) == 2
    payload, code = out
    assert code == 200
    assert payload.get("success") is True
    assert payload.get("data", {}).get("routes_tag") == CHART_CONSOLE_ROUTES_TAG


def test_routes_record_fallback() -> None:
    routes = ApiRoutes(_Svc())
    payload, code = routes.handle_post(
        "/api/internal/record_fallback",
        {"primary_url": "/api/a", "fallback_url": "/api/b", "reason": "test"},
    )
    assert code == 200
    assert payload["success"] is True
