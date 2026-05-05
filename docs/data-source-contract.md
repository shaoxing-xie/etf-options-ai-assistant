# 数据源与工具返回契约（助手侧）

## 原则

- 行情采集优先经 **OpenClaw 插件**（`openclaw-data-china-stock`）登记的 `tool_fetch_*` / `tool_run_data_cache_job` 及本仓库 **合并工具** `plugins/merged/*`（与插件采集链同源）。
- 失败时返回稳定 **`error_code`** 与 **`quality_status`**（`ok` / `degraded` / `error`），枚举与说明见仓库根下 [`data/meta/error_codes.yaml`](../data/meta/error_codes.yaml)。

## `tool_read_market_data`

- 返回体始终包含 **`_meta`**：`schema_name`=`tool_read_market_data`、`schema_version`、`quality_status`（`ok` / `degraded` / `error`）。
- 失败时额外包含 **`error_code`**（与 [`data/meta/error_codes.yaml`](../data/meta/error_codes.yaml) 中枚举一致，如 `INVALID_PARAMS`、`CACHE_MISS`、`NO_DATA`）。
- 单类型请求透传 `read_cache_data` 结果并补齐上述字段；多类型请求在部分失败时 `quality_status=degraded`、`error_code=UPSTREAM_FETCH_FAILED`。

## 推荐失败体（JSON）

```json
{
  "success": false,
  "error_code": "UPSTREAM_FETCH_FAILED",
  "quality_status": "error",
  "message": "human readable",
  "_meta": { "schema_name": "...", "schema_version": "..." }
}
```

## 插件侧缓存、预热与熔断（`openclaw-data-china-stock` ≥ 0.5.12）

- **进程内 TTL/LRU**：`plugins/utils/cache.py`（含资金流二次内存缓存）；高频工具勿重复自建 TTLCache。
- **磁盘预热**：插件仓库 `config/preheat_config.yaml` + `scripts/preheat_cache.py`，摘要落盘 `data/meta/preheat_result.json`；默认关闭 `preheat.enabled`。
- **Cron（宿主）**：在 `~/.openclaw/cron/jobs.json` 增加 exec 时须 **`bash -lc`**、**`set -a; source /home/xie/.openclaw/.env; set +a`**，并用插件 venv 绝对路径调用预热脚本，例如：
  - `/home/xie/.openclaw/extensions/openclaw-data-china-stock/.venv/bin/python`（或克隆路径下的 `.venv`）  
  - `.../scripts/preheat_cache.py --config .../config/preheat_config.yaml`
- 与本机 `jobs.json` 对齐的 job 片段归档：[`config/openclaw_cron_plugin_preheat_job.example.json`](../config/openclaw_cron_plugin_preheat_job.example.json)（合并时注意 id 唯一与分类排序约定）。
- **熔断**：环境变量 `OPENCLAW_CIRCUIT_BREAKER_ENABLED=1` 启用；OPEN 时返回 `error_code=CIRCUIT_OPEN`，**非静默成功**。全球指数抓取已在各 provider 外包一层（`global_index_spot:<provider>`）。
- **动态源 tie-break（可选）**：`config/source_priority.yaml` 默认 `dynamic_priority_enabled: false`；启用时仅在 `merge_global_index_spot_priority` 内按 `source_health_history_rollup` 成功率重排，审计追加 `data/meta/dynamic_priority_audit.jsonl`。

## 相关只读 API

- Chart Console：`GET /api/semantic/data_source_health`（读插件落盘的 `source_health_snapshot.json`；无快照时按页面提示运行 `tool_probe_source_health(write_snapshot=true)`）。
- 成功率趋势：`GET /api/semantic/data_source_health_history?days=7`（读插件 `data/meta/source_health_history_rollup.json`；由每次 `write_snapshot=true` 的 probe 采样刷新）。
- L4 估值 / PE 分位：`GET /api/semantic/l4_valuation_context`、`GET /api/semantic/l4_pe_ttm_percentile`（读 `data/semantic/l4_*`；缺时由 Chart 服务受控调用插件 `tool_l4_*` 落盘后再返回）。集成说明见 `docs/integration/plugin_assistant_integration_plan.md`。

## `src/data_collector.py` 收口清单（Phase 1）

- **已完成**：`fetch_index_daily_em` / `fetch_etf_daily_em` 优先调用合并工具 `tool_fetch_index_data` / `tool_fetch_etf_data`（historical），失败再回退 Tushare/AkShare 链。
- **本轮**：`fetch_stock_minute_em` 优先 `tool_fetch_stock_minute`（需已 `scripts/link_china_stock_data_collection.sh`），失败再回退东财分钟接口。
- **仍含直连、待 Phase 3 分级迁移**：ETF/指数分钟新浪路径、期权/A50/全球指数分支、`import akshare` 全局等 — 详见 [`docs/data_layer_direct_imports_backlog.md`](data_layer_direct_imports_backlog.md)（文件名别名：[`docs/remaining_direct_connections.md`](remaining_direct_connections.md)）。可复现扫描：`python scripts/scan_direct_connections.py`。

## 配置门闸

- Legacy 目录写入门闸：`config/feature_flags.json` 与示例 [`config/feature_flags.json.example`](../config/feature_flags.json.example)。代码缺省 **`legacy_write_enabled: false`**；本仓库已提交的 `feature_flags.json` 若含 `legacy_write_enabled: true` 则保持兼容旧行为。

## `tool_semantic_*_brief`（L4_semantic）

- **数据层**：`_meta.data_layer` 固定为 **`L4_semantic`**，与插件侧 **L4-data**（`tool_l4_*` 事实与分位）区分；叙事仅来自模板与阈值，不在工具内调用 LLM。
- **`_meta` 必填字段**（与统一投研契约一致）：`schema_name` / `schema_version`、`task_id`、`run_id`（由 `semantic_meta` 生成）、`data_layer`、`generated_at`、`trade_date`、`lineage_refs`（上游 `tool_*` id 列表）、`source_tools`、`quality_status`、`confidence`（0–1）。
- **`quality_status`**：`ok` / `degraded` / `error`；上游降级时语义工具应合并为 `degraded`（除非完全不可用则为 `error`），且 **`data.summary` 在 degraded 时仍须可读**（模板兜底句）。
- **血缘**：估值类须包含 `tool_resolve_symbol`、`tool_l4_valuation_context`、`tool_l4_pe_ttm_percentile` 等；具体以各工具返回的 `_meta.lineage_refs` 为准。登记见 [`data/meta/schema_registry.yaml`](../data/meta/schema_registry.yaml)。
- **Chart / Agent**：Chart 只读路由与 `tool_runner` 调用同一 Python 实现；详见 [`docs/ops/semantic_l4_openclaw_registration.md`](ops/semantic_l4_openclaw_registration.md)。
