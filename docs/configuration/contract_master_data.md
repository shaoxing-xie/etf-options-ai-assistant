# 合约主数据 vs 工具发现

## 角色

| 来源 | 用途 |
|------|------|
| **YAML `option_contracts`**（`signal_generation` 内，归一化后根键 `option_contracts`） | 生产运行时 **唯一骨架**：信号、Greeks、波动区间、缓存等 **只读此处**。 |
| **`get_option_contracts` / `tool_get_option_contracts`**（`plugins/data_collection/...`，可为 symlink） | 从交易所/新浪等 **动态列举**；用于人工核对、工具探索、与 YAML **对账**，**不自动覆盖** YAML。 |

## 换月 / 换档 PR Checklist

- [ ] 更新 `current_month`（若仍用该行权价反查逻辑）
- [ ] 更新各 `call_contracts` / `put_contracts` 的 `contract_code`、`strike_price`、`expiry_date`
- [ ] 核对 `signal_generation.option.max_contracts_per_side` 与列表长度
- [ ] 同一侧 **无重复 `contract_code`**
- [ ] 同步 **Universe**：`data_cache.etf_codes`、`etf_trading.enabled_etfs`（见 [universe_ssot.md](universe_ssot.md)）
- [ ] `python3 scripts/validate_config_cross.py` 与 `python3 scripts/check_universe_ssot.py` 通过
