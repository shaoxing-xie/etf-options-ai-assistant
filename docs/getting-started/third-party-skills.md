# 第三方 SKILL（技能包）依赖清单

本项目除了自定义插件与工具（`option-trading-assistant` 等）外，还会在部分工作流/Agent 编排中依赖 OpenClaw 生态中的**第三方 SKILL（技能包）**。

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

## 2. 可选（Optional）

- **`mootdx-china-stock-data`（A 股行情底座）**
  - **用途**：A 股实时行情、分钟线、Tick 等数据能力。
  - **备注**：本项目主链路（A股 / ETF）已有自己的采集/缓存工具；如果你希望把盯盘扩展到更多个股/板块，则建议安装。

- **`Capability Evolver`（能力演化/审阅顾问）**
  - **用途**：以“review 顾问”模式审阅研究流程与输出结构，提出改进建议（不直接改交易链路）。
  - **备注**：强烈建议仅在只读/评审模式使用，避免自动写文件或改关键策略参数。

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

