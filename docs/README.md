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

## 2. 使用指南（User Guide）

聚焦“怎么用”：

- 工作流与调度：
  - `docs/openclaw/工作流参考手册.md`
- 信号与风控巡检：
  - `docs/openclaw/信号与风控巡检工作流.md`
- 通知与日报：
  - 结合工具参考手册与相关工作流文档

更细的主题导航见：`docs/user-guide/README.md`。

---

## 3. OpenClaw 集成（Integration）

面向需要在 OpenClaw 中部署与维护本项目的用户：

- 当前可用运行文档：
  - `docs/openclaw/工作流参考手册.md`
  - `docs/openclaw/信号与风控巡检工作流.md`
- 历史配置/集成文档已归档至：
  - `docs/archive/openclaw/`（不纳入发布清单）

本专题索引见：`docs/openclaw/README.md`。

---

## 4. 工具与协议参考（Reference）

当你需要查某个工具的参数、返回值或错误码时使用：

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

## 5. 架构与开发（Architecture）

面向二次开发者和代码审阅者：

- `docs/PROJECT_LAYOUT.md`：项目目录结构与关键模块说明
- `docs/architecture/架构与工具审查报告.md`：架构审查与优化建议
- `tests/README.md`：pytest 与集成/手工测试脚本说明（`tests/integration/`、`tests/manual/`）
- `scripts/README.md`：运维、发布门禁、预警等 `scripts/` 脚本说明

索引见：`docs/architecture/README.md`。

---

## 6. 运维与排错（Ops）

包含常见问题、风险控制与回滚、钉钉/飞书连接排查等：

- `docs/ops/常见问题库.md`
- `docs/ops/RISK_CONTROL_AND_ROLLBACK.md`
- 以及其他 ops 相关文档（如交易日跳过参数清单等）

索引见：`docs/ops/README.md`。

---

## 7. 历史归档（Legacy）

`docs/legacy/` 下保留了历史设计文档、迁移方案与测试报告，仅供参考：

- 历史架构思路
- 早期实施计划
- 各类测试报告 / 草稿

注：`legacy` 文档中可能保留早期“期权优先”表述，不代表当前项目主线；当前主线以 A股 / ETF 为准。

说明见：`docs/legacy/README.md`。
