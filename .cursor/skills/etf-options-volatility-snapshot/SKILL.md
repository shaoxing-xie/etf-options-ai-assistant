---
name: etf-options-volatility-snapshot
description: Historical volatility snapshot tools (multi-window HV, cone, SSE IV) in etf-options-ai-assistant.
---

# ETF options — historical volatility snapshot

## When to use

- You need **realized / historical volatility (HV)** for ETF, index, or (via snapshot) A-stock names — not GARCH predictions or intraday range tools.
- You want **one number** for a single window vs a **multi-symbol, multi-window panel** with optional vol cone and SSE ETF option IV.
- You are wiring **OpenClaw / Cursor** workflows and must pick the right tool to save tokens (prefer one snapshot call over many single-window calls when appropriate).

## Tool comparison

| Tool | Role | Symbols | Windows / extras | Typical use |
|------|------|---------|------------------|-------------|
| `tool_calculate_historical_volatility` | Single-window HV (annualized %) | One | Single `lookback_days`; `fetch_index_daily_em` (ETF auto) | Legacy YAML, cron steps that only need one HV figure; **not** for A-share stocks |
| `tool_underlying_historical_snapshot` | Composite HV panel | Many (`symbols`, `max_symbols`) | Default windows from config; optional `vol_cone`, optional SSE near-month IV (`include_iv`); `asset_type` auto/stock/etf/index | Multi-window table, cone, IV in one call; **stocks** require `asset_type=stock` |
| `tool_historical_snapshot` | Same implementation | Same | Same | **Runner alias** for `tool_underlying_historical_snapshot` (OpenClaw / `tool_runner` both keys) |

## `config.yaml` — `historical_snapshot`

Keys used by the snapshot tool (defaults may change; see repo `config.yaml`):

- `enabled`, `default_windows`, `max_symbols`, `cone_history_calendar_days`, `include_vol_cone_default`, `include_iv_default`
- `iv.sse_only`, `iv.near_month_min_days`, `iv.atm_method`, `iv.eq_30d_enabled`

## Code and docs map

- **Shared HV math / config merge**: `src/realized_vol_panel.py`
- **Plugins**: `plugins/analysis/historical_volatility.py`, `plugins/analysis/underlying_historical_snapshot.py`
- **Narrative in repo**: `plugins/analysis/README.md` — **§5** (single-window) and **§5b** (snapshot)
- **OpenClaw**: `docs/openclaw/能力地图.md`, `docs/openclaw/工作流参考手册.md`
- **Playbook**: `research.md` (e.g. post-close flow mentions HV tools)

## Do not merge with `technical_indicators`

**`technical_indicators`** (`tool_calculate_technical_indicators`) is a separate plugin: MA/MACD/RSI/Bollinger (and optional KDJ/CCI/ADX/ATR). Do **not** treat it as part of the historical-volatility snapshot stack; keep HV tool choice explicit using the table above.

## Related project skills

- **Merged facade & trading copilot** (enum routers, `tool_trading_copilot`, `tool_runner`): see `.cursor/skills/etf-options-merged-copilot/SKILL.md`.
