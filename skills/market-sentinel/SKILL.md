---
name: market-sentinel
description: 市场情绪哨兵，聚合涨停/资金/北向/板块四源，输出综合评分、阶段判定与反证（非交易指令）。
version: 1.0.0
author: shaoxing-xie
tags:
  - market
  - sentiment
  - aggregate
  - risk
triggers:
  - 市场情绪
  - 情绪阶段
  - 综合情绪
  - 冰点高潮
  - 情绪评分
  - 北向资金情绪
---

# Market Sentinel

**职责边界：本 Skill 只做「四源情绪证据 → 综合分、阶段、反证、置信带」的聚合与解释；不提供异动扫描清单、不提供具体买卖/加减仓/杠杆建议、不替代 `market-scanner` 的时段监控与事件窗输出。**

**与 `market-scanner`：要找「今日谁涨得猛、板块异动、盘前/盘中扫描」用 `market-scanner`；要「整体情绪阶段、能否重仓的框架判断（非指令）」用本 Skill。**

## 错误用法示例（反例）

- 错误：用本 Skill 输出直接下单或设止损价。正确：仅作环境判断，交易决策须由用户策略与合规流程承担。
- 错误：把「涨停家数多」单独当成重仓依据而忽略资金流与北向反证。正确：必须四工具并行拉齐证据，并在 `risk_counterevidence` 中写明矛盾点。
- 错误：在 `market-scanner` 已给出异动列表后，又用本 Skill 重复要「今日热点板块排名」。正确：板块排名类扫描交给 `market-scanner`；本 Skill 读板块结构子分数即可。

## 目标

在单日或短回溯窗口内，对 A 股市场情绪做**可解释的综合评估**：综合分、阶段标签、主导因子与风险反证；不替代扫描类 Skill。

## 输入

- 用户问题（可含 `date`、`lookback_days`、`risk_mode`）
- 四类情绪工具返回的结构化证据

## 输出（固定结构）

1. 综合分与阶段（0–100 分 + 冰点/修复/高潮/退潮/震荡/混沌）
2. 子项分数与主导因子归因
3. 数据完整性比例与（如有）降级说明
4. 行动倾向框架与置信带

### 证据表（必选）

- 列出四依赖工具调用与各自 `quality_status`；综合分须能回溯到各子分数来源。

### 反证与局限（必选）

- 四源矛盾、某一源 `degraded` 时对综合分的稀释说明。

## 强制规则

- 仅通过 **manifest / `tool_runner`** 调用依赖工具，禁止引导直连 `plugins.data_collection`。
- **必须并行调用**四个依赖工具（异步/并发），禁止为省事串行阻塞；聚合结果可按 `config/market-sentinel_config.yaml` 的短 TTL 缓存复用。
- 核心证据不足以支撑结论时，输出 `insufficient_evidence` 并说明缺失项。
- 禁止输出具体买卖点、仓位比例、杠杆建议。
- 权重、`risk_mode`、动态调权规则与阶段阈值仅从 `config/market-sentinel_config.yaml` 读取。

## 依赖工具

- `tool_resolve_symbol`（L2；代码混合格式时）
- `tool_fetch_limit_up_stocks`
- `tool_fetch_a_share_fund_flow`
- `tool_fetch_northbound_flow`
- `tool_fetch_sector_data`

## 通用输出字段

- `overall_score`
- `sentiment_stage`
- `sub_scores`
- `factor_attribution`
- `data_completeness_ratio`
- `action_bias`
- `risk_counterevidence`
- `confidence_band`
- `degraded`
