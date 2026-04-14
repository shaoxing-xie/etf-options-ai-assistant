# 模块化改造策略：插件（Plugin）与 Skill 分层

> **文档性质**：架构演进规划，供评审与迭代；不作为对外发布「操作手册」。  
> **关联文档**：[`../PROJECT_LAYOUT.md`](../PROJECT_LAYOUT.md)、[`../publish/plugins-and-skills.md`](../publish/plugins-and-skills.md)、[`OpenClaw配置指南.md`](./OpenClaw配置指南.md)、[`工作流参考手册.md`](./工作流参考手册.md)。

---

## 1. 背景与目标

`etf-options-ai-assistant`（OpenClaw 侧插件 id：`option-trading-assistant`）经长期迭代，工具与工作流丰富，但 **目录耦合、职责边界** 随功能堆叠而变复杂。`plugins/data_collection` 已成功外置为独立仓库 **`openclaw-data-china-stock`**，主仓通过符号链接与路径约定衔接，证明 **「可执行能力插件化 + 主仓变薄」** 可行。

本策略目标：

1. **降低认知负担**：新贡献者与使用者能按「数据 / 分析 / 策略 / 风控 / 通知 / 编排」快速定位代码与配置。  
2. **控制变更半径**：高频演进模块独立版本与 CI，避免牵一发而动全身。  
3. **区分「机器可调用」与「人机规程」**：可执行、可测试的进 **插件**；流程、校验与叙事进 **Skill**（及工作流 YAML）。  
4. **保持最小安装可用**：与 [`plugins-and-skills.md`](../publish/plugins-and-skills.md) 的「必须项 / 建议项」叙事一致，可选能力以插件 + Skill 组合呈现。

---

## 2. 三层模型：插件、Skill、核心仓

| 层级 | 承载内容 | 典型形态 | 判断要点 |
|------|-----------|----------|----------|
| **OpenClaw 插件** | 稳定工具接口、副作用（IO、网络、通知）、可单测逻辑 | `openclaw.plugin.json`、`tools_manifest`、经 Gateway 暴露的 tool | 输入输出可描述、可回归测试、可单独发版 |
| **Skill** | 何时用哪些工具、顺序与检查清单、领域解释规范、降级策略 | Cursor/OpenClaw Skill 文档、与本仓 `prompt_templates/`、`workflows/` 互补 | 升级 tool 名时改 Skill 成本低；不替代缺少契约的「伪工具」 |
| **核心仓（本仓库）** | 本产品默认编排、工作流 YAML、与策略话术强绑定的配置、组合多个插件的「门面」 | `workflows/`、`config/openclaw_strategy_engine.yaml`、`tool_runner.py` 路由、安装脚本 | 换产品线需大改或不适用的部分优先留仓内 |

**原则**：Skill 描述 **怎么做**；插件提供 **能调用什么**；核心仓维护 **默认怎么拼在一起**。

---

## 3. 何时拆成独立插件（决策清单）

建议在满足 **多条** 时再拆独立仓库（或独立 npm/python 包 + OpenClaw 扩展），避免过度拆分。

1. **边界清晰**：对外契约主要是一组 tool + 少量 `configSchema` 字段（参考 `openclaw-data-china-stock` 的 `openclaw.plugin.json`）。  
2. **依赖重或变化快**：多数据源、Provider 链、额度与合规、DTO 演进——独立 CI 与版本号更可控。  
3. **跨产品复用**：其他助手只需子能力（例如「只要 A 股/ETF 数据」）而不必安装完整期权助手。  
4. **可自闭环测试**：不依赖本仓完整分层配置语义即可跑核心单测与工具冒烟。

**暂缓拆插件的信号**：与默认权重路径、Prompt 片段、单一工作流 YAML 强耦合且几乎无复用需求——更适合留在核心仓或先提取 **Skill** 固化流程。

---

## 4. 何时提炼为 Skill（决策清单）

Skill 适合固化 **agent 侧规程**，与定时工作流形成互补：YAML 偏自动执行，Skill 偏交互与例外处理。

1. **固定节奏的检查顺序**：盘前 / 盘后 / 开盘、异常时的降级与重试顺序。  
2. **输出与解释规范**：如何读 `tool_strategy_engine`、风控巡检结论写法的最低要求。  
3. **与文档同源**：已有专题说明（如波动区间收敛、通知路由）可收敛为 Skill 条目，减少「每次重新教模型」。  
4. **弱绑定实现细节**：工具名或参数调整时，主要改 manifest 与 Skill，而非业务核心算法。

**注意**：若某能力尚无稳定 tool 接口，仅有自然语言步骤，应先补插件或仓内工具，再写 Skill，否则难以验收。

---

## 5. 与当前仓库结构的对齐（非最终拆分结论）

以下按 [`PROJECT_LAYOUT.md`](../PROJECT_LAYOUT.md) 做 **映射**，便于后续做「能力地图」表格时直接填列；**不表示下一版必须拆仓**。

| 区域 | 当前角色 | 插件化倾向 | Skill 化倾向 |
|------|----------|------------|--------------|
| `plugins/data_collection/`（外链 `openclaw-data-china-stock`） | 行情与 A 股域数据 | **已完成外置**；主仓保留链接与安装说明 | 数据域选择、降级顺序、TOOL_MAP 查阅习惯 |
| `plugins/analysis/` | 指标、趋势、波动、关键位等 | 子域成熟、复用需求高时可拆 **分析类扩展** | 解读口径、A/B 切换与验证步骤 |
| `plugins/strategy_engine/` | 信号融合与引擎 | 若需独立发版或与主产品生命周期不同，可评估独立插件 | 融合结果阅读、人工复核清单 |
| `plugins/risk/`、`plugins/notification/` | 风控快照、消息通道 | 通知若多项目复用，可抽 **窄插件**；否则留仓 | 告警分级、与 SOUL/路由对齐说明 |
| `plugins/data_access/`、`plugins/merged/` | 缓存读取、聚合入口 | 视是否与外置数据插件的缓存契约绑定再定 | 读缓存前的参数与路径约定 |
| `workflows/*.yaml` + `docs/openclaw/*` | 定时与专题设计 | 一般不拆为插件 | **优先 Skill 化** 重复教模型的部分 |

**阶段 1 交付物**（已落地）：[`能力地图.md`](./能力地图.md)（工具 / 工作流 / 脚本 / 环境变量索引）、[`跨插件数据契约.md`](./跨插件数据契约.md)（缓存根、权重文件、关键 JSON 读写与稳定性约定）。

---

## 6. 分阶段路线图（建议）

阶段划分以 **风险可控、可回滚** 为准，顺序可讨论调整。

### 阶段 0：基线（已完成参考）

- 数据采集外置：`openclaw-data-china-stock` + 主仓 `scripts/link_china_stock_data_collection.sh` 等约定。

### 阶段 1：盘点与契约（**已实施**）

- **能力地图**：[`能力地图.md`](./能力地图.md) — `tools_manifest` 工具分组、工作流索引、关键脚本与数据路径指针、通用验收命令。  
- **跨插件契约**：[`跨插件数据契约.md`](./跨插件数据契约.md) — 仓库根与 `data/cache`、融合权重落盘、`STRATEGY_FUSION_WEIGHTS_PATH`、主要 `data/` 产物与 JSON 稳定性策略。

### 阶段 2：「候选插件」试点

- 每次只拆 **一个** 垂直域（例如通知适配或某一分析子包），配套：  
  - `openclaw.plugin.json` + manifest；  
  - 最小单测与冒烟；  
  - 主仓 **兼容层**（薄 wrapper 或文档化 symlink，避免大爆炸迁移）。

### 阶段 3：Skill 与发布叙事对齐

- 将「最小安装」与「可选插件」写入 [`plugins-and-skills.md`](../publish/plugins-and-skills.md) 的固定结构；每个可选插件对应一段 **启用条件 + 验收步骤**（可指向本目录下专题或独立 Skill 文件）。  
- 与已有 [`三Skill驱动ETF研究自动进化实施方案.md`](./三Skill驱动ETF研究自动进化实施方案.md)、[`execution_contract.md`](./execution_contract.md) 等 **并存**：本策略侧重 **交易助手工具链拆分**，不替代进化流水线契约。

### 阶段 4：持续瘦身核心仓

- `tool_runner.py` 分支与 manifest 条目 **随外置而减少**；核心仓聚焦编排、默认配置与工作流。  
- 指标：主仓插件包体量、Gateway 工具暴露数量（可与 [`OpenClaw工具与Token优化建议.md`](./OpenClaw工具与Token优化建议.md) 联动）。

---

## 7. 验收与质量门禁（每个拆出单元）

每增加或外移一个插件，建议至少满足：

1. **安装路径**：`plugins.load.paths` 或 extensions 安装说明可复现（参见 `scripts/setup_openclaw_option_trading_assistant.sh` 类脚本）。  
2. **`openclaw doctor`**：无插件加载错误；与主仓并存时无重复注册冲突。  
3. **冒烟**：至少一条代表性 tool 调用成功（可纳入现有 release-gate / 单测）。  
4. **文档**：说明与主仓 optional 组合关系，避免读者误以为「只装其一即可覆盖全部能力」。

---

## 8. 风险与刻意不做的方向

| 风险 | 缓解 |
|------|------|
| 跨仓循环依赖 | 依赖单向：插件 → 公共类型/契约；核心仓组合插件，不反向依赖「助手业务细节」 |
| 配置分裂 | 集中文档化「谁读哪段 config」；Schema 与示例放在插件或 `docs/publish` |
| 工具爆炸与 token 压力 | 拆插件不等于全量暴露；manifest 分组 + 与 Skill 说明「默认启用集」 |
| 过度拆分 | 无复用、无独立发版需求时保留核心仓，仅用 Skill 固化流程 |

**刻意不做**（除非后续有明确需求）：为拆而拆、同一域多仓库碎片化、无测试覆盖的「文档型伪插件」。

---

## 9. 待讨论议题（供下一轮对齐）

1. **下一候选插件优先级**：通知通道、策略引擎、或某一分析子域——以复用与变更频率为准。  
2. **缓存与数据主权**：外置数据插件与主仓 `read_cache_data` 的边界是否要进一步写成 **单一契约文档**。  
3. **Skill 存放位置**：Cursor 用户 Skill 与仓库内 `docs/openclaw` 专题的双向同步策略（谁为 source of truth）。  
4. ~~**能力地图**是否作为本文件的附录单独维护~~ → 已独立为 [`能力地图.md`](./能力地图.md)，本策略文仅保留链接。

**已定惯例（2026-04-04）**：`etf-options-ai-assistant/skills/` **仅**放自研 Skill；第三方安装在 `~/.openclaw/skills/` 或 `~/.openclaw/workspaces/shared/skills/`。自研包在仓库内改完后执行 `bash scripts/sync_repo_skills_to_openclaw.sh` 并重载 Gateway。进化流水线依赖的 `capability-evolver`、`agent-team-orchestration`、`github` 等须在本机 OpenClaw 技能目录中存在（自检命令见 `docs/getting-started/third-party-skills.md` §1b）。总说明见 `skills/README.md` 与 `docs/publish/plugins-and-skills.md` §2b。

**自研 Skill 包（`ota-*`）**：主链路 / 数据 / 研究 / 进化 / 运维场景见 [`skills/README.md`](../../skills/README.md) 索引；统一前缀 **`ota-*`**（Option Trading Assistant），与插件 id 区分于 Clawhub 全局技能。  
- **规模（随仓库迭代）**：当前仓库 `skills/` 下含 `SKILL.md` 的子包 **23 个**（2026-04-05 清点）；首版合入时为 **15 包**，后续增量含 `ota-quantitative-screening-brief`、及各专项 brief / 规程包。  
- **与 Agent 对齐**：真源片段 [`config/snippets/openclaw_agents_ota_skills.json`](../../config/snippets/openclaw_agents_ota_skills.json)；说明表 [`OpenClaw-Agent-ota-skills.md`](./OpenClaw-Agent-ota-skills.md)、[`OpenClaw-Gateway-Agent与Skills勾选指南.md`](./OpenClaw-Gateway-Agent与Skills勾选指南.md)。**入口主 Agent（`etf_main`）与业务核（`etf_business_core_agent`）**须与 **`etf_analysis_agent`** 同样挂载研究向 `ota_*`（轮动、策略研究闭环、量化筛选 brief），否则「工具已注册、规程未注入」导致口径漂移。

---

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-04 | 初稿：插件 / Skill / 核心仓分层、阶段路线、验收与风险 |
| 2026-04-04 | 补充：`skills/` 仅自研、第三方走 `~/.openclaw/skills/`，同步脚本与文档入口 |
| 2026-04-04 | 进化流水线三项本机自检（§1b）、`plugins-and-skills` §2b、`github` 入可选检查脚本 |
| 2026-04-04 | **阶段 1 实施**：新增 `能力地图.md`、`跨插件数据契约.md`，并更新本节阶段描述 |
| 2026-04-04 | 首版自研 Skill：`skills/ota-*` 共 15 包，见 `skills/README.md` |
| 2026-04-05 | 与现网对齐：自研包增至 **23**；补充 `ota-quantitative-screening-brief`；`etf_main` / `etf_business_core_agent` / `etf_notification_agent` 与 `config/snippets/openclaw_agents_ota_skills.json` 同步说明；§9 首版段落改为「当前规模 + 历史 15 包」 |
