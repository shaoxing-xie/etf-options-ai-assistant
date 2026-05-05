---
name: ota-equity-valuation-brief
description: 单标的估值语义摘要（PE/PB + 历史分位模板），开箱即用；深挖请转 fundamental-analyst。
version: 1.0.0
tags:
  - valuation
  - l4_semantic
  - brief
triggers:
  - 贵不贵
  - 估值分位
  - PE分位
  - 茅台估值
---

# OTA：估值语义 Brief

## 能力

- 调用 `tool_semantic_equity_valuation_brief` 获取 **确定性模板摘要**（非 LLM 编造数值）。
- 先阅读返回中的 `quality_status`；若为 `degraded`，在答复中声明数据受限。

## 依赖工具

- `tool_semantic_equity_valuation_brief`（首选）
- 必要时 `tool_resolve_symbol`（工具内部已解析）

## 输出格式

引用 `data.summary`，并列出 `pe`、`pe_percentile_0_100`、`valuation_level_key`。

## 禁止项

与 `fundamental-analyst` 一致：禁止给出买卖点、仓位与杠杆建议。
