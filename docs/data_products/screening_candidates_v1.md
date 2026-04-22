# screening_candidates_v1

- 数据集说明：夜盘候选证券快照，统一输出候选数组与质量摘要。
- Schema：`screening_candidates_v1`（L4）
- 更新频率：交易日夜盘 1 次
- SLA：交易日 22:00 前可回放
- 路径：`data/semantic/screening_candidates/YYYY-MM-DD.json`
- 依赖任务：`nightly-stock-screening`
- 回放：`GET /api/semantic/screening_candidates?trade_date=YYYY-MM-DD`

## 关键字段

- `run_date`: 交易日
- `candidates[]`: 候选证券列表（symbol/score/...）
- `summary.quality_score`: 质量分
- `summary.degraded`: 是否降级
- `artifact_ref`: 对应原始审计产物引用
- `_meta`: 契约元信息（版本、质量、血缘、交易日）

## 降级语义

- `ok`: 夜盘候选可用
- `degraded`: 因子缺失或数据质量不足但可输出候选
- `error`: 快照缺失或结构错误
