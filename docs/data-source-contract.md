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

## 相关只读 API

- Chart Console：`GET /api/semantic/data_source_health`（读插件落盘的 `source_health_snapshot.json`；无快照时按页面提示运行 `tool_probe_source_health(write_snapshot=true)`）。
- 成功率趋势：`GET /api/semantic/data_source_health_history?days=7`（读插件 `data/meta/source_health_history_rollup.json`；由每次 `write_snapshot=true` 的 probe 采样刷新）。

## `src/data_collector.py` 收口清单（Phase 1）

- **已完成**：`fetch_index_daily_em` / `fetch_etf_daily_em` 优先调用合并工具 `tool_fetch_index_data` / `tool_fetch_etf_data`（historical），失败再回退 Tushare/AkShare 链。
- **本轮**：`fetch_stock_minute_em` 优先 `tool_fetch_stock_minute`（需已 `scripts/link_china_stock_data_collection.sh`），失败再回退东财分钟接口。
- **仍含直连、待 Phase 3 分级迁移**：ETF/指数分钟新浪路径、期权/A50/全球指数分支、`import akshare` 全局等 — 详见 [`docs/data_layer_direct_imports_backlog.md`](data_layer_direct_imports_backlog.md)。

## 配置门闸

- Legacy 目录写入门闸：`config/feature_flags.json` 与示例 [`config/feature_flags.json.example`](../config/feature_flags.json.example)。代码缺省 **`legacy_write_enabled: false`**；本仓库已提交的 `feature_flags.json` 若含 `legacy_write_enabled: true` 则保持兼容旧行为。
