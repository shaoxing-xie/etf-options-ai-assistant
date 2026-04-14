# v0.2.0 Release Notes (English)

Release date: 2026-04-14  
Tag: `v0.2.0`

## Scope

`v0.2.0` is a **milestone enhancement release** on top of the `v0.1.0` baseline, focusing on:
configuration institutionalization, strategy modularization & fusion, prediction-quality hardening, and workflow/ops maturity.

This project remains for research and engineering practice only, not investment advice.

## Highlights

- **Institutionalized config architecture**: configuration is now loaded as a merged view from `config/environments/*` + `config/domains/*` + `config/reference/holidays_*.yaml`, with cross-validation scripts and CI gates.
- **Strategy engine & multi-signal fusion (experimental)**: introduced `tool_strategy_engine` and YAML-driven fusion policies, with audit-friendly outputs and scheduling hooks.
- **Prediction-quality loop**: normalization, quality gate, close-to-close verification, and weekly monitoring to reduce drift and bad data.
- **Workflow & ops expansion**: a cohesive set of before-open / opening / after-close / inspection / research / evolution workflows and runbooks, emphasizing “single-call” tool chaining and traceable artifacts.
- **Chart Console (TradingView-style)**: expanded research/backtest console with multi-chart views, indicator layers, and workspace persistence.

## Breaking changes

- **Removed repo-root `config.yaml`**: runtime must use the merged config view via `src/config_loader.py -> load_system_config()`. Docs referencing the old root file should be updated to “merged config” and point to the corresponding domain file.

## Migration notes

- Config entrypoints:\n
  - Default anchor: `config/environments/base.yaml` (empty anchor file)\n
  - Domain defaults: `config/domains/*.yaml`\n
  - Environment overlay: `config/environments/<profile>.yaml` (`ETF_OPTIONS_CONFIG_PROFILE`/`CONFIG_PROFILE`, default `prod`)\n
  - Local override: `config/local.yaml` (gitignored)\n
  - Trading calendar: `config/reference/holidays_*.yaml` loaded via `system.trading_hours.calendar_source=files`\n

- Validation commands:\n
  - `python3 scripts/validate_config_surface.py`\n
  - `python3 scripts/check_universe_ssot.py`\n
  - `python3 scripts/validate_config_cross.py`\n

## Notes

- `plugins/data_collection` may be a symlink to an OpenClaw extension (e.g., `openclaw-data-china-stock`) depending on deployment. This repo’s docs should clearly state the boundary between the main repo and external extensions.
