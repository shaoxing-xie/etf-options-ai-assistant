# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and follows semantic versioning.

## [Unreleased]

### Added
- **`tool_backtest_limit_up_pullback`**: optional `sector_keywords` (e.g. 军工 / 国防) to filter backtest trades by `board_name` substring; trades now include `sector`; ops doc §3.5.1 describes DingTalk-safe flow (tool-first, no spurious web search).

### Changed
- **OpenClaw 回测路由（A/B + cron 入口）**：`skills/ota-backtesting-integration-brief/SKILL.md` — **分支 A 默认单条 `exec`**，禁止先串 MCP 拉数+指标；文首 **速判表**、分支 A **成功后禁止再拉数核实**；仅 **分支 B** 深度对账走数据链。`workflows/backtesting_research_on_demand.yaml` 同步（**不确定默认 A**、成功后禁补链）。`config/snippets/openclaw_agents_ota_skills.json` 将 **`ota_backtesting_integration_brief` + `backtesting-trading-strategies` 排在 `ota_technical_indicators_brief` 之前**。`config/agents/cron_agents.yaml` 为 **`etf_cron_research_agent`** 补齐上述两 Skill（`requiredSkills` 全量替换模板，此前工作流入口可能读不到规程）。`docs/ops/回测使用指导-自动任务与日常交互.md` 文首补充 cron Agent 与 `render_agents_config.py`。
- **`docs/ops/回测使用指导-自动任务与日常交互.md`**：全文改为仅指导 `backtesting-trading-strategies` 脚本与 exec/运维；删除涨停回马枪工具（`tool_backtest_limit_up_*`）相关章节与提示词；原脚本实测并入 **§7**，`SKILL.md` 交叉引用更新为 §7；新增 **§5** 钉钉/OpenClaw 交互（通道约束、自然语言示例、`exec` 模板、回群结构与强约束话术）。
- **Backtesting skill (`skills/backtesting-trading-strategies`)**: CN six-digit symbols default to the repo `plugins/data_collection` ETF pipeline (aligned with `openclaw-data-china-stock`) instead of Yahoo; added `scripts/china_stock_loader.py`, `scripts/skill_settings.py` (YAML + `BACKTEST_SKILL_SETTINGS`, precedence CLI → env → `data.provider`), wired `data.cache_dir` / `reporting.output_dir` / `backtest.*` defaults from `config/settings.yaml`; `--data-source` / `--source` / optional `coingecko`; `scripts/run_backtest_trading_strategies.py` for single-command `exec`. Strategy-aware minimum bar check via `min_bars_for_strategy()`; `attrs['price_loader']` for audit logs.
- Removed deprecated, unregistered ETF rotation backtest implementation `plugins/backtest/etf_rotation_backtest.py` and cleaned stale documentation references to `tool_backtest_etf_rotation`, aligning docs with the active backtesting path (`backtesting-trading-strategies` + `backtesting_research_on_demand`).

## [0.2.0] - 2026-04-14

### Changed
- **分层配置（一次性切量）**：删除根目录 `config.yaml`；默认从 `config/environments/base.yaml` + `config/domains/*.yaml` + `config/environments/<profile>.yaml`（`ETF_OPTIONS_CONFIG_PROFILE` / `CONFIG_PROFILE`，默认 `prod`）+ 可选 `config/local.yaml` 合并加载（`src/config_loader.py`）。年度节假日来自 `config/reference/holidays_*.yaml`。`tick_client.get_best_tick` 默认走 `load_system_config`；`InternalAlertEngine` 默认走合并配置；`save_config` 默认写入 `config/environments/base.yaml`。
- **校验**：`src/config_validate.py` 与 `scripts/validate_config_cross.py`（重复合约 code、标的与 data_cache/etf_trading 对齐、次年节假日键提醒）。

### Added
- **Strategy engine & signal fusion (experimental)**:
  - `plugins/strategy_engine/` + `tool_strategy_engine`（聚合候选、融合输出、审计字段）
  - Fusion policy: `config/strategy_fusion.yaml`
  - OpenClaw routing/evolution: `config/openclaw_strategy_engine.yaml` + `workflows/strategy_fusion_routine.yaml`
- **Prediction quality loop**:
  - Quality gate: `prediction_quality` + `src/prediction_normalizer.py`
  - Close-to-close verification: `workflows/prediction_verification.yaml` + `scripts/verify_predictions.py`
  - Weekly monitoring: `scripts/prediction_metrics_weekly.py` + `prediction_monitoring`
- **Workflow & ops maturity**:
  - Expanded before-open / opening / after-close / inspection / research workflows under `workflows/`
  - Triage runbooks under `docs/ops/` and `docs/openclaw/` emphasizing single-call chaining and traceable artifacts
- **TradingView phase 2 (balanced 4-week baseline)**:
  - Frontend modularization: `apps/chart_console/frontend/app.js`, `api.js`, `charts.js`
  - Multi-chart sync + layer management: second linked price chart and `Vol/MACD/RSI/MA` toggles
  - API layered structure: `apps/chart_console/api/routes.py`, `services.py`, `serializers.py`
  - Backtest cost model: `fee_bps/slippage_bps` and metrics `total_cost/sharpe`
  - Workspace upgrades: history snapshots and template APIs (`/api/workspace_templates*`)
  - Production smoke scripts: `scripts/chart_console_phase2_smoke.py`, `scripts/check_indicator_consistency.py`
- **TradingView-style chart console (phase 1)**: Upgraded `apps/chart_console/app.py` with multi-timeframe controls, pane indicators (Volume/MACD/RSI), BOLL/MA overlays, drawing-object management, data-source status light, and workspace save/load/delete backed by `src/services/workspace_service.py` (`data/chart_console/workspaces.json`).
- **Independent frontend + API aggregator (route B baseline)**:
  - `apps/chart_console/frontend/index.html` (Lightweight Charts frontend)
  - `apps/chart_console/api/server.py` (`/api/ohlcv`, `/api/indicators`, `/api/backtest`, `/api/alerts/replay`, `/api/workspaces`)
  - `scripts/run_chart_console_pro.sh` (pro startup script)
- **Research backtest module**: `src/services/backtest_service.py` + enhanced `apps/chart_console/pages/backtest.py` for MA crossover backtest, strategy-vs-benchmark equity chart, and metrics (`total_return`, `max_drawdown`, `win_rate`, `trade_count`).
- **Alert replay page**: `apps/chart_console/pages/alert_replay.py` for event status distribution, filterable replay table, and timeline visualization from `data/alerts/internal_alert_events.jsonl`.
- **Documentation sync for phase-1 rollout**: updated maintenance/runbook docs and README links:
  - `docs/openclaw/Internal_Chart_Alert_内生类TradingView维护手册.md`
  - `docs/openclaw/Internal_Chart_Alert_Runbook_值班速查.md`
  - `README.md`
- **Configurable signal generation (options + ETF + A-share)**: Primary OpenClaw tool id **`tool_generate_option_trading_signals`** (alias **`tool_generate_signals`**), plus **`tool_generate_etf_trading_signals`** and **`tool_generate_stock_trading_signals`**. **`signal_generation`**（分层 YAML）在加载时经 `normalize_signal_generation_config` 合并；docs 与 Skills（`ota-signal-risk-inspection`, `ota-strategy-fusion-playbook`）已更新。工作流默认主期权工具 id。
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
  - `docs/publish/release-notes-v0.2.0.zh-CN.md`
  - `docs/publish/release-notes-v0.2.0.en.md`

### Notes
- Research and engineering use only; not investment advice.
