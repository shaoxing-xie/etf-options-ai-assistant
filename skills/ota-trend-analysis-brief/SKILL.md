---
name: ota_trend_analysis_brief
description: 三工具 tool_analyze_after_close / before_open / opening_market 的契约、report_meta、daily_report_overlay、落盘目录、trend_analysis_plugin 配置；盘前 A50-HXC 边界与 after_close_basis；叙事只引用返回字段。
---

# OTA：趋势分析三工具（盘前 / 盘后 / 开盘）

## 何时使用

- 调用或解释 **`tool_analyze_after_close`**、**`tool_analyze_before_open`**、**`tool_analyze_opening_market`** 的返回结构、落盘路径、配置开关。
- 用户问「为什么盘前又跑了一遍盘后」「A50 / 金龙失败影响谁」「`report_meta` 和 overlay 是什么」。

## OpenClaw：建议勾选的 Agent `id`

与本仓库片段 **[`config/snippets/openclaw_agents_ota_skills.json`](../../config/snippets/openclaw_agents_ota_skills.json)** 一致，下列 Agent 的 **`skills`** 中应包含 **`ota_trend_analysis_brief`**（`name:` 为下划线，与目录 `ota-trend-analysis-brief` 不同）：

| Agent `id` | 原因 |
|------------|------|
| **`etf_main`** | 总编排、多工作流入口；需统一解读三工具与 `after_close_basis`。 |
| **`etf_analysis_agent`** | 白名单含三工具；定时盘后/盘前/开盘与融合链路。 |
| **`etf_business_core_agent`** | 信号 + 风控 + 融合；常并列引用趋势结论。 |
| **`etf_notification_agent`** | 晨报/分析推送需按 `report_meta`、overlay 边界叙事，避免臆造字段。 |

**不勾选**：**`etf_data_collector_agent`**（仅采集）、**`ops_agent`**、**`code_maintenance_agent`**（角色无关趋势契约）。若本机另有自定义 Agent 暴露了 `tool_analyze_*` 或负责转述其 JSON，应同样加入该 Skill。

## 工具与数据源边界

| 项 | 说明 |
|----|------|
| **盘后** | `src.trend_analyzer.analyze_daily_market_after_close`；插件附加 **`daily_report_overlay`**（北向、全球现货、关键位、板块、可选 **ADX**）与 **`report_meta`**。 |
| **盘前** | `analyze_market_before_open`。**隔夜富时 A50 与纳斯达克中国金龙（HXC）仅在本流程拉取**；盘后、开盘**不调用** `fetch_a50_futures_data` / `fetch_nasdaq_golden_dragon`。A50 样本不足或 HXC **yfinance 限流**只影响盘前隔夜合成，见 `overnight_overlay_degraded`；可降级为仅靠盘后结论。 |
| **盘后复用** | 未传入盘后 dict 时，**先读落盘** `after_close`（自当日起向前最多 10 个自然日），再决定是否现场跑盘后；返回 **`after_close_basis`**：`passed` / `disk` / `computed`。 |
| **开盘** | 优先 `analyze_opening_market`；失败且 `trend_analysis_plugin.fallback.use_simple_opening` 为 true 时 **`_simple_opening_analysis`**。 |

## 返回结构（外层）

三工具均返回：`success`、`message`、`data`（分析主体）、`llm_enhanced`（仅当上游已注入 `llm_summary`）。

## `data` 内统一扩展

- **`report_meta`**（必有）：`analysis_type`、`timestamp`、`market_sentiment_score`、`trend_strength_label`、`key_metrics`、`overlay`（镜像 `daily_report_overlay`，无则为 `{}`）。
- **`daily_report_overlay`**（**仅盘后**且插件 `enabled`）：不要假设盘前/开盘也有此键。

盘前 **`key_metrics.after_close_basis`** 标明盘后结论来源。

## 落盘（`save_trend_analysis`）

| `analysis_type` | 目录（相对 `data_dir`，见 合并后配置 → `system.data_storage.trend_analysis`，域文件：`config/domains/platform.yaml`） |
|-----------------|-----------------------------------------------------------------------------------|
| `after_close` | `after_close_dir` |
| `before_open` | `before_open_dir` |
| `opening_market` | **`opening_dir`**（与 `before_open` 分离，避免同日覆盖） |

## 配置键

- **`trend_analysis_plugin`**（顶层）：`enabled`、`overlay.*`、`fallback.*`（见 `get_default_config`；合并后配置域文件：`config/domains/analytics.yaml`）。
- 存储路径：**`system.data_storage.trend_analysis`**（含 `opening_dir`）。

## 叙事约束（与 `ota_openclaw_tool_narration` 一致）

1. **只引用** 工具返回的 `data` 中实际字段（含 `report_meta`、`daily_report_overlay`、`data_stale_warning`、`after_close_basis` 等）；不得编造 ADX、北向、全球指数数值。
2. 非交易日可能出现指数日线「最新 bar 日期 ≠ 当日」类提示（`data_stale_warning`），应说明「结论基于最近可用交易日」而非断言插件故障。
3. 开盘模式下 `market_sentiment_score` 与 `trend_strength_label` 若看似不一致，因后者在无 overlay 时可能默认 `neutral`；可优先引用 `summary` 强弱家数或各指数 `strength`。

## 权威文档与代码

- [`plugins/analysis/README.md`](../../plugins/analysis/README.md) 第二节
- [`plugins/analysis/trend_analysis.py`](../../plugins/analysis/trend_analysis.py)
- [`src/trend_analyzer.py`](../../src/trend_analyzer.py)（`analyze_market_before_open`、A50/HXC）
- [`src/data_storage.py`](../../src/data_storage.py)（`save_trend_analysis` / `load_trend_analysis`）
- 冒烟：`scripts/smoke_trend_analysis.py`

## 相关 Skill

- 通用工具叙事：`ota_openclaw_tool_narration`
- 技术指标（盘后 overlay 中 ADX）：`ota_technical_indicators_brief`
