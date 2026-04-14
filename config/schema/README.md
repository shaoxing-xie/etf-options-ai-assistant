# 配置 JSON Schema（表层）

- **`runtime_surface.schema.json`**：要求 `load_system_config()` 合并并 `normalize_signal_generation_config` 之后，顶层 **至少** 存在所列键（与业务入口一致）。
- 校验命令：`python3 scripts/validate_config_surface.py`（从仓库根运行）。

更深层的字段级 schema 可按功能域逐步补充；未列键仍允许（`additionalProperties: true`）。
