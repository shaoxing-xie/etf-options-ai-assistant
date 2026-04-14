---
name: ota_cn_market_data_discipline
description: 标的物→数据域→周期；多 Provider 降级顺序；优先查 openclaw-data-china-stock 的 TOOL_MAP/README。与主仓采集 symlink 一致。
---

# OTA：A 股数据 — 域与降级

## 何时使用

- 选择 `tool_fetch_*` / 统一抓取接口前，先映射 **标的类型与周期**。
- 解释为何某次请求走了备用 Provider。

## 规程

1. **数据源主路径**：行情/参考数据由 **`openclaw-data-china-stock`**（本仓库 `plugins/data_collection` 符号链接）提供；工具名以 **Gateway manifest** 为准。
2. **查阅**：复杂映射查扩展内 **`plugins/data_collection/README.md`**、`ROADMAP.md`（TOOL_MAP、DTO）。
3. **降级**：多 Provider 链失败时按扩展文档顺序降级；在回复中可简要说明「降级原因」便于排障。
4. **本仓补充**：`docs/openclaw/fetch_realtime脚本说明.md` 等脚本向说明。

## 跨插件契约

- 缓存写入后读路径见 `docs/openclaw/跨插件数据契约.md`。

## 禁止

- 在未确认工具存在时臆造 `tool_*` 名称（以 manifest 为准）。
