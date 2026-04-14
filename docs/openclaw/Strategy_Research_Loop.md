# 策略研究闭环与工作流设计（Strategy Research Loop）

## 1. 目标与范围

- 在现有系统中，已经具备：
  - 信号生成与记录（`tool_generate_option_trading_signals`，别名 `tool_generate_signals` + `tool_record_signal_effect`）。
  - 策略表现查询与评分（`tool_get_strategy_performance`、`tool_calculate_strategy_score`）。
  - 策略权重调整工具（`tool_adjust_strategy_weights`、`tool_get_strategy_weights`）。
- 本文件的目标是：
  - 将上述能力组织成一个清晰的**策略研究闭环（Alpha Research Pipeline）**；
  - 通过 `workflows/strategy_evaluation.yaml`、`workflows/strategy_weight_adjustment.yaml` 与新增的 `workflows/strategy_research.yaml` 完成从信号 → 回放 → 评分 → 权重建议的链路；
  - 所有输出保持兼容「研究模式一」与现有钉钉/飞书通知渠道。

## 2. 策略研究闭环概览

```mermaid
flowchart TD
  signals[信号生成\n(tool_generate_option_trading_signals)] --> record[信号记录\n(tool_record_signal_effect)]
  record --> perf[策略表现统计\n(tool_get_strategy_performance)]
  perf --> score[策略评分\n(tool_calculate_strategy_score)]
  score --> weightAdj[权重调整建议\n(tool_adjust_strategy_weights)]
  weightAdj --> report[研究报告与巡检摘要\n(etf_notification_agent)]
```

## 3. 现有工作流与新工作流的分工

### 3.1 现有工作流

- `workflows/strategy_evaluation.yaml`：
  - 每周对多个策略（如 trend_following / mean_reversion / breakout）进行表现评估与评分；
  - 核心依赖：`tool_calculate_strategy_score`。
- `workflows/strategy_weight_adjustment.yaml`：
  - 在评分之后，根据当前权重与评分结果给出权重调整（通常为小幅 incremental 调整）；
  - 核心依赖：`tool_get_strategy_weights` + `tool_adjust_strategy_weights`。

### 3.2 新增工作流：`workflows/strategy_research.yaml`

- 角色与定位：
  - 更偏向「研究与回放评估」而不是直接线上调整；
  - 汇总多策略在统一回放窗口内的表现，对比不同 Market Regime 下的收益/回撤特征；
  - 生成一份完整的「策略研究报告」，通过现有钉钉/飞书渠道推送。
- 关键步骤（详见 YAML 文件）：
  - 加载历史信号与行情数据（通过 `tool_read_market_data` 或后续专用工具）；
  - 分策略调用 `tool_get_strategy_performance` 获取表现；
  - 调用 `tool_calculate_strategy_score` 统一评分；
  - 调用 `tool_adjust_strategy_weights` 生成**权重调整建议**（作为建议写入报告，不自动改配置）；
  - 最终调用 `tool_send_analysis_report`，设置 `report_type="strategy_research"`（将研究/分析类报告推送到钉钉）。

## 4. 回放评估与统一口径

### 4.1 回放数据来源

- 历史信号：
  - 由 `tool_record_signal_effect` 写入的信号记录（通常位于 `data/signal_records/` 路径下，具体以工具实现为准）。
- 行情数据：
  - 指数/ETF 日线与分钟线缓存（`tool_read_index_daily`、`tool_read_etf_daily`、`tool_read_index_minute`、`tool_read_etf_minute`）。
- 期权与波动相关：
  - 期权分钟与 Greeks（`tool_read_option_minute`、`tool_read_option_greeks`）；
  - 历史/预测波动率（`tool_calculate_historical_volatility` 单窗；`tool_underlying_historical_snapshot` 多窗/可选锥与 IV；`tool_predict_volatility`）。

> 统一建议：在实现具体回放逻辑时，保持「数据源与假设」在报告中显式说明，避免出现不可复现的“纸面胜率”。

### 4.2 评估指标建议

- 基础指标：
  - 总收益率/年化收益率；
  - 最大回撤；
  - 胜率与盈亏比；
  - 平均持有期与换手率；
  - 手续费与滑点假设下的净收益。
- Regime 维度：
  - 在 `Market_Regime_and_AI_Decision_Layer.md` 定义的 Regime 框架下，将样本拆分为不同 Regime 段；
  - 分别统计各策略在不同 Regime 下的表现，用于后续 AI 决策层的策略选择。

## 5. 研究报告结构与输出规范

- 通过 `etf_notification_agent` + `tool_send_analysis_report` 输出时，建议采用如下结构（兼容研究模式一）：\n
  - **📊 策略表现概览**：按策略列出关键指标（收益率/回撤/胜率等）的表格；\n
  - **📈 Regime × 策略表现矩阵**：展示不同 Regime 下各策略的相对优劣；\n
  - **🧮 权重调整建议**：结合评分结果与历史表现，给出建议的权重增减区间（不直接生效）；\n
  - **⚠️ 风险提示**：样本外风险、极端行情下可能失效的场景、数据缺失/降级说明；\n
  - **📂 数据与来源**：列出使用的核心工具（例如：`tool_get_strategy_performance`、`tool_calculate_strategy_score` 等）与数据区间；\n
  - **🧭 下一步行动建议**：例如「建议在下一个自然季度窗口再评估一次策略组合」「在特定 Regime 下进一步细化某策略参数」等。

所有 Markdown 输出应遵循 `~/.openclaw/prompts/research.md` 中关于表格与结构化输出的规范，确保在钉钉/飞书中渲染良好。

## 6. 与工作流A（信号 + 风控巡检）的联动

- 工作流A 产生的信号与风控结果，可以作为策略研究闭环的输入之一：
  - 将每轮巡检的候选信号、通过/拒绝结果与风险审计日志，与策略 ID/Regime 信息关联；
  - 在策略研究报告中展示「某策略在风控层被拒绝的主要原因分布」（例如单笔风险超限、综合成本过高等）。
- 策略研究结果不直接修改工作流A 的实际行为：
  - 仅通过研究报告和巡检报告向使用者提供更高维度的理解；
  - 实际策略启停与权重变更仍需人工决策，或在未来版本通过 AI 决策层与 risk_engine 联动后谨慎自动化。

