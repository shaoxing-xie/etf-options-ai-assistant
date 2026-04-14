# etf-options-ai-assistant (English Overview)

An OpenClaw-based assistant system for A-share/ETF trading that provides an end-to-end workflow for **data collection, analysis & signals, risk control, notifications, and research workflows**.

> Repository naming note: the repository name remains `etf-options-ai-assistant` for compatibility with existing scripts and deployment paths; the current product focus is A-share/ETF, with options as an optional extension.

## Why it matters now

In highly volatile markets, retail traders usually do not suffer from lack of information.  
They suffer from fragmented signals, emotional execution drift, and weak risk discipline.

This project is designed to convert "opinion-driven" decisions into a repeatable and auditable workflow.

## Who this is for

- Retail A-share/ETF traders who want more consistent intraday execution
- OpenClaw users who want an end-to-end market assistant workflow
- Developers looking for an extensible OpenClaw trading-assistant baseline

## Why OpenClaw

- Multi-agent collaboration for data, analysis, risk, and notifications
- Workflow scheduling for repeatable operations
- Observable runtime with logs and replayable context
- Extensible plugin ecosystem

> **Disclaimer**: This project is for strategy research and technical experiments only. **Nothing in this repository constitutes investment or trading advice.** Do not use it directly in live trading. You are solely responsible for all risks and consequences of any real-money trading.

## Emergency scenario (first 10 minutes after market open)

Goal: not to "predict price", but to enforce a disciplined execution path under stress.

1. Collect key A-share/ETF/index data
2. Generate a structured risk profile
3. Validate position and stop-loss rules
4. Push one consistent conclusion to channels

```text
Market shock -> Data -> Analysis -> Risk checks -> Notification -> Post-run trace
```

---

## Project Overview

### Core Capabilities

- **Multi-asset data collection**: Real-time / historical / intraday data for A-share stocks, indices, broad-based ETFs, and A50 index futures, with local caching and batched collection optimizations.
- **Trend & volatility analysis**: Pre-market / post-market / opening analysis, technical indicators, historical volatility and volatility forecasting, intraday range estimation.
- **Signals & strategy research**: Multiple signal-generation strategies, signal effect replay, strategy scoring and weight adjustment, forming a complete **Strategy Research Loop**.
- **Risk control & position management**: Position sizing suggestions, take-profit/stop-loss levels, tradability filters, and centralized risk checks (via `option_trader.py env/risk_check`).
- **OpenClaw integration & workflows**: Deep integration with OpenClaw, supporting multi-Agent collaboration, Cron-based scheduled workflows, Feishu notifications, and research / rotation / backtest workflows.
- **Ops & observability**: Unified logging, health checks, code maintenance tools, and collaboration with OpenClaw `ops` / `code_maintenance` agents.

### Value proposition

- Faster: minute-level structured outputs during market stress
- More consistent: one workflow across analysis, risk, and notifications
- More auditable: replayable evidence for each decision

### Tech Stack

- **Platform**: OpenClaw (Agents + Gateway + Cron workflows)
- **Language**: Python 3.8+ (core logic and tools)
- **Data sources**: AKShare, Tushare, Sina, etc.
- **Storage**: SQLite, Parquet, local JSON/CSV caches
- **Notifications**: Feishu (Feishu bots), with hooks for DingTalk / other channels later

---

## Quick Start

The steps below assume you are working in a WSL environment and have installed OpenClaw according to the official guide (version ≥ 2026.2.15).

### 1. Clone the repo and install dependencies

```bash
git clone https://github.com/shaoxing-xie/etf-options-ai-assistant.git
cd etf-options-ai-assistant

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment and parameters

- Copy and edit environment variables:

```bash
cp .env.example .env
# Fill in Tushare token, Feishu webhook, etc.
```

- Adjust parameters in layered config and `Prompt_config.yaml` if needed:
  - Anchor: `config/environments/base.yaml`
  - Domain defaults: `config/domains/*.yaml`
  - Environment overlay: `config/environments/<profile>.yaml` (via `ETF_OPTIONS_CONFIG_PROFILE` / `CONFIG_PROFILE`, default `prod`)
  - Local override: `config/local.yaml` (gitignored)
  - Trading calendar: `config/reference/holidays_*.yaml`

### 3. Install as an OpenClaw plugin

In WSL:

```bash
bash install_plugin.sh
```

This script will:

- Create the `option-trading-assistant` plugin directory under `~/.openclaw/extensions/`;
- Create a symlink pointing to this project;
- Install Python dependencies as needed;
- Register the plugin with OpenClaw (`index.ts` + `tool_runner.py`).

For detailed installation steps and Remote-WSL tips, see:

- `docs/getting-started/README.md`
- `docs/publish/README.md`
- `docs/archive/openclaw/README.md` (historical integration notes, reference only)

### 4. Run your first workflow (example)

After plugin installation, follow the 5-minute quickstart guide to validate:

- Read: `docs/overview/5分钟快速开始指南.md`
- Typical flow:
  - Run environment check scripts;
  - Install the plugin;
  - Run a post-market analysis or signal-generation workflow;
  - Check Feishu notifications / log outputs.

### 5. One-minute acceptance checklist

- `openclaw gateway status` shows `RPC probe: ok`
- At least one analysis workflow runs successfully
- At least one notification channel works

---

## Documentation Map

All detailed docs live under `docs/`. Recommended entry points:

- **Docs home**: `docs/README.md`
- **Getting Started**:  
  - `docs/getting-started/README.md`  
  - `docs/overview/5分钟快速开始指南.md`

- **User Guide**:  
  - Workflows & scheduling: `docs/openclaw/工作流参考手册.md`  
  - Signals & risk inspection: `docs/openclaw/信号与风控巡检工作流.md`  
  - Notifications & daily reports: see tool reference + related workflow docs  

- **OpenClaw Integration**:  
  - Release path: `docs/publish/README.md`  
  - Historical config/integration archive: `docs/archive/openclaw/README.md`

- **Tools & schema reference**:  
  - `docs/reference/工具参考手册.md`  
  - `docs/reference/工具参考手册-速查.md`  
  - `docs/reference/工具参考手册-场景.md`  
  - `docs/reference/工具参考手册-研究涨停回测.md`  
  - `docs/reference/错误码说明.md`  
  - `docs/reference/trading_journal_schema.md`  
  - `docs/reference/limit_up_pullback_default_params.md`

- **Architecture & development**:  
  - `docs/architecture/README.md`  
  - `docs/PROJECT_LAYOUT.md`  
  - `docs/architecture/架构与工具审查报告.md`  
  - `docs/architecture/strategy_engine_and_signal_fusion.md` — multi-source signal fusion (`tool_strategy_engine`), `config/strategy_fusion.yaml`, `config/openclaw_strategy_engine.yaml`, `plugins/strategy_engine/README.md`  
  - Scheduled **`strategy_fusion`** in `agents/analysis_agent.yaml`: **every 30 minutes** during `9:00–15:00` on trading days (`*/30 9-15 * * 1-5`); mirror in local `~/.openclaw/cron/jobs.json` if needed.

- **Ops & troubleshooting**:  
  - `docs/ops/常见问题库.md`  
  - `docs/ops/RISK_CONTROL_AND_ROLLBACK.md`  
  - `docs/ops/需要添加交易日判断跳过参数的工具清单.md`  
  - plus any Feishu / DingTalk troubleshooting docs in `docs/ops/`

- **Legacy / history**:  
  - `docs/legacy/` contains older design drafts, migration plans, and test reports for reference only.

---

## Directory Layout (Brief)

See `docs/PROJECT_LAYOUT.md` for full details. A short version:

```text
etf-options-ai-assistant/
├── README.md
├── README.en.md
├── LICENSE
├── config/environments/base.yaml            # Layered config anchor
├── config/domains/*.yaml                    # Domain defaults (merged)
├── config/environments/<profile>.yaml       # Environment overlays
├── config/reference/holidays_*.yaml         # Trading calendar files
├── Prompt_config.yaml
├── config/strategy_fusion.yaml              # Fusion thresholds & default weights
├── config/openclaw_strategy_engine.yaml     # OpenClaw routing / weight persistence (optional)
├── src/                 # Core business logic (data, analysis, signals, risk, etc.)
├── plugins/             # OpenClaw plugin layer (incl. plugins/strategy_engine fusion)
├── workflows/           # OpenClaw workflow definitions and generated artifacts
├── docs/                # Project docs (getting started, usage, integration, reference, arch, ops)
├── scripts/             # Install, diagnostics, utility scripts
├── tests/               # Test cases
└── .venv/               # Local Python virtual env
```

---

## Risk Warnings & Disclaimer

- This project is only a **reference implementation for quantitative research and system design**. All outputs (including but not limited to signals, analysis reports, and strategy suggestions) are **for research and educational purposes only**, and **do not constitute investment, legal, or tax advice**.
- Financial markets can be highly volatile and subject to “black swan” events. You bear all consequences (including but not limited to financial loss) of any actions or decisions made using this project.
- Before connecting to a real trading account or running any automated trading, thoroughly validate strategies and system stability in **non-live environments** (e.g. backtests or paper trading).

---

## License

This project is licensed under the [MIT License](LICENSE).  
When using or redistributing this code, please keep the original copyright and license.

---

## Public roadmap

- `v0.1.x`: open-source baseline stability (docs, templates, minimal CI)
- `v0.2.x`: strategy modularization and richer intraday risk templates
- `v1.0.0`: standardized production deployment and rollback process

---

## Screenshots / Demo (recommended for first public release)

> Suggested asset location: `docs/assets/`

At least two screenshots are recommended:

1. **Gateway and workflow health** (`openclaw gateway status` + key logs)
2. **Notification delivery sample** (Feishu/DingTalk structured output)

Placeholder markdown (replace with real files):

```markdown
![Gateway Health](docs/assets/gateway-health.png)
![Notification Sample](docs/assets/notification-sample.png)
```

Optional third screenshot:

3. **First-10-minutes scenario output** (data summary + risk check + final action)

