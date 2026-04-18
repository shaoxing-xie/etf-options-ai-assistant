# 技术指标工具下线执行手册（四阶段）

## Phase 1：去依赖改造（保留旧注册）
- 执行：
  - workflow/agent 全部改为 `tool_calculate_technical_indicators_unified`
- 验证：
  - `python scripts/inventory_indicator_paths.py`
  - 低/中/高风险各跑 1 轮 test 模式

## Phase 2：灰度与门禁
- 冻结基线：
  - `python scripts/freeze_etf_rotation_baseline.py --from-cache --output artifacts/indicator-migration/phase2_baseline.json`
- 生成新样本后对比：
  - `python scripts/compare_indicator_migration_runs.py --base artifacts/indicator-migration/phase2_baseline.json --new <new.json> --enforce-gate`
- 门禁阈值：
  - Top10 重叠率 >= 95%
  - duration 回归 <= 0%

## Phase 3：下线旧注册与解绑
- 执行：
  - 移除 `tool_calculate_technical_indicators` 在 manifest/tool_runner/agent 的注册与绑定
  - 清理 workflow 指引中的旧工具名
- 验证：
  - 旧工具调用应返回 unknown tool
  - 新统一工具与核心 workflow 冒烟通过

## Phase 4：治理收口与防回流
- 防回流守卫（可入 CI）：
  - `python scripts/inventory_indicator_paths.py --fail-on-legacy-direct`
- 守卫范围：
  - `workflows/**`, `agents/**`, `config/tools_manifest.*`, `tool_runner.py`
- 通过标准：
  - 无旧工具直连引用

## 紧急回滚
- 任务路由回滚：
  - `config/domains/analytics.yaml` -> `indicator_migration.tasks.<task>.enabled: false`
- 高风险回滚：
  - `indicator_migration.tasks.etf_rotation_research.force_rollback_to_legacy: true`
