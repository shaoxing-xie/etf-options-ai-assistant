# Cron 自动修复可观测验收清单

用于每日快速判断三 skill 组合能力（`github` + `agent-team-orchestration` + `capability-evolver`）是否真正生效。

## 每日必看 3 项

1. 结构化判定是否齐全
   - `TEAM_RESULT=...`
   - `RISK=LOW|MEDIUM|HIGH`
   - `AUTOFIX_ALLOWED=true|false`

2. 证据链是否存在
   - `EVIDENCE_REF` 至少包含 1 个有效 runId/jobId/日志路径
   - 出现 TEAM_OK 时必须可回溯到 RAW 证据

3. 风险门控是否正确
   - 仅 `TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true` 才允许自动修复并发起 PR
   - `MEDIUM/HIGH` 仅建议，不自动改动

## 建议检查命令

```bash
# 1) 看质量兜底任务最近运行结果
openclaw cron runs quality-backstop-audit --limit 5

# 2) 看是否出现结构化字段
rg "TEAM_RESULT=|RISK=|AUTOFIX_ALLOWED=|EVIDENCE_REF=" ~/.openclaw/cron/runs -n

# 3) 看是否有低风险自动修复PR动作
rg "TEAM_OK|RISK=LOW|AUTOFIX_ALLOWED=true|gh pr create|github_create_pr" ~/.openclaw/cron/runs ~/.openclaw/agents -n
```

## 通过标准

- 最近 1 次兜底巡检包含完整结构化字段；
- 至少 1 条记录能展示有效证据链；
- 风险门控行为与策略一致（不存在 MEDIUM/HIGH 自动改代码情况）。
