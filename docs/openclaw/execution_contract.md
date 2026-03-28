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

## 9. 双轨证据（本地可复核 + 外部可引用）与外部知识边界

**机器可读**：`config/evolution_invariants.yaml` → **`dual_evidence`**。

- **适用范围**：因子 / 策略 / 研究文档（报告线）/ 波动区间等 **`*_evolution_on_demand`** 类研究演化；**不**强制要求纯 CI / Cron 机械取证类工作流（见 invariants 中 `not_required_when`）。
- **Builder**：在四段证据不变的前提下，`[RAW_OUTPUT]` 内须含 **`[LOCAL_EVIDENCE]`** 与 **`[EXTERNAL_REFS]`**（逻辑小节，小标题即可）。本地段须能指回命令输出或仓库路径；外部段须含至少一次检索得到的 **`https://` 链接**（标题 + 摘录）。检索结论写入 **`EVIDENCE_REF`**（与 Orchestrator 8 行键值一致）。
- **外部知识角色**：仅作**假设、对标、术语与表述升级**；**不能**替代本地命令与数据复核，也不得在矛盾时压过本地 RAW。
- **是否改代码**：仅当 **`[LOCAL_EVIDENCE]`** 已包含与改动匹配的**短样本验证**（有限回测、定向测试、`verify_predictions` 等），且 Reviewer 通过**样本期 / 过拟合**门禁（`SAMPLE_TOO_SHORT`、`OVERFIT_RISK` 等）时，方可 `AUTOFIX_ALLOWED=true` 并开 PR。缺任一脚：**`DUAL_EVIDENCE_INCOMPLETE`**（见 `failure_codes.md`）。
- **边界**：不将权限扩至 `denied_paths`（采集、脚本、通知等）；先进性与可用性在 **allowed_paths** 内靠证据链提升。

## 10. 用户侧：自然语言指令与输出克制

**机器可读**：`config/evolution_invariants.yaml` → **`user_facing`**。

- **指令**：用户不必每次附带长篇「规划话术」或工作流 YAML 全名；口语意图即可。Agent **仍须**在内部 `read` 三文件并遵守双轨证据与门禁；简短指令**不是**跳过 read 的借口。
- **对用户的回复**：默认 **少讲契约、少要确认**；不要把 invariants/contract 大段贴给用户，也不要例行追问「您是否确认遵守某条规则」。结论用人话写短（几句或要点列表即可）。
- **机器块**：演化/编排类任务的 **8 行 `KEY=value`** 仍须在回复中**完整、可截取**地给出（通常置于**末尾单独一段**）；这是为日志与自动化解析，**不是**要求用户逐条口头确认。
- **例外**：用户明确要求「打印门禁依据 / 教学 / 审计」时，可展开引用路径与片段。
- **报告诊断 → 文档实跑（同会话连续两拍）**：用户可先只做诊断；在同一会话中用简短话确认实跑后，Agent 应**连续执行**阶段二（见 `evolution_invariants.yaml` → `user_facing.chained_report_diagnosis_to_doc_pr`），不必要求用户重贴长模板。对**契约条款**的啰嗦确认仍应避免；对**是否改仓库**的**一次**业务确认允许且建议保留。

