# screening_view_v1

- 数据集说明：研究台核心聚合视图，汇总夜盘候选、尾盘推荐、效果指标、任务监控与板块热度。
- Schema：`screening_view_v1`（L4）
- 更新频率：交易日内按需刷新（支持按日快照回放）
- SLA：交易日内分钟级可读，日终必须可回放
- 路径：`data/semantic/screening_view/YYYY-MM-DD.json`
- 依赖任务：`nightly-stock-screening`、`intraday-tail-screening`、`weekly-selection-review`
- 回放：`GET /api/semantic/screening_view?trade_date=YYYY-MM-DD`

## 关键字段

- `candidates.nightly / candidates.tail`
- `performance_context / effect_stats`
- `tail_paradigm_pools`
- `task_execution_monitor`
- `sector_rotation_heatmap`
- `_meta.quality_status / lineage_refs`

## 降级语义

- `ok`: 三类上游数据齐备
- `degraded`: 出现 `stale/missing` 任务状态，允许展示但需提示
- `error`: 快照不可读或聚合失败
