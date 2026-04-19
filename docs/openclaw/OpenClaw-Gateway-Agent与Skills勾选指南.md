# OpenClaw Gateway：Agent 与 `ota-*` Skills 勾选指南

> **Web UI**：技能总览与勾选通常在 Gateway 控制台 **Skills** 页，例如 [http://127.0.0.1:18789/skills](http://127.0.0.1:18789/skills)（与 `http://localhost:18789/skills` 等价，视本机绑定而定）。  
> **真源**：Agent 最终加载的列表以 **`~/.openclaw/openclaw.json`** 中 **`agents.defaults.list[]`**（不是 `agents.list`）各条目的 **`skills`** 为准；修改后需 **重启 Gateway**（或按控制台提示重载）。  
> **同内容简表**：[`OpenClaw-Agent-ota-skills.md`](./OpenClaw-Agent-ota-skills.md)。

---

## 1. Skill 在配置里写什么名字？

OpenClaw 按每个 Skill 的 **`SKILL.md` 前置元数据里的 `name:`** 过滤（与目录名 `ota-xxx` 的 kebab-case **不同**）。  
本仓库自研包一律为 **`ota_` + 蛇形命名**，例如：

| 目录（磁盘 / rsync 目标） | `openclaw.json` / UI 勾选应填的 `name` |
|---------------------------|----------------------------------------|
| `skills/ota-strategy-fusion-playbook/` | `ota_strategy_fusion_playbook` |

完整列表见 **[`skills/README.md`](../../skills/README.md)**。

---

## 2. 按 Agent 特点勾选 `ota-*`（推荐组合）

以下与 **`config/snippets/openclaw_agents_ota_skills.json`** 一致，便于复制核对。

| Agent `id` | 角色 | 建议勾选的 `ota-*`（及常见第三方） |
|------------|------|-------------------------------------|
| **`etf_main`** | 总编排、日程、巡检、融合入口 | `ota_daily_session_routine`、`ota_signal_risk_inspection`、`ota_strategy_fusion_playbook`、`ota_volatility_range_brief`、`ota_technical_indicators_brief`、`ota_trend_analysis_brief`、`ota_openclaw_tool_narration`、`ota_volatility_prediction_narration`、`ota_historical_volatility_snapshot`、`ota_risk_assessment_brief`、`ota_signal_watch_narration`、`ota_notification_soul_routing`、`ota_market_regime_checklist`、`ota_etf_rotation_research`、`ota_strategy_research_loop`、`ota_equity_factor_screening_brief`；可选 `tavily`、`topic-monitor`、`qmd` |
| **`etf_data_collector_agent`** | 采集 / 域选择 / 降级 | `ota_cn_market_data_discipline`、`ota_cache_read_discipline` |
| **`etf_analysis_agent`** | 分析、轮动与研究延展 | `ota_openclaw_tool_narration`、`ota_volatility_prediction_narration`、`ota_historical_volatility_snapshot`、`ota_risk_assessment_brief`、`ota_signal_watch_narration`；以及 `ota_strategy_fusion_playbook`、`ota_volatility_range_brief`、`ota_technical_indicators_brief`、`ota_trend_analysis_brief`、`ota_cache_read_discipline`、`ota_market_regime_checklist`、`ota_daily_session_routine`、`ota_etf_rotation_research`、`ota_strategy_research_loop`、`ota_equity_factor_screening_brief`；可选 `tavily`、`topic-monitor`、`qmd` |
| **`etf_notification_agent`** | 飞书/钉钉结构与 SOUL | `ota_notification_soul_routing`、`ota_volatility_range_brief`、`ota_trend_analysis_brief`、`ota_openclaw_tool_narration`、`ota_volatility_prediction_narration`、`ota_signal_watch_narration`、`ota_signal_risk_inspection`、`ota_risk_assessment_brief`、`ota_market_regime_checklist`、`ota_historical_volatility_snapshot` |
| **`etf_business_core_agent`** | 业务核：信号 + 风控 + 融合 | `ota_openclaw_tool_narration`、`ota_volatility_prediction_narration`、`ota_historical_volatility_snapshot`、`ota_risk_assessment_brief`、`ota_signal_watch_narration`；以及 `ota_strategy_fusion_playbook`、`ota_signal_risk_inspection`、`ota_daily_session_routine`、`ota_volatility_range_brief`、`ota_technical_indicators_brief`、`ota_trend_analysis_brief`、`ota_market_regime_checklist`、`ota_cache_read_discipline`、`ota_etf_rotation_research`、`ota_strategy_research_loop`、`ota_equity_factor_screening_brief`；可选 `tavily`、`topic-monitor`、`qmd` |
| **`ops_agent`** | 运维 / Token / 路由 | `ota_openclaw_token_discipline`、`ota_llm_model_routing`、`ota_cmec_collaboration` |
| **`code_maintenance_agent`** | 进化 / CI / CMEC | `ota_evolution_execution_contract`、`ota_ci_autofix_runbook`、`ota_cmec_collaboration`、`ota_openclaw_token_discipline` |

**说明**：

- **不要**把 `ota_evolution_execution_contract` 绑在纯交易巡检 Agent 上，避免与盘中风控规程混用。  
- 第三方技能名称以 **本机已安装包** 为准；若 UI 显示为 `tavily-search` 等，以 `openclaw doctor` / 技能目录实际为准并改 JSON。

---

## 3. 操作流程建议

1. 确认已执行 **`bash scripts/sync_repo_skills_to_openclaw.sh`**，且 `~/.openclaw/skills/`（或 shared skills）下存在各 `ota-*` 目录与 `SKILL.md`。  
2. 打开 [http://127.0.0.1:18789/skills](http://127.0.0.1:18789/skills) 浏览已发现技能。  
3. 在 **Agent 配置**（同一控制台或 `openclaw.json`）中按上表勾选 / 粘贴 `skills` 数组。  
4. **重启 Gateway**，对新会话执行 `openclaw doctor` 或试跑一条主工作流。

若 Web UI 与 JSON 冲突，以合并后的 **`openclaw.json`** 为准并重新保存。

---

## 4. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-04 | 初版：与 `openclaw.json` 及 `config/snippets/openclaw_agents_ota_skills.json` 对齐 |
| 2026-04-04 | 增加 `ota_openclaw_tool_narration`、`ota_volatility_prediction_narration`、`ota_signal_watch_narration`（替代进程内 `llm_enhancer` 叙事） |
| 2026-04-04 | 增加 `ota_technical_indicators_brief`（`tool_calculate_technical_indicators`：pandas_ta / legacy、配置与依赖口径） |
| 2026-04-04 | 增加 `ota_trend_analysis_brief`（三工具趋势分析、`report_meta`、落盘、`trend_analysis_plugin`、A50/HXC 仅盘前） |
| 2026-04-05 | `etf_main` / `etf_business_core_agent` 对齐分析向 Skill：`ota_etf_rotation_research`、`ota_strategy_research_loop`、`ota_equity_factor_screening_brief`；`etf_notification_agent` 增加 `ota_market_regime_checklist`、`ota_historical_volatility_snapshot`；新增包 `ota-equity-factor-screening-brief`（替代已 deprecated 的 `ota-quantitative-screening-brief`） |
