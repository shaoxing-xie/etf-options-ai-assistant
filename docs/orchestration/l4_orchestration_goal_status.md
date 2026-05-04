# L4 编排优化：目标完成度（与方案核心原则对齐）

## 核心原则（验收口径）

> YAML/workflow 数量从约 40 收敛到**少量逻辑编排单元**，**不意味着减少 Cron 触发次数或改动业务期望的时点**。执行节奏可与现网一致：每个原时点仍可独立触发，只是底层改为 **统一编排 + 共享数据管道 + L4**，替代「分散脚本各自为政」。

**据此推导的「目标完成」判据（Cron 侧）**：

1. **时点**：每条 `jobs.json` 的 `schedule` 与现网对表一致（或经书面评审的 stagger 例外）。
2. **执行体**：同一业务时点对应的 **shell 入口** 收敛为 **`orchestrator_cli.py run <task_id>`**（或经评审的少数豁免项并记录在案），且 `<task_id>` 定义在 **`config/tasks_registry.yaml`** 与/或自动合并的 **`config/tasks_registry.cron_jobs.yaml`**（Cron 镜像任务 `cron__*`；由 `scripts/sync_cron_to_orchestrator.py` 自 `jobs.json` 生成）。
3. **数据管道**：B/C 类采集与监控在 Registry 中可表达为 **`data_pipeline` / `unified_intraday` 等 + `context`**，避免多条 Cron 各自拼不同脚本口径。
4. **L4**：语义与运行摘要走契约化落盘（如 `task_run_record_v1`、`data/semantic/*`），展示层只读语义层（项目既有硬规则）。

**当前结论（2026-05-04）**：`~/.openclaw/cron/jobs.json` **47/47** 条 `agentTurn` 任务已统一为「单 `exec` + `orchestrator_cli.py run cron__<job_id>`」；镜像任务与载荷见 **`config/tasks_registry.cron_jobs.yaml`**、`config/cron_agent_payload_manifest.json` 与 `config/cron_agent_messages/*`。对表命令：`scripts/inventory_cron_registry_gap.py` 统计「已 orchestrator_cli」应为 **47**。

## 已完成（可复用资产）

- `config/tasks_registry.yaml`、`config/tasks_registry.cron_jobs.yaml`（合并加载）、`src/orchestrator/*`、`scripts/orchestrator_cli.py`
- `quality-backstop-audit` 内层仍为 `daily_health`；外层与其它 Cron 一致走 `cron__*` 入口
- 对表与回滚：`docs/orchestration/cron_parity.md`
- 缺口清单（机器生成）：`scripts/inventory_cron_registry_gap.py` → 见下一节命令

## 下一步（可选收敛）

1. 将多条 `cron__*` 中重复的 **exec /bash** 进一步合并为少量共享 task（如统一 `data_pipeline` + `--context`），减少 `tasks_registry.cron_jobs.yaml` 体积；**须自 `jobs.json.bak` 或现网备份再跑** `sync_cron_to_orchestrator.py`，避免对已迁移 message 二次解析造成自引用。
2. 演化周任务当前为 `evolution_workflows_dry_run.sh` 确定性入口；若需恢复「全量多 Agent」语义，须在评审后改 Registry 步并单独验收。

## 生成迁移缺口表

```bash
/home/xie/etf-options-ai-assistant/.venv/bin/python \
  /home/xie/etf-options-ai-assistant/scripts/inventory_cron_registry_gap.py \
  --jobs ~/.openclaw/cron/jobs.json
```

将输出 Markdown 表：**当前路径**、**建议 Registry task_id**、**是否已满足目标判据**。

**方案正文对齐**：`~/.cursor/plans/l4_orchestration_v0.6_6275161b.plan.md` 已更新 **§1 实施后归档**、**§8.1～§8.3 勾选**（与仓库现状一致；未达标项在方案内标为待办）。
