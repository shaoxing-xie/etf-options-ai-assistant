# sentiment_snapshot_v1

- 数据集说明：盘前情绪检查的标准化快照，面向研究台和风控门闸解释。
- Schema：`sentiment_snapshot_v1`（L4）
- 更新频率：交易日盘前（通常 09:10 后）
- SLA：交易日 10:00 前可读；超时标记为时效风险
- 路径：`data/semantic/sentiment_snapshot/YYYY-MM-DD.json`
- 依赖任务：`pre-market-sentiment-check`
- 回放：`GET /api/semantic/dashboard`（主锚）或读取对应日快照文件

## 关键字段

- `overall_score`: 综合情绪分
- `sentiment_stage`: 情绪阶段标签
- `sentiment_dispersion`: 分歧度
- `degraded`: 是否降级
- `_meta`: 契约元信息（版本、质量、血缘、交易日）

## 降级语义

- `ok`: 数据源完整且评分有效
- `degraded`: 部分上游缺失或兜底逻辑触发
- `error`: 文件损坏/结构不合法/无法读取
