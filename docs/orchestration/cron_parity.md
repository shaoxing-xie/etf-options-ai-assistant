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

## T2：`tool_l4_*` 附录（定点接入）

- **开关**：`ASSISTANT_INCLUDE_L4_SNAPSHOT=1`（默认）在下列链路附加报告/产物末尾 **`## L4 / 估值摘要`**（`report_l4_snapshot_attachment_v1`）；`0`/`false`/`off` 关闭，正文与旧版一致（parity 基线）。
- **失败策略**：L4 调用失败时降级（`quality_status` 在 `l4_snapshot._meta` / `l4_attachment._meta`），**不阻断**主报告核心段落。
- **分档清单**：见 [`t2_l4_tier_matrix.md`](t2_l4_tier_matrix.md)。

| job_id | 锚点入口 | L4 挂载 |
|--------|-----------|---------|
| `etf-rotation-research` | `tool_etf_rotation_research` / `report_data` | Top5 标的批量估值+PE |
| `position-tracking` | `position_tracking_and_persist.py` | 观察池 symbols |
| `strategy-calibration` | `strategy_calibration_and_persist.py` | 飞书定调消息附录 |
| `weekly-selection-review` | `weekly_selection_review_and_persist.py` | `weekly_review.json` → `l4_attachment` |
| `intraday-tail-screening` | `intraday_tail_screening_and_persist.py` | 推荐列表标的；飞书通知追加附录 |
| `nightly-stock-screening` | `nightly_screening_and_persist.py` | 打分 Top 标的 → `nightly_*.json` payload |
| `8c548101-85b7-4c95-a458-8b0e15317d46` | `tool_analyze_after_close_and_send_daily_report` | 日报 ETF 清单 |
| `f0d82a29-45de-4377-9570-5dda65b3f58a` | `tool_run_opening_analysis_and_send`（legacy variant） | 开盘采集 ETF |
| `8f2ef8c2-4d0e-4df4-b3ad-3524d74b47be` | `tool_run_opening_analysis_and_send`（realtime variant） | 同上 |
| `etf-midday-recap-1200` | `tool_run_midday_recap_and_send` | 固定宽基 ETF |

## 变更记录

- **2026-05-04**：`quality-backstop-audit` 切换为 `orchestrator_cli.py run daily_health`（`schedule` 未改）。
- **2026-05-04（最优）**：`payload.timeoutSeconds` 调至 **2400**；message 内 **yieldMs 建议 1800000**（对齐 Registry 步骤超时之和 1200s + 重试/启动余量）；命令去掉对 `daily_health` 无效的 `--no-file-lock`。
- **2026-05-04（全量）**：`jobs.json` 共 47 条 `agentTurn` 统一为 `exec.arguments` + `orchestrator_cli.py run cron__*`；`src/orchestrator/registry.py` 自动合并 `tasks_registry.cron_jobs.yaml`。
