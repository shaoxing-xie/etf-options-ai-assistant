# 策略版本（`strategy_version`）

## 字段

- **`signal_params.strategy_version`**：期权/规则侧策略族标识（与 `signal_params` 内权重、阈值一并理解）。
- **`etf_trading.strategy_version`**：ETF 侧策略族标识；**应与 `signal_params.strategy_version` 对齐**（同一发布内修改）。

## 使用约定

- 回测脚本与生产进程应 **读取同一分层配置**（`load_system_config`），禁止在回测里硬编码一套与 YAML 分叉的 magic number。
- 未来若引入 `signal_params.profiles.<name>.*` 收拢权重，根级旧键仅作 deprecated 别名时，须在 PR 描述中写明 **迁移对照表**。

## 弃用流程（建议）

在 PR 中维护「旧键 → 新键 → 计划删除版本」三列表；代码中对已弃用键可打 **限频** `DeprecationWarning` 日志（待实现时可挂 `strategy_version` 门控）。
