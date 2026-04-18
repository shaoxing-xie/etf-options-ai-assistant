---
name: ota_etf_rotation_research
description: ETF 轮动研究：标的池、因子入口、tool_etf_rotation_research 与 rotation_config.yaml；与盘中巡检 Skill 分开使用。
---

# OTA：ETF 轮动研究工作流

## 何时使用

- 定时或手动跑 **轮动研究**（`etf_rotation_research*.yaml`）。
- 用户问轮动池、因子、输出通知格式。

## 规程

1. **配置入口**：`config/rotation_config.yaml`，标的池与 `symbols.json` 等见专题文档。
2. **工具管道**：`tool_etf_rotation_research`（`etf_pool` 空则读配置）；通知常接 `tool_send_analysis_report`。
3. **Cron（agentTurn）**：须 **单次** `tool_send_etf_rotation_research_report`（内部已串联计算+发送）。**不要**在 Cron 里先调 `tool_etf_rotation_research`（易超大 toolResult → LLM 超时/降级后 `tool_send_*` 不可用）。
4. **双轨**：`etf_rotation_research.yaml`（工具管道）与 `etf_rotation_research_agent.yaml`（agentTurn）**择一**绑定 Cron，避免重复。

## 策略研究闭环（已合并：原 `ota_strategy_research_loop`）

当用户问到「策略研究任务」「strategy_research*.yaml」「回放与 WFE 口径」「tool_strategy_research 如何接入主链」时：

1. **工具入口**：使用 `tool_strategy_research`，默认读取 `config/strategy_research.yaml`（切分、成本、Holdback 等）。
2. **输出定位**：研究输出可接日报/钉钉，但**不替代**盘中风控与信号巡检；实盘执行仍遵守巡检/风控技能铁律。
3. **调度边界**：`strategy_research_playback.yaml`（agentTurn）与工具管道可并存，但避免同一 Cron 重复调度造成重复发送/超时链路。

## 权威文档

- `docs/openclaw/ETF_Rotation_Research_Workflow.md`
- `workflows/README.md`
