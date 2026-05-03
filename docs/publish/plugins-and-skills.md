# 第三方插件与技能（Skills）说明

## 目标

明确“必须安装”和“可选增强”，避免因为技能缺失导致能力不一致。

## 1. 必须项（建议首发最小集）

- OpenClaw 基础运行能力（gateway/node）
- 本项目插件：`option-trading-assistant`
- 通知通道（至少一种）：Feishu 或 DingTalk

## 2. 建议项（能力增强）

- **`openclaw-data-china-stock`**（A 股/ETF 等采集与情绪四工具 + `market-sentinel`）：安装、同步到 `~/.openclaw/extensions`、与 `etf-options-ai-assistant` Agent/工具白名单对齐见 [`openclaw-data-china-stock-etf-assistant.md`](../openclaw/openclaw-data-china-stock-etf-assistant.md)。**契约与宿主集成真源**：[`docs/integration/plugin_assistant_integration_plan.md`](../integration/plugin_assistant_integration_plan.md)（含 `plugins/data_collection` 符号链接、`china_stock_upstream`、L4 只读 API、`OPTION_TRADING_ASSISTANT_DEBUG_PLUGIN_CATALOG` 等）。
- `tavily-search`：外部信息检索与事件补全
- `topic-monitor`：主题监控（如已采用）
- `qmd-cli` / 记忆相关技能：研究上下文沉淀

## 2b. 进化流水线（可选，跑 `*_evolution_on_demand` / CI 修复类工作流时需要）

第三方 Skill 安装在 **`~/.openclaw/skills/`** 或 **`~/.openclaw/workspaces/shared/skills/`**（以本机 workspace 为准，**同一技能只需在其一存在**）：

- `capability-evolver`
- `agent-team-orchestration`
- `github`（不少环境仅装在 `workspaces/shared/skills`）

**自检**：`docs/getting-started/third-party-skills.md` → 章节「进化流水线必备」中的 shell 片段；可选运行 `bash scripts/check_third_party_skills.sh`（Optional 段含上述技能）。

**本仓库自研 Skill**：只放在仓库 `skills/<name>/`，改完后在仓库根执行 `bash scripts/sync_repo_skills_to_openclaw.sh` 再重载 Gateway；详见 `skills/README.md`。

**叙事类（与工具解耦）**：默认不在 Python 内二次调用 LLM（合并后配置 → `llm_enhancer.enabled: false`）。晨报/波动/信号的可读解读依赖 Gateway 主模型 + `ota_openclaw_tool_narration`、`ota_volatility_prediction_narration`、`ota_signal_watch_narration`；**历史已实现波动**（`tool_calculate_historical_volatility` / `tool_underlying_historical_snapshot`）与预测类工具区分见 **`ota_historical_volatility_snapshot`**；**单标的风险评估**（`tool_assess_risk`，ETF/指数/A 股、合并后配置 → `risk_assessment`）见 **`ota_risk_assessment_brief`**；**盘后/盘前/开盘趋势三工具**另需 **`ota_trend_analysis_brief`**（`report_meta` / `daily_report_overlay` / 落盘 / `after_close_basis` 等边界）。**A 股多因子选股**（`tool_screen_equity_factors` 或与 **`tool_screen_by_factors`** 等价入口，`success`/quality/degraded 契约；夜盘收尾 `tool_finalize_screening_nightly`）见 **`ota_equity_factor_screening_brief`**；**轮动 / 策略研究闭环**分别见 **`ota_etf_rotation_research`**、**`ota_strategy_research_loop`**——**`etf_main` 与 `etf_business_core_agent` 应与 `etf_analysis_agent` 一并勾选**，避免入口会话缺规程。以上勾选见 `config/snippets/openclaw_agents_ota_skills.json`。若定时任务只跑工具、无 Agent 总结步骤，推送正文可能仅有结构化片段——应在工作流中保留「模型生成摘要」一步。

## 3. 安装/校验建议

先看技能清单：

- `docs/getting-started/third-party-skills.md`

**本项目插件 `option-trading-assistant`（仓库即扩展）**：在 OpenClaw 2026.4.x 上，请在克隆本仓库后于仓库根执行一次 `./scripts/setup_openclaw_option_trading_assistant.sh`，再重启 Gateway。该脚本会把本仓库绝对路径写入 `plugins.load.paths`，并默认去掉 `~/.openclaw/extensions/option-trading-assistant` 下指向同一仓库的符号链接，避免「仅 symlink 时 `plugins.allow` 报 plugin not found」或重复加载。详见 `docs/openclaw/OpenClaw配置指南.md` 与 `scripts/README.md`。

安装后验收：

- `openclaw doctor` 中插件/skills 无报错
- `openclaw plugins list` 中出现 `option-trading-assistant`
- 关键工作流可完整跑通（含通知）

可选：`VERIFY_OTA_LOAD_PATHS=1 bash scripts/verify_openclaw_config.sh` 校验本机 `openclaw.json` 是否已包含仓库路径。

## 4. 发布建议

- 在 README 中公开“最小依赖集合”
- 第三方技能版本尽量固定，减少漂移
- 升级技能后执行一次回归检查（至少跑 1 条主工作流）
