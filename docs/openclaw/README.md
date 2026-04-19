# OpenClaw 集成与配置

本目录面向负责 OpenClaw 环境、Gateway、Cron 工作流和插件部署的使用者。

> 文档状态说明：本目录含“历史积累 + 当前可用”内容。  
> 对外发布与稳定运行请优先使用 `docs/publish/` 下的主线文档（部署、环境变量、Ollama、服务启停、插件技能）。

主要内容包括：

- **当前可用（推荐）**  
  - `模块化改造策略-插件与Skill分层.md`：**架构演进规划**（插件外置与 Skill 分层、阶段路线、验收与风险）；与 `openclaw-data-china-stock` 外置模式对齐，供评审迭代，非对外操作手册。  
  - `能力地图.md`：**阶段 1** — 工具 id 分组、工作流索引、环境变量与数据路径指针（维护时请与 `config/tools_manifest.yaml` 同步）。  
  - `跨插件数据契约.md`：**阶段 1** — 缓存根、融合权重文件、关键 `data/` 读写方与 JSON 稳定性约定。  
  - **自研 OpenClaw Skill（`ota-*`）**：源文件在仓库 [`skills/README.md`](../../skills/README.md)（索引与同步脚本）；主链路优先 `ota-strategy-fusion-playbook`、`ota-signal-risk-inspection`、`ota-daily-session-routine`；趋势三工具解读见 **`ota-trend-analysis-brief`**（与 `tool_analyze_after_close` / `before_open` / `opening_market` 对齐）。**`tool_screen_equity_factors`** / **`tool_finalize_screening_nightly`** 的契约与叙事见 **`ota-equity-factor-screening-brief`**（旧 **`ota-quantitative-screening-brief`** 已 deprecated）。包数量以 **`skills/README.md` 索引表**（含 `SKILL.md` 的 `ota-*` 子目录）为准，并与 **`OpenClaw-Agent-ota-skills.md`** 中「覆盖性」条数一致维护。  
  - [`OpenClaw-Gateway-Agent与Skills勾选指南.md`](./OpenClaw-Gateway-Agent与Skills勾选指南.md)：Gateway **[/skills](http://127.0.0.1:18789/skills)** 与 `openclaw.json` 中按 Agent 勾选 `ota_*` 的对照表；片段见 [`config/snippets/openclaw_agents_ota_skills.json`](../../config/snippets/openclaw_agents_ota_skills.json)。合并片段后须执行 **`bash scripts/sync_repo_skills_to_openclaw.sh`** 并重载 Gateway。  
  - [`OpenClaw-Agent-ota-skills.md`](./OpenClaw-Agent-ota-skills.md)：`openclaw.json` 中各 Agent 的 `skills` allowlist 与 [Gateway 技能页](http://localhost:18789/skills) 说明。  
  - `工作流参考手册.md`：各个工作流（盘前、盘后、盘中、研究模式一、策略评估等）的配置与调度。  
  - `workflow_cron_timeline.md`：交易日 Cron 时间线摘要（与 `workflows/README.md`、本机 `jobs.json` 对照）。  
  - `agent_maintenance_guide.md`：Cron 执行 Agent 的维护手册（单一事实源、渲染脚本、校验脚本、日常操作顺序）。  
  - `dingtalk_delivery_contract.md`：钉钉长文投递契约（权威）；各 `structured_message` 内为摘要 pointer。  
  - `institutional_alignment_checklist.md`：机构级对齐轻量自检（SLO/血缘/DQ/双轨互斥等可选补强）。  
  - **策略引擎与信号融合**：工具 `tool_strategy_engine`（返回 `summary`、`fused_by_symbol` 等）；仓库定时 **`strategy_fusion`**（交易时段 **每 30 分钟**）；解读 Skill `skills/ota-strategy-fusion-playbook/SKILL.md`；详见 `docs/architecture/strategy_engine_and_signal_fusion.md`、`config/openclaw_strategy_engine.yaml`、`workflows/strategy_fusion_routine.yaml`；本机 Cron 以 `~/.openclaw/cron/jobs.json` 为准。
  - `Strategy_Research_Loop.md`：策略研究闭环设计与相关工作流说明。
  - `ETF_Rotation_Research_Workflow.md`：ETF 轮动研究工作流（工具管道与配置入口；标的池与因子见仓库根 `config/rotation_config.yaml`）。
  - `信号与风控巡检工作流.md`：巡检工作流与风控检查流程（落地 YAML：`workflows/signal_risk_inspection.yaml`；组合快照 `tool_portfolio_risk_snapshot`；排错：`docs/ops/cron_signal_inspection_triage.md`）。
  - `workflows/README.md`：工作流一览（含 `daily_market_report`、`limitup_pullback_after_close`、`etf_rotation_research_agent`、`strategy_research_playback` 等与 `research.md` 口径相关的定时定义）。
  - `宽基ETF巡检快报-日内波动区间收敛说明.md`：缓存口径收敛、字段含义与验证方式。
  - `OpenClaw与Cursor协作代码维护执行通道CMEC实施方案.md`：OpenClaw 与 Cursor 的代码维护执行通道（CMEC）共享目录协作实施方案文档。
  - **三 Skill 驱动 ETF 研究自动进化（总纲，已实施并验证）**：`三Skill驱动ETF研究自动进化实施方案.md` — 说明如何把 **GitHub + agent-team-orchestration + capability-evolver** 收敛为「研究友好、采集保守」的自动进化流水线；机器可读边界见 `config/evolution_invariants.yaml`、`config/evolver_scope.yaml`。
  - **三个 Skill 生产化流水线（CI 自动修复 + 质量兜底）**：把 `github`、`agent-team-orchestration`、`capability-evolver` 组合成受约束的“证据驱动执行协议”。核心资产：`docs/openclaw/execution_contract.md`、`docs/openclaw/failure_codes.md`、`docs/openclaw/runbooks/github_actions_log_fetch.md`，以及工作流：`workflows/ci_autofix_triage_on_demand.yaml`（事件驱动入口）、`workflows/quality_backstop_audit.yaml`（定时质量兜底）、以及按需 `workflows/*_evolution_on_demand.yaml`。

- **优化与成本控制**  
  - `OpenClaw工具与Token优化建议.md`：如何通过精简工具暴露、调整 Agent 工具权限来减少 token 消耗与运行成本。

- **历史归档（不纳入发布清单）**  
  - `docs/archive/openclaw/README.md`
  - `docs/archive/openclaw/OpenClaw配置指南.md`
  - `docs/archive/openclaw/插件集成到OpenClaw指南.md`
  - `docs/archive/openclaw/README_WSL_ACCESS.md`

如需对 Gateway / Cron / Agent 配置进行较大调整，建议先完整阅读本目录下的文档，再在测试环境中演练。

**自动化进化相关阅读顺序建议**：`三Skill驱动ETF研究自动进化实施方案.md` → `execution_contract.md` → `prompt_templates/*_evolution.md` → `工作流参考手册.md`。
