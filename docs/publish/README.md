# 发布版文档入口（Publish Docs）

本目录面向“准备部署并稳定运行”的用户，重点解决以下高频问题：

默认业务定位：A股 / ETF 交易辅助（期权能力按需启用，不作为默认主叙事）。
命名兼容说明：仓库名保留为 `etf-options-ai-assistant`，用于兼容既有自动化脚本与路径约定。

- OpenClaw 如何部署本交易助手
- 环境变量如何分层配置（项目 vs 平台）
- 本地 Ollama 及模型如何安装与校验
- 哪些第三方插件/技能必须安装，分别做什么
- OpenClaw 服务如何启动、重启、排障

## 推荐阅读顺序（首次部署）

1. `deployment-openclaw.md`（部署总流程）
2. `env-vars.md`（环境变量规范与模板）
3. `ollama-and-models.md`（Ollama 与模型准备）
4. `plugins-and-skills.md`（第三方插件/技能依赖）
5. `service-ops.md`（服务启停与故障排查）

## 与现有文档关系

- 本目录是“可执行主线”
- 历史文档统一在 `docs/archive/openclaw/` 与 `docs/legacy/` 查阅（不纳入发布清单）
- 运行细节补充可参考：
  - `docs/openclaw/工作流参考手册.md`
  - `docs/ops/常见问题库.md`
  - `docs/getting-started/third-party-skills.md`
