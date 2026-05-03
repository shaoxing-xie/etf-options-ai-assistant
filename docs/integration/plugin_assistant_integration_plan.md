# 采集插件（openclaw-data-china-stock）与交易助手集成：评估与实施计划

## 1. 集成测试结果（本仓库）

已执行：

- `pytest tests/test_smoke_tool_runner.py`（含 `tool_screen_equity_factors` / `tool_screen_by_factors` / `tool_plugin_catalog_digest` / `tool_resolve_symbol`）
- `pytest tests/test_data_collection_plugins.py`

**根因与修复（必记）**

- 助手通过 **动态加载** 插件单文件（如 `equity_factor_screening.py`）时，上游模块会 `import plugins.utils.plugin_data_registry`。
- 助手仓自身存在 `plugins.utils` 包，**不能把插件根目录长期插在 `sys.path` 最前**，否则会覆盖助手 `plugins.utils`。
- **做法**：`plugins/china_stock_upstream.py` 在 `exec_module` 前后 **临时**将插件仓根路径插入 `sys.path`，并支持：
  - 环境变量 `OPENCLAW_CHINA_STOCK_PLUGIN_ROOT`
  - 与助手同级的 `openclaw-data-china-stock`
  - `~/.openclaw/extensions/openclaw-data-china-stock`

**陷阱**：上游薄封装 **不得**放在 `plugins/utils/` 包路径下作为新模块再 `import`，否则会先执行助手 `plugins/utils/__init__.py`，把 `plugins.utils` **固定为助手实现**，随后即使临时插入插件根路径，`from plugins.utils.plugin_data_registry` 仍会失败。观测类封装已改为 `plugins/catalog_digest_upstream.py`、`plugins/attempts_rollup_upstream.py`。

## 2. 插件侧近期能力与助手差距

| 插件能力 | 助手现状（修复前/后） | 建议 |
|---------|----------------------|------|
| `factor_registry` + catalog 合并（全球指数、资金流、技术指标引擎顺序） | 行情链路已走 symlink 的 `fetch_global` 等，**自动继承**合并逻辑；无需助手重复实现 | 报告/运维文案可读取 `source_route.catalog_merge`、`meta.catalog_engine_order` 做可观测展示 |
| `tool_screen_by_factors` | 已加入 `tool_runner` + manifest | 工作流/Cron 新任务优先用别名或与 equity 等价参数 |
| L4：`tool_l4_*`、`tool_resolve_symbol`、`tool_get_entity_meta` | 已增加薄封装 + TOOL_MAP + manifest | Chart/开盘逻辑如需估值事实，优先调用 L4 而非自算 |
| `tool_plugin_catalog_digest`、`tool_summarize_attempts` | 已注册 | 巡检任务只读观测 |

## 3. 分阶段实施计划（助手侧）

### P0（已完成/本轮）

- [x] `china_stock_upstream` 加载器 + `equity_factor_screening` stub 导出 `_norm_code_6`、`tool_screen_by_factors`
- [x] `l4_data_tools`、`catalog_digest`、`attempts` 上游薄封装
- [x] `tool_runner` + `config/tools_manifest.yaml` + `generate_tools_json.py` 产物刷新
- [x] `data/meta/schema_registry.yaml` 等与插件 schema 对齐（起步集）

### P1（建议 1～2 迭代）

1. **开盘/午间/Chart**：对 `tool_fetch_global_index_spot` 响应增加可选展示字段：`source_route.catalog_merge`、`active_priority`（仅日志/卡片 debug 区，避免扰民）。**运维**：设置环境变量 `OPTION_TRADING_ASSISTANT_DEBUG_PLUGIN_CATALOG=1` 时，Chart `build_global_market_snapshot` 在文档根级附带 `_debug.plugin_catalog.global_index_spot`（分批 `catalog_merge` / `active_priority`）；开盘 `report_data` 同步写入 `_debug`；日报/钉钉脚注 `_build_opening_global_spot_diagnostics_line` 追加紧凑 `catalog_debug=...`。
2. **技术指标**：助手侧指标引擎在 debug 环境下于返回 `data.meta.catalog_engine_order`（当前为解析后的本地引擎名列表，如 `["standard"]`）；若未来统一链路改为插件编排并下发插件级 `meta.catalog_engine_order`，同一字段名将自动贯通；统一入口 `tool_calculate_technical_indicators_unified` 仍可向 `meta.indicator_runtime` 叠加路由信息。
3. **选股流水线**：**`tool_finalize_screening_nightly(screening_result=...)` 接受任意满足 `src.screening_utils.validate_screening_response` 的 JSON**。插件别名 **`tool_screen_by_factors` 与 `tool_screen_equity_factors` 参数与返回信封一致**（同一上游实现），故夜盘收尾可直接传入任一脚本的完整返回；manifest 中 finalize 的表述保留「equity」仅为历史命名，契约上以字段为准而非工具 id。

### P2（按需）

1. 将 **助手仓 `skills/`（ota-*）** 中重复的行情/估值叙述改为 **显式引用** `tool_l4_*` / `tool_resolve_symbol`（与插件 SKILL 策略一致）。
2. **语义层 API**：Chart Console 已增加 **`/api/semantic/l4_valuation_context`**、**`/api/semantic/l4_pe_ttm_percentile`**（查询参数 `trade_date`、`stock_code`、`refresh`、`window_years`），优先读 `data/semantic/l4_*` 落盘；缺失时受控调用 `tool_l4_*` 再写入，映射契约 `valuation_context_v1` / `pe_ttm_percentile_band_v1`。
3. **Cron**：对依赖选股/估值的任务做一次 `rg tool_screen_equity_factors`，评估是否切换别名或统一走 registry 文档中的因子列表。

## 4. 运维检查清单

- 插件安装路径是否在 `resolve_openclaw_china_stock_root()` 候选列表内；若自定义路径，设置 `OPENCLAW_CHINA_STOCK_PLUGIN_ROOT`。
- 升级插件后发版前跑：`pytest tests/test_smoke_tool_runner.py tests/test_data_collection_plugins.py`。
- Gateway：重启前执行 `python3 scripts/generate_tools_json.py` 使 `tools_manifest.json` 与 YAML 一致。
