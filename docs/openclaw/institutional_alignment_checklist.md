# 机构级对齐自检（轻量清单）

非法律或合规认证；用于个人/小团队 **可审计性、可恢复性、运营纪律** 自检。与 `workflows/quality_backstop_audit.yaml`、`config/evolution_invariants.yaml`、`docs/openclaw/execution_contract.md` 交叉引用。

## 任务与可观测

- [ ] 关键任务（如 9:28 开盘、15:30 盘后、16:30 日报）在运维侧有 **期望完成窗** 或 **迟到告警**（不仅依赖 20:30 `quality_backstop_audit`）。
- [ ] Cron / Gateway 失败有 **可查询日志**（runId、jobId 与 `EVIDENCE_REF` 类字段见各 on_demand 契约）。

## 数据与血缘

- [ ] 对外报告或信号在可能范围内附 **数据快照时间**、**配置/权重版本**（与 `tool_strategy_engine` 的 `inputs_hash`、`prediction_records` 等一致）。
- [ ] 核心行情步骤失败时，下游 **不发误导性信号** 或明确标注「数据不足」（参见巡检模板与 `continue_on_failure` 使用场景）。

## 环境分级

- [ ] 生产定时任务 **禁止** 用 `test` 模式冒充已投递钉钉（见 `docs/openclaw/dingtalk_delivery_contract.md`）。

## 职责与变更

- [ ] 研究类工作流标注「研究级」；**自动 PR / 演化** 不直接 merge `main`（见三 Skill 与 `cron_error_autofix_on_demand`）。
- [ ] 双轨工作流（`etf_rotation_research` vs `*_agent` 等）在 **jobs.json 仅启用其一**。

## 外部事件

- [ ] 重大事件日前后，考虑 **`tool_event_sentinel`** 与政策/新闻类工具互补（见 `workflows/README.md` 可选步骤说明）。
