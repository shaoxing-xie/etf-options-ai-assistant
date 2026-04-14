---
name: ota_evolution_execution_contract
description: 摘要版：何时走 *_evolution_on_demand 工作流、双证据、失败码与 evolver 边界；完整条文见 execution_contract.md。勿与日常交易巡检混装。
---

# OTA：能力进化 — 执行契约（摘要）

## 何时使用

- 触发或审阅 **`factor_evolution_on_demand`**、**`strategy_param_evolution_on_demand`**、**`volatility_range_evolution_on_demand`**、**`research_checklist_evolution_on_demand`** 等。
- 判断 Builder/Reviewer/Evolver 输出是否有效。

## 摘要铁律

1. **不变量**：`config/evolution_invariants.yaml`；**允许路径**：`config/evolver_scope.yaml`。
2. **双证据**（若工作流要求）：本地证据 + 外链 `https://` 缺一不可，否则 `DUAL_EVIDENCE_INCOMPLETE`。
3. **合 PR 条件**：仅 **`TEAM_OK` + `RISK=LOW`**（及工作流明示的额外门闩）才可自动修复/提 PR；**禁止自动合 main**（以总纲文档为准）。
4. **第三方 Skill**：编排侧常需 **`agent-team-orchestration`**、**`capability-evolver`**、**`github`**（装于系统 skills 或 shared）；见 `docs/getting-started/third-party-skills.md`。

## 权威长文（必读细节）

- `docs/openclaw/execution_contract.md`
- `docs/openclaw/failure_codes.md`
- `docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md`

## 禁止

- 用本 Skill 替代 **盘中交易风控**（改用 `ota-signal-risk-inspection`）。
- 在 `denied_paths` 外自动改采集/密钥/生产配置。
