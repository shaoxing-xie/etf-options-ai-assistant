# Cron L4 分档冻结（T0 / T1 / T2）

与计划「Cron 任务定点接入 tool_l4_*」对齐：**仅 T2 实施 L4 内嵌**；本表为验收口径单一事实源之一。

## T2（实施全集，顺序 01→10）

| 序号 | job_id | 名称 |
|------|--------|------|
| 01 | `etf-rotation-research` | ETF 轮动研究 |
| 02 | `position-tracking` | 盘中观察池跟踪 |
| 03 | `strategy-calibration` | 周一策略定调 |
| 04 | `weekly-selection-review` | 周度选股复盘 |
| 05 | `intraday-tail-screening` | 尾盘选股落盘 |
| 06 | `nightly-stock-screening` | 夜盘选股落盘 |
| 07 | `8c548101-85b7-4c95-a458-8b0e15317d46` | 每日市场分析 |
| 08 | `f0d82a29-45de-4377-9570-5dda65b3f58a` | 盘前行情分析 |
| 09 | `8f2ef8c2-4d0e-4df4-b3ad-3524d74b47be` | 开盘实盘报告 |
| 10 | `etf-midday-recap-1200` | 午间行情盘点 |

## T1（暂缓接入 tool_l4_*）

- `prediction_metrics`：`six-index-*` 等预测指标任务  
- `strategy_research_screening` 内 evolution dry-run（`factor-evolution-weekly`、`strategy-evolution-weekly`）  
- 部分 `intraday_monitoring`（除非产品单独评审）

## T0（不接 L4）

- `data_collection_cache` 全部  
- `ops_quality_guard`（health、postcheck、retention、autofix、code health 等）  
- 其余未列入 T2 的 `intraday_monitoring`、`manual_one_off`、disabled 任务  

## 环境开关

- `ASSISTANT_INCLUDE_L4_SNAPSHOT=1`：在支持的 T2 链路上附加 L4 摘要（默认生产可开启）。  
- `ASSISTANT_INCLUDE_L4_SNAPSHOT=0` 或未设置：不调用 `tool_l4_*` 附加块（基线行为）。
