# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and follows semantic versioning.

## [Unreleased]

### Added
- **OpenClaw ↔ strategy_engine**: `config/openclaw_strategy_engine.yaml` (routing + evolution), `Prompt_config.yaml` → `openclaw_strategy_engine_routing`, `agents/analysis_agent.yaml` lists **`tool_strategy_engine`** and adds **`strategy_fusion`** cron (**every 30 min** `*/30 9-15 * * 1-5`); optional weight persistence → `get_strategy_weights` reads `data/strategy_fusion_effective_weights.json` (override with `STRATEGY_FUSION_WEIGHTS_PATH`); workflow template `workflows/strategy_fusion_routine.yaml`; project docs updated (`README.md`, `docs/README.md`, `docs/openclaw/*`, `docs/architecture/strategy_engine_and_signal_fusion.md`, `docs/reference/工具参考手册.md`, etc.).
- **Strategy engine (experimental v1.0)**: `plugins/strategy_engine/` with `SignalCandidate` schema, YAML-driven fusion (v1/v1.1/v1.2), and **`tool_strategy_engine`**; docs in `docs/architecture/strategy_engine_and_signal_fusion.md`. Does not change `tool_generate_signals` behavior.
- Optional `journal_extra` on `tool_record_signal_effect` for fusion audit fields in trading journal.
- `CRON_JOBS_EXAMPLE.json` optional `strategy-fusion-example` job (disabled by default).
- Open-source release baseline documents (`SECURITY.md`, `CONTRIBUTING.md`, `.env.example` standardization).
- GitHub-first publishing guidance in deployment plan.
- Repository naming compatibility note added across release-facing docs (`README.md`, `README.en.md`, docs index/publish/contributing).

## [0.1.0] - 2026-03-21

### Added
- First public baseline for A-share/ETF trading assistant on OpenClaw (with optional options extensions).
- Core workflow coverage for data collection, analysis, risk checks, and notifications.
- Release notes:
  - `docs/publish/release-notes-v0.1.0.zh-CN.md`
  - `docs/publish/release-notes-v0.1.0.en.md`

### Notes
- Research and engineering use only; not investment advice.
