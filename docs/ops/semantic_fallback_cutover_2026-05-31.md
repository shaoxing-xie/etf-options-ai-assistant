# Semantic Fallback Cutover Plan (2026-05-31)

## Goal
- Decommission legacy non-semantic read paths for Chart Console research views.
- Keep semantic APIs as the only production read source.

## Timeline
- T0 to T+2 weeks:
  - Keep fallback enabled.
  - Show explicit UI fallback banner.
  - Record each fallback via `/api/internal/record_fallback`.
- T+2 to T+4 weeks:
  - Default fallback disabled behind feature flag.
  - Enable fallback only for break-glass incidents.
- Deadline (2026-05-31):
  - Remove old fallback route usage in research views.
  - Keep only semantic endpoints for dashboard/timeline/screening/diagnostics.

## Exit Criteria
- No fallback events for 7 consecutive days in `data/meta/evidence/fallback_events.jsonl`.
- Smoke and regression tests all green for:
  - `/api/semantic/research_metrics`
  - `/api/semantic/research_diagnostics`
  - `/api/semantic/factor_diagnostics`
  - `/api/semantic/strategy_attribution`
