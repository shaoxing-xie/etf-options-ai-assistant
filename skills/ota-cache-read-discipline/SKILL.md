---
name: ota_cache_read_discipline
description: 读本地 parquet 缓存前的路径约定；采集写、分析读的分工；对齐 data/cache 布局与 plugins/data_access。
---

# OTA：缓存与只读数据访问

## 何时使用

- 工作流标注 **仅读缓存**（如部分 `signal_generation`、`etf_510300_intraday_monitor`）。
- 用户要从缓存拉 K 线而非实时全量拉取。

## 规程

1. **根路径**：缓存根为 合并后配置 → `system.data_storage.data_dir`（默认 `data`；域文件：`config/domains/platform.yaml`）下的 **`data/cache/`**。
2. **布局**：`index_daily`、`etf_minute` 等子路径规则由 `src/data_cache.get_cache_file_path` 定义；见 `docs/openclaw/跨插件数据契约.md`。
3. **工具**：优先经 **`read_cache_data` / `tool_read_market_data` 等合并入口**（见 `plugins/data_access`、`plugins/merged`），避免手写路径拼错。
4. **缺失**：若缓存未命中，按工具实现决定是否触发补数；勿绕过工具直接写生产缓存除非在允许路径内（进化边界见 `config/evolver_scope.yaml`）。

## 权威文档

- `docs/PROJECT_LAYOUT.md`（`plugins/data_access`）
- `docs/openclaw/能力地图.md`、`docs/openclaw/跨插件数据契约.md`
