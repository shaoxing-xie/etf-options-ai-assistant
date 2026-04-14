---
name: etf-options-merged-copilot
description: >-
  Guides use of merged facade tools (enum routing to analysis/data_collection) and
  trading_copilot orchestration in etf-options-ai-assistant. Use when editing or
  invoking plugins/merged, plugins/copilot, tool_runner registrations, OpenClaw
  tool aliases, or when choosing between thin routers vs underlying implementations.
---

# ETF options — merged tools & trading copilot

## When to use

- Adding or changing a **merged** tool branch (`data_type`, `action`, `moment`, etc.).
- Debugging **OpenClaw** / **`tool_runner.py`** tool names vs Python module paths.
- Explaining **`tool_trading_copilot`** pipeline (status → regime → fetch → signal → positions).
- Deciding whether logic belongs in **merged** (router only) vs **`analysis.*`** / **`data_collection.*`**.

## Merged facade (`plugins/merged/`)

- **Role**: Single entry + enum parameter per domain; **no** heavy business logic — delegate to `analysis.*`, `plugins.data_collection.*`, `data_access.read_cache_data`, or `send_feishu_notification` (webhook + cooldown).
- **Docs**: `plugins/merged/README.md`
- **Examples**: `tool_fetch_index_data(data_type=...)`, `tool_read_market_data(data_type|data_types)`, `tool_strategy_analytics(action=...)`, `tool_send_feishu_notification(notification_type=...)`.
- **Read cache**: Minute default date range uses **calendar** `timedelta(days=5)` when dates omitted — not trading-calendar days unless callers pass explicit dates.

## Trading copilot (`plugins/copilot/trading_copilot.py`)

- **Tool**: `tool_trading_copilot` — one call chains trading status, A-share regime, index/ETF/A50/global fetch, optional `tool_generate_option_trading_signals`, positions from `~/.openclaw/workspaces/etf-options-ai-assistant/memory/positions.json`, state/throttle in `copilot_state.json`.
- **Docs**: `plugins/copilot/README.md`
- **`focus_stocks`**: Currently affects `meta` only; default quick scan is config-driven indices + ETFs — do not assume stock rows without extending the code.
- **`disable_network_fetch`**: Skips network-heavy steps; use in sandboxes.

## `tool_runner.py`

- Maps OpenClaw-exposed names to `module_path` + `function_name` (e.g. `merged.fetch_index_data`, `copilot.trading_copilot`).
- **Aliases** may inject `data_type` / `action` for old tool names — see runner definitions when a call fails with “unsupported enum”.

## Do not confuse with

- **`strategy_engine`**: separate plugin; see `plugins/strategy_engine/README.md`.
- **Historical volatility snapshot**: different skill — `.cursor/skills/etf-options-volatility-snapshot/` — for HV panels vs merged routers.
