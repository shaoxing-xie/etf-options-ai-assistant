# 第三方 SKILL（技能包）依赖清单

本项目除了自定义插件与工具（`option-trading-assistant` 等）外，还会在部分工作流/Agent 编排中依赖 OpenClaw 生态中的**第三方 SKILL（技能包）**。

## 与本仓库 `skills/` 目录的关系

- **`etf-options-ai-assistant/skills/`** 仅保留**项目自研** Skill 源文件；**不要**把 Clawhub / 外网下载的第三方包放进该目录。
- 自研 Skill 调通后，用仓库脚本同步到 OpenClaw 加载路径（**只覆盖同名自研包，不会清空**全局目录里其他技能）：

```bash
bash scripts/sync_repo_skills_to_openclaw.sh
```

- 第三方 Skill 一律安装到 `~/.openclaw/skills/` 或 `~/.openclaw/workspaces/shared/skills/`（见下文），例如通过 Clawhub CLI；与本仓库 `skills/` 分离。

### 自研 Skill 改完后同步到本机 OpenClaw

在仓库中新增或修改 **`skills/<name>/SKILL.md`** 后，于**仓库根目录**执行（将自研包 rsync 到上述 OpenClaw 路径，**不删除**目录内其他第三方 Skill）：

```bash
cd /path/to/etf-options-ai-assistant
bash scripts/sync_repo_skills_to_openclaw.sh
```

然后**重启或重载 Gateway**，并用 `openclaw doctor` 或实际工作流验收。

本页用于回答两个问题：

- 第一次安装时，需要安装哪些第三方 SKILL？
- 如何把这些 SKILL 放到正确的位置，并验证已生效？

> 说明：不同 OpenClaw 安装方式（单机/多工作区/shared workspace）会导致 SKILL 的实际目录略有差异。本文以常见约定为主：`~/.openclaw/skills/` 或 `~/.openclaw/workspaces/shared/skills/`。

---

## 1. 必装 / 建议安装（Recommended）

这些技能会显著增强“盯盘/事件哨兵/外部信息补全”等能力；如果你只跑最基础的定时分析工作流，可以先不装，但建议尽早补齐。

- **`tavily-search`（外部信息检索）**
  - **用途**：政策/新闻/公告等外部信息补全（事件驱动的解释与风险提示）。
  - **典型使用点**：`event-sentinel`（事件哨兵）相关编排。
  - **依赖**：通常需要配置对应 API Key（按该 SKILL 的 `SKILL.md` 指引）。

- **`topic-monitor`（主题监控）**
  - **用途**：对指定主题周期扫描 → 摘要 → 达到条件触发进一步分析。
  - **典型使用点**：事件哨兵与“自动盯盘”的外围触发器。

- **`qmd-cli`（本地知识检索/轻量查询）**
  - **用途**：在不消耗大量上下文的前提下检索本地策略库/复盘库/文档库（如果你有此类知识库）。

---

## 1b. 进化流水线必备（Evolution）：本机是否存在

以下工作流与文档依赖 **`capability-evolver`、`agent-team-orchestration`**，并常与 **`github`** Skill（GitHub 操作约定）一并使用，见 `docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md` 与 `workflows/*_evolution_on_demand.yaml`。

它们必须安装在 OpenClaw **会加载**的技能目录中（通常是下面二者之一或两者；以你本机 `openclaw.json` / workspace 为准）：

- `~/.openclaw/skills/<skill-name>/SKILL.md`
- `~/.openclaw/workspaces/shared/skills/<skill-name>/SKILL.md`

**快速检查（文件层）**：下列命令若输出路径则表示该处已安装且含 `SKILL.md`（无输出表示该路径未安装）。

```bash
for s in capability-evolver agent-team-orchestration github; do
  for d in "$HOME/.openclaw/skills" "$HOME/.openclaw/workspaces/shared/skills"; do
    f="$d/$s/SKILL.md"
    [[ -f "$f" ]] && echo "OK $f"
  done
done
```

说明：**同一 Skill 可以只存在于其中一处**即可被加载（不必两处各装一份）。例如本机常见情况为 `github` 仅在 `workspaces/shared/skills` 下，而 `capability-evolver` 在两处各有一份副本。

也可用脚本中的「可选」扫描（含上述三项）：

```bash
bash scripts/check_third_party_skills.sh
```

（该脚本对「Recommended」仍只校验 `tavily-search` 等盯盘向技能；进化相关三项在 **Optional** 段落中列出。）

---

## 2. 可选（Optional）

- **`mootdx-china-stock-data`（A 股行情底座）**
  - **用途**：A 股实时行情、分钟线、Tick 等数据能力。
  - **备注**：本项目主链路（A股 / ETF）已有自己的采集/缓存工具；如果你希望把盯盘扩展到更多个股/板块，则建议安装。

- **`Capability Evolver` / `capability-evolver`（能力演化）**
  - **用途**：研究自动进化流水线中的 Evolver 角色；与 `docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md`、工作流 `*_evolution_on_demand.yaml` 等配合。
  - **安装**：通过 Clawhub 等安装到 **`~/.openclaw/skills/`**（或 shared skills），**不要**再放进本仓库 `skills/`。

- **`agent-team-orchestration`（多 Agent 编排）**
  - **用途**：Builder / Reviewer 分角色与 handoff；与上一条同一套进化流水线。
  - **安装**：同上，安装到 OpenClaw 技能目录即可。

- **`github`（GitHub 协作 Skill）**
  - **用途**：进化流水线中与 PR、分支、Actions 日志等相关的约定与操作指引（与 `docs/openclaw/execution_contract.md` 等配合）。
  - **安装**：安装到 **`~/.openclaw/skills/`** 或 **`~/.openclaw/workspaces/shared/skills/`**；部分环境仅装在 shared 路径即可。

- **妙想 / 东方财富系 Clawhub Skill**（如历史使用过的 `mx-data`、`mx-search`、`mx-moni` 等）
  - **用途**：外部金融数据或自选等能力；与本项目主链路采集工具独立。
  - **安装**：仅通过 Clawhub 安装到 OpenClaw 技能目录；**不要**提交到本仓库 `skills/`。

---

## 3. 安装位置（Where to install）

通常有两类可用位置（任选其一即可，按你的 OpenClaw 部署习惯）：

- **全局技能目录**：`~/.openclaw/skills/`
- **共享工作区技能目录**：`~/.openclaw/workspaces/shared/skills/`

每个技能一般应具备类似结构：

```text
<skill-name>/
└── SKILL.md
```

---

## 4. 验证是否安装成功（Verify）

最可靠的方式是检查技能目录中是否存在对应文件，并且 OpenClaw/Gateway 启动时能加载这些技能。

你可以做两步验证：

### 方式 A：一键检查脚本（推荐）

本仓库提供一份“第三方 SKILL 是否安装齐全”的一键检查脚本：

```bash
bash scripts/check_third_party_skills.sh
```

- 若输出 `Result: OK`：表示“Recommended”清单已满足。
- 若输出 `Result: FAIL`：表示仍缺少部分 Recommended 技能，需要补装后再跑一次。

### 方式 B：手动检查（文件层 + 运行态）

1) **文件层验证**

```bash
ls -la ~/.openclaw/skills/
ls -la ~/.openclaw/workspaces/shared/skills/
```

2) **运行态验证**

- 重启或重载 OpenClaw Gateway 后，查看日志中是否有技能加载/注册信息。
- 或在你实际用到该技能的工作流/Agent 里触发一次相关行为，确认不会报“skill not found / tool not found”。

---

## 5. 本项目当前“会引用到”的技能清单（Source of truth）

目前仓库内对第三方技能的引用主要集中在 `AGENTS.md` 的“Trading Skills（自定义）/基础能力（数据/检索）”段落。

如果你新增/引入了新的第三方 SKILL，请同步更新：

- 本页（`docs/getting-started/third-party-skills.md`）
- 以及 `docs/getting-started/README.md` 的安装检查清单

