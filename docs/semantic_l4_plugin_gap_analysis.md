# 语义化 L4 Agent 上下文：插件仓依赖缺口结论（阶段一）

对照实施方案，语义工具所需底座能力已存在于 **openclaw-data-china-stock**（经助手侧 symlink / `china_stock_upstream` 加载）及助手仓已有工具：

- **L2**：`tool_resolve_symbol`、`tool_get_entity_meta`
- **L4-data**：`tool_l4_valuation_context`、`tool_l4_pe_ttm_percentile`；组合维度 `tool_l4_portfolio_valuation_context`
- **市场 / 资金**：`tool_detect_market_regime`、`tool_fetch_index_data`（merged）、`tool_sector_heat_score`、`tool_fetch_a_share_fund_flow`、`tool_capital_flow`

**结论**：本轮无需在插件仓新增 `tool_l4_*` 或 data-only 聚合；若后续需要「单一涨跌家数口径」等再开插件 PR。
