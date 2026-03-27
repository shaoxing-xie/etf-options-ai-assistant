# Hybrid Trigger Mapping（事件优先 + 定时兜底）

本文给出三个 Skill 在五阶段中的触发映射，供 `jobs.json` / 手动调度 / agent-team-orchestration 调用时统一参考。

## 1. 映射总览

| 阶段 | 场景 | 触发方式 | 入口工作流 | 主责 Skill 组合 |
|---|---|---|---|---|
| 1 | CI gate 失败 | 事件驱动 | `ci_autofix_triage_on_demand.yaml` | orchestration + github(exec/gh) + evolver |
| 2 | Cron/任务异常 | 事件 + 定时兜底 | `quality_backstop_audit.yaml` | orchestration + evolver |
| 3 | 工具运行时 BUG | 事件 + 定时兜底 | `quality_backstop_audit.yaml` | orchestration + evolver |
| 4 | 预测准确性漂移 | 定时 + 阈值触发 | `quality_backstop_audit.yaml` | orchestration + evolver |
| 5 | 运维问题闭环 | 事件 + 定时复盘 | `quality_backstop_audit.yaml` | orchestration + github + evolver |

## 2. 任务定义建议（jobs.json）

每类任务均建议包含以下字段：

- `trigger_type`: `event` / `scheduled_backstop`
- `phase`: `1|2|3|4|5`
- `entry_workflow`: 对应 YAML 名称
- `contract_required`: `true`
- `risk_gate_enabled`: `true`

最小执行约束：

1. Builder 必须回传四段证据块。
2. Reviewer 无 RAW 证据直接 `TEAM_FAIL: NO_EVIDENCE`。
3. 非 `TEAM_OK + RISK=LOW` 禁止自动修复。

## 3. 失败闭环动作

- 失败码进入统一统计（按天/周）。
- Evolver 每次输出：
  - 问题分类
  - 标准排查命令
  - 是否允许自动修复（YES/NO）
  - 下次 checklist

