---
name: ota_historical_volatility_snapshot
description: 选用 tool_calculate_historical_volatility（单窗口）或 tool_underlying_historical_snapshot（多标的/多窗口/可选锥与 IV）；与 tool_predict_volatility、日频区间工具区分 horizon；配置 historical_snapshot。
---

# OTA：历史波动率 — 单窗口 vs 复合快照

## 何时使用

- 用户或工作流需要 **一个数字**（如「60 日 HV」）→ `tool_calculate_historical_volatility`。
- 需要 **多窗口、多标的、同一截面、少次调用**（降 token）→ `tool_underlying_historical_snapshot`（runner 别名 `tool_historical_snapshot`）。
- 需要 **波动率锥分位** 或 **SSE ETF 近月 ATM IV**（可选）→ 仅快照工具；`include_iv` 默认关，IV 仅上交所 ETF 期权标的有效。

## 工具对照

| 工具 | 适用 |
|------|------|
| `tool_calculate_historical_volatility` | 单标的、单 `lookback_days`；走 `fetch_index_daily_em`（含 ETF 自动识别）；**不用于 A 股个股** |
| `tool_underlying_historical_snapshot` | `symbols` 列表或逗号分隔；`asset_type`: auto/stock/etf/index；默认窗口等见 合并后配置 → **`historical_snapshot`**（域文件：`config/domains/analytics.yaml`） |
| `tool_predict_volatility` | GARCH/ARIMA 等 **预测**，horizon 与 realized vol 不同；勿与 HV 混读为同一语义 |
| `tool_predict_daily_volatility_range` | **全日** 价格区间；与「已实现波动率数值」不同维度 |

## 输出解读（叙事）

- `hv_by_window` 的键为 **字符串**（如 `"20"`），值为 **年化 %** 或 `null`（该窗口样本不足不判整标的失败）。
- `vol_cone`（若开启）：每窗 `min` / `max` / `mean` / `percentile` / `current`；percentile 为经验分位 **0–100**。
- `iv`（若开启）：`iv_atm_front_pct`、`iv_eq_30d_pct` 可能为 `null`；`iv_rank` v1 固定 `null` + `iv_rank_note`；无期权标的见 `iv_skip_reason`。

## 权威路径

- 实现：`plugins/analysis/historical_volatility.py`、`plugins/analysis/underlying_historical_snapshot.py`、`src/realized_vol_panel.py`
- 文档：`plugins/analysis/README.md` §5 / §5b；`config/tools_manifest.yaml`

## 相关 Skill

- Token 与白名单：`ota_openclaw_token_discipline`
- 波动预测类叙事：`ota_volatility_prediction_narration`、`ota_volatility_range_brief`
