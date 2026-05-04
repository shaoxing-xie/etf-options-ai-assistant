# Cron ↔ Orchestrator 对表（parity）

维护方式：对 `~/.openclaw/cron/jobs.json` 运行

```bash
/home/xie/etf-options-ai-assistant/.venv/bin/python \
  /home/xie/etf-options-ai-assistant/scripts/export_orchestrator_cron_parity.py \
  --jobs ~/.openclaw/cron/jobs.json
```

## OpenClaw 载荷说明（重要）

当前 OpenClaw `CronPayloadSchema` **仅允许** `payload.kind` 为 `agentTurn` 或 `systemEvent`，**不存在**顶层 `payload.kind: "exec"`。  
因此「exec 迁移」在现网表现为：**`agentTurn` + `toolsAllow: ["exec"]` + message 内嵌整行 `/bin/bash -lc "… orchestrator_cli.py …"`**（与既有 `code-daily-health-check` 等任务一致）。

## 全量迁移（2026-05-04）

- **生成 / 再生成**（会写 `config/tasks_registry.cron_jobs.yaml`、agent 载荷与 `config/cron_agent_messages/*`；`--write-all` 会先备份 `jobs.json` 为 `jobs.json.bak` 再改 payload）：
  ```bash
  /home/xie/etf-options-ai-assistant/.venv/bin/python \
    /home/xie/etf-options-ai-assistant/scripts/sync_cron_to_orchestrator.py --write-all
  ```
- **每条 Cron** 对应 Registry 任务 id：**`cron__` + `job_id` 中 `-` 改为 `_`**（与 `orchestrator_cli.py run` 参数一致）。
- **长 Agent 载荷**（3 条：`ops-health-merged-aedca0060dd8`、`etf-backtesting-research-on-demand`、`manual-once-screening-emergency-stop`）：由 `scripts/run_openclaw_agent_cron_payload.py` 读 manifest + 落盘 message 执行 `openclaw agent --local`。
- **演化周任务**（2 条）：Registry 步为 `evolution_workflows_dry_run.sh factor|strategy`（替代原先易触发 context overflow 的全量 Agent 提示）。

## 已迁移条目（示例：`daily_health` 链）

| job_id | name | schedule (cron) | task_id（Registry） | context / 备注 |
|--------|------|-------------------|---------------------|----------------|
| `quality-backstop-audit` | quality: 质量兜底巡检（定时） | `30 16 * * 1-5` Asia/Shanghai | `cron__quality_backstop_audit` → 内层仍执行原 `daily_health` bash | 全量迁移后外层统一 `cron__*`；内层 command 仍含 `orchestrator_cli.py run daily_health --trade-date …`（与迁移前语义一致） |

**`quality-backstop-audit` 内层 command（摘要）**：仍为 `orchestrator_cli.py run daily_health --trade-date $(date -d yesterday …)`，定义在自动生成的 `cron__quality_backstop_audit` 任务第一步 exec（见 `tasks_registry.cron_jobs.yaml`）。

### 与旧 CLI 的差异

- **旧**：`scripts/run_quality_backstop_audit_cli.py`（内部 `semantic_quality_backstop_audit.py --no-notify` + 合并飞书摘要等）。
- **新**：`orchestrator_cli.py run daily_health`（`config/tasks_registry.yaml`：catalog_digest → attempts 占位 → `semantic_quality_backstop_audit.py --no-notify`）。

### 回滚（恢复旧 exec 命令）

将 `quality-backstop-audit` 的 `payload.message` 中 **command** 改回：

```bash
/bin/bash -lc "set -euo pipefail; set -a; source /home/xie/.openclaw/.env || true; set +a; cd /home/xie/etf-options-ai-assistant; /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/run_quality_backstop_audit_cli.py"
```

并把 `description` 改回描述 `run_quality_backstop_audit_cli.py` 的文案即可。

## 变更记录

- **2026-05-04**：`quality-backstop-audit` 切换为 `orchestrator_cli.py run daily_health`（`schedule` 未改）。
- **2026-05-04（最优）**：`payload.timeoutSeconds` 调至 **2400**；message 内 **yieldMs 建议 1800000**（对齐 Registry 步骤超时之和 1200s + 重试/启动余量）；命令去掉对 `daily_health` 无效的 `--no-file-lock`。
- **2026-05-04（全量）**：`jobs.json` 共 47 条 `agentTurn` 统一为 `exec.arguments` + `orchestrator_cli.py run cron__*`；`src/orchestrator/registry.py` 自动合并 `tasks_registry.cron_jobs.yaml`。
