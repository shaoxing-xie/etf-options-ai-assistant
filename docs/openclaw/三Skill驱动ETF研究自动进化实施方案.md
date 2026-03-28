## 三 Skill 驱动 ETF 研究自动进化实施方案（github + 编排 + Evolver）

> 目标：在 `etf-options-ai-assistant` 内，把 **github + agent-team-orchestration + capability-evolver** 变成一条“对 ETF/股票研究友好、对数据采集保守”的自动进化流水线——让分析类、指标计算、策略研究模块可以持续自我改进，而数据采集与平台集成模块保持稳态。

---

### 一、进化边界：允许进化 vs. 只读区域

#### 0. 配置文件：`config/evolver_scope.yaml`

为避免仅依赖 Prompt 在运行时“记忆”边界，建议在仓库根目录新增一份结构化配置：

```yaml
# config/evolver_scope.yaml（示例）
allowed_paths:
  - "plugins/analysis/**"
  - "strategies/**"
  - "docs/research/**"
  - "docs/openclaw/**"

denied_paths:
  - "plugins/data_collection/**"
  - "scripts/**"
  - "config/openclaw_*.yaml"
  - "plugins/notification/**"
  - ".github/**"

risk_rules:
  RISK_LOW: >
    变更仅限文档、研究 Checklist、因子实现或策略参数，且有回测或诊断证据显示效果改善或风险下降。
  RISK_MEDIUM: >
    变更涉及策略核心逻辑或样本期 < 2 年 / 标的过少 / 风险指标边界模糊。
  RISK_HIGH: >
    涉及 data_collection、平台集成、配置密钥、通知通道或无法提供充分证据支撑的逻辑大改。
  OUT_OF_SCOPE: >
    任何修改 denied_paths 中的文件或不在 allowed_paths 中的路径。
```

所有演化相关的 Prompt（Orchestrator / Builder / Reviewer / Evolver）应在开头显式声明：

> “先读取 `config/evolver_scope.yaml`，所有自动修改必须落在 allowed_paths 内；若涉及 denied_paths，则直接判定为 OUT_OF_SCOPE 并返回 TEAM_FAIL。”

#### 1.1 只读 / 受限模块（禁止自动代码修改）

- **数据采集与平台集成**：
  - `plugins/data_collection/**`
  - 与 OpenClaw 平台路径强绑定的脚本，例如：
    - `scripts/release_safety_gate.py`
    - `scripts/check_cron_token_usage.py`
    - `scripts/cleanup_unused_openclaw_agents.py`
    - `scripts/sync_openclaw_model_routes.py`
    - 其他对 `~/.openclaw/**` 有显式依赖的脚本
  - 平台/通知配置：
    - `config/openclaw_*.yaml`
    - `plugins/notification/**`
- **约束要求**：
  - Evolver 发现这些区域存在问题时，只能：
    - 生成 **Issue / TODO** 或
    - 生成 **人工处理建议**（不直接改代码）
  - Reviewer 对任何涉及上述路径的自动 Patch，必须：
    - 设置：`TEAM_RESULT=TEAM_FAIL`
    - 在 `FAILURE_CODES` 中包含：`OUT_OF_SCOPE`

#### 1.2 允许自动进化的模块（SAFE-AUTOFIX 范围）

- **分析与研究模块**：
  - `plugins/analysis/**`：A 股指标、因子、统计特征计算
  - `plugins/research/**`：回测解释、报告生成辅助
  - `strategies/**`：交易策略规则、参数、过滤器与风险控制逻辑
- **文档与 Checklist 模块**：
  - `docs/research/**`：研究类说明、方法论、Checklist
  - `docs/openclaw/**` 中与 ETF 研究相关的流程文档 / 模板（不含平台安装与密钥配置说明）
- **约束要求**：
  - Evolver 的自动 Patch 仅可落在上述路径中。
  - Reviewer 在审查时，对任何超出允许路径的变更都应视为 `OUT_OF_SCOPE` 错误。

> 建议在仓库新增 `config/evolver_scope.yaml`（可选），显式列出 **allow-list 与 deny-list**，供 Prompt 和工具统一引用。

---

### 二、GitHub 级别的“进化工作流”约束

#### 2.1 AI 进化专用分支与命名规范

- **进化分支前缀**：
  - `ai-evolve/analysis-*`：指标、因子、统计特征相关演化
  - `ai-evolve/strategy-*`：策略参数、过滤器、风控规则演化
  - `ai-evolve/report-*`：研究报告模板、Checklist、解读文档演化
- **规则**：
  - Evolver 仅允许在以上前缀分支上触发：
    - `github_create_pr`
    - `github_commit`
  - 任何来自非 `ai-evolve/*` 分支的自动提交请求，Reviewer 必须标记为高风险并拒绝。

#### 2.2 PR 标题与描述模板

- **标题格式**：
  - 分析/因子类：`[AI Evolver][LOW-RISK] refine A-share factor XXX`
  - 策略类：`[AI Evolver][LOW-RISK] tune strategy YYY params`
  - 文档类：`[AI Evolver][DOC] update intraday research checklist`
- **PR 描述必含字段（与执行契约对齐）**：
  - `TEAM_RESULT=TEAM_OK | TEAM_FAIL`
  - `FAILURE_CODES=...`
  - `ROOT_CAUSE=...`
  - `RISK=LOW | MEDIUM | HIGH`
  - `AUTOFIX_ALLOWED=true | false`
  - `EVIDENCE_REF=<回测 ID / CI Run ID / 日志路径>`
  - `TOP_ACTIONS=<本 PR 所采取的主要措施>`
- **合并策略**：
  - 任何自动 PR **都不自动 merge** 到 `main`，始终需要人工 review + merge。
  - 仅当：
    - `TEAM_RESULT=TEAM_OK`
    - `RISK=LOW`
    - `AUTOFIX_ALLOWED=true`
    - 且改动范围局限于允许进化路径
    时，建议采用“快速通道”人工合并。

> 具体的分支前缀、前置条件与字段约束，已经在 `docs/openclaw/prompt_templates/orchestrator_evolution.md` 与 `builder_evolution.md` 中固化：Orchestrator 负责在满足 `TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true` 且仅触及 `allowed_paths` 时，才允许 Builder 使用 github 工具在 `ai-evolve/*` 分支上创建 PR。 

---

### 三、团队编排：Builder / Reviewer / Evolver 三角色分工

#### 3.1 Builder（code_maintenance_agent）

- **主要职责**：
  - 在允许进化模块中实施具体改动：
    - 新增或优化 A 股指标 / 因子实现
    - 调整策略参数、过滤器、风控规则
    - 根据研究任务生成最小可运行回测脚本（仅复用已有数据采集输出）
  - 使用 `exec` 工具运行有限集合的标准命令（例如：回测脚本、单次 CI 任务）。
- **能力边界**：
  - 禁止：
    - 直接修改 data_collection 模块
    - 修改带密钥/敏感路径的配置项
  - 允许：
    - 修改 `analysis/**`、`strategies/**`、`docs/research/**`
    - 在 Evolver 允许的前提下，通过 github skill 创建/更新 `ai-evolve/*` 分支上的代码。

#### 3.2 Reviewer（etf_analysis_agent）

- **主要职责**：
  - 对 Builder 的改动做“研究员视角”的质量把关：
    - 校验统计显著性、样本期长度、过拟合风险
    - 评估策略与指标变更对风险暴露和换手的影响
  - 输出统一格式的审查结论：
    - `TEAM_RESULT` / `FAILURE_CODES` / `ROOT_CAUSE` / `RISK` / `AUTOFIX_ALLOWED` / `EVIDENCE_REF` / `TOP_ACTIONS`
- **硬约束**：
  - 无充足证据（无回测/无 CI/无日志）不得给 `TEAM_OK`。
  - 若改动涉及超出允许范围（如 data_collection），必须：
    - `TEAM_RESULT=TEAM_FAIL`
    - `FAILURE_CODES` 包含 `OUT_OF_SCOPE`。
  - 建议 Reviewer 至少回答以下量化问题，并在结论中简要给出判断依据：
    - **样本期**：回测是否覆盖 ≥ 3 年、多个市场环境？若否，应在 `FAILURE_CODES` 中包含 `SAMPLE_TOO_SHORT`。
    - **收益与风险**：本次改动是否带来 Sharpe / 信息比率提升，或最大回撤/波动下降？若改善不显著，应将 `RISK` 至少评为 `MEDIUM`。
    - **过拟合信号**：参数是否强依赖极短时间段或极少数标的？若有，应附加 `OVERFIT_RISK` 到 `FAILURE_CODES`。
    - **边界检查**：是否有任何 diff 触及 `denied_paths` 中的路径？如有，直接判定 `OUT_OF_SCOPE` 并拒绝自动修复/PR。

#### 3.3 Evolver（capability-evolver skill）

- **主要职责**：
  - 从失败 / 退化 / 偏差案例中，抽象出 **可复用的演化模式**：
    - `ERROR_CLASS`：如 `SIGNAL_DRIFT` / `OVERFIT` / `DATA_LEAK` / `DOC_GAP` 等
    - `STANDARD_COMMANDS`：以后遇到类似问题时，优先尝试的命令组合
    - `CHECKLIST_UPDATE`：补充或调整研究 Checklist 与工作流 SOP
    - （可选）`PROMPT_PATCH`：针对 Builder/Reviewer prompt 的小幅优化建议
- **产出落地位置建议**：
  - 因子/指标相关：`docs/research/factor_evolution_log.md`
  - 策略相关：`docs/research/strategy_evolution_log.md`
  - 通用执行模式：更新 `docs/openclaw/execution_contract.md` 或对应 Prompt 模板。

#### 3.4 双轨证据与外部知识边界（P0–P2 已落盘）

在**不扩权**到 `evolver_scope.denied_paths`（采集、`scripts/**` 修改、通知等）的前提下，三 Skill 的产出上限主要由证据是否**同时**满足 **本地可复核** 与 **外部可引用** 决定：

| 层级 | 落点 | 内容 |
|------|------|------|
| P0 | `config/evolution_invariants.yaml` → **`dual_evidence`** | 适用边界、`[LOCAL_EVIDENCE]` / `[EXTERNAL_REFS]` 结构、`EVIDENCE_REF` 双修、外部知识角色、改代码短样本门禁 |
| P0 | `docs/openclaw/execution_contract.md` §9 | 与人读协议对齐 |
| P0 | `docs/openclaw/failure_codes.md` | **`DUAL_EVIDENCE_INCOMPLETE`** |
| P1 | `docs/openclaw/prompt_templates/builder_evolution.md`、`reviewer_evolution.md`、`orchestrator_evolution.md`、`evolver_evolution.md` | 检索写入 RAW、Reviewer 校验、编排指令、Evolver 复盘 |
| P2 | `workflows/*_evolution_on_demand.yaml`、`AGENTS.md`、`agent_system_snippets/etf_main_evolution_preflight.md` | 分析 / 策略 / 报告三线工作流说明与 OpenClaw 预检 |

**原则**：检索与引用进入 Builder **RAW** 与 **EVIDENCE_REF**；外部材料仅限**假设与表述升级**；**是否改代码**由 **本地短样本验证** + Reviewer **样本期 / 过拟合**门禁裁定。

---

### 四、按模块拆分的典型“自动进化”场景

#### 场景 A：A 股指标 / 因子库演化（analysis/**）

- **触发条件**：
  - 质量巡检或人工评审发现：
    - 某指标实现依赖的财报字段/接口已过时；
    - 某因子在近期样本中表现退化、暴露异常或信息含量明显下降。
- **流程**：
  1. Builder：
     - 读取现有实现（analysis 模块 + 对应回测脚本）。
     - 启动标准回测命令（仅限指定标的与时间窗，避免大规模资源消耗）。
     - 在 `analysis/**` 里添加或重构指标/因子实现。
  2. Reviewer：
     - 检查回测结果是否有统计意义、是否降低风险或提高收益。
     - 若收益/风险改善不显著或存在明显过拟合迹象：返回 `TEAM_FAIL` 或 `RISK>=MEDIUM`。
  3. Evolver：
     - 记录“问题 → 操作 → 结果”链路，更新因子演化日志与 Checklist。

#### 场景 B：交易策略参数与过滤器演化（strategies/**）

- **触发条件**：
  - 定期回测结果中某策略长期跑输基准或波动/回撤超出预期。
- **自动进化范围限制**：
  - 只允许调整：
    - 参数、阈值
    - 过滤条件（如流动性过滤、市值过滤）
    - 风险控制规则（止损、仓位上限）
  - 不自动更改：
    - 入场/出场信号定义
    - 标的池定义
- **流程与审查**：
  - 与场景 A 类似，但 Reviewer 更侧重：
    - 回撤、最大回撤恢复时间
    - 策略与基准的跟踪误差与风控约束。

#### 场景 C：研究报告模版与 Checklist 演化（docs/research/**）

- **触发条件**：
  - 质量巡检发现：
    - 报告缺少对关键风险的覆盖；
    - 研究流程中常见失误没有被 Checklist 捕捉。
- **演化内容**：
  - 完全不改业务逻辑代码，仅更新：
    - 报告模版中的章节与关键指标列表；
    - Checklist 条目与执行顺序；
    - 对应 Runbook 中的诊断步骤说明。
- **风险级别**：
  - 通常为 `RISK=LOW`，可纳入自动 PR 快速通道，仍由人工合并。

---

### 五、调度与触发：如何“自动”但不失控

在现有 `quality_backstop_audit.yaml`、`cron_error_autofix_on_demand.yaml` 等基础上，扩展以下触发类型：

#### 5.1 日级 / 周级“研究演化任务”调度（建议低频）

- 示例（后续可在 `workflows/` 下补充 YAML）：
  - `factor_evolution_weekly.yaml`：每周汇总近期因子表现，筛选候选演化任务。
  - `strategy_evolution_weekly.yaml`：每周对主要策略做归因与参数稳定性检查。
- 行为：
  - 不强制每次都动代码，而是：
    - 产出“候选演化任务列表”；
    - 对每个候选由 Reviewer+Evolver 决定是：
      - 仅创建 Issue；
      - 还是允许 Builder 发起低风险 PR。

#### 5.2 CI 成功但带 WARNING 的场景挂钩

- CI 若报告：
  - 样本期过短；
  - 数据分布偏移；
  - 因子/策略表现退化但未到失败程度；
- 行为：
  - 记录为 Evolver 的输入样本；
  - 由 Evolver 决定是否：
    - 更新 Checklist / 模版；
    - 排队到下一次演化任务调度中。

---

### 六、风险控制与权限策略

#### 6.1 对 data_collection 的“只读”保护

- 所有自动演化工作流必须在 Prompt 与执行契约中明确：
  - `plugins/data_collection/**` 为只读；
  - 任何针对该路径的 Patch 视为违规。
- Reviewer 模板中应固化：
  - 一旦检测到 data_collection 路径变更：
    - `TEAM_RESULT=TEAM_FAIL`
    - `FAILURE_CODES` 至少包含：`OUT_OF_SCOPE`。

#### 6.2 低风险优先与人工盖章

- 自动 PR 的前置条件：
  - 变更路径在允许进化范围内；
  - `TEAM_RESULT=TEAM_OK`；
  - `RISK=LOW`；
  - `AUTOFIX_ALLOWED=true`。
- 即便满足上述条件：
  - 仍然只允许 **自动创建 PR，不允许自动 merge**。
  - 保留人工对 PR 的最终决策权。

---

### 七、推荐的分阶段落地路线

1. **阶段 1：仅文档与 Checklist 演化**
   - 范围：`docs/research/**`、`docs/openclaw/**` 中研究相关部分。
   - 收益：对现有研究流程和报告结构的改善，风险极低。
2. **阶段 2：因子/指标库演化（analysis/**）**
   - 基于少量回测用例与明确的统计标准，引入低风险因子调整。
3. **阶段 3：策略参数与过滤器演化（strategies/**）**
   - 在有稳定回测框架与风险评估工具后，逐步开放参数层的自动调优。

每一阶段都建议先通过：

- 1–2 次“演练式”工作流（手动触发）；
- 检查生成的 PR / Issue / 文档是否符合执行契约与风险约束；
- 再考虑升级为定时调度或 CI 挂钩。

---

### 八、日常使用与操作指南（How-To）

#### 8.0.1 OpenClaw：为 `etf_main` 挂载固定 system 片段（强制 evolution 先 read）

仓库已提供**可复制**的预检正文：**`docs/openclaw/agent_system_snippets/etf_main_evolution_preflight.md`**（文件内「片段正文」围栏中的整段）。

**操作建议**：

1. 打开该 Markdown，复制「片段正文」代码块内的全部文字。  
2. 在 OpenClaw 配置里找到 **Agent `etf_main`** 的 **system prompt** 追加区（常见字段名：`systemPrompt`、`extraSystemPrompt`、`additionalInstructions` 等，以你本机 OpenClaw 版本文档为准）。  
3. 将复制内容**粘贴在 system 尾部**，保存后**重启或重载** OpenClaw 网关 / Agent 进程。  
4. 若 OpenClaw 支持从工作区**按路径注入**额外 system 文件，可改为指向工作区内上述 `.md` 的绝对路径，减少手工同步。

效果：钉钉、CLI 等待办只要路由到 `etf_main` 且用户话轮命中 evolution 相关意图，模型会先被硬性要求 **read** `evolution_invariants.yaml` 等三份文件，再允许改仓库；与 **`AGENTS.md`**、四角色 Prompt 模板互为补充。

#### 8.1 手动触发三类演化工作流（推荐起步方式）

在确认网关与代理正常的前提下，日常可以按需触发以下三类 on-demand 工作流：

- **因子 / 指标演化**：
  - 工作流：`workflows/factor_evolution_on_demand.yaml`
  - 典型使用场景：某个因子最近 6 个月信息比率明显下降，希望 AI 团队先给出“是否需要调整”的建议与候选补丁。
- **策略参数 / 过滤器演化**：
  - 工作流：`workflows/strategy_param_evolution_on_demand.yaml`
  - 场景：策略回撤放大或波动异常，希望在不改核心信号逻辑的前提下，对止损/仓位/过滤条件做调优。
- **研究文档 / Checklist 演化**：
  - 工作流：`workflows/research_checklist_evolution_on_demand.yaml`
  - 场景：某研究报告模板或 Checklist 经常被实际使用“踩坑”，需要补充风险说明或样本期要求。
- **宽基 ETF 预测波动区间优化**：
  - 工作流：`workflows/volatility_range_evolution_on_demand.yaml`
  - 场景：`tool_predict_volatility` / `tool_predict_intraday_range` 与快报缓存区间需对照近期实际表现做校准，并结合可引用的网上方法论做证据化改进（详见 **8.1.2**）。

触发方式可以有两种：

1. **通过 OpenClaw Agent（推荐）**：在 DingTalk / 本地 CLI 中对 `etf_main` 发指令，明确说明：
   - 使用哪一个 `*_evolution_on_demand.yaml`；
   - 指定目标对象（因子/策略/doc 路径）与问题描述（performance_issue/gap_summary）。
2. **通过 `openclaw agent --local` + 结构化 message**：在 message 中明确写出：
   - 目标工作流名；
   - 触发类型与输入参数；
   - 要求 Orchestrator 按 `orchestrator_evolution.md` 模板执行。

#### 8.1.1 本地干跑示例（脚本已 smoke，可直接复用）

仓库提供 **`scripts/evolution_workflows_dry_run.sh`**，把三条 `*_evolution_on_demand.yaml` 的占位参数、`openclaw agent --local` 调用方式，以及「仅输出键值行」的提示词约定都写好，便于日常复制演练或接入简单自动化。

**前置条件**

- 已安装 `openclaw`，且本机可正常调用配置的 LLM。
- `~/.openclaw/.env` 中可配置 `GITHUB_PAT=`（脚本会导出为 `GH_TOKEN`，供 GitHub 类工具使用）。
- Agent **`etf_main`** 与项目工作区 **`~/.openclaw/workspaces/etf-options-ai-assistant`** 指向的代码树一致（若与 `~/etf-options-ai-assistant` 为同一目录或符号链接，`cp` 时出现 “same file” 属于正常）。

**常用命令**

```bash
cd ~/etf-options-ai-assistant
chmod +x scripts/evolution_workflows_dry_run.sh   # 首次

# 三条分别演练（推荐串行，避免同一会话队列冲突）
./scripts/evolution_workflows_dry_run.sh research
./scripts/evolution_workflows_dry_run.sh factor
./scripts/evolution_workflows_dry_run.sh strategy

# 一次跑完三条（总耗时会较长）
./scripts/evolution_workflows_dry_run.sh all

# 可选：自定义会话前缀，便于区分多次试验
EVO_RUN_ID=smoke-$(date +%Y%m%d) ./scripts/evolution_workflows_dry_run.sh research
```

脚本内占位含义一览：

| 子命令 | YAML | `--timeout`（秒） | 主要输入（可在脚本内改） |
|--------|------|-------------------|---------------------------|
| `research` | `research_checklist_evolution_on_demand.yaml` | 300 | `target_doc`、`gap_summary` |
| `factor` | `factor_evolution_on_demand.yaml` | 600 | `target_factor`、`problem_summary` |
| `strategy` | `strategy_param_evolution_on_demand.yaml` | 600 | `target_strategy`、`performance_issue` |

**与脚本等价的「单条手工」示例（Checklist / research）**

若不用脚本，可直接：

```bash
cd ~/etf-options-ai-assistant
export GH_TOKEN="$(grep '^GITHUB_PAT=' ~/.openclaw/.env | cut -d= -f2- | tail -n 1)"

openclaw agent --local \
  --agent etf_main \
  --session-id "evo-doc-$(date +%Y%m%d-%H%M%S)" \
  --thinking off \
  --timeout 300 \
  --verbose on \
  --json \
  --message "使用 workflows/research_checklist_evolution_on_demand.yaml 做一次干跑：
- target_doc=docs/research/factor_research_checklist.md
- gap_summary=（在此写你发现的问题，例如样本期/过拟合条款不够可执行）

仅文档建议、不改代码、不创建 PR。最终只输出键值行：
ORCH_STATUS FAILURE_CODES RISK AUTOFIX_ALLOWED PR_CREATED PR_REF EVIDENCE_REF TOP_ACTIONS
（第一行必须以 ORCH_STATUS= 开头；不要 NO_REPLY 前缀；每个键值单独一行更佳。）"
```

**典型终端输出如何看**

- 日志里 **`embedded run done ... aborted=false`** 表示本次运行正常结束。
- 若启用了 **`--json`**，最终 JSON 里 **`payloads[0].text`** 即为模型给出的结构化小结；干跑阶段可重点解析：
  - `ORCH_STATUS=TEAM_OK|TEAM_FAIL`
  - `FAILURE_CODES=`（如 `NONE`、`NO_EVIDENCE`）
  - `RISK=LOW|MEDIUM|HIGH`
  - `AUTOFIX_ALLOWED` / `PR_CREATED` / `PR_REF` / `EVIDENCE_REF` / `TOP_ACTIONS`
- **因子 / 策略** 干跑若工具调用较多，可适当提高 `--timeout`（脚本中 factor/strategy 已设为 600 秒）。
- 若在 WSL 下执行脚本报 **`bash\r`**：说明脚本为 CRLF 换行，可执行  
  `sed -i 's/\r$//' scripts/evolution_workflows_dry_run.sh`  
  仓库根目录 **`.gitattributes`** 已对 `*.sh` 约定 `eol=lf`，克隆后一般可避免复发。
- `feishu` / `qwen-portal-auth` 插件加载失败、`mem0 capture failed: fetch failed` 等多为环境或网络侧问题，**不必然**代表演化工作流本身失败；以 **`aborted` 与 `ORCH_STATUS`** 为准。

#### 8.1.2 宽基 ETF「预测波动区间」优化（三 Skill + 网上方法论）

盘中 / 盘前 / 信号工作流里调用的 **`tool_predict_volatility`**、**`tool_predict_intraday_range`** 与快报缓存 **`data/volatility_ranges/*.json`** 共用一套收敛口径（见 `docs/openclaw/宽基ETF巡检快报-日内波动区间收敛说明.md`）。若要**基于近期实际表现**系统性地改进预测模型与参数，可使用专用按需工作流：

- YAML：`workflows/volatility_range_evolution_on_demand.yaml`
- `config/evolver_scope.yaml` 已扩展允许改动：`config.yaml`（须限定在波动/监控相关键）、`src/volatility_range.py`、`src/volatility_range_fallback.py`、`src/on_demand_predictor.py` 及原有 `plugins/analysis/**` 等；**仍禁止**改 data_collection、通知、`config/openclaw_*.yaml` 等。

**推荐流程（人工执行要点）**

1. **取证**：让 Builder 读取最近若干交易日的 `data/prediction_records/predictions_*.json`、`data/volatility_ranges/*.json`，对照真实高低价做简单覆盖 / 突破率统计（不必长回测，但要可复核）。  
2. **外部知识**：至少一次 **`tavily_search` / `web-search`**（或 Agent 已挂载的等价工具），检索可落地的方法论（如 Parkinson / EWMA / HAR、预测区间校准、realized volatility 与日内区间等），**写清标题与链接**写入 `EVIDENCE_REF`。  
3. **改哪里**：  
   - 参数层：`config.yaml -> signal_params -> intraday_monitor_510300 -> volatility`（`min_intraday_pct` / `max_intraday_pct` 等）；  
   - 实现层：`plugins/analysis/intraday_range.py`、`plugins/analysis/volatility_prediction.py`、`src/volatility_range.py`、必要时 `src/on_demand_predictor.py`。  
4. **Reviewer**：窗口是否过短、是否过拟合某一段行情、`config.yaml` 是否出现与波动无关的改动。  
5. **干跑与正式**：首次可 `AUTOFIX_ALLOWED=false` 仅要诊断与 `TOP_ACTIONS`；确认后再允许低风险 PR。

**OpenClaw 工作区与 `data/`（避免「本机有文件、Agent 报空」）**

- `prediction_records`、`volatility_ranges` 落在 **`data/`** 下，且 **`data/` 被 `.gitignore`**，不会随仓库推到远端，也未必出现在 **`~/.openclaw/workspaces/etf-options-ai-assistant`** 这份「工作区副本」里。
- Agent 的 **`read` / `exec` 一般以 workspaceDir 为根**（JSON meta 里 `systemPromptReport.workspaceDir`）。在克隆目录 `ls` 有文件，并不等于工作区里一定有。
- **建议在跑 volatility 演化前先同步一次**（按需二选一或都做）：

```bash
WS=~/.openclaw/workspaces/etf-options-ai-assistant
mkdir -p "$WS/data/prediction_records" "$WS/data/volatility_ranges"
rsync -a ~/etf-options-ai-assistant/data/prediction_records/ "$WS/data/prediction_records/"
rsync -a ~/etf-options-ai-assistant/data/volatility_ranges/ "$WS/data/volatility_ranges/"
```

然后在工作区验证：`ls "$WS/data/prediction_records" | tail` 与 `ls "$WS/data/volatility_ranges" | tail`。

**一键同步 + 干跑（仓库脚本）**

```bash
cd ~/etf-options-ai-assistant
# 将本机克隆下的 data/ 同步到 OpenClaw workspace（Agent 的 read/exec 以该目录为准）
./scripts/evolution_workflows_dry_run.sh sync-data

./scripts/evolution_workflows_dry_run.sh volatility
```

也可设置 `OPENCLAW_WORKSPACE=/path/to/workspace` 后执行 `sync-data`。

#### 8.1.3 干跑与实跑：什么时候可以「真改代码、真开 PR」

- **干跑**（`volatility` 及脚本里写明「不改代码、不创建 PR」或 `AUTOFIX_ALLOWED=false`）：只做流程与取证校验，适合首次摸底、环境不通、或只想看 `TOP_ACTIONS`。
- **实跑**：在同一条 evolution 工作流下，由 Reviewer 在证据充分时给出 **`TEAM_OK` + `RISK=LOW` + `AUTOFIX_ALLOWED=true`**，Orchestrator 按 `orchestrator_evolution.md` 允许 Builder 做**最小范围**修改，并通过 **github 工具**在 **`ai-evolve/analysis-*` / `ai-evolve/strategy-*` / `ai-evolve/report-*`** 上**创建 PR**；**不会**自动 merge **main**，合并须人工审核。

仓库脚本已提供波动区间 **实跑** 入口（请先 `sync-data`，再执行）：

```bash
cd ~/etf-options-ai-assistant
./scripts/evolution_workflows_dry_run.sh sync-data
EVO_PAIN_SUMMARY='这里写你的具体痛点与期望，例如：近 20 日区间突破率偏高、置信度与实现波动脱节等' \
  ./scripts/evolution_workflows_dry_run.sh volatility-live
```

其他三类 evolution（research / factor / strategy）若要从干跑改为实跑：把发给 Agent 的 message 中与「禁止 PR」相反的句子，改成与 **`orchestrator_evolution.md` 第 3 节**一致的 PR 前置条件表述即可；波动区间已与 **`volatility-live`** 对齐。

**等价 `openclaw agent --local` 示例（可自行改 `pain_summary` / 窗口）**

```bash
cd ~/etf-options-ai-assistant
export GH_TOKEN="$(grep '^GITHUB_PAT=' ~/.openclaw/.env | cut -d= -f2- | tail -n 1)"

openclaw agent --local \
  --agent etf_main \
  --session-id "evo-vol-$(date +%Y%m%d-%H%M%S)" \
  --thinking off \
  --timeout 900 \
  --verbose on \
  --json \
  --message "使用 workflows/volatility_range_evolution_on_demand.yaml。

target_symbols=510300
evaluation_window=30
pain_summary=近期预测日内区间偏宽/偏窄或与实现波动不匹配（在此补充你的观察）。

硬性门禁（违反任一条则 ORCH_STATUS=TEAM_FAIL，不得 FAILURE_CODES=NONE）：
1) exec：ls -la data/prediction_records data/volatility_ranges 2>&1，真实输出须出现在对话中。
2) read config/evolver_scope.yaml。
3) 若无 predictions_*.json / 无 volatility_ranges/*.json：FAILURE_CODES=NO_LOCAL_PREDICTION_ARTIFACTS，TOP_ACTIONS=先跑工作流落库后再演化；禁止编造「手建目录、新开发模块」。
4) 若有 json：read 至少一个具体文件。
5) 实际调用 tavily_search；EVIDENCE_REF 须含字面量 https://。
6) 首次仅诊断：AUTOFIX_ALLOWED=false，不创建 PR；改进优先 config/置信度再模型层。

最终只输出键值行：ORCH_STATUS FAILURE_CODES RISK AUTOFIX_ALLOWED PR_CREATED PR_REF EVIDENCE_REF TOP_ACTIONS
（第一行必须以 ORCH_STATUS= 开头；禁止 NO_REPLY 前缀。）"
```

> **说明**：`--timeout 900` 因含检索与多文件读取；若超时可在保证串行、无其它 `etf_main` 任务的前提下再上调。

**验收一次 volatility 干跑是否「真取证」**

单看 JSON 里 `ORCH_STATUS=TEAM_OK` **不够**：LLM 可能未调用工具却写出占位 `EVIDENCE_REF`（例如 `prediction_records_none`、无 `https://` 的「方法论」字样）。请在 **`--verbose on` 日志**中确认至少出现：

- **`tool=exec`**（如对 `data/prediction_records`、`data/volatility_ranges` 的 `ls`）；
- **`tool=read`**（`config/evolver_scope.yaml`，以及存在时的具体 `*.json`）；
- **`tool=tavily_search`**（或等价检索工具）。

**本地无落库文件时**：应判 **`TEAM_FAIL` + `FAILURE_CODES=NO_LOCAL_PREDICTION_ARTIFACTS`**（或等价），`TOP_ACTIONS` 应为「先跑工作流让 `tool_predict_*` 写出 `prediction_records` / `volatility_ranges`」，而不是「新建目录、实现新模块」——后者多为模型幻觉。  
**`EVIDENCE_REF` 中含 `https://`** 可视为检索已落地的最低门槛（与脚本门禁一致）。

若全程无工具调用却报 `TEAM_OK`，或 `FAILURE_CODES=NONE` 与「无数据/无 URL」并存，应视为**无效干跑**；请拉取最新 `scripts/evolution_workflows_dry_run.sh` 中的 **`volatility`** 子命令后重跑。

#### 8.1.4 钉钉里怎么给 OpenClaw 下任务（示例话术）

**原则已固化在仓库配置**：`config/evolution_invariants.yaml`（Orchestrator / Builder / Reviewer / Evolver 模板与 `AGENTS.md` 已要求演化类任务 **read** 该文件）。钉钉话术可与 invariants 并用；若冲突，以 invariants 为准。该文件**不在** `evolver_scope.allowed_paths` 内，自动进化 PR **不得**修改本文件。  
**钉钉仍易跑偏时**：务必按 **「8.0.1」** 把 **`docs/openclaw/agent_system_snippets/etf_main_evolution_preflight.md`** 中的片段挂进 OpenClaw 里 `etf_main` 的 system 尾部。

以下假设你已在 OpenClaw 里把 **钉钉消息入口** 绑到 Agent **`etf_main`**（群机器人 @、或应用允许的私信/会话）。**具体以 `~/.openclaw` 里网关与 Agent 路由为准**；若当前只接了分析/通知而没有接入 `etf_main`，需要先在 OpenClaw 侧配置「该会话 → etf_main」。

**授权（已写入仓库配置）**：在钉钉上**仅**允许用户 **「谢富根」** 发起或要求执行**完整三 Skill 演化**（多角色编排 + Evolver + 满足门禁后的改仓库 / `ai-evolve/*` PR）。名单与拒绝时的键值输出规则见 **`config/evolution_invariants.yaml`** → **`dingtalk_three_skill_evolution`**；执行协议见 **`docs/openclaw/execution_contract.md` §8**。其他用户可走只读分析，或请谢富根代发演化任务；钉钉群权限建议与此一致做硬隔离。

**极简自然语言（推荐日常）**  
一次性把 **`docs/openclaw/agent_system_snippets/etf_main_evolution_preflight.md`** 片段挂进 **`etf_main`** 的 system 尾部后，**不必**每次在钉钉粘贴示例 A–J 的全文技术话术。用**普通中文**说清意图即可，例如：

- 「帮我诊断开盘行情分析这条线，报告最好接近机构晨报，先别改仓库。」
- 「因子动量 20 日均线这半年走弱，干跑演化，别建 PR。」

细则（`read` 三文件、`dual_evidence`、8 行键值、钉钉授权等）由 **`config/evolution_invariants.yaml` → `user_facing`** 与 **`docs/openclaw/execution_contract.md` §10** 规定在**模型内部遵守**。Bot **默认不应**向群里长篇复述契约或追问「您是否确认某某条」；**仍须在回复末尾**给出可截取的 **8 行 `KEY=value`**（这是机器解析用，不是让你逐条口头确认）。需要审计/教学时再单独说：「请展开门禁依据」。

**话术结构（仅在需要可复制模板或新人排障时使用）：**

1. **目标 Agent**：`etf_main`（若你们群固定路由到它，可省略，但首次建议写明）。  
2. **工作流**：`workflows/xxx_evolution_on_demand.yaml` 的文件名。  
3. **输入参数**：`target_*` / `gap_summary` / `pain_summary` 等（见对应 YAML）。  
4. **模式**：干跑（不写代码、不建 PR）还是实跑（满足门禁可开 `ai-evolve/*` PR）。  
5. **输出**：要求最终回复只给键值行：`ORCH_STATUS` `FAILURE_CODES` `RISK` `AUTOFIX_ALLOWED` `PR_CREATED` `PR_REF` `EVIDENCE_REF` `TOP_ACTIONS`。  
6. **契约**：按 `orchestrator_evolution` / `reviewer_evolution` 执行；先读 `config/evolver_scope.yaml`。

**与实施方案对齐的加严条款（钉钉实跑时强烈建议附带）**

以下三条用于避免「单 Agent 写长文、口头授权绕过 Reviewer、无 PR 直提交」等偏离 **GitHub + 三 Skill 编排 + Evolver** 的情况：

1. **三角色与证据**：使用 `sessions_spawn`（或你环境中与 OpenClaw 等价的子 Agent / 分步调用），按 **Builder → Reviewer → Evolver** 执行；**Builder** 必须产出四段证据 **`[COMMAND]` / `[STDOUT]` / `[STDERR]` / `[RAW_OUTPUT]`**，**Reviewer** 仅基于证据给出 `TEAM_RESULT`、`FAILURE_CODES`、`RISK`、`AUTOFIX_ALLOWED`；**Evolver** 须给出可复制的 **`ERROR_CLASS`、`STANDARD_COMMANDS`、`CHECKLIST_UPDATE`（或 `PROMPT_PATCH`）** 等复盘要素（与 `evolver_evolution` 模板一致）。  
2. **禁止用「用户授权」替代门禁**：当 Reviewer 已判定 **`RISK=MEDIUM|HIGH`** 或 **`AUTOFIX_ALLOWED=false`** 时，**不得**仅因用户在钉钉回复「授权 autofix」就修改仓库或直推分支；若业务上允许中风险人工强开，须在 **`execution_contract.md` / 本方案**中**单独成章**约定范围（例如仅允许改 `config.yaml` 指定键），**不得**默认可绕过当前 **`TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true`** 的自动进化门槛。  
3. **GitHub PR 与 8 行键值**：任何实跑产生的代码变更，须落在 **`ai-evolve/analysis-*` / `strategy-*` / `report-*`** 等约定前缀分支并**创建 PR**，回复中必须给出 **`PR_REF`**（链接或分支名）；**禁止**只宣称「已 git commit」却无 PR、**禁止**自动 merge **`main`**。最终回复除可选简报外，须**另起一段仅含 8 行** `KEY=value`：`ORCH_STATUS`、`FAILURE_CODES`、`RISK`、`AUTOFIX_ALLOWED`、`PR_CREATED`、`PR_REF`、`EVIDENCE_REF`、`TOP_ACTIONS`（与 `orchestrator_evolution` 一致）。

完整话术可复制 **示例 F**。

---

**示例 A：研究 Checklist 演化（干跑，只改文档建议）**

```text
@机器人 etf_main

任务：使用 workflows/research_checklist_evolution_on_demand.yaml 做干跑。
target_doc=docs/research/factor_research_checklist.md
gap_summary=希望把样本期、过拟合检查写得更可执行，只要文档修改建议，不要改代码、不要创建 PR。

请按 evolution 系列 Prompt 执行，最后只回复 8 行键值：
ORCH_STATUS / FAILURE_CODES / RISK / AUTOFIX_ALLOWED / PR_CREATED / PR_REF / EVIDENCE_REF / TOP_ACTIONS
```

---

**示例 B：因子演化（干跑）**

```text
@机器人 etf_main

任务：workflows/factor_evolution_on_demand.yaml 干跑。
target_factor=factor_momentum_20d
problem_summary=近半年该因子在 510300 上 Sharpe 走弱，请只做证据收集与门禁输出，不改代码、不建 PR。

按 orchestrator_evolution 编排 Builder/Reviewer/Evolver，最终只输出上述 8 个键值行。
```

---

**示例 C：策略参数演化（实跑，允许通过门禁后开 PR）**

```text
@机器人 etf_main

任务：workflows/strategy_param_evolution_on_demand.yaml 实跑。
target_strategy=trend_following_510300
performance_issue=回撤比近一年均值高约 30%，希望在不动核心信号定义的前提下收紧过滤器/止损参数。

请读 evolver_scope 与 execution_contract。仅当 TEAM_OK、RISK=LOW、AUTOFIX_ALLOWED=true 且改动全在 allowed_paths 时，在 ai-evolve/strategy-* 上创建 PR；禁止直接改 main，禁止自动 merge。最后给出 8 行键值结论。
```

---

**示例 D：宽基波动区间（干跑，含数据与检索门禁）**

```text
@机器人 etf_main

任务：workflows/volatility_range_evolution_on_demand.yaml 干跑。
target_symbols=510300
evaluation_window=30
pain_summary=想验证预测区间与 recent prediction_records / volatility_ranges 是否一致，只做诊断。

请先 sync 或确认 OpenClaw 工作区里 data 下有 json；再 exec ls、read 样例文件、调用 tavily_search，EVIDENCE_REF 里要有 https 链接。AUTOFIX_ALLOWED=false，不建 PR。最后 8 行键值。
```

（工作区无 `data` 时，先在跑 OpenClaw 的机器上执行仓库里的 **`./scripts/evolution_workflows_dry_run.sh sync-data`**，再在钉钉重发。）

---

**示例 E：波动区间实跑**

```text
@机器人 etf_main

任务：workflows/volatility_range_evolution_on_demand.yaml 实跑。
target_symbols=510300
evaluation_window=30
pain_summary=近 20 交易日日内预测区间突破率偏高，希望在证据充分下做最小参数/实现调整。

满足 TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true 时，在 ai-evolve/analysis-volatility-* 开 PR；否则只给诊断。最终 8 行键值。
```

---

**示例 F：波动区间实跑（加强版，对齐三 Skill + GitHub PR）**

与上文「加严条款」一一对应，建议在**实跑**或**钉钉易跑偏**时整段使用（可拆成多条消息发送）。

```text
@机器人 etf_main

任务：workflows/volatility_range_evolution_on_demand.yaml 实跑（加强版）。
target_symbols=510300
evaluation_window=30
pain_summary=近窗日内预测区间突破率偏高等问题（可具体写清）。

【编排】须使用 sessions_spawn 或 OpenClaw 等价能力，按序：Builder=code_maintenance_agent → Reviewer=etf_analysis_agent → Evolver=capability-evolver。若单会话模拟，须分块标题标明三角色，且 Reviewer 不得复述未经验证的 Builder 结论而无证据指向。

【Builder】必须输出四段：[COMMAND]、[STDOUT]、[STDERR]、[RAW_OUTPUT]；含对 data/prediction_records、data/volatility_ranges（或工作区路径）及 config/evolver_scope 的取证。

【Reviewer】仅基于 RAW 输出 TEAM_RESULT、FAILURE_CODES、RISK、AUTOFIX_ALLOWED；若 RISK 非 LOW 或 AUTOFIX_ALLOWED=false，只输出诊断与 TOP_ACTIONS。

【禁止】Reviewer 已判 RISK=MEDIUM|HIGH 或 AUTOFIX_ALLOWED=false 时，禁止仅因用户钉钉「授权 autofix」就改代码或推 main。

【GitHub】代码变更必须在 ai-evolve/analysis-volatility-* 上开 PR，回复须含 PR_REF；禁止仅声称 git commit、禁止自动 merge main。

【Evolver】须给出 ERROR_CLASS、STANDARD_COMMANDS、CHECKLIST_UPDATE（或 PROMPT_PATCH）中可复制的条目。

【输出】可选一段人类可读摘要；最后必须单独一段、严格 8 行、每行一条键值，无其它文字：
ORCH_STATUS=
FAILURE_CODES=
RISK=
AUTOFIX_ALLOWED=
PR_CREATED=
PR_REF=
EVIDENCE_REF=
TOP_ACTIONS=

【PR 前置】全满足才可 PR_CREATED=true：TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true + diff 仅 evolver_scope 的 allowed_paths。
```

---

**示例 G：检查 / 诊断 / 分析 `cron` 定时任务（本机 OpenClaw）**

```text
@机器人 etf_main

任务：运维诊断 — OpenClaw 本机定时任务。

请 read 并分析 `~/.openclaw/cron/jobs.json`，按实际路径读取等价配置）。要求：
1) 列出当前 enabled/disabled 的 job、schedule/cron 表达式、触发的命令或 workflow 引用；
2) 检查是否存在重复触发、时区歧义、与 8.3 方案描述不一致的项；
3) 给出风险等级与可执行建议（是否应启用/停用/改频率/改 message）；
4) 仅在用户明确要求且变更落在 OpenClaw 配置目录、并符合你们 execution_contract 时，才可提出具体修改稿或补丁；否则只给诊断与建议，不擅自改文件。

最后请用简短结构化输出：现状摘要、问题列表、建议动作（若无可写「无阻塞项」）。
```

---

**示例 H：检查 / 诊断 / 分析 / 建议 `workflows/` 下工作流**

```text
@机器人 etf_main

任务：运维诊断 — 仓库 `workflows/` 目录下 YAML 工作流。

请结合 `config/evolver_scope.yaml` 与 `config/evolution_invariants.yaml`（只读，理解契约即可），对 `workflows/` 中与本方案相关的 `*_evolution_on_demand.yaml`（及你们实际在用的其它工作流）做：
1) 结构检查：必填参数、与文档 8.x 示例是否一致、有无过时路径或已删模块引用；
2) 执行风险：干跑/实跑边界、是否易触发越权改仓库；
3) 改进建议：参数命名、注释、与钉钉话术示例 A–F 的对应关系。

禁止在未满足 TEAM_OK + allowed_paths 等门禁时直接改仓库；若建议改 YAML，请明确标出「建议 diff」或「待人工 PR」。最后给出：概览表（文件名 → 用途 → 状态 OK/待关注）、TOP_FIXES（最多 5 条）。
```

---

**示例 I：针对钉钉里 OpenClaw 已发出的分析报告做复盘 / 诊断 / 建议**

```text
@机器人 etf_main

任务：复盘诊断 — 钉钉会话中由 OpenClaw（本机器人或同网关路由）近期发出的分析报告。

请基于用户在本条消息中粘贴的**原文或摘要**（可多条合并），或说明「从同会话上文引用最近 N 条机器人长消息」：
1) 核对报告中的结论是否与 8 行键值字段（ORCH_STATUS、FAILURE_CODES、EVIDENCE_REF 等）一致，有无「无证据断言」或键值缺失；
2) 判断是否误触实跑/干跑、是否遗漏 read evolver_scope、EVIDENCE_REF 是否可复核；
3) 给出后续话术或配置侧改进建议（例如下次应附带示例 F 哪一段、是否应改为仅干跑）。

若用户未粘贴内容且会话中无法取得原文，请先回复「请粘贴报告全文或关键片段」再分析。输出：一致性结论（PASS/WARN/FAIL）、具体问题点、建议的下次钉钉话术模板（可条列）。
```

---

**示例 J：分析报告诊断 → 确认后改文档（钉钉原文，复制即发）**

```text
@机器人 etf_main

开盘行情分析我想升级成机构晨报那种水平：前一天 A 股、夜盘美股和全球财经要写全，要有引领性，最好能说清当天大盘大概怎么走、热点可能怎么换。你先自己把仓库里最近的开盘分析产物、定时任务日志翻一遍，再上网找几篇像样的盘前/晨报对着看，告诉我差在哪、怎么改。这一轮只出诊断和建议，不要动仓库、不要开 PR。说完用简短中文总结一下，最后单独一段写 **标准 8 行键值**：必须是 ORCH_STATUS、FAILURE_CODES、RISK、AUTOFIX_ALLOWED、PR_CREATED、PR_REF、EVIDENCE_REF、TOP_ACTIONS（不要 DIAGNOSIS_STAGE 那种）；EVIDENCE_REF 里要有真实文件路径和 https 链接。我下一句会回「确认阶段二」让你再改文档。
```

```text
@机器人 etf_main

确认阶段二。必须出**可验证优化**：用 apply_patch 或等价改 docs/openclaw/工作流参考手册.md 与 docs/research/opening_morning_brief_roadmap.md，创建 ai-evolve/report-* 分支并 **gh pr create**，8 行键值里 PR_CREATED=true、PR_REF=链接。不许只写建议不严。
```

```text
@机器人 etf_main

盘后增强那条线也帮我看看：结论要能核对来源，风险单独一段。你先自己找最近产物和日志，再上网看优质收盘复盘怎么写，只诊断不改仓库，结尾简短总结 + 8 行键值。我要实跑时再 @ 你。
```

```text
@机器人 etf_main

确认阶段二。改 docs/research/factor_research_checklist.md，按你上条说的办。
```

**J-合并：一条钉钉里「先诊断、我已预同意实跑」（同一助手回合内应办完拍 A+拍 B）**

```text
@机器人 etf_main

开盘行情分析要对标机构晨报：先自己取证+上网对标，给一个短诊断；然后**直接**在仓库里改 docs/openclaw/工作流参考手册.md 和 docs/research/opening_morning_brief_roadmap.md（按诊断补章节），在 ai-evolve/report-* 上创建 PR，给我 PR 链接。若环境不能 gh/不能写盘，8 行键值里写 TEAM_FAIL 和 AUTOFIX_BLOCKED_ENV，说明原因，不要假装已优化。

【实跑确认】
```

**若始终「只有诊断、没有 PR」**（常见原因）

1. **第二轮没发**：须在同会话再发「确认阶段二…」，或用上面 **J-合并** 一次带 `【实跑确认】`。  
2. **OpenClaw 未给 `etf_main` 写权限 / 未配置 `gh`**：Agent 只能长文建议 → 应出现 **`AUTOFIX_BLOCKED_ENV`**，你本机手敲 `git checkout -b ai-evolve/report-…` 按 `TOP_ACTIONS` 改。  
3. **预检未更新**：确保 **`etf_main_evolution_preflight.md`** 最新版已进 Agent system（含 **phase_b_closure**）。详见 **`docs/research/opening_morning_brief_roadmap.md` §6**。

**边界说明（避免期望错位）**

- 换任务时：照上面四段，改掉任务描述和「确认阶段二」里的文件路径即可。  
- **允许自动 PR 的**通常是：`docs/research/**`、研究向 `docs/openclaw/**`、以及 `evolver_scope.allowed_paths` 内与**文案/Checklist/指标说明**相关的调整。  
- **工作流 YAML、采集、通知、脚本**等若在 `denied_paths`：拍 A 仍可诊断 + **建议 diff**；拍 B 自动改仓库须**人工**另 PR 或扩 `evolver_scope`。  
- 与 **示例 I** 区分：**示例 I** 复盘键值与聊天输出；**示例 J** 以**自检索报告正文** + 双轨 + 网上对标为主，**确认后同会话落地文档**。  
- **只做诊断、不要拍 B**：首条消息写明「仅拍 A、不要等我确认实跑」即可；或你始终不回复「确认阶段二」，Agent 不得擅自拍 B。

---

**提示**：日常只需 **极简自然语言**（见上节）；长示例用于排障或新人。**钉钉单条消息有长度限制**，长模板可拆多条。**实跑优先用示例 F**，示例 E 适合简短试探。**运维与复盘类**（定时任务、工作流体检、历史报告核对）可用 **示例 G / H / I**；**例行分析报告结构与质量迭代**可用 **示例 J**（也可口语化，由 `user_facing` 内部对齐）。

#### 8.2 如何解读一次演化任务的结果

无论是因子、策略还是文档演化，每次任务结束后，你至少应关注以下几个关键信号：

- **Reviewer 输出**（来自 `reviewer_evolution` 模板）：
  - `TEAM_RESULT=TEAM_OK | TEAM_FAIL`
  - `FAILURE_CODES=...`（如 `NO_EVIDENCE`, `OUT_OF_SCOPE`, `SAMPLE_TOO_SHORT`, `OVERFIT_RISK`）
  - `RISK=LOW|MEDIUM|HIGH`
  - `AUTOFIX_ALLOWED=true|false`
  - `EVIDENCE_REF`（回测命令 / 日志 / run id）
- **Orchestrator 输出**（来自 `orchestrator_evolution` 模板）：
  - `ORCH_STATUS=TEAM_OK | TEAM_FAIL`
  - `PR_CREATED=true|false`
  - `PR_REF=<分支名或 PR 链接>`
  - `TOP_ACTIONS=<本次主要动作>`
- **Evolver 输出**（来自 `evolver_evolution` 模板）：
  - `ERROR_CLASS`（问题归类）
  - `STANDARD_COMMANDS`（以后遇到类似问题的标准命令组合）
  - `CHECKLIST_UPDATE` / `PROMPT_PATCH`（后续应当写回文档或 Prompt 的改进点）

实务上建议：

- 对于 `TEAM_RESULT=TEAM_OK, RISK=LOW, PR_CREATED=true` 的场景：
  - 打开 PR，重点检查 diff 是否严格落在 `allowed_paths` 内；
  - 对比回测/评估结果与 Reviewer 的结论是否一致；
  - 决定是否合并，并将 Evolver 建议同步到相应的研究文档/Checklist。
- 对于 `TEAM_FAIL` 或 `RISK>=MEDIUM` 的场景：
  - 视为“诊断报告”，不合并任何自动 PR；
  - 根据 `FAILURE_CODES` 与 `STANDARD_COMMANDS` 安排后续人工分析或更深度回测。

#### 8.3 何时启用 / 调整每周演化 Cron 任务

在 `~/.openclaw/cron/jobs.json` 中已预置两个默认禁用的周任务：

- `factor-evolution-weekly`：每周五 19:00，针对因子/指标演化；
- `strategy-evolution-weekly`：每周五 19:30，针对策略参数/过滤器演化。

**建议启用时机**：

- 至少完成几次手动 `*_evolution_on_demand.yaml` 的完整演练，并确认：
  - 输出字段符合执行契约；
  - PR diff 范围、质量在你可接受范围内；
  - LLM 超时与调用配额在可控水平。
- 之后再将对应 job 的 `enabled` 字段从 `false` 改为 `true`，实际运行一到两周，观察：
  - 每周触发的任务数量与 PR 数量；
  - 是否有“泛滥式微调”或无效 PR，需要进一步收紧触发条件。

若发现负载或风险偏高，可以：

- 先把周任务 `enabled` 设回 `false`，保留 on-demand 工作流；
- 或调整 cron 时间与频率（例如改为双周一次），并在 `message` 中限制每次最多处理的候选数量。

#### 8.4 日常巡检时的快速检查清单

日常想确认“三 Skill 自动进化链路”是否健康，可以按以下顺序快速检查：

1. `config/evolver_scope.yaml` 是否仍与实际目录结构一致（有无新增模块需要加入 allowed/denied 列表）。  
2. 最近几次演化任务的输出中：
   - 是否总是缺少 `EVIDENCE_REF` 或容易出现 `NO_EVIDENCE`，提示 Builder 需要加强取证；  
   - `RISK` 分布是否合理（长期大量 HIGH/ MEDIUM 说明触发条件应更保守）。  
3. GitHub 上 `ai-evolve/*` 分支与 PR 数量是否在合理范围，有无明显“噪声 PR”。  
4. Evolver 输出的 `CHECKLIST_UPDATE` / `PROMPT_PATCH` 是否已经被落实到对应文档与 Prompt 中，避免同类错误反复出现。

通过以上习惯性操作，你可以让“三 Skill 自动进化”真正成为 ETF 研究与策略改进的**长期助推器**，而不是“偶尔跑一次的演示脚本”。 

