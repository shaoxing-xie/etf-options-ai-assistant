# Execution Contract（执行协议）

本文定义 `github + agent-team-orchestration + capability-evolver` 的统一执行约束，用于避免幻觉、跑偏、超时扩散和“无证据结论”。

**机器可读不变量**：与本文配套的硬性原则同时固化在 **`config/evolution_invariants.yaml`**（Orchestrator / Builder / Reviewer / Evolver 在演化任务中须 `read` 该文件并遵守；该文件**不在**自动进化可改路径内，仅人工维护）。

## 1. 角色职责

- Orchestrator（`etf_main`）
  - 负责任务拆解、阶段推进与停止决策。
  - 仅在 Reviewer 返回 `TEAM_OK` 且 `RISK=LOW` 时推进修复与 PR。
- Builder（`code_maintenance_agent`）
  - 只负责执行与产出证据。
  - 不可在缺少证据时给“已修复”结论。
- Reviewer（`etf_analysis_agent`）
  - 仅基于 Builder 的 RAW 证据判定。
  - 不接受“总结代替原始证据”。
- Evolver（`capability-evolver`）
  - 对每次任务进行复盘沉淀。
  - 产出下一轮可复用 checklist 与标准命令。

## 2. 强制输出合同

Builder 每次执行后必须输出以下四段（顺序固定）：

1. `[COMMAND]`
2. `[STDOUT]`
3. `[STDERR]`
4. `[RAW_OUTPUT]`

规则：

- `RAW_OUTPUT` 必须包含可复现的关键原始片段（日志、错误行、命令回显等）。
- 禁止仅输出“总结”而不附原始证据。
- 若命令执行失败，仍须完整输出上述四段（空值也要显式留空）。

## 3. 审核门禁

Reviewer 必须按以下规则返回：

- 缺少 RAW 证据：`TEAM_FAIL: NO_EVIDENCE`
- 有 RAW 证据但无法定位根因：`TEAM_FAIL: UNKNOWN_CAUSE`
- 可定位且可执行时：
  - `TEAM_OK`
  - `ROOT_CAUSE=...`
  - `FIX=...`
  - `RISK=LOW|MEDIUM|HIGH`

## 4. 停止条件与升级路径

Orchestrator 在以下情况必须停止自动修复并升级：

- `TEAM_FAIL:*`
- `RISK!=LOW`
- 触发高危失败码（见 `failure_codes.md`）

升级动作：

- 转人工审批；
- 保留证据块；
- 记录“未自动修复原因”。

## 5. 风险分级

- LOW：路径泄漏、文档/脚本 lint 与 gate 类问题、非敏感配置卫生问题
- MEDIUM：跨模块逻辑变更、依赖版本调整、非核心策略参数改动
- HIGH：交易风控逻辑、生产敏感运维配置、资金/信号主流程核心算法

约束：

- 仅 LOW 允许自动修复；
- 所有写操作必须经分支 + PR，不允许主干直接改动。

## 6. GitHub 执行约束

在当前项目形态下，GitHub 操作统一使用 `exec + gh`：

- 不假设存在 `github_*` 工具名。
- 读取失败日志优先使用 run logs zip 方案（见 runbook）。
- 任何“CI 已修复”的结论都必须附可核验证据（run id + status + 关键日志）。

## 7. 每次任务的最小交付

每次闭环任务结束时至少产出：

- 失败码（或 `TEAM_OK`）
- 四段证据块
- 修复策略（含风险等级）
- Evolver 复盘条目（分类 + 标准命令 + checklist）

## 8. 钉钉渠道与三 Skill 演化授权

**机器可读名单**：`config/evolution_invariants.yaml` → `dingtalk_three_skill_evolution`。

- **当前策略**：在钉钉上**仅**允许显示名为 **「谢富根」** 的用户（及未来填入 `authorized_dingtalk_user_ids` 的账号）发起或要求执行**完整三 Skill 演化**（Builder → Reviewer → Evolver，含满足门禁后的改仓库与 `ai-evolve/*` PR）。
- **不在名单内**：Orchestrator 应**拒绝实跑**，输出 `FAILURE_CODES=DINGTALK_EVOLUTION_UNAUTHORIZED`，**不**进入改代码/开 PR；可提供**只读**分析或引导其联系授权用户。
- **技术说明**：仓库内配置为**编排与合规约束**；钉钉侧仍建议用**群成员权限 / 机器人可见范围**做硬隔离；二者同时生效最佳。

