---
name: ota_ci_autofix_runbook
description: CI 失败取证：拉 GitHub Actions 日志、对照 failure_codes；衔接 ci_autofix_triage_on_demand 与 gh api 路径。
---

# OTA：CI 自动修复 Runbook

## 何时使用

- `workflows/ci_autofix_triage_on_demand.yaml` 或人工处理 **GitHub Actions 失败**。

## 规程

1. **先取证**：拉取对应 run 的日志（zip 或 `gh api`）；步骤见 runbook。
2. **再分类**：对照 `docs/openclaw/failure_codes.md` 与 `execution_contract.md` 输出块。
3. **后动作**：仅低风险按工作流进入修复与 PR；否则只出报告。

## 权威文档

- `docs/openclaw/runbooks/github_actions_log_fetch.md`
- `docs/openclaw/cron_autofix_observability.md`（三 Skill 观测）
- `docs/openclaw/execution_contract.md`

## 相关工具

- `gh`、`exec`（以本机 OpenClaw 安全策略为准）
