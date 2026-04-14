---
name: ota_risk_assessment_brief
description: 单标的仓位/止损/波动率风险评估（tool_assess_risk）：ETF/指数/A 股、realized_vol 口径、config 与数据路径；与组合风控 tool_portfolio_risk_snapshot 区分。
---

# OTA：`tool_assess_risk` 风险评估口径

## 何时使用

- 调用或解读 **`tool_assess_risk`**（`plugins/analysis/risk_assessment.py`）。
- 用户问「风险评估」「凯利」「止损」「仓位占比」「波动率多少」且针对 **单一标的**（非组合巡检）。

## 与组合风控的边界

| 工具 | 场景 |
|------|------|
| **`tool_assess_risk`** | 单标的：持仓市值占比、止损隐含风险、简化凯利、HV（`realized_vol_windows`，%%） |
| **`tool_portfolio_risk_snapshot`**（`plugins/risk`） | 多标的组合：权重 + ETF 缓存、VaR/回撤等 |

二者互补；**不要**用组合工具代替单标的评估，反之亦然。

## 参数要点

- **`symbol`**：6 位或 `sh600000` / `600000.SH` 形式。
- **`asset_type`**：`auto` \| `stock` \| `etf` \| `index`。缺省读 **合并后配置 → `risk_assessment.default_asset_type`**（域文件：`config/domains/risk_quality.yaml`）。
  - 显式 `etf` / `index` / `stock`：**缓存优先**（`read_cache_data` / `get_cached_stock_daily`），不足再拉日线。
  - **`auto`**：与 `tool_calculate_historical_volatility` 一致，直接走 `fetch_index_daily_em` / `fetch_stock_daily_hist` 路由（不强行先读 ETF 缓存）。
- **`lookback_trading_days`**：波动率窗口（交易日）；缺省读 **`risk_assessment.default_lookback_trading_days`**（通常 60）。
- **`stop_loss`**：可选；不传则按年化 HV（%%）与 **`risk_assessment.stop_loss_multiplier`** 估算；无 HV 时约为入场价 × 0.97。
- 其它：`entry_price`、`position_size`、`account_value` 必填（见 manifest）。

## 数据与波动率

- 年化波动率 **`volatility`** 输出为 **百分数（%%）**，与 **`tool_calculate_historical_volatility`**、**`realized_vol_windows`** 同口径。
- 个股日线经 **`fetch_stock_daily_hist`** → `fetch_single_stock_historical`（多源链，与 openclaw-data-china-stock 采集插件对齐）；详见 `plugins/data_collection/stock/fetch_historical.py`。

## 配置真源

- **合并后配置 → `risk_assessment`**：`stop_loss_multiplier`、`kelly.*`、风险等级阈值、高波动提示等（域文件：`config/domains/risk_quality.yaml`）。

## 权威文档与代码

- [`plugins/analysis/README.md`](../../plugins/analysis/README.md) §7（`risk_assessment.py`）
- 分层配置入口见 `docs/configuration/README.md`（域文件：`config/domains/risk_quality.yaml`）
- [`config/tools_manifest.yaml`](../../config/tools_manifest.yaml)（`tool_assess_risk`）

## 相关 Skill

- **`ota_historical_volatility_snapshot`**：单窗 HV 工具 vs 复合快照；与 `tool_assess_risk` 的 HV 口径一致但用途不同。
- **`ota_signal_risk_inspection`**：巡检顺序与组合块；可衔接 `tool_assess_risk` 作为单标风险补充。
- **`ota_strategy_fusion_playbook`**：融合后可再调用 `tool_assess_risk` 做仓位侧校验。
