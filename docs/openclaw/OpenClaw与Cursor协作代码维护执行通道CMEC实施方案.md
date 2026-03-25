# OpenClaw 与 Cursor 协作（代码维护执行通道 CMEC）实施方案

## 目标

在**不安装额外插件**的前提下，让 OpenClaw 与 Cursor 通过共享目录协作：

- OpenClaw 负责分析、产出任务与补丁；
- Cursor 侧监听共享目录并自动应用改动；
- 执行结果形成可观测回执（不限定单一路径），由 OpenClaw 感知后继续流程。

> 说明：本文已从“设计稿”升级为“运行手册”。当前仓库已完成 P0/P1 与 **P2 β（平台 JSON 受控补丁）**；P2 其余项（审计汇总、回执增强等）仍可按需补齐。

## 文档导读

- **定位**：CMEC 端到端运行手册——OpenClaw 产出 `.handoff/` → Cursor 侧 `handoff_worker` 应用补丁与 `verify.sh` → 回执落盘（`result.md` / 审计 / 日志）。
- **建议阅读顺序**：先看 **「当前实施进度」** 与 **「目录与文件约定」** → 按 **「P0 已落地内容」** 把 worker 跑起来 → 读 **「OpenClaw 接入规范」** 与 **「补丁格式」** → 需要验收时跳到 **「测试与验收」** → 出问题查 **「常见失效模式」**。

**章节地图（自上而下）**

| 区块 | 章节标题（文中检索） | 用途 |
|------|----------------------|------|
| A | 目标 · 适用场景 · **总体架构** | 建立概念 |
| B | **当前实施进度** · 目录约定 · 角色 | 能做什么 |
| C | 安全与回执 · **补丁格式** · 任务模板 | 怎么写补丁 |
| D | **OpenClaw 接入规范**（含 SOUL 模板） | Agent 与路由 |
| E | 里程碑 **P0/P1/P2** · **不在范围内** | 历史分期与边界 |
| F | **P2（扩展能力）** 细则 | 平台 JSON、审计、verify 日志 |
| G | 任务分级 · 首批任务 · **P0 已落地** | 启动 worker、依赖、自检、FAQ |
| H | **测试与验收**（§P1 手工 · §P2 钉钉） | 本机演练与 OpenClaw 话术 |
| I | 对齐清单 · 每日代码健康 · **失效模式** | 治理与排障 |

## 适用场景

- OpenClaw 需要推动代码修改，但不直接在 IDE 内操作；
- 你希望减少手工复制粘贴 patch；
- 你需要可审计、可回滚的自动化协作链路。

## 总体架构

```text
OpenClaw 任务生成 -> .handoff/task.md + changes.diff (+ verify.sh)
                -> Cursor 监听脚本发现变更
                -> 自动 apply patch + 运行验证
                -> 结果落盘（result.md / 项目文件更新 / 插件与OpenClaw相关文件更新）
                -> OpenClaw 通过文件变化或日志感知结果并继续流程
```

## 当前实施进度（2026-03-25）

| 阶段 | 状态 | 要点（一条） |
|------|------|----------------|
| **P0** | 完成 | `.handoff` 骨架、`handoff_worker.sh`、`handoff_start.sh` |
| **P1** | 完成 | `risk_level`、路径白名单、`approval.txt`、备份、幂等 patch |
| **Agent** | 完成 | `code_maintenance_agent` 固化 CMEC 协议（Codebase Maintainer） |
| **P2 β** | 完成 | 仅 `openclaw.json` / `cron/jobs.json` + `approval` + sha → `patch-openclaw`；**禁止**与仓库路径混在同一 diff |
| **P2 配套** | 完成 | `cmec-audit.jsonl`、`verify.last.log`、`verify_openclaw_config.sh`、`cmec_audit_summary.sh` |
| **待补齐** | 可选 | 网关重启 / `systemctl` 不经 CMEC；跨 Agent SOUL 持续对齐 |

细则与操作说明见下文 **「优先级实施方案（里程碑）」**、**「P2（扩展能力）」**、**「P0 已落地内容」**。

## 目录与文件约定

建议在项目根目录创建 `/.handoff/`：

- `task.md`：任务描述（目标、范围、约束）
- `changes.diff`：可应用的补丁（建议使用标准 unified diff；见下文“补丁格式注意事项”）
- `verify.sh`：可选，改动后验证脚本
- `result.md`：执行结果（成功/失败/日志摘要，**可选回执通道之一**）
- `.backup/`：自动备份（可选）

## 角色边界

- **OpenClaw 负责**：
  - 生成变更意图与 patch；
  - 写入 `task.md`、`changes.diff`、`verify.sh`；
  - 感知执行结果后决定下一步（重试/修复/结束）。结果来源可为 `result.md`、目标文件实际变更、或运行日志。
- **Cursor 负责**：
  - 监听 `.handoff/changes.diff`；
  - 自动 apply patch；
  - 执行验证命令；
  - 产出执行回执（可回写 `result.md`，也可直接落到目标文件与日志）。

> **OpenClaw 侧（Agent 分工、配置、SOUL、标准流程、验收）**：与下文 **「OpenClaw 接入规范（将代码维护执行通道 CMEC 作为标准执行通道）」** 合并阐述，见该节 **§1 通道定位**、**§2 路由与守卫**、**§6 最小改造清单** 及文末 **SOUL 可复制模板**。

## 安全与边界控制（推荐）

- 仅允许在项目目录内操作（`~/etf-options-ai-assistant/**`）。
- `verify.sh` 默认只允许运行仓库内常规检查命令（如测试、lint、type-check）。
- 自动应用失败时不得继续链式执行，必须写回失败原因。
- 每次自动执行前保留备份（patch 文件与关键日志）。

## 执行回执与失败处理规范

### 回执通道（按优先级建议）

1. **标准回执（推荐）**：写 `result.md`（结构化、便于 OpenClaw 稳定解析）。
2. **文件即回执**：直接修改目标文件（例如插件代码、工具脚本、文档），并在提交说明/日志中标记执行状态。
3. **日志回执**：仅写运行日志（适用于临时调试），但不建议长期依赖。

> 结论：`result.md` 是推荐而非强制。只要回执可被 OpenClaw 稳定感知，即可形成闭环。

- `changes.diff` 应用失败：
  - `result.md` 标记 `status: failed`；
  - 写明失败片段（hunk/文件名）；
  - OpenClaw 需生成修复版 patch 后重试。

## 补丁格式注意事项（避免常见坑）

- **推荐格式**：标准 unified diff（`diff -u` 生成），不要求包含 `diff --git` / `index ...` 行。
- **禁止**写形如 `index 0000000..0000000` 的占位哈希：这会导致 `git apply` 直接失败。
- 若你希望用 `git diff` 风格（含 `diff --git` / `index`），则 `index` 行必须是真实哈希（由 git 自动生成），不要手写。
- **hunk 必须带范围**：`@@ -start,count +start,count @@`，不能只写一行 `@@`，否则 `patch`/`git apply` 会报 “garbage / No valid patches”。

### 快速生成补丁（推荐复制）

在项目目录下，用临时文件生成 `diff -u`（避免手写出错）：

```bash
cd ~/etf-options-ai-assistant

cp -f docs/openclaw/README.md /tmp/README.md.bak
python3 - <<'PY'
from pathlib import Path
p=Path('docs/openclaw/README.md')
s=p.read_text(encoding='utf-8')
p.write_text(s.replace('本目录面向负责 OpenClaw 环境、Gateway、Cron 工作流和插件部署的使用者。',
                       '本目录面向负责 OpenClaw 环境、Gateway、Cron 工作流和插件部署的使用者。（handoff test）',1),
            encoding='utf-8')
PY

diff -u /tmp/README.md.bak docs/openclaw/README.md > .handoff/changes.diff
mv -f /tmp/README.md.bak docs/openclaw/README.md
```

> 上面示例只用于演练补丁格式，实际业务改动请让 OpenClaw 直接输出正确的 unified diff。
- `verify.sh` 失败：
  - `result.md` 标记 `status: failed`；
  - 写明失败命令与摘要；
  - 不自动提交。
- 成功：
  - 若使用 `result.md`，标记 `status: ok` 并记录执行时间与关键命令；
  - 若不使用 `result.md`，至少保证目标文件变更与执行日志可追溯。

## 任务模板（OpenClaw 侧）

`task.md` 建议模板：

```markdown
## Task
- goal:
- scope:
- files:
- constraints:
- test-plan:
```

`result.md` 建议模板：

```markdown
## status: ok|failed
### applied
- time:
- files:
### verify
- command:
- result:
### notes
- ...
```

## 与当前 OpenClaw 路由策略的关系

本方案仅解决代码改动协作链路，不改变现有通知路由：

- 研究/分析类：钉钉主通道
- 运维/巡检类：飞书主通道

相关说明见：`docs/openclaw/通知通道路由与SOUL对齐说明.md`。

## OpenClaw 接入规范（将代码维护执行通道 CMEC 作为标准执行通道）

结合多 Agent 编排与 HITL（Human-in-the-loop）常见实践，代码维护执行通道（CMEC）在本项目中的定位为：
**“OpenClaw 的标准代码改动执行通道”**，而不是临时脚本能力。

### 1) 通道定位与触发条件

- 当任务涉及代码/脚本/文档改动时，`etf_main` 不直接改文件，统一路由给 `code_maintenance_agent`。
- `code_maintenance_agent` 负责产出三件套：`task.md`、`changes.diff`、`verify.sh`。
- Cursor worker 只负责“受控执行”（apply + verify + 回执），不负责业务决策。

### 2) 路由规范（建议固化到 SOUL）

- **入口规则**：出现“修改代码/修复 bug/改文档/改配置方案文档”等意图时，进入 CMEC 通道。
- **分级规则**：
  - `auto`：低风险、可逆、影响面小（如文档、注释、轻微重构）。
  - `guarded`：默认级别，要求白名单 + verify 通过。
  - `approval`：高风险（平台配置、服务重启、跨目录大改）必须先审批再执行。
- **退出规则**：读取 `result.md`（优先）与目标文件变化；成功则归档，失败则生成修复补丁重试。

### 2.1) 先分类后执行（Router->Executor）机制

为避免“知道 CMEC 但不优先使用”，建议采用 Router->Executor 固化机制：

- `etf_main` 先做任务语义分类，再决定执行器，不直接进入自由回答。
- 任何命中“代码维护意图”的任务必须路由到 `code_maintenance_agent`，不得直接改文件或让用户手工执行。
- 推荐触发关键词（可持续扩展）：
  - `代码维护`、`代码检查`、`代码体检`、`修复`、`报错`、`异常`
  - `lint`、`ruff`、`mypy`、`pytest`、`bandit`
  - `补丁`、`diff`、`重构`、`脚本修改`、`模块开发`

### 2.2) 防跑偏守卫（Guardrails）

为避免降级到“人工代执行模式”，在 SOUL 中加入硬约束：

- 禁止输出：
  - “我无法访问文件系统，请你执行命令”
  - “请你手工运行以下命令再把结果贴给我”
- 若模型出现上述倾向，必须自动改写为：
  - 走 CMEC：产出 `task.md` / `changes.diff` / `verify.sh`
  - 读取 `result.md` 后再给最终结论

### 2.3) 固定回报结构（便于验收）

`code_maintenance_agent` 的最终回报建议固定为四段：

1. `已执行`（执行了哪些检查与步骤）
2. `已修复`（自动/手动修复项）
3. `未修复`（问题清单 + 未修原因）
4. `后续人工建议`（按 P0/P1/P2 分级）

该结构可显著降低“只给命令、不交付结果”的漂移。

### 3) 交接上下文规范（防止“会做但做错”）

- `task.md` 必填：`goal`、`scope`、`files`、`constraints`、`test-plan`、`risk_level`。
- `changes.diff` 必须使用 unified diff（建议由 `diff -u` 或 `git diff` 生成，禁止手写占位 `index`）。
- `verify.sh` 必须可在当前环境执行；无额外依赖时可回退到仓库默认轻量检查。
- 每次下发补丁时，建议在 `task.md` 追加“handoff justification”（为何此变更进入该通道），降低误路由。

### 4) 执行控制规范（Cursor worker 侧）

- **幂等执行**：已应用补丁再次触发时应安全跳过（当前已实现）。
- **单实例互斥**：通过锁避免并发 apply（当前已实现）。
- **白名单约束**：仅允许既定目录，越界立即失败（当前已实现）。
- **审批门禁**：`approval` 必须匹配 `approval.txt` 中的补丁 sha256（当前已实现）。
- **失败即止损**：patch 失败/verify 失败立即停止，不链式继续（当前已实现）。

### 5) 审计与可追溯规范

- `result.md` 保留结构化字段：`status`、`apply_method`、`verify.result`、`notes`。
- `.handoff/.backup/` 保留输入快照（patch/task/verify/result.before）。
- 对 `approval` 任务，建议额外记录“审批人/审批时间/审批原因”（可先写入 `task.md` 扩展字段）。

### 6) OpenClaw 侧最小改造清单（可直接执行）

1. 在 `etf_main` SOUL 增加路由条款：凡“需要改动文件”的任务统一派发 `code_maintenance_agent`。  
2. 在 `code_maintenance_agent` SOUL 固化 CMEC 协议（字段、分级、失败重试、回执读取顺序）。  
3. 将 `bash scripts/handoff_start.sh` 纳入你的日常启动脚本，确保 worker 常驻。  
4. 每日巡检增加 1 条健康检查：`pgrep` 期望 1 个 worker + 1 个 inotifywait。  
5. 对 `approval` 场景，先在团队约定审批责任人（避免任务卡死）。

### 7) 运行口径（统一对内说明）

- OpenClaw 负责：任务决策、补丁生成、结果消费与重试策略。  
- Cursor worker 负责：受控执行与回执，不承担业务判断。  
- CMEC 负责：把“改动意图”转成“可审计、可回滚、可恢复”的执行流水线。

### 8) 可直接复制的 SOUL 模板（即贴即用）

下面两段可直接粘贴到对应 Agent 的 SOUL 中。

**`etf_main` 模板段：**

```markdown
## OpenClaw->Cursor 代码维护执行通道（CMEC）路由（标准执行通道）

- 当任务包含“改代码/改脚本/改文档/改配置方案文档/修复报错”等文件改动意图时：
  - 你不得直接执行文件修改；
  - 必须将任务派发给 `code_maintenance_agent`（代码维护执行官）。

- 你向代码维护执行官下发任务时，必须要求其产出并写入：
  - `/.handoff/task.md`
  - `/.handoff/changes.diff`
  - `/.handoff/verify.sh`（可选覆盖默认）

- 风险分级必须明确：
  - `risk_level: auto | guarded | approval`
  - 未声明时按 `guarded` 处理。

- 回执消费顺序固定：
  1. 先读 `/.handoff/result.md`
  2. 再核对目标文件是否按预期变化
  3. 必要时补读执行日志

- 失败处理：
  - 若 `result.md` 显示 `failed`，必须要求代码维护执行官给出“修复版 patch + 重试步骤”；
  - 不得把失败静默当成功。
```

**`code_maintenance_agent` 模板段：**

```markdown
## OpenClaw->Cursor 代码维护执行通道（CMEC）执行协议

- 你是 CMEC 的代码维护执行官（Codebase Maintainer，而非直接改文件执行者）：
  - 必须输出 `task.md`、`changes.diff`、`verify.sh` 三件套到 `/.handoff/`。

- `task.md` 必填字段：
  - `goal` / `scope` / `files` / `constraints` / `test-plan` / `risk_level`
  - 建议附加 `handoff_justification`（为何走 CMEC）。

- `changes.diff` 规范：
  - 必须是 unified diff（推荐 `diff -u` 或 `git diff` 生成）；
  - 禁止手写占位 `index 000...`；
  - 变更路径应限制在白名单目录内（`docs/**`,`plugins/**`,`scripts/**`,`workflows/**`,`config/**` 等）。

- `risk_level` 语义：
  - `auto`：低风险可逆改动；
  - `guarded`：默认级，要求白名单 + verify 通过；
  - `approval`：高风险任务；需等待 `/.handoff/approval.txt` 中出现当前补丁 sha256 才可继续。

- 回执与重试：
  - 写完补丁后，优先读取 `/.handoff/result.md` 判定执行结果；
  - 若 `status=failed`，必须输出“失败原因 + 修复版补丁”再重试；
  - 若 `status=ok`，给出简短变更摘要并结束。
```

## 不在本方案范围内

- 不直接实现 OpenClaw 对 Cursor 的原生 RPC 控制；
- 不引入额外 Cursor 插件或 OpenClaw 插件；
- 不在本阶段自动提交 git commit/push。

## 优先级实施方案（分阶段里程碑，与「当前实施进度」对照）

### P0（先打通，1 天内）

- 建立 `.handoff/` 目录与 4 个基础文件：`task.md`、`changes.diff`、`verify.sh`、`result.md`。
- 在 Cursor 侧部署监听脚本（`inotifywait`），实现：
  - 监听 `changes.diff`；
  - 自动 apply patch；
  - 自动执行 `verify.sh`（存在时）；
  - 写回执行结果（`result.md` 或日志）。
- 仅开放**低风险任务**：
  - 文档修改；
  - 代码检查（lint/test/typecheck）；
  - 小范围 bug 修复（白名单目录内）。

### P1（稳态运行，1-2 天）

- 增加任务分级字段（写入 `task.md`）：
  - `risk_level: auto | guarded | approval`
- 增加路径白名单与命令白名单：
  - 路径建议：`docs/**`, `plugins/**`, `scripts/**`, `workflows/**`
  - 禁止直接写高风险路径（如 `~/.openclaw/openclaw.json`）除非 `approval`
  - `approval` 落地机制：要求 `.handoff/approval.txt` 中包含当前 `changes.diff` 的 sha256（worker 会在 `result.md` 输出该 sha256）
- 增加失败保护：
  - patch 应用失败立即停止；
  - verify 失败不继续后续动作；
  - 保留 `.handoff/.backup/` 备份。

### P2（扩展能力，按需）

- **（β 已落地）受控平台配置补丁**（仅 `approval` + `approval.txt` 的 sha256）：
  - 允许修改的文件 **仅此两个绝对路径**（解析自 `$HOME`）：`~/.openclaw/openclaw.json`、`~/.openclaw/cron/jobs.json`。
  - 补丁里请使用 **绝对路径** 头，例如：
    ```text
    --- /home/xie/.openclaw/openclaw.json
    +++ /home/xie/.openclaw/openclaw.json
    ```
    （将 `/home/xie` 换为你的 `$HOME`）。Worker 使用 **`patch -d / -p0`** 应用。
  - **禁止**在同一 `changes.diff` 中混改 ETF 仓库文件与上述平台文件；请分两次任务。
  - `result.md` 中 `apply_method` 为 **`patch-openclaw`** 时表示本次为平台路径应用。
- **审计（JSONL，已落地）**：
  - 路径：`.handoff/cmec-audit.jsonl`（追加写，一行一条 JSON）。
  - 汇总：`bash scripts/cmec_audit_summary.sh`（默认 `~/etf-options-ai-assistant`）。
  - Cron/飞书日报可 `tail -n 50` 该文件或调用上述脚本生成摘要。
- **平台补丁的 verify（建议）**：
  - 默认 `.handoff/verify.sh` 仍以 **ETF 仓库** `compileall` 为主；**纯平台 JSON 任务**建议在 `task.md` 中说明由 OpenClaw 覆盖 `verify.sh`，例如仅执行：
    ```bash
    #!/usr/bin/env bash
    set -euo pipefail
    bash "$(git rev-parse --show-toplevel 2>/dev/null || echo "$HOME/etf-options-ai-assistant")/scripts/verify_openclaw_config.sh"
    ```
    或与现有 `verify.sh` **串联**（先 OpenClaw JSON，再 compileall）。
- **（未纳入 CMEC）运维动作**：`openclaw gateway restart` / `systemctl --user` 等 **不由 handoff worker 执行**；仍由 `ops_agent` 或人工按手册操作。
- **（已默认）verify 输出落盘**：每次实际执行 `verify.sh` 时，stdout/stderr 写入 **`.handoff/verify.last.log`**（带时间头）；`result.md` 的 `### verify` 下列出 **`- log:`** 路径。注意：**补丁判为 already applied 并提前返回时不会跑 verify**，故该次不会刷新 `verify.last.log`。

## 任务分级建议（落地标准）

| 分级 | 默认执行策略 | 示例 |
|------|--------------|------|
| `auto` | 自动执行 | 文档改写、代码检查、注释修正 |
| `guarded` | 自动执行 + 白名单 + 备份 + verify 必过 | 小范围 bug 修复、多文件重命名 |
| `approval` | 明确批准后执行 | 平台配置修改、服务重启、批量重构 |

## 首批上线任务（建议）

1. 文档任务：`docs/openclaw/*.md` 更新（`auto`）  
2. 代码检查任务：`verify.sh` 仅跑 lint/test（`auto`）  
3. 小修复任务：`plugins/notification/*.py`（`guarded`）  
4. 平台任务演练：只做一次 `gateway restart`（`approval`）  

以上 4 类跑通后，再扩大范围。

## P0 已落地内容（仓库内）

当前仓库已提供 CMEC 最小骨架：

- `/.handoff/README.md`
- `/.handoff/task.md`
- `/.handoff/changes.diff`
- `/.handoff/verify.sh`
- `/.handoff/result.md`
- `scripts/handoff_worker.sh`（Cursor 侧监听并自动 apply/verify/回执）
- `scripts/verify_openclaw_config.sh`（P2：平台 JSON 语法校验，供 `verify.sh` 引用）
- `scripts/cmec_audit_summary.sh`（P2：汇总 `cmec-audit.jsonl`）
- `.handoff/cmec-audit.jsonl`（worker 每次结论追加一行，见 `result.md` 中 `audit_log`）
- `.handoff/verify.last.log`（最近一次 `verify.sh` 的完整输出，见 `result.md` 中 `verify` → `log`）

### 启动方式（本机执行）

```bash
cd ~/etf-options-ai-assistant

# 推荐：使用一键脚本（会自动清理残留监听/worker 并启动）
bash scripts/handoff_start.sh

# 备用：你也可以手工直接启动（不做清理）
# bash scripts/handoff_worker.sh
```

本机需常驻 `bash scripts/handoff_start.sh`。

### 启动后自检（推荐）

```bash
pgrep -af "bash scripts/handoff_worker\\.sh"
pgrep -af "inotifywait"
```

预期：

- `bash scripts/handoff_worker.sh`：1 条
- `inotifywait ... .handoff ...`：1 条

### 依赖与一次性准备

监听脚本依赖 `inotifywait`（来自 `inotify-tools` 包）。

1. **安装依赖**（若尚未安装）：

```bash
sudo apt-get update && sudo apt-get install -y inotify-tools
```

2. **启动监听 worker**（建议在 Cursor 里开一个终端常驻运行）：

```bash
cd ~/etf-options-ai-assistant
bash scripts/handoff_worker.sh
```

### 常见问题（第一次演练容易踩坑）

- **补丁反复写入导致重复应用/失败**：`handoff_worker.sh` 已做“幂等”处理：若检测到补丁已应用，会自动跳过并在 `result.md` 记录 `already applied`。
- **补丁为空或只有注释**：会被自动忽略，不触发 apply。
- **补丁不生效/不匹配**：优先用 `diff -u` 生成补丁，避免手写 `@@` 或手写 `index ...`。
- **提示需要 approval 才能执行**：将 `result.md` 中提示的 sha256 追加写入 `.handoff/approval.txt` 后，再次写入同一份 `changes.diff`（触发 close_write）即可执行。
- **路径白名单拦截**：将变更控制在白名单内（默认如 `docs/**`, `plugins/**`, `scripts/**`, `workflows/**`, `config/**` 等）；需要扩白名单时，优先通过调整方案文档并一起提交变更依据。

## 测试与验收

> **§P1**：本机手工演练（白名单 / approval / 拦截）。**§P2**：钉钉上 `etf_main` → `code_maintenance_agent` 话术（与 §P1 相互独立，可单独执行）。

### P1 手工演练（建议按顺序）

> 目的：确认三件事都生效：**白名单**、**approval 门禁**、**verify 默认脚本**。

### 1) guarded（白名单内变更自动执行）

1. 在 `.handoff/task.md` 设置：

```md
- risk_level: guarded
```

2. 生成一个对白名单目录内文件的补丁（例如 `docs/openclaw/README.md`），写入 `.handoff/changes.diff` 并保存。
3. 预期：worker 自动应用补丁，`.handoff/result.md` 显示 `status: ok` 且 `verify: passed`。

### 2) approval（先拦截，后批准再执行）

1. 在 `.handoff/task.md` 设置：

```md
- risk_level: approval
```

2. 写入任意白名单内补丁到 `.handoff/changes.diff` 并保存。
3. 预期：`.handoff/result.md` 显示 `status: failed`，并提示 `sha256: <...>`（要求写入 `.handoff/approval.txt`）。
4. 将该 sha256 追加写入 `.handoff/approval.txt`（一行一个 sha256），然后**重新保存一次同一份** `.handoff/changes.diff`（触发 close_write）。
5. 预期：补丁被放行并执行，`.handoff/result.md` 显示 `status: ok`。

### 3) 白名单拦截（非白名单路径应直接失败）

写一个补丁试图修改 **非** P2 β 允许的平台路径（例如 `~/.openclaw/credentials.json`、项目根下未豁免的隐藏文件等），且不要使用 `approval` 放行。

预期：worker 不会 apply，`.handoff/result.md` 显示 `path allowlist denied` 并列出 `bad_paths`。

（**对照**：仅 `openclaw.json` / `cron/jobs.json` 在 **`risk_level: approval` + `approval.txt` sha** 下可放行，成功时 `apply_method: patch-openclaw`。）

### P2 OpenClaw（钉钉 / 会话）

> 目的：通过 **OpenClaw**（`etf_main` → `code_maintenance_agent`）驱动本机 **`.handoff/`**，验证 P2 β（平台 JSON）、混改拦截、审计与 verify 日志等能力。以下话术可直接复制到钉钉；将示例中的 `$HOME`（如 `/home/xie`）按你本机替换。

#### 前置（本机）

1. **常驻 worker**：`cd ~/etf-options-ai-assistant && bash scripts/handoff_start.sh`（或等价监听进程）。
2. **handoff 对齐**：若 `code_maintenance_agent` 的 workspace 为 `shared`，需保证 **`~/.openclaw/workspaces/shared/.handoff/` 与 ETF 仓库的 `.handoff/` 为同一目录**（符号链接），否则 OpenClaw 写入与 Cursor worker 监听不一致。
3. **路由**：消息入口应能命中 **`etf_main`**，再由其派发 **`code_maintenance_agent`**（见前文「路由与失效模式」）。

#### 场景 A：P2 β 平台 JSON（`approval` + sha）

**目的**：验证 **`apply_method: patch-openclaw`**、`approval.txt` 门禁、（可选）`verify_openclaw_config.sh`。

**钉钉话术示例：**

```text
请 etf_main 交给 code_maintenance_agent，走 CMEC，做 P2 平台配置测试：
1) .handoff/task.md 写 risk_level: approval；changes.diff 仅修改 ~/.openclaw/cron/jobs.json（或 openclaw.json）一处可逆、可解释的改动。
2) unified diff 的 ---/+++ 必须使用绝对路径，例如 /home/xie/.openclaw/cron/jobs.json；禁止与 ETF 仓库内路径混在同一 diff。
3) 若 result.md 提示 sha256，将 sha 写入 .handoff/approval.txt 后再次保存同一份 changes.diff。
4) verify.sh 建议调用仓库 scripts/verify_openclaw_config.sh。
完成后读 .handoff/result.md 与 .handoff/cmec-audit.jsonl 最后一行，说明 apply_method 是否为 patch-openclaw。
```

**本机验收：**

- `.handoff/result.md`：`apply_method: patch-openclaw`；`status: ok`（或先 `failed` + sha，补 `approval.txt` 后再 ok）。
- `.handoff/cmec-audit.jsonl`：最后一条 JSON 中 `patch_kind` 为 `platform`。
- 若实际执行了 verify：存在 `.handoff/verify.last.log`，且 `result.md` 的 `### verify` 下列出 **`- log:`**。

#### 场景 B：混改拦截（MIXED）

**目的**：确认 **同一 `changes.diff` 不得同时包含 ETF 仓库路径与 `~/.openclaw` 下允许的两份 JSON**。

**钉钉话术示例：**

```text
请 code_maintenance_agent 走 CMEC，做负面测试：在一个 changes.diff 里同时修改 docs/openclaw 下某 md 的一行，和 /home/xie/.openclaw/openclaw.json 的一行（均为合法 unified diff）。risk_level: approval。
预期 worker 拒绝 mixed。完成后读 result.md，应含 mixed patch not supported 或同类说明。
```

**本机验收：** `result.md` 为 `failed`，`notes` 指向 mixed / 拆分 handoff；平台与仓库文件不应被错误地部分应用（以 `result.md` 与目标文件内容为准）。

#### 场景 C：审计与 verify 日志（仅仓库，不碰平台）

**目的**：验证 **`cmec-audit.jsonl`**、**`verify.last.log`**（需 **真正执行 apply + verify**，不能停留在「already applied」早退）。

**钉钉话术示例：**

```text
请 code_maintenance_agent 走 CMEC，risk_level: guarded：在 docs/openclaw 下任选一篇 md 末尾增加一行测试标记（如 CMEC P2 audit probe 与日期），并生成可全新应用的 changes.diff；保留或显式使用会 run compileall 的 verify.sh。
完成后汇报 result.md；并说明 cmec-audit.jsonl 最后一行与 verify.last.log 是否更新。
```

**本机验收：**

- `bash scripts/cmec_audit_summary.sh`
- `tail -n 1 .handoff/cmec-audit.jsonl`
- `test -f .handoff/verify.last.log && tail .handoff/verify.last.log`

若 OpenClaw 反馈「已应用过」导致未跑 verify，可要求 **再改一字或换标记** 重新生成 diff，或本地先还原该 md 再测。

#### 场景 D：回执读取约束（可选，减少漏读）

在任务末尾追加：

```text
闭环必须包含：read .handoff/result.md；若成功且跑过 verify 则 read .handoff/verify.last.log 尾部；read .handoff/cmec-audit.jsonl 最后一行。不得仅凭记忆汇报。
```

#### 小结

| 测试点 | OpenClaw 侧要点 | 本机核对 |
|--------|-----------------|----------|
| 平台 JSON | `approval`、仅 `openclaw.json`/`jobs.json`、绝对路径、单独 diff | `patch-openclaw`、`approval` 流程 |
| 混改拦截 | 同一 diff 混仓库 + 平台 | `failed` + mixed 提示 |
| 审计 / verify 日志 | 新补丁 + 实际执行 verify | `cmec-audit.jsonl`、`verify.last.log` |

## 全面实施对齐清单（P2）

以下为“从已可用到全面实施”的建议执行项，按优先级排序：

1. **SOUL 口径统一（高优先）**
   - `etf_main`、`code_maintenance_agent`、`ops_agent` 对 CMEC 的角色边界与命名保持一致：统一使用“代码维护执行官（Codebase Maintainer）”。
   - `etf_main` 明确“只路由不改文件”；`code_maintenance_agent` 明确“体检/调试/脚本/模块开发均走 CMEC 交付”；`ops_agent` 保持“默认不改代码”。

2. **高风险任务白名单化（高优先）**
   - **（P2 β 已部分落地）** 平台配置 **`openclaw.json` / `cron/jobs.json`** 已在 worker 层支持 **`approval` + sha256 + 绝对路径补丁**；其他 `~/.openclaw/**` 仍禁止。
   - **（仍建议人工 / ops）** `openclaw gateway restart`、`systemctl --user` 等 **不纳入** `handoff_worker`：继续由运维手册或 `ops_agent` 执行，避免无人值守重启。

3. **审计与回放（中优先）**
   - **（部分落地）** `.handoff/cmec-audit.jsonl` + `scripts/cmec_audit_summary.sh`；仍可按需叠加 `.handoff/.backup/` 与人工复盘模板。
   - 固化“失败复盘模板”：失败原因、修复补丁、二次验证结果。

4. **运行健康检查（中优先）**
   - 日常巡检中固定检查：`handoff_worker.sh` 进程 1 个、`inotifywait` 进程 1 个。
   - 异常时统一使用 `scripts/handoff_start.sh` 清理并拉起，避免多实例竞争。

5. **变更边界持续治理（中优先）**
   - 白名单目录扩容前，先在 `task.md` 写明 `handoff_justification` 与风险等级，再调整策略。
   - 非白名单需求优先拆分为“低风险子补丁 + 审批子补丁”，降低一次性大变更失败率。

6. **CMEC 命中率评估（持续）**
   - 每周统计三项指标：
     - `CMEC 路由命中率`：代码类任务中走 CMEC 的比例；
     - `人工代执行率`：出现“请你执行命令”类回复的比例（目标趋近 0）；
     - `闭环完成率`：存在 `result.md` 且最终输出含“已修复+未修复清单”的比例。
   - 连续两周未达标时，优先调整 `etf_main` 路由关键词与 `code_maintenance_agent` 的输出守卫规则。

## 每日代码健康“自动修复 + 报告”实施（已接入）

已将“shared: 每日代码健康体检（code_maintenance_agent）”从“只出报告”升级为“先自动修复可修项，再输出报告”。

- 执行脚本：`/home/xie/.openclaw/workspaces/shared/tools/code_health_autofix.py`
- 扫描范围：`/home/xie/.openclaw/workspaces/shared`
- 报告产物：
  - `memory/code-health-autofix-YYYY-MM-DD.md`
  - `memory/code-health-autofix-YYYY-MM-DD.json`
- 报告必须包含：
  - 已自动修复项（数量 + 关键文件）
  - 未修复问题清单（文件/规则/原因）
  - 人工修复优先级（P0/P1/P2）

### 自动修复策略（保守优先）

- 优先自动修复：可安全、低风险、可回滚问题（如 `F401` / `F541` / `E401`）。
- 不强行自动修复：高风险或语义不确定问题（如复杂异常语义、架构性调整、安全策略相关）。
- 对未自动修复项，必须在报告中明确“未修复原因 + 建议动作”。

## 常见失效模式与修复（实战排障）

### 失效模式 1：OpenClaw 回复“请你执行命令”

**现象**：回复中出现“我无法直接执行系统命令，请你执行以下命令”。  
**根因**：实际响应会话未命中 CMEC 路由规则（或走了 shared 全局人格但未配置 CMEC 硬约束）。

**修复动作**：

1. 在 `etf_main` 与 `code_maintenance_agent` 的 SOUL 写死：
   - 代码维护任务必须先走 CMEC；
   - 禁止“请用户执行命令”话术。
2. 在 `~/.openclaw/workspaces/shared/SOUL.md` 增加 CMEC 全局硬约束（防止非预期会话绕过）。
3. 复测同一任务，验收标准：
   - 不再出现人工代执行话术；
   - 生成并消费 `.handoff/task.md`、`.handoff/changes.diff`、`.handoff/result.md`；
   - 最终输出含“已执行/已修复/未修复/后续人工建议”四段。

### 失效模式 2：入口绑定到错误 Agent（常见且高影响）

**现象**：虽然 `etf_main` / `code_maintenance_agent` 已写 CMEC 规则，但实际对话仍输出“请你执行命令”。  
**根因**：通道绑定将消息入口直接指向了分析 Agent（如 `etf_analysis_agent`），导致主路由规则未生效。

**本项目已验证的关键检查点**：

- 检查 `~/.openclaw/openclaw.json` 的 `bindings`：
  - 若 `dingtalk` 默认入口绑定到 `etf_analysis_agent`，代码维护任务会高概率绕过 CMEC。
- 修复方式：
  - 将 `dingtalk/default` 入口绑定改为 `etf_main`；
  - 在 `analysis_agent` SOUL 增加“代码维护任务强制转派 CMEC”的兜底条款。

**验收方式**：

1. 重启 OpenClaw（使 bindings 生效）；
2. 发送代码维护任务；
3. 验收“无人工命令清单 + 有 `.handoff/result.md` 回执 + 四段式交付”。
