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
3. **双轨**：`etf_rotation_research.yaml`（工具管道）与 `etf_rotation_research_agent.yaml`（agentTurn）**择一**绑定 Cron，避免重复。

## 权威文档

- `docs/openclaw/ETF_Rotation_Research_Workflow.md`
- `workflows/README.md`
