# OpenClaw Agent 维护速查（5分钟）

适用场景：任务路由调整后快速同步、快速校验、快速复测。

## 一键流程（按顺序执行）

1) 同步受管 Agent 与任务映射

```bash
python scripts/render_agents_config.py --apply-jobs
```

2) 做矩阵校验（技能/路由/边界）

```bash
python scripts/validate_agent_skill_matrix.py
```

3) 做边界快速校验（交互 Agent 不承载 cron）

```bash
python scripts/validate_cron_agent_boundaries.py --jobs ~/.openclaw/cron/jobs.json
```

4) 重启 Gateway 使配置生效

```bash
openclaw gateway restart
```

5) 核验任务列表（抽查关键任务）

```bash
openclaw cron list | rg "每日市场分析报告|巡检快报|backstop|轮动研究|price-alert"
```

## 日报任务复测（关键）

```bash
bash scripts/test_cron_tools.sh --mode cron --filter "^8c548101-85b7-4c95-a458-8b0e15317d46$" --wait-finished --verify-send --expect-final --include-send
```

## 常见结果判定

- `validate_agent_skill_matrix: PASS`：技能和映射结构正确
- `PASS: no cron-agent boundary violations.`：`etf_main`/`etf_analysis_agent` 已无 cron 承载
- `VERIFY_SEND: PASS`：该任务发生了发送工具成功调用

## 常见故障快速处理

- 报 `missing required skills`
  - 检查 `config/agents/cron_agents.yaml` 的 `requiredSkills` 是否配置正确
  - 重新执行 render + validate

- 报 `enabled job bound to blocked agent`
  - 检查 `jobAgentMapping` 是否遗漏
  - 重新执行 `python scripts/render_agents_config.py --apply-jobs`

- `cron list` 仍显示旧 agent
  - 执行 `openclaw gateway restart`
  - 再次 `openclaw cron list`

