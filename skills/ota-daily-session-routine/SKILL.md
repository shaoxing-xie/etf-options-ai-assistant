---
name: ota_daily_session_routine
description: 交易日盘前/开盘/盘中/盘后的检查顺序与对应工作流 YAML；失败时是否继续通知的决策提示。依赖 option-trading-assistant 定时任务与本机 jobs.json。
---

# OTA：交易助手 — 盘前 / 开盘 / 盘中 / 盘后规程

## 何时使用

- 用户问「今天该跑什么」「盘前做什么」「盘后做什么」。
- 编排或复盘 **Cron / 工作流** 是否与文档一致。

## 规程（逻辑顺序）

1. **盘前**：对应 `before_open_analysis.yaml`（机构晨报等）；详见工作流参考手册。
2. **开盘**：`opening_analysis.yaml`（开盘独立完整链路）。
3. **盘中**：`intraday_analysis.yaml`、`signal_generation.yaml`、`signal_risk_inspection.yaml`、`etf_510300_intraday_monitor.yaml` 等 — **以 cron 调度绑定为准**。
4. **盘后**：`after_close_analysis_enhanced.yaml` 为主；其它如 `limitup_pullback_after_close.yaml`、`prediction_verification.yaml` 按调度执行。

## 失败与通知

- 若某步 `continue_on_error: true`，后续仍可能执行；**是否在失败时发通知** 以具体 YAML 与 Agent 策略为准，避免重复告警。
- 外部信息补全：若已安装 **`tavily-search`** / **`topic-monitor`**，可在盘前或事件哨兵步骤后按工作流做 **事件补全**（不重复维护检索 API 细节）。

## 权威文档

- `docs/openclaw/工作流参考手册.md`
- `workflows/README.md`
- 工作流中常见 **`tool_calculate_technical_indicators`** 的参数与引擎说明：Skill **`ota_technical_indicators_brief`**、`plugins/analysis/README.md`
- 盘后/盘前/开盘 **`tool_analyze_*`** 的字段与叙事口径：Skill **`ota_trend_analysis_brief`**
- 盘后多窗口 HV / 可选波动率锥与 IV：Skill **`ota_historical_volatility_snapshot`**（`tool_underlying_historical_snapshot`）；与仍使用单窗 `tool_calculate_historical_volatility` 的旧 YAML 可并存

## 第三方衔接（可选）

- `docs/getting-started/third-party-skills.md`
