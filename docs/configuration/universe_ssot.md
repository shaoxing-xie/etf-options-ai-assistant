# Universe 单一事实源（SSOT）

## 权威顺序

1. **期权运行骨架**：`signal_generation.option_contracts`（加载并归一化后为 `option_contracts`）— 决定信号/波动/缓存使用的 **ETF 标的与合约行**。
2. **采集缓存标的**：`data_cache.index_codes` / `data_cache.etf_codes` / `data_cache.stock_codes` — 须 **覆盖** 所有 `option_contracts` 中出现的 ETF 标的（`51*` / `15*`），否则 Cron/缓存会漏采。
3. **ETF 交易模块标的**：`etf_trading.enabled_etfs` — 若配置非空，应 **包含** 所有期权标的 ETF，避免策略与信号标的不一致。

## 变更流程

- 增删期权标的或换月：先改 **`signal_generation.option_contracts`**，再同步 **`data_cache`** 与 **`etf_trading.enabled_etfs`**。
- 合并后运行：`python3 scripts/validate_config_cross.py`（hard 失败会 exit 1）、`python3 scripts/check_universe_ssot.py`。

## 与动态合约列表

`get_option_contracts` / `tool_get_option_contracts`（采集插件）仅用于 **核对或探索**，**不**自动写回生产 YAML。见 [contract_master_data.md](contract_master_data.md)。
