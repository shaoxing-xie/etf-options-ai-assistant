# Failure Codes（失败码规范）

本文定义三个 Skill 协同流程中的统一失败码、触发条件、处理动作与是否允许自动修复。

## 1. 失败码列表

| Code | 含义 | 典型触发 | 自动修复 |
|---|---|---|---|
| `LOG_FETCH_FAILED` | 失败日志获取失败 | `gh run view --log` 为空，且 `gh api .../logs` 也失败 | 否 |
| `NO_EVIDENCE` | 无原始证据 | Builder 未提供 `RAW_OUTPUT` | 否 |
| `DUAL_EVIDENCE_INCOMPLETE` | 双轨证据缺一 | 研究类演化缺少 `[LOCAL_EVIDENCE]` 或 `[EXTERNAL_REFS]`（含有效 `https://`），或 `EVIDENCE_REF` 未同时锚定本地与外部 | 否 |
| `UNKNOWN_CAUSE` | 原因未知 | 有证据但无法定位根因 | 否 |
| `FIX_RISK_HIGH` | 修复风险高 | Reviewer 判定 `RISK=MEDIUM/HIGH` | 否 |
| `LOCAL_REPRO_FAILED` | 本地复现失败 | 无法稳定复现实例或验证修复 | 否 |
| `CI_RERUN_FAILED` | CI 重跑失败 | 修复后 rerun 仍失败 | 视风险而定（默认否） |

## 2. 状态判定规则

- 仅当 Reviewer 输出 `TEAM_OK` 且 `RISK=LOW`，流程可进入自动修复。
- 任一失败码都必须触发 Orchestrator 的“停止推进”分支。
- 失败码不得被自由文本替代，必须保留标准编码。

## 3. 失败码与动作映射

| Code | Orchestrator 动作 | Builder 动作 | Reviewer 动作 | Evolver 动作 |
|---|---|---|---|---|
| `LOG_FETCH_FAILED` | 停止，转日志兜底流程 | 切换 logs zip runbook | 标记证据缺失 | 记录数据通道失效模式 |
| `NO_EVIDENCE` | 停止，要求重跑取证 | 重新执行并补齐四段输出 | 返回 `TEAM_FAIL:NO_EVIDENCE` | 追加“证据完整性检查” |
| `DUAL_EVIDENCE_INCOMPLETE` | 停止，要求补本地或补检索 | 补齐 RAW 内 LOCAL/EXTERNAL 小节并重跑最小验证命令 | 返回 `TEAM_FAIL` 并列出缺哪一脚 | 记入 Checklist：演化必双修 |
| `UNKNOWN_CAUSE` | 停止自动修复，升级人工 | 扩展采样与对比命令 | 返回 `TEAM_FAIL:UNKNOWN_CAUSE` | 记录新故障类别候选 |
| `FIX_RISK_HIGH` | 停止自动修复，走审批 | 输出变更方案不直接改 | 返回风险与影响面 | 更新风险边界策略 |
| `LOCAL_REPRO_FAILED` | 停止合并，要求补复现 | 提供最小复现步骤 | 标记验证不充分 | 记录复现门槛与环境依赖 |
| `CI_RERUN_FAILED` | 回退并升级问题等级 | 收集新 run 证据 | 重新归因 | 更新“修复后二次失败”模板 |

## 4. 输出规范（失败场景）

失败时推荐最小输出：

```text
TEAM_FAIL: <FAILURE_CODE>
ROOT_CAUSE: <已知则填，未知写 UNKNOWN>
NEXT_ACTION: <下一步动作，必须可执行>
```

## 5. 扩展规则

- 新增失败码必须满足：
  - 可重复识别；
  - 对应明确处置动作；
  - 可用于 Evolver 统计学习。
- 新失败码需同步更新：
  - `execution_contract.md`
  - Prompt 模板
  - 相关 runbook/checklist

