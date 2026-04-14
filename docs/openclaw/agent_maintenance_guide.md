# OpenClaw Agent 维护指南

本文档用于说明如何维护 Cron 执行 Agent，并保持任务路由稳定、可追踪。

> 快速执行版请先看：`docs/openclaw/agent_maintenance_quickstart.md`

## 背景与目的

近期故障主要来自两类问题：

- 工作流串线（例如：日报任务跑进巡检流程）
- 任务显示完成，但未发生投递（finished-but-no-delivery）

为避免回归，本仓采用“单一事实源 + 自动渲染 + 自动校验”的维护方式。

## 单一事实源

- `config/agents/cron_agents.yaml`

该文件统一定义：

- 禁止承载 cron 的交互型 Agent（`blockedCronAgents`）
- 受管的 cron 执行 Agent（`managedAgents`）
- 任务到 Agent 的映射（`jobAgentMapping`）
- 每个受管 Agent 的必需技能（`requiredSkills`）

## 维护工具

### 1）渲染脚本（初始化/同步 Agent 与任务映射）

- 脚本：`scripts/render_agents_config.py`
- 常用示例：
  - `python scripts/render_agents_config.py`
  - `python scripts/render_agents_config.py --apply-jobs`
  - `python scripts/render_agents_config.py --dry-run --json`

作用说明：

- 将受管 `etf_cron_*` Agent 同步到 `~/.openclaw/openclaw.json`（存在则更新，不存在则创建）
- 将 YAML 中 `requiredSkills` 覆盖到对应受管 Agent
- 可选把 `jobAgentMapping` 同步到 `~/.openclaw/cron/jobs.json`

### 2）矩阵校验脚本（技能 + 路由 + 边界）

- 脚本：`scripts/validate_agent_skill_matrix.py`
- 常用示例：
  - `python scripts/validate_agent_skill_matrix.py`
  - `python scripts/validate_agent_skill_matrix.py --json`

校验内容：

- 每个受管 Agent 是否存在于 `openclaw.json`
- 每个受管 Agent 是否具备 YAML 要求的 `requiredSkills`
- 启用任务是否错误挂在 `blockedCronAgents` 上
- YAML 中映射任务是否与 `jobs.json` 的 `agentId` 一致

### 3）边界快速校验（轻量门禁）

- 脚本：`scripts/validate_cron_agent_boundaries.py`
- 示例：
  - `python scripts/validate_cron_agent_boundaries.py --jobs ~/.openclaw/cron/jobs.json`

## 日常维护推荐流程

1. 只改 `config/agents/cron_agents.yaml`
2. 执行渲染：
   - `python scripts/render_agents_config.py --apply-jobs`
3. 执行校验：
   - `python scripts/validate_agent_skill_matrix.py`
   - `python scripts/validate_cron_agent_boundaries.py --jobs ~/.openclaw/cron/jobs.json`
4. 重启 Gateway 使配置生效：
   - `openclaw gateway restart`
5. 使用 `scripts/test_cron_tools.sh` 对关键任务做冒烟回归

## 维护策略（必须遵守）

- `etf_main` 与 `etf_analysis_agent` 为交互通道 Agent，不承载 cron 执行任务
- Cron 执行任务统一挂到专用 `etf_cron_*` Agent
- 若任务中未发生发送工具调用，必须显式失败（`ERROR_NO_DELIVERY_TOOL_CALL`）

## 故障排查

### 校验失败：缺少必需技能（missing required skills）

- 先检查并修正 `config/agents/cron_agents.yaml` 的 `requiredSkills`
- 再执行渲染脚本同步到 `openclaw.json`

### 校验失败：任务挂在禁止 Agent（enabled job bound to blocked agent）

- 修正 `config/agents/cron_agents.yaml` 中 `jobAgentMapping`
- 重新执行 `render_agents_config.py --apply-jobs`

### 已修改但 `cron list` 仍显示旧 Agent

- 执行 `openclaw gateway restart`
- 再次执行 `openclaw cron list` 确认生效

