---
name: market-scanner
description: 市场扫描仪，提供盘前/盘中/盘后三阶段市场扫描、异动识别与情绪状态判断。
version: 1.0.0
author: shaoxing-xie
tags:
  - market
  - scanner
  - sector
  - flow
triggers:
  - 市场扫描
  - 盘前扫描
  - 盘中监控
  - 盘后复盘
  - 板块轮动
  - 今日热点
  - 涨跌家数
---

# Market Scanner

## 目标

对 A 股市场进行时段化扫描，输出可执行前的结构化观察结论与风险提示。

## 输入

- 用户问题（盘前/盘中/盘后）
- 指数、板块、资金流、涨停池与交易时段工具数据

## 输出（固定结构）

1. 市场快照（指数、涨跌家数、成交环境）
2. 板块与资金强弱
3. 异动监控（放量突破/冲高回落/炸板）
4. 情绪状态与应对剧本

## 强制规则

- 盘中叙事前必须先调用 `tool_check_trading_status`。
- 输出必须带 `event_window` 与 `data_freshness`。
- 缺少核心行情或广度数据时输出 `insufficient_evidence`。
- 禁止输出买卖点、仓位比例、杠杆建议。
- 情绪阈值从 `config/market-scanner_config.yaml` 读取。

## 依赖工具

- `tool_check_trading_status`
- `tool_fetch_market_data`
- `tool_fetch_sector_data`
- `tool_fetch_a_share_fund_flow`
- `tool_fetch_northbound_flow`
- `tool_fetch_limit_up_stocks`

## 通用输出字段

- `market_snapshot`
- `breadth`
- `sector_strength`
- `flow_snapshot`
- `anomaly_watchlist`
- `sentiment_state`
- `playbook`
- `risks`
- `event_window`
- `data_freshness`

