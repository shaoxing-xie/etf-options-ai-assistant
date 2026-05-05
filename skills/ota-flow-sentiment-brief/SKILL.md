---
name: ota-flow-sentiment-brief
description: A 股资金流向与板块热度语义摘要（模板）；深挖请转 fund-flow-analyst。
version: 1.0.0
tags:
  - fund_flow
  - sentiment
  - l4_semantic
triggers:
  - 资金流向
  - 主力
  - 板块资金
  - 净流入
---

# OTA：资金与情绪 Brief

## 能力

- 调用 `tool_semantic_flow_sentiment_brief` 获取市场整体资金 proxy 与行业排名抽样。

## 依赖工具

- `tool_semantic_flow_sentiment_brief`

## 输出格式

引用 `data.summary`，补充 `flow_score`、`top_sectors_sample`（若有）。

## 禁止项

禁止交易指令；若 `quality_status!=ok`，明确提示上游受限。
