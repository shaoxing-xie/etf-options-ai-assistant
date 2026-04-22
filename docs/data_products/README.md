# 语义数据产品目录（L4）

- `sentiment_snapshot_v1`
  - 业务含义：盘前情绪快照（温度、阶段、分歧、降级标记）
  - 更新频率：交易日 1 次（盘前任务后）
  - 路径：`data/semantic/sentiment_snapshot/YYYY-MM-DD.json`
  - Owner：投研数据产品负责人（Research Data Owner）

- `screening_candidates_v1`
  - 业务含义：夜盘候选池标准化快照（候选列表 + 质量摘要）
  - 更新频率：交易日 1 次（夜盘任务后）
  - 路径：`data/semantic/screening_candidates/YYYY-MM-DD.json`
  - Owner：选股引擎负责人（Screening Engine Owner）

- `screening_view_v1`
  - 业务含义：研究台聚合视图（夜盘/尾盘/效果/监控/板块热度）
  - 更新频率：交易日多次（支持按日回放）
  - 路径：`data/semantic/screening_view/YYYY-MM-DD.json`
  - Owner：图表工作台负责人（Chart Console Owner）

- `ops_events_view_v1`
  - 业务含义：执行审计 + 采集质量事件
  - 更新频率：交易日 1 次快照 + 按需实时聚合
  - 路径：`data/semantic/ops_events/YYYY-MM-DD.json`
  - Owner：运维数据产品负责人（Ops Data Owner）

统一口径：
- `_meta.quality_status`: `ok | degraded | error`
- 回放方式：API 统一支持 `?trade_date=YYYY-MM-DD`
- 证据入口：`data/meta/evidence/` 与 `data/meta/monitoring/`
