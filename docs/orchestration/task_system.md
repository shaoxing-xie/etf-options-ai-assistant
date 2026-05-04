# 任务编排系统（v0.6）

## 目标完成度（核心原则）

方案所述「时点不变、底层统一编排」在 **Cron 全量** 上的完成度与缺口表：[`l4_orchestration_goal_status.md`](l4_orchestration_goal_status.md)；机器生成表见 `scripts/inventory_cron_registry_gap.py`。

## 单一事实源

- **任务定义**：[`config/tasks_registry.yaml`](../../config/tasks_registry.yaml)
- **执行入口**：`scripts/orchestrator_cli.py`（`run` / `list`）
- **实现包**：`src/orchestrator/`（`DAGExecutor`、`gate`、Registry 加载）
- **运行落盘**：`data/semantic/task_runs_v1/{YYYY_MM_DD}/{run_id}.json`（`task_run_record_v1`）

## 回滚开关

1. **Registry 总开关**：`tasks_registry.yaml` 顶层 `orchestrator.enabled: false` 时，CLI 返回 `orchestrator_disabled_in_registry`。
2. **单任务开关**：各 `tasks[].enabled: false`。
3. **Cron**：保持原 `tool_run_*` 的 `jobs.json` 条目，不改为 `exec` 即回滚到旧路径（时间保持，§2.1）。

## 时间保持与 `cron_parity` 对表

现网对表明细与回滚命令见 **[`cron_parity.md`](cron_parity.md)**（随 `jobs.json` 变更更新）。

迁移时 **不要删改 `schedule`**，只把执行体换为：

```bash
/bin/bash -lc 'set -a; source /home/xie/.openclaw/.env || true; set +a; cd /home/xie/etf-options-ai-assistant && /home/xie/etf-options-ai-assistant/.venv/bin/python scripts/orchestrator_cli.py run daily_health'
```

**对表模板**（复制到表格维护）：

| job_id（OpenClaw） | cron expr | task_id（Registry） | context JSON | 备注 |
|--------------------|-----------|---------------------|--------------|------|
| （填） | （填） | daily_health | `{}` | 示例 |

## 非交易日调试

须使用 **`--trade-date=上一交易日`**（见仓库规则 §6.1），避免假日误报缺数据。

## 跨任务依赖（拓扑 + 环检测）

- `tasks[].dependencies` 列出必须先成功的任务 id；`DAGExecutor` 按 **Kahn 拓扑序** 先跑依赖再跑目标任务。
- **环**或**未知依赖**：执行失败，`message` 为 `dependency_cycle` 或 `unknown_dependency:<id>`。
- 多任务一次执行时，落盘 `payload.dependency_execution_order` 记录顺序；步骤 `step_id` 形如 `parent_task::step_id`。
- **禁用依赖**：若依赖链上任一任务 `enabled: false`，返回 `dependency_disabled:<id>`。

## B+C 管道与 monitor phase

- **共享缓存键**：与 `tool_run_data_cache_job` 的 `job` 参数一致；Cron 可通过 `--context '{"job":"intraday_minute"}'` 注入；**`profile`** 键在无 `job` 时映射为同一 `job` 参数（别名）。
- **monitor phase**：`unified_intraday` 示例步骤使用 `params_from_context: [phase]`，由 `--context '{"phase":"midday"}'` 覆盖 YAML 默认 `phase`。
- **§9 同刻争用**：`tasks[].concurrency.file_lock: true` 时，非 dry-run 对 `data/meta/orchestrator_locks/<task>_<trade_date>_<job>.lock` 使用 **fcntl 建议锁**；超时见 `lock_acquire_timeout_seconds`。测试或紧急旁路：`ORCHESTRATOR_NO_FILE_LOCK=1` 或 CLI **`--no-file-lock`**（写入 `context.skip_file_lock`）。

## 现网 jobs 对表导出（仓库侧）

```bash
python scripts/export_orchestrator_cron_parity.py --jobs ~/.openclaw/cron/jobs.json
python scripts/export_orchestrator_cron_parity.py --jobs ~/.openclaw/cron/jobs.json --json
```

生成 Markdown/JSON 表（含 `references_orchestrator`），供 **cron_parity** 归档；**不修改** `jobs.json`。

## Phase3（可选范围，方案 p3）

策略深化 / paper trading / 机构导出等：**不在本仓库默认交付**；若启用须单独走契约（`schema_registry` / `task_data_map` / `data_contract_version`）与受影响任务评审。

## Chart 只读 API

- `GET /api/orchestrator/task-runs?trade_date=&limit=50`
- 别名：`GET /api/orchestrator/task-dashboard`（同上）
- 响应 `data` 含 `runs` 与 `summary`（`run_count`、`step_ok_ratio_avg`、`unique_task_ids`、`task_run_schema_coverage_ratio` 等，便于面板聚合）

## Phase 门闸与终局测试

见仓库方案 §6.2 / §8.3。最小可复现命令集：

**Phase1 门闸（`gate-phase1`）**

```bash
cd /home/xie/etf-options-ai-assistant
.venv/bin/python -m pytest \
  tests/test_orchestrator_registry.py tests/test_orchestrator_gate.py \
  tests/test_orchestrator_dag_dry_run.py tests/test_orchestrator_dag_dependencies.py \
  tests/test_orchestrator_daily_health_budget.py tests/test_orchestrator_context_inject.py \
  tests/integration/test_orchestrator_cli_smoke.py tests/integration/test_orchestrator_task_runs_api.py \
  tests/integration/test_export_cron_parity.py -q
.venv/bin/python scripts/orchestrator_cli.py list
.venv/bin/python scripts/orchestrator_cli.py run daily_health --dry-run --trade-date YYYY-MM-DD
# scripts/test_cron_tools.sh 开头会自动跑 orchestrator_cli list + dry-run（可用 ORCHESTRATOR_SMOKE=0 跳过）
```

**Phase2 门闸（`gate-phase2`）**：在 Phase1 命令全绿基础上，全量 `pytest` 或至少 `apps/chart_console` + orchestrator 相关用例再跑一轮。

**Phase3（可选，`p3-optional-scope`）**：策略深化 / paper trading / 机构导出等仅在与契约变更联动时启用。

**终局 QA（§8.3，`final-qa-833`）**：单元 + 集成测试通过；按 `cron_parity` 表逐任务核对 schedule；归档最近一次 `run_id` 与 orchestrator 退出码；对现网 jobs 运行 `scripts/export_orchestrator_cron_parity.py` 导出并随发布说明附上 `references_orchestrator` 列。

## 示例：仅合并一条 Cron（勿直接覆盖整文件）

本地示例片段：[`config/openclaw_orchestrator_exec.example.json`](../../config/openclaw_orchestrator_exec.example.json)
