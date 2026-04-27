# 文档总览

本目录包含 `etf-options-ai-assistant` 的全部文档，面向三类读者：

> 命名兼容说明：仓库名 `etf-options-ai-assistant` 保留用于兼容历史脚本与部署路径，不代表当前业务主线；当前主线为 A股 / ETF，期权为可选扩展。

- **使用者**：想在 OpenClaw 中使用本助手做 A股 / ETF 研究与日常分析的人；
- **OpenClaw 运维 / 配置者**：负责 Gateway、Agent、Cron 工作流与插件部署的人；
- **开发者 / 贡献者**：希望阅读、修改、扩展本项目代码与工具的人。

推荐阅读入口如下。

---

## 1. 入门（Getting Started）

适合首次接触本项目的使用者和运维：

- `docs/getting-started/README.md`：入门总览与阅读顺序
- `docs/getting-started/third-party-skills.md`：第三方 SKILL（技能包）依赖清单与安装验证
- `docs/overview/5分钟快速开始指南.md`：5 分钟完成环境检查、插件安装与首个工作流运行

---

## 1.5 发布与部署主线（强烈推荐）

如果你关注“如何稳定部署与运行”，优先阅读：

- `docs/publish/README.md`
- `docs/publish/deployment-openclaw.md`
- `docs/publish/env-vars.md`
- `docs/publish/ollama-and-models.md`
- `docs/publish/plugins-and-skills.md`
- `docs/publish/service-ops.md`

---

## 2. 三 Skill 自动化进化（研究 / 工程迭代）

> **状态**：`docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md` 所述能力已在仓库**实施并完成验证**（GitHub PR 约束 + Builder/Reviewer 编排 + Evolver 复盘 + 质量兜底与 CI 分流）。

**核心思想**：在**固定边界**内让「分析、策略、研究文档」持续改进——**允许路径**内可证据化自动 PR；**数据采集、通知、`scripts/`、`.github/`** 等默认不自动改代码，只能 Issue/人工或运维脚本处理。

**必读配置与契约**：

| 文件 | 作用 |
|------|------|
| `config/evolution_invariants.yaml` | 不变量：三角色顺序、四段证据、Reviewer 门禁、Orchestrator 输出键等 |
| `config/evolver_scope.yaml` | `allowed_paths` / `denied_paths` |
| `docs/openclaw/execution_contract.md` | 执行契约与失败码 |

**入口文档**：`docs/openclaw/三Skill驱动ETF研究自动进化实施方案.md`  
**工作流目录**：`workflows/`（`*_evolution_on_demand.yaml`、`quality_backstop_audit.yaml`、`ci_autofix_triage_on_demand.yaml` 等）  
**预测与质量闭环**（与进化配套）：合并后配置 `prediction_quality` / `prediction_monitoring`（来源：`config/domains/risk_quality.yaml`）、`scripts/verify_predictions.py`、`scripts/prediction_metrics_weekly.py`；详见根目录 `README.md` 与 `config/openclaw_strategy_engine.yaml`。

---

## 3. 使用指南（User Guide）

聚焦“怎么用”：

- 工作流与调度：
  - `docs/openclaw/工作流参考手册.md`
- 信号与风控巡检：
  - `docs/openclaw/信号与风控巡检工作流.md`
- **策略引擎与多路信号融合**（`tool_strategy_engine`）：
  - `docs/architecture/strategy_engine_and_signal_fusion.md`
  - `config/openclaw_strategy_engine.yaml`、`workflows/strategy_fusion_routine.yaml`
  - 仓库 `agents/analysis_agent.yaml` 中 **`strategy_fusion`**：交易时段 **每 30 分钟**；本机 OpenClaw 以 `~/.openclaw/cron/jobs.json` 为准
- 通知与日报：
  - 结合工具参考手册与相关工作流文档

更细的主题导航见：`docs/user-guide/README.md`。

---

## 4. OpenClaw 集成（Integration）

面向需要在 OpenClaw 中部署与维护本项目的用户：

- 当前可用运行文档：
  - `docs/openclaw/工作流参考手册.md`
  - `docs/openclaw/信号与风控巡检工作流.md`
- 历史配置/集成文档已归档至：
  - `docs/archive/openclaw/`（不纳入发布清单）

本专题索引见：`docs/openclaw/README.md`。

---

## 5. 工具与协议参考（Reference）

当你需要查某个工具的参数、返回值或错误码时使用：

- **策略融合工具**：`tool_strategy_engine` — 见 `docs/reference/工具参考手册.md` 与 `config/tools_manifest.yaml`

- **数据采集插件的分类与 Provider 约定**：`plugins/data_collection/README.md`、`plugins/data_collection/ROADMAP.md`\n+  - 注：该目录在部分部署形态中为指向 OpenClaw 扩展（如 `openclaw-data-china-stock`）的符号链接；若你是纯 clone 本仓库且未安装扩展，请先按 `docs/publish/plugins-and-skills.md` 完成扩展安装/链接，再阅读该索引。
- `docs/reference/工具参考手册.md`
- `docs/reference/工具参考手册-速查.md`
- `docs/reference/工具参考手册-场景.md`
- `docs/reference/工具参考手册-研究涨停回测.md`
- `docs/reference/错误码说明.md`
- `docs/reference/trading_journal_schema.md`
- `docs/reference/limit_up_pullback_default_params.md`
- `docs/reference/akshare/README.md`：AKShare 接口说明（本地镜像索引）

更多内容见：`docs/reference/README.md`。

---

## 6. 架构与开发（Architecture）

面向二次开发者和代码审阅者：

- `docs/PROJECT_LAYOUT.md`：项目目录结构与关键模块说明
- `docs/architecture/strategy_engine_and_signal_fusion.md`：策略引擎与信号融合（含 OpenClaw / 本机 Cron 约定）
- `docs/architecture/架构与工具审查报告.md`：架构审查与优化建议
- `tests/README.md`：pytest 与集成/手工测试脚本说明（`tests/integration/`、`tests/manual/`）
- `scripts/README.md`：运维、发布门禁、预警等 `scripts/` 脚本说明

索引见：`docs/architecture/README.md`。

---

## 7. 运维与排错（Ops）

包含常见问题、风险控制与回滚、钉钉/飞书连接排查等：

- `docs/ops/常见问题库.md`
- `docs/ops/市场数据源能力与调用建议.md`（数据源能力/限流特征/调用建议）
- `docs/ops/RISK_CONTROL_AND_ROLLBACK.md`（若该文件不存在，以 `docs/ops/` 目录实际内容为准）
- `docs/ops/cron_signal_inspection_triage.md`（信号+风控巡检 Cron 排错）
- 以及其他 ops 相关文档（如交易日跳过参数清单等）

索引见：`docs/ops/README.md`。

---

## 8. 研究与报告口径（Research）

- 索引：`docs/research/README.md`
- 每日市场报告章节基准：`docs/research/daily_market_report_web_benchmark.md`（配合 `workflows/daily_market_report.yaml`）
- 开盘晨报路线图：`docs/research/opening_morning_brief_roadmap.md`
- 预测融合试验：`docs/research/prediction_fusion_contract.md`

---

## 9. 历史归档（Legacy）

`docs/legacy/` 下保留了历史设计文档、迁移方案与测试报告，仅供参考：

- 历史架构思路
- 早期实施计划
- 各类测试报告 / 草稿

注：`legacy` 文档中可能保留早期“期权优先”表述，不代表当前项目主线；当前主线以 A股 / ETF 为准。

说明见：`docs/legacy/README.md`。
