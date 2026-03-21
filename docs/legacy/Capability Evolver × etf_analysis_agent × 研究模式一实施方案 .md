## Capability Evolver × `etf_analysis_agent` × 研究模式一  
**实施方案（Draft）**

---

### 一、目标与范围

- **目标**：让 `etf_analysis_agent` 在“研究模式一”（A 股量化研究与风控巡检）下，能通过 Capability Evolver **持续优化自己的分析质量与研究流程**，但不直接触碰交易执行链路。
- **作用范围**：
  - 仅作用于：  
    - `etf_analysis_agent` 的提示词 / 研究流程 / 输出结构；  
    - 与“研究模式一”相关的 prompts、研究说明文档、研究类 memory。
  - 不作用于：
    - 实盘交易 agent（如 `etf_main`、`etf_business_core_agent`）；  
    - 策略执行代码、下单脚本、风控硬阈值等。

---

### 二、约束与安全边界

- **模式限制**：  
  - 仅启用 Capability Evolver 的 **review 模式**：  
    - 生成“进化方案（diff / 建议）”；  
    - 不自动写任何文件、不调用任何 CLI backend。
- **配置约束（Evolver 自身 config）**：  
  - `allow_auto_apply: false`  
  - `scope: "prompt_only"`（可再细化为：prompt + 研究说明 + 研究类记忆）  
  - `max_evo_cycles: 1~2`  
  - `network_enabled: false`（默认禁止对外上报进化数据）
- **权限约束（在 `etf_analysis_agent` 维度）**：
  - 允许：
    - 读取 `~/.openclaw/prompts/research.md` 与分析相关 prompts；  
    - 读取研究类 memory / 历史研究 session；  
    - 调用内部研究工具（回测、统计、报告生成等）。
  - 禁止：
    - 调用实盘交易工具（`option_trader` 等）；  
    - 调用运维类工具（`ansible_runner`、`system_health_check` 等）；  
    - 修改 `~/.openclaw/openclaw.json`、Cron 任务、外部渠道配置。

---

### 三、架构与绑定关系（逻辑视图）

- **Agent：** `etf_analysis_agent`  
  - 角色：研究/分析主脑，承接“研究模式一”全部任务（盘前/开盘/盘中/盘后/波动率预测等）。
- **Prompt：** `~/.openclaw/prompts/research.md` 中的【研究模式一】  
  - 由 Evolver 重点分析与优化（结构、指令清晰度、工具调用顺序等）。
- **Skill：** Capability Evolver  
  - 以“工具/子 agent”的形式挂载在 `etf_analysis_agent` 下；  
  - 只接收：与研究模式一相关的历史对话摘要 / 输出样本 / 报错记录；  
  - 输出：  
    - Prompt 调整建议；  
    - 研究流程调整建议（如工具调用顺序、fallback 策略）；  
    - 输出模板与风险提示文案优化建议。
- **LLM 选择**：  
  - Evolver 的“思考模型”优先使用：  
    - `glm5-api-nvidia` 或 `siliconflow-DS-v3.2`；  
  - 如你后续通过 `openclaw-aisa-leading-chinese-llm` 接入 AISA 模型，可在研究模式一中单独指定。

---

### 四、实施步骤（Phase by Phase）

#### Phase 0：准备与审查

- **1）确认 Capability Evolver 源码路径与版本**
  - 确认在本地 `~/.openclaw/workspaces/shared/skills/` 或 `~/.openclaw/skills/` 下的实际路径；
  - 快速审查：
    - `SKILL.md`：确认使用说明、权限说明；  
    - `evolver.py`：入口逻辑、是否有 `--review` / `mode: review`；  
    - `gep/apply.py`：有哪些文件写操作，明确风险点。
- **2）快照/备份关键文件**
  - 手工备份：
    - `~/.openclaw/prompts/research.md`  
    - `~/.openclaw/agents/etf-options-ai-assistant/analysis_agent/agent/SOUL.md`  
    - 与研究模式一相关的 Cron 配置（`cron/jobs.json`）。

#### Phase 1：Evolver 配置成“只读顾问”

- **1）在 Evolver config 中设置（示例）**  
  - 例如在 Evolver 自身的 `config.json`（具体路径以后落地时按实际为准）中设：
    - `allow_auto_apply: false`  
    - `scope: "prompt_only"`  
    - `max_evo_cycles: 1`  
    - `network_enabled: false`
- **2）在 `etf_analysis_agent` 中限定调用方式**
  - 在 `SOUL.md` 或 Agent 配置中增加约束：
    - “当你调用 Capability Evolver 时，只允许使用 review 模式，并将修改建议以自然语言 + diff 形式返回，禁止尝试直接写文件或调用 CLI 工具。”

#### Phase 2：绑定到“研究模式一”上下文

- **1）定义标准调用 Prompt 模板**（给人/系统用）  
  示例一：总体验证  
  ```text
  用 Capability Evolver 的 review 模式，针对「研究模式一」的实际执行记录（最近 7 天 `etf_analysis_agent` 的研究任务对话与日志），
  给出一份改进方案，但不要自动修改任何文件或配置。

  输出结构：
  1）当前研究模式一的主要问题列表（含具体例子：如报告过长、结论不够明确、风险提示缺失等）
  2）对 `~/.openclaw/prompts/research.md` 的修改建议（以段落级 diff 描述）
  3）对 `etf_analysis_agent` 输出结构与用词风格的优化建议
  4）建议的安全边界（哪些内容绝不应由 Evolver 自动修改）
  ```
  示例二：针对 510300 研究链路  
  ```text
  请在 review 模式下，用 Capability Evolver 分析最近 10 次「510300 相关研究模式一」任务的完整输入输出，
  聚焦以下问题：
  - 趋势判断是否稳定、一致？
  - 波动率与日内区间预测的可读性与可执行度？
  - 风控/风险提示部分是否到位？

  请仅输出修改建议和示例，不要写入任何文件。
  ```

- **2）在 `research.md` 中为 Evolver 预留说明区块（可选）**
  - 如增加一个“小节”说明：  
    - 什么时候会调用 Evolver；  
    - Evolver 的输出如何被人类/你手动审核后再落地。

#### Phase 3：人工审核与小步落地

- **1）每轮 Evolver 输出后，执行三步人工检查**
  - 校验：
    - 有无触碰交易 / 风控硬阈值的建议；  
    - 有无建议更改外部通道（钉钉、飞书）的行为；  
    - 是否保持了“研究模式一”的核心结构（数据优先级、结构化输出、风险提示）。
  - 对“只涉及表达和结构”的建议，可以优先采纳；
  - 对“隐含策略调整”的建议（如更积极/更保守）要单独评估。

- **2）手工更新相关文件**
  - 按需更新：
    - `~/.openclaw/prompts/research.md`  
    - 如有必要，微调 `SOUL.md` 中对研究模式一的说明。
  - 每次更新前建议再快速备份一次旧版本。

#### Phase 4：观察期与指标跟踪

- **1）定义简单的“进化成效指标”**
  - 例如：
    - 每份日报的字数 / 关键要点数量；  
    - 是否减少“报告模糊、缺乏结论”类人工反馈；  
    - 是否减少因 prompt 不清导致的工具调用错误。

- **2）阶段性回顾**
  - 比较：
    - Evolver 接入前 vs 接入后  
    - 研究报告在“清晰度、一致性、风险揭示、可执行建议”四个维度的主观评分。

---

### 五、监控与回滚策略

- **监控要点**：
  - 关注：
    - Evolver 输出中是否出现“建议修改交易逻辑 / 风控阈值 / 下单频率”的内容；  
    - 报告是否开始偏离“研究模式一”的结构与任务边界。
- **回滚手段**：
  - 如某次 Evolver 建议导致研究效果变差：
    - 直接用备份恢复 `research.md` / `SOUL.md`；  
    - 暂停调用 Evolver（从 cron / agent 配置中移除或注释对应调用）。
  - 回滚后，记录一次“反例”，作为下一轮 Evolver 分析时的负样本。

---

### 六、后续可能的扩展（立即实施）

- 在 review-only 运行稳定一段时间后，可考虑：
  - 将 `scope` 从 `prompt_only` 扩展到“研究类 memory 的结构调整”（如如何记日记、如何归档研究结论）；  
  - 为 Evolver 增加“回测流程建议”能力——仍然只输出建议，不直接改代码；
  - 在确保安全的前提下，让 Evolver 帮你自动生成一部分“研究周报/复盘模板”。

---

**总结一句话**：  
这套方案的核心是：让 Capability Evolver 只在 **`etf_analysis_agent` + 研究模式一** 里、以 **review 顾问** 的方式，持续打磨你的研究提示词和输出结构，而不直接触碰任何“能动手”的链路。