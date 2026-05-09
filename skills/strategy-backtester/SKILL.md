---
name: strategy-backtester
description: 策略回测师，基于历史行情与技术指标执行轻回测编排并输出绩效评估。
version: 1.0.0
author: shaoxing-xie
tags:
  - backtest
  - strategy
  - performance
  - optimization
triggers:
  - 回测
  - 策略回测
  - 策略优化
  - 参数优化
  - 夏普
  - 最大回撤
---

# Strategy Backtester

## 目标

在无专用 `tool_backtest_*` 的当前能力下，基于行情与指标工具完成轻回测编排与绩效分析输出。

## 输入

- 用户策略描述
- 历史行情数据
- 技术指标数据

## 输出（固定结构）

1. 策略规格与回测窗口
2. 收益与风险指标
3. 交易统计与参数敏感性
4. 限制条件与下一步实验

### 证据表（必选）

- 列出 `tool_fetch_market_data`、`tool_calculate_technical_indicators` 等调用与 `quality_status`；收益/回撤等须来自工具或明确声明为 **MVP 派生计算** 并附公式。

### 反证与局限（必选）

- 样本外区间、幸存者偏差、未计入成本/滑点时对结论的影响。

## 强制规则

- 仅通过 **manifest / `tool_runner`** 调用依赖工具，禁止引导直连 `plugins.data_collection`。
- 若缺少足够历史数据，输出 `insufficient_evidence`。
- 若无专用回测工具，必须声明 `MVP mode` 与能力边界。
- 禁止输出买卖点、仓位比例、杠杆建议。
- 参数搜索范围从 `config/strategy-backtester_config.yaml` 读取。

## 依赖工具

- `tool_resolve_symbol`（L2；标的解析）
- `tool_fetch_market_data`
- `tool_calculate_technical_indicators`
- `tool_l4_valuation_context`（L4-data；标的含个股时可选并列估值事实字段）

## 通用输出字段

- `strategy_spec`
- `backtest_window`
- `performance`
- `risk_metrics`
- `trade_stats`
- `parameter_sensitivity`
- `limitations`
- `next_experiments`

