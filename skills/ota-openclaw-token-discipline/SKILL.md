---
name: ota_openclaw_token_discipline
description: 精简工具暴露、Agent 工具白名单与调用顺序，降低 token；面向维护者与高成本会话。
---

# OTA：OpenClaw 工具与 Token 纪律

## 何时使用

- 配置 Agent **允许的工具列表**、Cron 任务工具集。
- 设计「少而准」的调用链，避免重复大 payload。

## 规程

1. **最小够用**：仅暴露当前任务域所需 `tool_*`；合并类工具优先于多次细粒度调用（见 manifest 说明）。**多窗口 realized vol / 锥 / 可选 IV** 优先一次 `tool_underlying_historical_snapshot`，避免对同一标的重复拉日线；细则见 Skill **`ota_historical_volatility_snapshot`**。
2. **输出**：工具侧默认 JSON 可序列化；避免把完整 DataFrame 原文塞进对话。
3. **复核**：改动白名单后跑一条主工作流 smoke。

## 权威文档

- `docs/openclaw/OpenClaw工具与Token优化建议.md`
- `docs/openclaw/能力地图.md`
- 历史波动单窗口 vs 复合快照：`skills/ota-historical-volatility-snapshot/SKILL.md`（`ota_historical_volatility_snapshot`）
