# 旧技术指标工具下线阶段验收报告

## 结论
- 结论：Go（四阶段均已完成）。
- 旧工具 `tool_calculate_technical_indicators` 已完成执行面下线。
- 统一入口 `tool_calculate_technical_indicators_unified` 已接管工作流与 Agent 路径。

## Phase 1（去依赖）
- 变更：
  - 新增统一工具：`plugins/analysis/technical_indicators_unified.py`
  - workflow 切换：`opening_analysis`、`opening_real_session_report`、`signal_generation`、`signal_generation_on_demand`、`intraday_analysis`、`etf_510300_intraday_monitor`
  - agent 切换：`agents/analysis_agent.yaml`
- 测试：
  - unified 工具调用 smoke 通过
  - 低/中/高代表任务 test 通过（允许数据源降级）

## Phase 2（门禁）
- 变更：
  - `scripts/compare_indicator_migration_runs.py` 增加门禁参数与 fail-fast。
- 测试：
  - 基线文件：`artifacts/indicator-migration/phase2_baseline.json`
  - 对比文件：`artifacts/indicator-migration/phase1_highrisk_snapshot.json`
  - 结果：Top10 重叠 100%，duration 回归 0%，门禁 PASS。

## Phase 3（下线注册与解绑）
- 变更：
  - 删除旧工具注册：`config/tools_manifest.yaml/json`
  - 删除 tool_runner 旧工具映射：`tool_runner.py`
  - 删除 agent 旧工具绑定：`agents/analysis_agent.yaml`
  - 清理 workflow 旧工具指引：`workflows/backtesting_research_on_demand.yaml`
- 测试：
  - 调用旧工具返回 unknown tool（符合预期）
  - 调用 unified 工具成功
  - 核心 workflow（opening）test 模式回归通过

## Phase 4（治理收口）
- 变更：
  - 增强守卫脚本：`scripts/inventory_indicator_paths.py --fail-on-legacy-direct`
  - 更新执行手册与迁移清单文档
- 测试：
  - 守卫扫描执行路径无旧工具直连引用

## 后续维护建议
- 将 `python scripts/inventory_indicator_paths.py --fail-on-legacy-direct` 纳入 CI。
- 每周对高风险链路运行一次门禁对比（TopN + duration）。
