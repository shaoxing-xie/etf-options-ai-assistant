# 开盘行情分析 → 机构晨报水平：对标与分阶段落地

> 与 `docs/openclaw/工作流参考手册.md`「开盘行情分析输出规范」配套；用于排期与 scope 划分（**自动进化可改** vs **须人工 PR**）。

## 1. 产物与路径（诊断时勿写错）

| 说明 | 路径 |
|------|------|
| 盘前/趋势落盘（配置键 `before_open_dir`） | `data/trend_analysis/before_open/`（**不是** `workflows/data/...`） |
| 工作流定义 | `workflows/before_open_analysis.yaml`、`workflows/before_open_analysis_enhanced.yaml`、`workflows/opening_analysis.yaml` |
| Cron / 执行痕迹 | `~/.openclaw/cron/jobs.json`、`~/.openclaw/cron/runs/*.jsonl` |
| 本规范与路线图 | `docs/research/**`（**allowed_paths**，可经 `ai-evolve/report-*` PR 修改） |

## 2. 目标分层

- **文档层（MVP）**：固定章节、免责、元数据字段、与 `docs/openclaw/工作流参考手册.md` 对齐——**不依赖新采集**即可先统一「长什么样」。
- **分析层**：在 `plugins/analysis/**` 内增强汇总/模板（**allowed_paths**），把已有工具输出组装成晨报结构。
- **数据层**：美股/商品/结构化新闻/滚动推送等——多涉及 **`plugins/data_collection/**`、`scripts/**`**（多为 **evolver denied_paths**），须**单独工程任务**与人工 PR，**不能**指望仅「确认阶段二」文档演化一次完成。

## 3. 分阶段建议（与钉钉诊断对齐）

| 阶段 | 内容 | 主要落点 | 典型风险 |
|------|------|----------|----------|
| P0-A | 输出规范、章节骨架、免责与 `EVIDENCE_REF` 可追溯 | `docs/openclaw/**`、`docs/research/**` | 低 |
| P0-B | 在现有工具范围内补全「隔夜外盘摘要、要闻列表」等（若已有 tavily/全球指数等） | `plugins/analysis/**`、`config.yaml` 白名单键 | 中 |
| P1 | 北向/资金面等：**先确认** `tool_fetch_northbound_flow` 在开盘链路已挂载且可用 | `tool_runner`、Agent 工具列表、工作流 YAML | 中 |
| P2 | 新采集、新脚本、多 channel 滚动 | `data_collection`、`scripts`、通知 | 高，需专项评审 |

## 4. 工具与事实核对（实施前必查）

- **`tool_fetch_northbound_flow`**：已在 `config/tools_manifest.yaml` / `tool_runner` 注册；是否接入**开盘**工作流需 **grep 工作流与 `trend_analyzer`** 实测。
- **`tool_fetch_global_index_spot`** 等：以当前 `tools_manifest` 为准，诊断中不得虚构未注册工具名。

## 5. OpenClaw 拍 A / 拍 B 与 8 行键值

- **拍 A**（只诊断）：末尾仍须 **ORCH_STATUS、FAILURE_CODES、RISK、AUTOFIX_ALLOWED、PR_CREATED、PR_REF、EVIDENCE_REF、TOP_ACTIONS**（见 `config/evolution_invariants.yaml` → `user_facing.chained_report_diagnosis_to_doc_pr.phase_a_machine_block`），**禁止**仅用 `DIAGNOSIS_STAGE` 等替代字段。
- **拍 B**（确认后改文档）：须有 **git diff 或 PR_REF**；禁止仅建议无改动（见 `phase_b_closure`）。单条消息末带 **【实跑确认】** 时可在同一回合内拍完 A 再拍 B。

## 6. 何谓「优化闭环」（避免只诊断不疼）

| 情况 | 是否算已优化 |
|------|----------------|
| 仅有长文诊断、`DIAGNOSIS_STAGE` 或非标准 8 键 | **否** |
| 拍 A 结束 | **否**（只读） |
| 拍 B：**git 可见 diff** 或 **PR_REF** 指向 `ai-evolve/report-*`，且改的是 `docs/research/**` 或 `docs/openclaw/**` | **是（文档层）** |
| 采集/工作流/通知代码变更 | **须**单独开发 PR（多半不在自动进化 allow-list） |

若已发「确认阶段二」仍无 PR：检查 Agent 是否挂载 **写仓库 + gh**、`etf_main` 是否贴齐 **预检片段**、钉钉路由是否到 **`etf_main`**；模型须输出 **`AUTOFIX_BLOCKED_ENV`** 而非伪成功。

## 7. 修订记录

- 2026-03-28：初稿，承接钉钉诊断与仓库 evolver_scope 边界。
- 2026-03-28：§6 闭环说明。
