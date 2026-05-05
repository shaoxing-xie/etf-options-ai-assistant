---
name: ota-market-regime-brief
description: 市场 regime + 指数快照 + 可选板块热度语义摘要；深挖请转 market-scanner。
version: 1.0.0
tags:
  - market
  - regime
  - l4_semantic
triggers:
  - 市场怎么样
  - 大盘
  - 盘面
  - 震荡
---

# OTA：市场 Regime Brief

## 能力

- 调用 `tool_semantic_market_regime_brief` 获取研究级 regime 标签与上证综指类指数快照。

## 依赖工具

- `tool_semantic_market_regime_brief`

## 输出格式

引用 `data.summary`，点出 `regime` 与 `index_change_pct`（若有）。

## 禁止项

禁止买卖建议；regime 为研究标签，不等于预测收益。
