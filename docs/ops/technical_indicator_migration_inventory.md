# 技术指标迁移清单与风险分级

## 范围
- 目标：统一到 `plugins.analysis.technical_indicators_unified.tool_calculate_technical_indicators_unified` 与 `src/services/indicator_runtime.py`。
- 时间：本次实施对应分批计划 Phase 0~3。

## 调用路径盘点（现状 -> 目标）
- `plugins/notification/run_opening_analysis.py`
  - 现状：直接调用 `tool_calculate_technical_indicators`
  - 目标：通过 `indicator_runtime.calculate_indicators_via_tool` 统一入口
  - 风险：低（展示/解读类）
- `plugins/notification/run_signal_risk_inspection.py`
  - 现状：直接调用 `tool_calculate_technical_indicators` 作为补充文案
  - 目标：通过 `indicator_runtime` 统一入口
  - 风险：中（信号辅助）
- `plugins/analysis/trend_analysis.py`（ADX overlay）
  - 现状：调用 `calculate_technical_indicators`
  - 目标：通过 `indicator_runtime` 统一入口
  - 风险：中（信号辅助）
- `plugins/analysis/etf_rotation_research.py`
  - 现状：固定 `score_engine="58"`，高耦合评分链路
  - 目标：配置化主引擎 + 影子双跑 + 回滚
  - 风险：高（评分/排序核心链路）

## 风险分批
- 低风险（Phase 1）：`opening_analysis`（展示增强，不直接触发交易执行）
- 中风险（Phase 2）：`signal_risk_inspection`、`trend_analysis`（信号辅助）
- 高风险（Phase 3）：`etf_rotation_research`（核心评分排序）

## 开关与回滚
- 配置位置：`config/domains/analytics.yaml` -> `indicator_migration`
- 关键字段：
  - `enabled`：全局启用迁移
  - `tasks.<task>.enabled`：任务级开关
  - `tasks.<task>.dual_run`：双跑开关（高风险阶段启用）
  - `tasks.etf_rotation_research.force_rollback_to_legacy`：紧急回滚到 legacy

## 验收建议
- 一致性：TopN 重叠率、信号方向一致率
- 性能：平均耗时、P95、失败率/超时率
- 审计：每次运行记录 `indicator_runtime` 与 `shadow_compare`

## 当前状态（四阶段下线后）
- workflow/agent 执行路径已切换至 `tool_calculate_technical_indicators_unified`。
- `tool_calculate_technical_indicators` 已从 manifest 与 tool_runner 下线。
- 防回流守卫已支持：`python scripts/inventory_indicator_paths.py --fail-on-legacy-direct`。
