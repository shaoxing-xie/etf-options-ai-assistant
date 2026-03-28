# ETF Stock AI Assistant

面向普通投资者（散户）的 A 股 / ETF 行情交易助手，基于 OpenClaw 运行。  
这个项目的出发点很直接：在高波动市场里，散户最缺的不是观点，而是**稳定、可复现、可追溯**的决策流程。

> 仓库名兼容说明：仓库名称暂保留为 `etf-options-ai-assistant` 以兼容既有脚本与部署路径；当前产品主线为 A股 / ETF，期权能力为可选扩展。

## 为什么现在需要它（Why now）

在震荡与突发行情并存的市场中，散户的痛点通常不是“看不到信息”，而是：

- 看到了很多信息，但信息之间没有统一口径
- 有策略，但盘中执行容易被情绪打断
- 有风控意识，但缺少自动化检查与复盘证据链

本项目把这些环节收敛成一个可持续执行的交易助手流程，目标是帮助你从“感觉驱动”走向“流程驱动”。

## 适用人群

- 以 A 股 / ETF 交易为主，想要提升盘中执行稳定性的个人投资者
- 希望把盯盘、分析、通知、复盘打通的 OpenClaw 用户
- 需要一个可二次开发的散户交易助手基础框架的开发者

## 为什么基于 OpenClaw

- **多 Agent 协作**：把数据、分析、风控、通知拆分成可维护角色
- **可编排工作流**：Cron + Workflow 让日常动作自动化
- **可追踪运行态**：每次运行有日志、有上下文、有可回放证据
- **插件生态可扩展**：便于持续加入新数据源与策略工具

当市场快速下跌、突发消息密集、板块联动加速时，人工盯盘很容易出现三类问题：

- 信息延迟：关键数据到达慢，错过操作窗口
- 决策失序：盘中情绪干扰，执行和策略不一致
- 风控失焦：仓位、止损、事件风险无法同时覆盖

本项目通过 OpenClaw 提供多 Agent 协作流程，把“数据采集 -> 分析判断 -> 风控校验 -> 通知执行”串成一条闭环链路，帮助散户在压力场景下保持纪律化决策。

> **免责声明**：本项目仅用于研究与工程实践，不构成任何投资建议。任何实盘行为与损益后果均由使用者自行承担。

## ETF Stock 龙虾（OpenClaw）生态长项：从“会分析”到“会复现、会迭代、会进化”

本项目的价值不在于堆更多结论，而在于把**研究、交易决策与工程变更**统一成可执行、可追溯、可改进的闭环：**日常自动化跑通流程**，**异常与退化时按契约进化代码与文档**（在明确边界内），而不是依赖单次会话的“口头修复”。

你会在这里体验到几项 OpenClaw ETF/股票龙虾生态的核心长项：

- **证据驱动的端到端流程**：多 Agent 把“采集 -> 分析 -> 风控校验 -> 通知 -> 复盘”串成闭环；每次运行都有日志与上下文，减少“口嗨式结论”。
- **Cron + Workflow 自动化**：盘前 / 盘中 / 盘后 / 研究任务按固定节奏运行，把盯盘从靠意志力变成靠系统。
- **三 Skill 驱动的 ETF 研究自动进化（已落地并验证）**  
  实施方案全文见 **`docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md`**。思想可以概括成三条能力拧成一股绳：
  1. **GitHub**：在 `ai-evolve/*` 等约定分支上**提 PR、不自动合 main**，变更可 diff、可审查。
  2. **agent-team-orchestration**：**Builder（如 code_maintenance_agent）+ Reviewer（如 etf_analysis_agent）** 分角色执行，输出带 `TEAM_RESULT` / `FAILURE_CODES` / `RISK` 等可解析结论。
  3. **capability-evolver**：把失败案例抽象为 `ERROR_CLASS`、`STANDARD_COMMANDS`、`CHECKLIST_UPDATE`，沉淀到研究与 OpenClaw 文档，而不是只修一次算一次。

  **机器可读边界与不变量**（运行前必读，避免“越权自动改采集/通知/脚本”）：
  - `config/evolution_invariants.yaml` — 三角色顺序、四段证据、口头授权不可绕过门禁、Orchestrator 最终输出键等。
  - `config/evolver_scope.yaml` — `allowed_paths` / `denied_paths`，自动修改只允许落在允许路径内。
  - `docs/openclaw/execution_contract.md` — 执行契约与证据块格式。

  **典型入口工作流**（`workflows/`）：按需演化（因子 / 策略参数 / 波动区间 / Checklist 等 `*_evolution_on_demand.yaml`）、CI 失败分流（`ci_autofix_triage_on_demand.yaml`）、定时质量兜底（`quality_backstop_audit.yaml`）、Cron 报错修复（`cron_error_autofix_on_demand.yaml`）。Prompt 模板见 `docs/openclaw/prompt_templates/*_evolution.md`。

- **预测与验证的工程化（与“进化”配套的数据闭环）**  
  预测落库经 **`src/prediction_recorder.py`** 与 **`src/prediction_normalizer.py`**，质量门禁阈值在 **`config.yaml` → `prediction_quality`** 可配；收盘后验证见 **`scripts/verify_predictions.py`**（工作流 **`workflows/prediction_verification.yaml`**）；滚动命中率与相对基线告警见 **`scripts/prediction_metrics_weekly.py`**（**`config.yaml` → `prediction_monitoring`**）。多模型区间融合仅作离线试验时见 **`docs/research/prediction_fusion_contract.md`** 与 **`scripts/prediction_fusion_experiment.py`**。

- **GitHub 运维稳定 IO**：在当前 OpenClaw 形态下，GitHub 操作以 `exec + gh` 为主，结合 `gh api .../actions/runs/<id>/logs` 的 zip 日志兜底路径，确保可核验证据。

**建议阅读顺序（自动化进化）**：`docs/openclaw/README.md` → **`三Skill驱动ETF研究自动进化实施方案.md`** → `execution_contract.md` → `工作流参考手册.md`（含 Cron 与任务 ID 约定）。

## 紧急场景示例（开盘 10 分钟）

场景：开盘后 10 分钟内，A 股 / ETF 快速下挫、消息面噪声增大。  
散户常见状态是“看到了很多信息，但无法在 1-2 分钟内形成可执行判断”。

本项目在这个窗口期的目标不是“预测涨跌”，而是给出一条可执行的纪律化流程：

1. 自动抓取关键行情与波动数据（A 股/ETF/指数）
2. 输出结构化风险画像（趋势、波动、流动性、事件）
3. 按预设规则进行仓位与止损校验
4. 通过 Feishu/DingTalk 推送同一版结论，避免多端口径不一致

这样做的价值是：即便结论是“观望”，也能做到有证据、可复盘、可追责，避免情绪化下单。

### 开盘 10 分钟执行流（简图）

```text
行情突发 -> 数据抓取 -> 波动/趋势分析 -> 风控校验 -> 统一通知 -> 复盘留痕
   |           |             |               |            |            |
 A股/ETF    多源行情      结构化结论      仓位/止损      Feishu/DT   日志/会话
```

---

## 项目概览

### 核心能力

- **多资产数据采集**：支持股票、指数、宽基 ETF、A50 期指等多源数据的实时 / 历史 / 分钟级获取，并带有本地缓存与批量采集优化。
- **趋势与波动分析**：内置盘前 / 盘后 / 开盘分析、技术指标计算、历史波动率与波动率预测、日内区间估计等能力。
- **信号与策略研究**：支持多策略信号生成、信号效果回放、策略评分与权重调整，形成完整的策略研究闭环（Strategy Research Loop）。
- **风险控制与仓位管理**：提供仓位建议、止盈止损计算、可交易性过滤、集中风控（通过 `option_trader.py env/risk_check`）等能力。
- **OpenClaw 集成与工作流**：与 OpenClaw 深度集成，支持多 Agent 协同、定时工作流（Cron）、飞书通知与研究型轮动/回测工作流。
- **三 Skill 自动化进化**：在 `evolution_invariants` + `evolver_scope` 约束下，通过编排技能 + GitHub PR + Evolver 复盘，使分析/策略/研究文档可持续迭代；数据采集与通知通道默认**不自动改代码**。
- **运维与可观测性**：统一日志、健康检查、代码体检工具，与 OpenClaw 的 ops / code_maintenance Agent 协作；预测验证与周报脚本支撑质量趋势，而非仅单次结论。

### 你能获得什么（Value）

- 更快：盘中关键结论分钟级产出，而不是零散手工拼接
- 更稳：同一套规则贯穿分析、风控、通知，减少执行漂移
- 更可控：每次决策都可复盘，便于持续改进策略和参数

### 技术栈

- **平台**：OpenClaw（Agent + Gateway + Cron 工作流）
- **语言**：Python 3.8+（核心逻辑与工具实现）
- **数据源**：AKShare、Tushare、新浪等
- **存储**：SQLite、Parquet、本地 JSON/CSV 缓存
- **通知**：飞书（Feishu）与钉钉（DingTalk），支持按需切换

---

## 快速开始（最小可运行）

以下步骤假设你已在 Linux/WSL 环境中工作，且已安装 OpenClaw（建议版本 `>= 2026.3.x`）。

### 1. 克隆仓库并安装依赖

```bash
git clone https://github.com/shaoxing-xie/etf-options-ai-assistant.git
cd etf-options-ai-assistant

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

- 复制并编辑环境变量（只填你实际需要的项）：

```bash
cp .env.example .env
# 填写 ETF_*（项目层）与 OPENCLAW_*（平台层）变量
```

- 根据需要调整 `config.yaml` 与 `Prompt_config.yaml`（数据目录、日志目录、策略参数）。

### 2.5 第三方 SKILL（可选但推荐）

本项目除了自定义插件与工具外，部分“自动盯盘 / 事件哨兵 / 外部信息补全”能力还会依赖 OpenClaw 生态中的第三方 SKILL（技能包）。建议首次安装时先看清单并按需安装：

- `docs/getting-started/third-party-skills.md`

### 3. 安装为 OpenClaw 插件（项目能力接入）

在 WSL 中执行：

```bash
bash install_plugin.sh
```

该脚本会自动：

- 在 `~/.openclaw/extensions/` 下创建 `option-trading-assistant` 插件目录；
- 建立指向本项目的符号链接；
- 安装 Python 依赖（如有必要）；
- 注册插件到 OpenClaw（`index.ts` + `tool_runner.py`）。

详细安装说明与 Remote-WSL 使用建议见：

- `docs/getting-started/README.md`
- `docs/publish/README.md`
- `docs/archive/openclaw/README.md`（历史配置/集成说明，仅供参考）

### 4. 运行第一个工作流（验证闭环）

完成插件安装后，按 5 分钟指南跑一个最小流程进行验证：

- 先阅读：`docs/overview/5分钟快速开始指南.md`
- 典型流程包括：
  - 环境检查脚本；
  - 安装插件；
  - 运行一个盘后分析或信号生成工作流；
  - 检查飞书通知 / 日志输出。

### 5. 1 分钟验收标准

满足以下条件，说明项目已“最小可用”：

- `openclaw gateway status` 显示 `RPC probe: ok`
- 你能触发至少一个分析工作流并看到日志结果
- 通知渠道（Feishu/DingTalk）至少一个可正常收消息

---

## 文档导航

本项目的详细文档都集中在 `docs/` 目录下，建议从这里开始：

- **数据采集插件（标的物 / 数据域 / 行情周期、Provider 矩阵）**：`plugins/data_collection/README.md`（与 [`ROADMAP.md`](plugins/data_collection/ROADMAP.md) 互链）
- **文档首页**：`docs/README.md`
- **入门（Getting Started）**：  
  - `docs/getting-started/README.md`  
  - `docs/overview/5分钟快速开始指南.md`

- **三 Skill 与自动化进化（实施完成，建议通读）**：  
  - **`docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md`** — 总纲：GitHub + 编排 + Evolver、边界与 PR 约定。  
  - `config/evolution_invariants.yaml`、`config/evolver_scope.yaml`、`docs/openclaw/execution_contract.md` — 运行时硬约束。  
  - `workflows/*_evolution_on_demand.yaml`、`workflows/quality_backstop_audit.yaml` 等 — 入口与兜底。

- **使用指南（User Guide）**：  
  - 工作流与调度：`docs/openclaw/工作流参考手册.md`  
  - 信号与风控巡检：`docs/openclaw/信号与风控巡检工作流.md`  
  - **策略引擎与多路信号融合**：`docs/architecture/strategy_engine_and_signal_fusion.md`（工具 `tool_strategy_engine`）；OpenClaw 衔接配置 `config/openclaw_strategy_engine.yaml`；仓库定时 **`strategy_fusion`** 为交易时段 **每 30 分钟**，本机请在 `~/.openclaw/cron/jobs.json` 中按需启用对应任务。  
  - 通知与日报：参考工具手册与相关工作流文档  

- **OpenClaw 集成（Integration）**：  
  - 发布主线：`docs/publish/README.md`  
  - 历史配置/集成归档：`docs/archive/openclaw/README.md`

- **工具与协议参考（Reference）**：  
  - `docs/reference/工具参考手册.md`  
  - `docs/reference/工具参考手册-速查.md`  
  - `docs/reference/工具参考手册-场景.md`  
  - `docs/reference/工具参考手册-研究涨停回测.md`  
  - `docs/reference/错误码说明.md`  
  - `docs/reference/trading_journal_schema.md`  
  - `docs/reference/limit_up_pullback_default_params.md`

- **架构与开发（Architecture）**：  
  - `docs/architecture/README.md`  
  - `docs/PROJECT_LAYOUT.md`  
  - `docs/architecture/架构与工具审查报告.md`  
  - `docs/architecture/strategy_engine_and_signal_fusion.md`（策略引擎与多路信号融合 v1.0）

- **运维与排错（Ops）**：  
  - `docs/ops/常见问题库.md`  
  - `docs/ops/RISK_CONTROL_AND_ROLLBACK.md`  
  - `docs/ops/需要添加交易日判断跳过参数的工具清单.md`  
  - 以及后续归档的钉钉 / 飞书排错文档

- **历史归档（Legacy）**：  
  - `docs/legacy/` 下的设计草稿、测试报告与迁移方案，仅供参考。

---

## 目录结构概览

详细结构见 `docs/PROJECT_LAYOUT.md`，这里给一个简略版：

```text
etf-options-ai-assistant/
├── README.md
├── LICENSE
├── config.yaml                       # 含 prediction_quality / prediction_monitoring 等
├── Prompt_config.yaml
├── config/strategy_fusion.yaml       # 融合阈值与默认权重
├── config/openclaw_strategy_engine.yaml  # OpenClaw 路由、策略融合与预测验证指针
├── config/evolution_invariants.yaml  # 三 Skill 演化不变量（机器可读）
├── config/evolver_scope.yaml         # 允许/禁止自动修改的路径边界
├── src/                 # 核心业务逻辑；含 prediction_recorder / prediction_normalizer
├── plugins/             # OpenClaw 插件层（含 plugins/strategy_engine 策略融合）
├── workflows/           # 工作流：交易链路 + *_evolution_on_demand + 质量兜底等
├── docs/                # 含 docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md
├── scripts/             # 安装、诊断、verify_predictions、prediction_metrics_weekly 等
├── tests/               # 测试用例
└── .venv/               # Python 虚拟环境（本地）
```

---

## 联系与反馈

| 场景 | 建议做法 |
|------|----------|
| **使用问题 / 功能建议 / Bug** | 到本仓库 [**Issues**](https://github.com/shaoxing-xie/etf-options-ai-assistant/issues) 新建一条；涉及策略融合时可注明 `strategy_engine` / `tool_strategy_engine`（说明见 [`plugins/strategy_engine/README.md`](plugins/strategy_engine/README.md)）。 |
| **代码贡献** | 阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md) 后提交 **Pull Request**。 |
| **安全漏洞** | 勿在公开 Issue 中披露利用细节，请按 [`SECURITY.md`](SECURITY.md) 报告。 |

若仓库已启用 **GitHub Discussions**，也可在讨论区发帖交流。Fork 开发可在你的 Fork 上提 Issue，或向上游发 PR。

---

## 风险提示与免责声明

- 本项目仅作为量化研究与系统设计参考实现，所有输出仅供研究与学习，不构成投资、法律或税务建议。
- 金融市场存在剧烈波动与黑天鹅风险，使用本项目产生的任何损益后果由使用者自行承担。
- 在连接真实账户或执行自动化交易前，请务必先在回测/模拟环境验证策略与系统稳定性。

---

## License

本项目采用 [MIT License](LICENSE)。  
在使用或分发本项目代码时，请保留原始版权与许可声明。  

---

## Roadmap（公开路线图）

- `v0.1.x`：开源基线稳定（文档、配置模板、最小 CI）
- `v0.2.x`：策略模块化与更多盘中风险模板
- **三 Skill 自动化进化**：实施方案已在仓库落地并跑通验证（见上文与 `docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md`）；后续以 **证据化 PR、扩大回测窗口、监控告警调参** 为主迭代，而非扩大自动修改面。
- `v1.0.0`：生产部署与回滚流程标准化

参与方式见上文 [**联系与反馈**](#联系与反馈)（Issue / PR / 安全披露）。

---

## Screenshots / Demo（建议首发即提供）

> 建议把截图放在：`docs/assets/`，并在此处直接引用。

推荐最少 2 张图（可显著提升仓库转化）：

1. **网关与工作流健康图**（`openclaw gateway status` + 关键日志）
2. **通知到达图**（Feishu/DingTalk 接收结构化结论）

示例占位（你补图后会自动显示）：

```markdown
![Gateway Health](docs/assets/gateway-health.png)
![Notification Sample](docs/assets/notification-sample.png)
```

可选第三张：

3. **开盘 10 分钟流程结果图**（数据摘要 + 风控结论 + 最终建议）
