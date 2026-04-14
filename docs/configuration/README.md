# 配置分层（机构化）

## 真相源位置

- **默认**：`config/environments/base.yaml`（非敏感业务默认值）
- **共享域文件**：`config/domains/*.yaml`（按功能域拆分的默认值；由 loader 固定顺序合并）
- **环境覆盖**：`config/environments/<profile>.yaml`，profile 由环境变量 **`ETF_OPTIONS_CONFIG_PROFILE`** 或 **`CONFIG_PROFILE`** 指定，缺省为 **`prod`**
- **本机覆盖（gitignore）**：`config/local.yaml`（见 `config/local.yaml.example`）
- **年度日历文件**：`config/reference/holidays_*.yaml`（由 `system.trading_hours.calendar_source=files` 自动合并进运行时 `holidays`）

加载顺序：`base.yaml` → `config/domains/*.yaml` → `<profile>.yaml` → `local.yaml` → `config/reference/holidays_*.yaml`，均为 **dict 深度合并**；**列表整键替换**（与 `merge_config` / `signal_config_normalize` 行为一致，详见下文）。

实现入口：[src/config_loader.py](../../src/config_loader.py) 中 `load_layered_user_config` / `load_system_config`。

## 延伸阅读

- [功能域与代码包矩阵（完整版）](domain_matrix.md)
- [Universe 单一事实源](universe_ssot.md)
- [合约主数据 vs 工具发现 + PR checklist](contract_master_data.md)
- [合并语义（dict / list）](merge_semantics.md)
- [策略版本 strategy_version](strategy_versioning.md)
- [JSON Schema 表层说明](../../config/schema/README.md)

## 功能域 ↔ 配置键（扩展时先定域）

| 域 | 职责 | 主要配置键 |
|----|------|----------------|
| A Reference & Universe | 标的、合约骨架、日历 | `signal_generation.option_contracts`（归一化后 `option_contracts`）、`system.trading_hours`、`data_cache` |
| B Market Data | 多源、熔断、Tick | `data_sources`、`tushare`、`realtime_full_fetch_cache` |
| C Analytics & Models | 指标、波动引擎、日频区间 | `technical_indicators`、`volatility_engine`、`daily_volatility_range`、`historical_snapshot` |
| D Alpha & Signals | 信号、日内、图表告警 | `signal_generation`、`signal_params`、`internal_chart`、`etf_trading` |
| E Risk & Quality | 工具风控、预测质量 | `risk_assessment`、`prediction_quality`、`prediction_monitoring` |
| F Distribution & Narrative | 推送、日报 overlay、LLM | `notification`、`trend_analysis_plugin`、`llm_enhancer`、`llm_structured_extract` |
| G Platform & Ops | 日志、存储、调度 | `logging`、`system`、`opening_analysis` |

新增能力时：在对应域下增加键，避免跨域散落同名概念。

## 域文件布局

- `config/domains/reference.yaml`：A Reference & Universe
- `config/domains/market_data.yaml`：B Market Data
- `config/domains/analytics.yaml`：C Analytics & Models
- `config/domains/signals.yaml`：D Alpha & Signals
- `config/domains/risk_quality.yaml`：E Risk & Quality
- `config/domains/outbound.yaml`：F Distribution & Narrative
- `config/domains/platform.yaml`：G Platform & Ops

## 合约：运行骨架 vs 工具发现

- **`option_contracts`（YAML）**：信号、缓存、波动等模块使用的 **运行时期权合约骨架**（经 `normalize_signal_generation_config` 合并）。
- **`get_option_contracts` / `tool_get_option_contracts`**（若存在 `plugins/data_collection/...`）：从行情接口 **动态列举**，用于核对或探索；**不自动覆盖** 生产 YAML。
- **换月 checklist**：更新 `current_month`、各合约 `expiry_date` / `contract_code`、`signal_generation.option.max_contracts_per_side`，并跑 `python3 scripts/validate_config_cross.py`。

## `signal_config_normalize` 与列表覆盖

详见 [merge_semantics.md](merge_semantics.md)。单测见 `tests/test_signal_config_normalize.py` 与 `tests/test_config_merge_semantics.py`。

## 策略版本

见 [strategy_versioning.md](strategy_versioning.md)。`signal_params.strategy_version` 与 `etf_trading.strategy_version` 应对齐。

## 相关脚本

- `python3 scripts/validate_config_cross.py`：交叉校验；**hard**（重复合约、Universe 漂移）exit 1；**soft**（次年节假日键提醒）仅打印 stderr
- `python3 scripts/check_universe_ssot.py`：仅 Universe / 合约 hard 检查（与 CI 门禁一致）
- `python3 scripts/validate_config_surface.py`：校验合并后顶层键满足 `config/schema/runtime_surface.schema.json`
