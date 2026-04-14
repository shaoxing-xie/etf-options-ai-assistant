# merged — 合并工具包

将多组独立工具合并为**单一入口函数 + 枚举参数**（`moment` / `data_type` / `action` / `mode` 等），便于 OpenClaw 等编排层以较少工具名调用，逻辑仍委托给 `analysis.*`、`plugins.data_collection.*`、`data_access.*` 等模块。

## 设计说明

- **门面路由**：本目录只做参数校验、分支转发与统一返回结构；业务实现在上游模块。
- **延迟导入**：分支内 `import`，减轻启动负担并避免循环依赖。
- **返回约定**：一般为 `{"success": bool, "message": str, "data": ...}`；个别工具会附加 `formatted_output`、`channel`、`detail` 等字段。

## 工具一览

| 模块 | 入口函数 | 路由参数 | 说明 |
|------|----------|----------|------|
| `analyze_market.py` | `tool_analyze_market` | `moment`: `after_close` \| `before_open` \| `opening` | 时段市场分析 → `analysis.trend_analysis` |
| `fetch_etf_data.py` | `tool_fetch_etf_data` | `data_type`: `realtime` \| `historical` \| `minute` | ETF 采集 → `plugins.data_collection.etf` |
| `fetch_index_data.py` | `tool_fetch_index_data` | `data_type`: `realtime` \| `historical` \| `minute` \| `opening` \| `global_spot` | 指数采集 → `plugins.data_collection.index` |
| `fetch_option_data.py` | `tool_fetch_option_data` | `data_type`: `realtime` \| `greeks` \| `minute` | 期权采集（需 `contract_code`）→ `plugins.data_collection.option` |
| `read_market_data.py` | `tool_read_market_data` | `data_type` 或 `data_types[]` | 从缓存读数 → `data_access.read_cache_data` |
| `strategy_analytics.py` | `tool_strategy_analytics` | `action`: `performance` \| `score` | 策略表现 / 评分 → `analysis.strategy_tracker` / `strategy_evaluator` |
| `strategy_weights.py` | `tool_strategy_weights` | `action`: `get` \| `adjust` | 策略权重 → `analysis.strategy_weight_manager` |
| `stop_loss_take_profit.py` | `tool_stop_loss_take_profit` | `action`: `calculate` \| `check` | 止盈止损 → `analysis.etf_risk_manager` |
| `volatility.py` | `tool_volatility` | `mode`: `predict` \| `historical` | 波动率 → `analysis.volatility_prediction` / `historical_volatility` |
| `position_limit.py` | `tool_position_limit` | `action`: `calculate` \| `check` \| `apply` | 仓位与硬限制 → `analysis.etf_position_manager` |
| `send_feishu_notification.py` | `tool_send_feishu_notification` | `notification_type`: `message` \| `signal_alert` \| `daily_report` \| `risk_alert` | 飞书 webhook 通知（含正文组装与冷却去重） |

## 常用参数备忘

### `read_market_data`

- 类型枚举：`index_daily`、`index_minute`、`etf_daily`、`etf_minute`、`option_minute`、`option_greeks`。
- 期权类需 `contract_code` 或 `symbol`；指数/ETF 未指定时默认指数 `000300`、ETF `510300`（与代码一致）。
- 分钟级在未提供 `date` / `start_date` / `end_date` 时，会自动使用「当前日起往前约 5 个自然日」的区间（`timedelta(days=5)`），避免空日期导致失败；若需严格对齐交易日，请显式传入日期或由上游用交易日历计算。

### `fetch_index_data`

- 支持 `mode`（如实时、分钟等场景）；`opening` 可通过 `index_codes` 或 `index_code` 传入标的。
- 旧工具名由上层 `tool_runner` 映射为 `data_type` 时，仍走本统一入口。

### `send_feishu_notification`

- 配置：`notification.feishu_webhook`（见 `src.config_loader`）；也可传 `webhook_url` 覆盖。
- `cooldown_key` + `cooldown_minutes`：防刷屏；`risk_alert` / `signal_alert` 默认冷却 30 分钟（以代码为准）。
- `daily_report` 可从 `report_data` 自动抽取摘要字段（如 `llm_summary`、`summary` 等）。

## 与 `tool_runner` 的关系

合并工具常作为 **OpenClaw 暴露名**；旧工具名可在 `tool_runner` 中注入 `data_type` / `action` 等别名，再调用本包对应函数，无需重复实现业务逻辑。

## 扩展新分支

1. 在对应 `*.py` 中增加分支与参数说明（docstring）。
2. 使用延迟导入指向实际实现模块。
3. 非法枚举值返回 `success: False` 并写明合法取值。
