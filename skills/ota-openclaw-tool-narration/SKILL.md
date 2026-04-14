---
name: ota_openclaw_tool_narration
description: 在调用趋势/盘前/开盘/盘后/盘中/日报投递工具后，仅依据工具返回的结构化事实撰写自然语言；对齐原 Prompt_config 章节与字数；禁止编造数值；缺失写「未提供」；日报 llm_summary 与盘后口径一致。
---

# OTA：OpenClaw 工具结果叙事（通用）

## 何时使用

- 已执行 `tool_*` 或工作流返回了 JSON/表格/Markdown 骨架，需要向用户给出**可读总结**。
- **权威叙事口径**：默认由网关主模型 + 本 Skill 叙事；`Prompt_config.yaml` 的 `llm_prompts` 保留作回滚参考。**勿与本文双份改文案。** 若 `llm_enhancer.enabled` 为 true 且 `analysis_types` 含 `after_close`，`tool_send_daily_report` 进程内生成的 `llm_summary` 须与本 Skill「盘后 / 日报」口径一致，且只读已合并字段。
- 场景覆盖 **`before_open`**、**`opening_market`**、**`after_close`**、**`intraday_summary`**，以及 **`daily_market` / `tool_send_daily_report` 的 `llm_summary`**。

## 硬约束

1. **只根据工具返回中出现的字段与数值**撰写；不得捏造涨跌幅、点位、资金流向或新闻。
2. 某字段缺失时写 **「数据未提供」** 或 **「未提供」**，不得推测补全。
3. **不要**在回复中提及「模型」「API」「JSON」「工具名称」等实现细节。
4. 策略类表述保持 **中性、谨慎**；可给方向与节奏建议，避免具体买卖指令与目标价。

## 输出结构（Markdown，可按场景取舍）

### 盘前（`before_open` 口径）

- **Cron（与 idle 超时同级）**：优先**单次** **`tool_run_before_open_analysis_and_send`**（`mode=prod`，`fetch_mode=production`），进程内采集并发送，避免多轮搬运 `report_data`；排障时再按 `workflows/before_open_analysis.yaml` 逐步 `tool_*`。
- **趋势总结**：一句话核心判断  
- **隔夜外盘**：一句话（仅基于工具中的外盘/商品/摘要字段）  
- **政策面**：仅当存在 `policy_news`/要闻字段时概括，否则「未提供要闻」  
- **关键洞见**：2–4 条要点  
- **风险警示**  
- **交易建议**：对沪深300ETF期权的简要思路（仓位与风控）

### 开盘（`opening_market` 口径）

- **趋势总结**  
- **关键洞见**：2–4 条（指数强弱、量能、风格分化等）  
- **风险警示**  
- **交易建议**：日内思路；**置信度**须引用工具结果中的综合 `confidence`（若存在），勿混用中间步骤置信度。

### 盘后（`after_close` 口径）

对应原 `Prompt_config.yaml` → `llm_prompts.after_close`；用于解读 **`tool_analyze_after_close`** 返回的 **`data`**（含 `overall_trend` / `trend_strength` / `intraday_summary` / `daily_report_overlay` 等）。

- **篇幅**：约 **200–400 字**（用户可见段落，非 JSON）。
- **内容顺序**：
  1. **盘面总结**：一句话概括当天市场态势（如放量下跌、缩量震荡、稳步上行），**1–2 句**说明依据（指数、量能、涨跌家数、趋势与强度等**仅来自 data**）。
  2. **关键观察**：**2–4 条**要点（权重/成长分化、行业轮动、情绪过热/过冷等），只写 JSON 中**有证据**的。
  3. **风险提示**：**1–2 条**中短期风险或不确定性（不编造具体消息或事件）。
  4. **后续思路**：**1–2 个交易日**内对沪深300ETF及期权的**方向与节奏**（偏多/偏空/防守），强调仓位与节奏；**不**给具体买卖价与目标价。
- **输出 Markdown 标题（固定）**：
  - **盘面总结** / **关键观察**（列表） / **风险提示** / **后续思路**
- **策略表述**：可随波动与信号清晰度调整措辞，但不得捏造数值。

### 每日市场日报（`daily_market` / `tool_send_daily_report` / `tool_analyze_after_close_and_send_daily_report`）

与 `workflows/daily_market_report.yaml`、cron「每日市场分析报告」一致：**结构化数据与叙事分离**。

0. **优先（cron 与 idle 超时同级）**：**单次**调用 **`tool_analyze_after_close_and_send_daily_report`**（`mode=prod`；补采产物用 **`extra_report_data`** 浅合并），避免主模型在 `tool_analyze_after_close` 与 `tool_send_daily_report` 之间传递大 JSON 被截断或触发网关 **LLM idle timeout**。
0b. **合并后配置 → `llm_structured_extract`**：与网关主模型叙事分离；进程内可把 **Tavily 素材或上游工具 JSON 序列化事实** 按指令交给同套 OpenClaw 模型链（见 `plugins/utils/llm_structured_extract.py` 的 `llm_prose_from_unstructured` / `llm_json_from_unstructured`），产出 **JSON 抽取结果**或**中文自然语言段落**（例如 overlay 外盘综述），再并入 `report_data` 由发送层排版。
1. **数据（硬约定·两步发送时）**：调用 `tool_send_daily_report` / `tool_send_analysis_report` 时，`report_data` **必须**包含 **`tool_analyze_after_close`**，值为**当轮** `tool_analyze_after_close` 的**完整工具返回**（含 `success` / `message` / `data`），供 `send_daily_report` 与 `analysis` **合并**；**禁止**只传自编 `analysis` 而不带该键。
2. **`report_data.analysis`** **必须以** `tool_analyze_after_close` 返回的 **`data` 对象为底稿**（保留 `daily_report_overlay`、`intraday_summary` 等），仅可 **merge** 补采结果；禁止用自编 JSON **整体替换**（否则易判缺字段或降级）。
3. **叙事**：若由网关主模型在发送前生成 **`report_data.llm_summary`**（或写在 `analysis.llm_summary`），**章节与语气与上一节「盘后（after_close）」相同**：**盘面总结 → 关键观察 → 风险提示 → 后续思路**；篇幅 **200–400 字**。
4. **进程内 llm_enhancer（可选）**：当 **`llm_enhancer.enabled` 为 true** 且 **`analysis_types` 含 `after_close`** 时，`tool_send_daily_report` 可在合并归一化后生成 `llm_summary`；**仍只依据已合并进 `report_data` / `analysis` 的事实**，**不能**代替传入真实 `tool_analyze_after_close` 完整返回体，也**不得**改写结构化 `analysis`。
5. **与降级正文的关系**：若系统已生成「完整性状态 / 缺失项」章节，`llm_summary` 作为**补充摘要**置于后段，**不得**与缺失清单矛盾（不假装已有关键字段）。
6. **禁止**：编造新闻、北向数值、外盘涨跌幅；仅引用已合并进 `report_data` / `analysis` 的字段。

### 盘中（`intraday_summary` 口径）

对应原 `llm_prompts.intraday_summary`（若有 **`history_summaries`**，仅作时间序上下文）。

- **篇幅**：约 **150–300 字**。
- **盘中总结** → **关键观察**（2–3 条：区间位置、突破概率、与此前分析一致/背离、量价/IV 等）→ **风险提示** → **交易思路**（偏谨慎、仓位与止损）。

### 技术指标（`tool_calculate_technical_indicators`）

- 优先复述工具返回的 **`message`** 或 `data.signal.summary`，以及各子指标下的数值与「金叉/超买」等**已有文案**。
- **不要**自行推算 RSI/MACD 数值；若 `success: false`，照 `message` 解释（常见：K 线不足、未装 `pandas_ta` 已回退 legacy）。
- 用户追问「与以前不一致」时，可说明 **standard** 与 **legacy** 的 RSI/MACD 定义差异，并建议对比调用；细则见 **`ota_technical_indicators_brief`**。

### 历史波动快照（`tool_underlying_historical_snapshot`）

- 依据 `data.results[]` 中每标的的 `hv_by_window`、`vol_cone`、`iv`（若存在）概括；**null 窗口**视为样本不足，勿编造。
- 勿将已实现波动（HV）与 `tool_predict_volatility` 的预测输出混为同一句话；口径见 **`ota_historical_volatility_snapshot`**。

## 相关 Skill

- 技术指标**字段与引擎口径**：`ota_technical_indicators_brief`
- 波动区间**字段口径**：`ota_volatility_range_brief`
- 历史 HV 单窗 vs 复合快照：`ota_historical_volatility_snapshot`
- 解读步骤可用较高档位模型：`ota_llm_model_routing`
