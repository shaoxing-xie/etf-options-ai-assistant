# 数据分层与采集边界（索引）

本页为 **入口索引**：具体契约、清单与脚本以下列文件为准，避免多份「SSOT」漂移。

## 契约与错误码

- [`docs/data-source-contract.md`](../data-source-contract.md) — 工具返回体、`error_code` / `quality_status`、只读语义 API。
- [`data/meta/error_codes.yaml`](../../data/meta/error_codes.yaml) — 错误码说明（键与描述）。
- [`plugins/utils/error_codes.py`](../../plugins/utils/error_codes.py) — 与 YAML **键集合**对齐的 `ERROR_CODE_KEYS`；CI 由 [`scripts/check_error_codes_sync.py`](../../scripts/check_error_codes_sync.py) 对照**同级插件仓** `plugins/utils/error_codes.py`（见 `.github/workflows/release-gate.yml`）。

## 采集收口与直连 backlog

- [`docs/DATA_COLLECTOR_PLUGIN_BOUNDARY.md`](../DATA_COLLECTOR_PLUGIN_BOUNDARY.md) — `data_collector` 与 `openclaw-data-china-stock` 边界。
- [`docs/data_layer_direct_imports_backlog.md`](../data_layer_direct_imports_backlog.md) — 仍含直连的模块分级与季度审计说明。
- [`docs/remaining_direct_connections.md`](../remaining_direct_connections.md) — 与上一文件同义别名（兼容外部报告中的文件名）。

## 可复现扫描

```bash
python scripts/scan_direct_connections.py
python scripts/scan_direct_connections.py --summary-only
```

扫描范围：`import` / `from` 形式的 **akshare、tushare、baostock**（与 backlog 中手工 `rg` 意图一致）。

## Chart Console 只读语义（健康）

- 快照：`GET /api/semantic/data_source_health`
- 趋势：`GET /api/semantic/data_source_health_history?days=7`  
  数据由插件侧 `tool_probe_source_health(write_snapshot=true)` 落盘与 rollup；详见 `docs/data-source-contract.md`「相关只读 API」节。
