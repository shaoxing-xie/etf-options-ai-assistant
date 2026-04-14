# 工作流 Cron 时间线（交易日摘要）

与 `workflows/README.md`、本机 `~/.openclaw/cron/jobs.json` 对照使用；**以 jobs.json 为运行真源**，下表为仓库 YAML 常见约定。

## 工作日（周一至周五）

| 本地时间（Asia/Shanghai） | 工作流 / 任务 | 渠道与备注 |
|---------------------------|---------------|------------|
| ~9:15 | 早盘数据采集（多无单独 YAML；见 jobs.json） | 飞书运维摘要；**非** 16:30 日报 |
| 9:20 | `before_open_analysis` | 盘前机构晨报 |
| 9:28 | `opening_analysis` | 钉钉；开盘独立完整版 |
| 9:00–15:00 | `intraday_analysis`（每 15 分钟） | 分钟/期权/Greeks 等 |
| 9:00–15:00 | `signal_generation`（每 30 分钟） | 读日线缓存 |
| 9:00–15:00 | `etf_510300_intraday_monitor`（每 5 分钟，错开采集） | 仅读本地缓存；飞书建议级 |
| 见 jobs.json | `signal_risk_inspection`（早盘/午盘/下午模板） | 钉钉巡检快报 |
| 15:30 | `after_close_analysis_enhanced` | 盘后增强 |
| 15:35 | `prediction_verification` | 预测校验 |
| 15:40 | `limitup_pullback_after_close` | 涨停回马枪盘后 |
| 16:30 | `daily_market_report` | 每日市场分析（钉钉）；**勿与早盘/开盘混用** |
| 18:00 | `etf_rotation_research`（管道版） | 与 agent 版二选一 |
| 18:10 | `etf_rotation_research_agent` | 与管道版二选一 |
| 20:30 | `quality_backstop_audit` | 质量兜底 |

## 周五额外

| 时间 | 工作流 | 备注 |
|------|--------|------|
| 18:00 | `strategy_evaluation` | 策略评分 |
| 18:15 | `strategy_weight_adjustment` | 权重调整（在评分之后） |
| 19:00 | `strategy_research` | 工具管道版 |
| 19:10 | `strategy_research_playback` | agentTurn；与管道版二选一 |

## 重叠与资源提示

- **盘中**：`intraday_analysis`、`signal_generation`、`etf_510300_intraday_monitor` 均可能计算 510300 相关指标 — 数据源与频率不同（实时 vs 日线缓存 vs 本地分钟缓存），属**分层设计**；若需降载，在 jobs.json 中互斥或拉长间隔。
- **策略融合**（可选）：Agent 内 `strategy_fusion` 常见 `*/30 9-15 * * 1-5`，与 `signal_generation` 30 分钟可能同频；二者目的不同（融合 vs 单路信号），见 `docs/architecture/strategy_engine_and_signal_fusion.md`。
