# v0.2.0 发布说明（中文）

发布日期：2026-04-14  
版本标签：`v0.2.0`

## 版本定位

`v0.2.0` 是在 `v0.1.0` 基线之上的一次 **阶段性增强版本**：聚焦 **策略模块化与融合**、**预测质量闭环**、**工作流与运维体系完善**、以及 **配置架构机构化**（分层 + 按域拆分 + 校验）。

本版本依然面向研究与工程实践，不构成投资建议。

## Highlights（摘要）

- **配置机构化**：主配置从单体迁移为 `config/environments/*` + `config/domains/*` + `config/reference/holidays_*.yaml`，并提供交叉校验与 CI 门禁脚本。
- **策略引擎与多路信号融合（experimental）**：新增 `tool_strategy_engine` 与融合策略配置（含权重、策略候选与摘要输出），支持定时与审计字段。
- **预测质量闭环**：预测标准化、质量门禁、收盘后验证与周报监控，降低“口径漂移/脏数据”风险。
- **工作流与运维体系扩展**：盘前/开盘/盘后/巡检/研究/演化一组工作流模板与 runbook，强调“单次工具串接”与可追溯产物。
- **Chart Console（TradingView 风格）**：研究与回测控制台能力扩展，支持多图联动、指标/回测与工作区持久化。

## 破坏性变更（Breaking changes）

- **删除仓库根 `config.yaml`**：统一走 `src/config_loader.py -> load_system_config()` 的合并后配置视图；旧文档中若仍引用根 `config.yaml`，应改为“合并后配置”并指向对应域文件。

## 迁移提示（Migration）

- **配置入口**：\n
  - 默认：`config/environments/base.yaml`（空入口文件，用于分层顺序锚定）\n
  - 默认域配置：`config/domains/*.yaml`（按功能域拆分）\n
  - 环境 overlay：`config/environments/<profile>.yaml`（由 `ETF_OPTIONS_CONFIG_PROFILE`/`CONFIG_PROFILE` 决定，默认 `prod`）\n
  - 本机覆盖：`config/local.yaml`（gitignore）\n
  - 年度日历：`config/reference/holidays_*.yaml`（由 `system.trading_hours.calendar_source=files` 加载）\n

- **校验命令**：\n
  - `python3 scripts/validate_config_surface.py`\n
  - `python3 scripts/check_universe_ssot.py`\n
  - `python3 scripts/validate_config_cross.py`\n

## 已知说明

- `plugins/data_collection` 在部分部署形态中为符号链接到 OpenClaw 扩展（如 `openclaw-data-china-stock`）。本仓库文档会明确“主仓 vs 扩展”的边界，避免新 clone 误以为采集插件源码必然随仓库提供。
