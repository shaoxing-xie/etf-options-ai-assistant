# 配置合并语义

## `merge_config`（`src/config_loader.py`）

- **dict**：递归合并；overlay 的键覆盖 base 同名字段的子树。
- **list**：**整段替换**，不逐项合并。例如 `data_cache.etf_codes` 在 overlay 中给出新列表时，结果为 overlay 列表，而非与 base 求并集。

## `deep_merge_signal_dict`（`src/signal_config_normalize.py`）

- 仅对 **dict** 递归；**非 dict 的值（含 list）整键覆盖**。
- 典型陷阱：`signal_generation.option_contracts.underlyings` 在 overlay 中一旦出现，会 **完全替换** 根级 `option_contracts.underlyings`，而不是与根级列表按 `underlying` 字段合并。

## 回归测试

- `tests/test_signal_config_normalize.py` — `test_normalize_option_contracts_underlyings_list_whole_replace`
- `tests/test_config_merge_semantics.py` — `test_merge_config_list_replaces_not_appends`
