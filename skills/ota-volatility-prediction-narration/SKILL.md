---
name: ota_volatility_prediction_narration
description: 在 tool_predict_volatility / tool_predict_intraday_range / tool_predict_daily_volatility_range 返回后解读区间、置信度、位置、RSI、剩余时间、期权 Greeks/IV；不重复表格内已有数字；遵守时间与到期语义。
---

# OTA：波动预测工具结果解读

## 何时使用

- 用户刚看过 `tool_predict_volatility`、`tool_predict_intraday_range` 或 `tool_predict_daily_volatility_range` 的 Markdown/结构化结果，需要**补充叙事**（非重复粘贴表格）。
- 或刚看过 **`tool_underlying_historical_snapshot`** / `tool_calculate_historical_volatility` 的 HV/锥/IV 字段，需与预测类工具区分语义。

## 已实现波动（`tool_calculate_historical_volatility` / `tool_underlying_historical_snapshot`）

- **语义**：对 **历史收盘收益** 的年化标准差类指标（**%**），不是模型 forward 预测。
- **快照工具**：多窗口 `hv_by_window`、可选 `vol_cone`、`include_iv` 时 SSE ETF 近月 ATM IV；勿称为「预测波动率」。
- **与 `tool_predict_volatility`**：后者为 **预测/条件波动** 路径；同一轮对话并置时须分开表述。
- 字段与选型见 Skill **`ota_historical_volatility_snapshot`**。

## 日频全日区间（`tool_predict_daily_volatility_range`）

- **语义**：估计的是 **整个交易日** 的潜在运行区间（高/低带宽），不是「从当前时刻到收盘」的缩放区间。  
- **与 `tool_predict_volatility`**：后者多绑定 **剩余交易分钟** 与日内模型；若用户问「今天全天大概能晃多远」，优先引用本工具；若问「剩下半天波动」，用日内工具。  
- **叙事要点**：多窗口 HV + ATR 融合的 **稳健性**（短窗敏感、长窗锚定）；若 `intraday_adjusted` 为真，说明已用分钟信息做 **有界纠偏**，勿夸大命中承诺。  
- **勿混用口径**：同一轮对话中若并置两工具结果，须明确各自 horizon，避免把全日上下沿说成「剩余时段」边界。

## 标的物（指数 / ETF / A 股）

1. **区间判断**：当前价在区间中的位置、是否接近上下沿、突破概率（若工具提供）。  
2. **关键观察**（2–3 条）：区间宽度是否合理、RSI 是否超买超卖、剩余交易时间对波动的含义等。  
3. **风险提示**（1 条为主）：如贴近边界、指标背离等。  
4. **交易建议**：针对该标的相关期权思路；**置信度**必须引用工具中的 `confidence` 字段表述（如「约 0.52」或「约 52%」）。

**勿**编造未出现的数值或点位；**勿**复述表格中已逐行列出的同一数字（可概括关系）。

## 期权合约

除上述原则外，注意：

- **时间语义**：若 `remaining_minutes` 为 0，多表示**非交易时段或收盘后**，不等于合约已到期；须结合 `current_date` / `current_datetime` 与 `expiry_date`、`days_to_expiry`（若有）说明。  
- 观察 **Delta、IV、Greeks 贡献、IV Percentile**（若工具提供）；IV 高位偏卖方风险、低位偏买方机会等需在**有数据支撑**时表述。  
- 时间价值衰减：结合剩余天数谨慎表述。

## 相关 Skill

- 快报口径与缓存：`ota_volatility_range_brief`
- 通用叙事纪律：`ota_openclaw_tool_narration`
- 历史 HV 单窗 vs 复合快照：`ota_historical_volatility_snapshot`

## 巡检快报口径（已合并：原 `ota_volatility_range_brief`）

当用户问到「宽基 ETF 巡检快报」里的日内区间字段（如 `range_pct` / `confidence`），或问「为什么区间变窄/置信度上限」时，按以下**口径检查**解读（避免把预测工具口径与快报缓存混为一谈）：

1. **快报数据源**：优先读取 `data/volatility_ranges/{date}.json`（同日可多条）；不要把 `tool_predict_intraday_range` 的直出当作快报字段口径。
2. **收敛/夹紧规则**：生成源头在 `src/volatility_range.py`；合并后配置位于 `config/domains/signals.yaml` → `signal_params.intraday_monitor_510300.volatility` 的 `min_intraday_pct` / `max_intraday_pct`。
3. **置信度硬上限**：`confidence` 不应超过 **0.6**；当区间很宽时，置信度应倾向更低，避免出现逻辑矛盾组合。
4. **对称重算**：若 `range_pct` 被夹紧，说明上下界按对称逻辑重算（不要只改宽度不改边界）。
