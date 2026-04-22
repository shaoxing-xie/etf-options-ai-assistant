#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    html = (root / "apps" / "chart_console" / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (root / "apps" / "chart_console" / "frontend" / "screening.js").read_text(encoding="utf-8")
    checks = {
        "quality_badge": 'id="researchQualityBadge"' in html,
        "timeline_anomaly_filter": 'id="researchTimelineOnlyAnomaly"' in html,
        "fallback_banner": 'id="researchFallbackBanner"' in html,
        "api_research_metrics": "/api/semantic/research_metrics" in js,
        "api_record_fallback": "/api/internal/record_fallback" in js,
        "factor_diag_section": 'id="researchFactorDiagTbody"' in html,
        "strategy_attr_section": 'id="researchAttribution"' in html,
        "api_factor_diagnostics": "/api/semantic/factor_diagnostics" in js,
        "api_strategy_attribution": "/api/semantic/strategy_attribution" in js,
    }
    ok = all(checks.values())
    print(json.dumps({"success": ok, "checks": checks}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
