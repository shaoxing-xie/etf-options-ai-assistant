---
name: ota_signal_risk_inspection
description: 信号+风控巡检铁律（env → strategy_config → risk_check）、Tick/分钟降级；模板输出后钉钉投递 tool_send_dingtalk_message(mode=prod)，对齐 workflows/signal_risk_inspection.yaml 与 dingtalk_delivery_contract §巡检快报。
---

# OTA：信号与风控巡检规程

## 何时使用

- 执行或解释 **工作流 A**（盘中信号 + 风控巡检 + 通知）。
- 用户问「巡检顺序」「为何降级到分钟线」「能否跳过风控」。

## 铁律（顺序固定）

1. **先 env**：决策前通过环境与数据能力视图（含 Tick 是否可用、执行模式等）。
2. **再 config / strategy_config**：策略参数来自配置与代码，**禁止在 Prompt 里硬编码**交易参数。
3. **最后 risk_check**：任何潜在下单动作必须经集中风控；**禁止绕过**。

## Tick / 分钟降级

- 当 Tick 不可用或标的受限时，按工作流约定 **自动降级到分钟线**，并在输出中 **说明降级原因**（便于审计）。

## 输出与通知

- **最终对外**：仅输出 **模板本体**（见 YAML 硬约束）。**Cron 推荐单次** **`tool_run_signal_risk_inspection_and_send`**（`phase` 与任务档一致，`mode=prod`）：进程内拉指数/ETF/组合风险并调用 `tool_send_signal_risk_inspection`，避免 Gateway 多轮传 JSON。手工排障仍可 **`tool_send_signal_risk_inspection`** → **`tool_send_dingtalk_message`**（**mode=prod**），依赖 `OPENCLAW_DINGTALK_CUSTOM_ROBOT_*`；**禁止**飞书扇出同一份快报。关键词、拆条、`INSPECTION_RUN_STATUS` 见 **`docs/openclaw/dingtalk_delivery_contract.md` §巡检快报**。
- 第四节组合指标：复合工具已内置 `tool_portfolio_risk_snapshot`；手工路径须先调该工具再填 `report`，失败则填「数据不足」。

## 权威文档

- `docs/openclaw/信号与风控巡检工作流.md`
- `workflows/signal_risk_inspection.yaml`
- `docs/openclaw/通知通道路由与SOUL对齐说明.md`

## 相关工具（以 manifest 为准）

- 投递：`tool_send_dingtalk_message`（巡检）；信号/风控分析步见工作流与 manifest。
- 信号类：`tool_generate_option_trading_signals`（期权，别名 `tool_generate_signals`）、`tool_generate_etf_trading_signals`、`tool_generate_stock_trading_signals`；其他风控与通知类 `tool_*` 见 `docs/openclaw/能力地图.md` 与 **`plugins/notification/README.md`**。
- 单标的风险：`tool_assess_risk`（ETF/指数/A 股；`asset_type`、`lookback_trading_days`；HV 与 `realized_vol_windows` 同口径；配置：合并后配置 → `risk_assessment`，域文件：`config/domains/risk_quality.yaml`）。解读口径见 Skill **`ota_risk_assessment_brief`**。
- 组合风险：`tool_portfolio_risk_snapshot`（`plugins/risk`，与上互补）
