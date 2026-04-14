# OpenClaw Agent 与 `ota-*` Skill 绑定

> **配置真源（本机）**：`~/.openclaw/openclaw.json` → **`agents.defaults.list[]`** 每项的 **`skills`** 字段（allowlist：仅加载列出的 Skill）。  
> **注意**：路径是 **`agents.defaults.list`**，不是顶层的 `agents.list`。  
> **字符串**须与各包 `SKILL.md` 中 YAML frontmatter 的 **`name:`** 一致（下划线形式，如 `ota_strategy_fusion_playbook`）；与目录名 `ota-strategy-fusion-playbook` 不同。  
> **Gateway 控制台**：浏览器打开 [http://localhost:18789/skills](http://localhost:18789/skills)（端口以 `gateway` 配置为准，默认 **18789**）；**Agent 页**（如 `/agents`）按 Agent 勾选须与下表及 JSON 一致，改后点 **Save**。  
> **Skill 源**：仓库 [`skills/README.md`](../../skills/README.md)；改完后执行 `bash scripts/sync_repo_skills_to_openclaw.sh` 并重载 Gateway。  
> **与下列文档一致**：[`OpenClaw-Gateway-Agent与Skills勾选指南.md`](./OpenClaw-Gateway-Agent与Skills勾选指南.md)、[`config/snippets/openclaw_agents_ota_skills.json`](../../config/snippets/openclaw_agents_ota_skills.json)。仓库检核时可将本机 `openclaw.json` 中各 Agent 的 `skills` 与 snippet **逐字比对**。

## 绑定表（按 Agent `id`）

下列 **`skills` 数组**与当前本机 `~/.openclaw/openclaw.json`（`agents.defaults.list`）及 **`config/snippets/openclaw_agents_ota_skills.json`** 对齐。

### `etf_main`

`ota_daily_session_routine`, `ota_signal_risk_inspection`, `ota_strategy_fusion_playbook`, `ota_volatility_range_brief`, `ota_technical_indicators_brief`, `ota_trend_analysis_brief`, `ota_openclaw_tool_narration`, `ota_volatility_prediction_narration`, `ota_historical_volatility_snapshot`, `ota_risk_assessment_brief`, `ota_signal_watch_narration`, `ota_notification_soul_routing`, `ota_market_regime_checklist`, `ota_etf_rotation_research`, `ota_strategy_research_loop`, `ota_quantitative_screening_brief`, `tavily`, `topic-monitor`, `qmd`

### `etf_data_collector_agent`

`ota_cn_market_data_discipline`, `ota_cache_read_discipline`

### `etf_analysis_agent`

`ota_strategy_fusion_playbook`, `ota_volatility_range_brief`, `ota_technical_indicators_brief`, `ota_trend_analysis_brief`, `ota_openclaw_tool_narration`, `ota_volatility_prediction_narration`, `ota_historical_volatility_snapshot`, `ota_risk_assessment_brief`, `ota_signal_watch_narration`, `ota_cache_read_discipline`, `ota_market_regime_checklist`, `ota_daily_session_routine`, `ota_etf_rotation_research`, `ota_strategy_research_loop`, `ota_quantitative_screening_brief`, `tavily`, `topic-monitor`, `qmd`

### `etf_notification_agent`

`ota_notification_soul_routing`, `ota_volatility_range_brief`, `ota_trend_analysis_brief`, `ota_openclaw_tool_narration`, `ota_volatility_prediction_narration`, `ota_signal_watch_narration`, `ota_signal_risk_inspection`, `ota_risk_assessment_brief`, `ota_market_regime_checklist`, `ota_historical_volatility_snapshot`

### `etf_business_core_agent`

`ota_strategy_fusion_playbook`, `ota_signal_risk_inspection`, `ota_daily_session_routine`, `ota_volatility_range_brief`, `ota_technical_indicators_brief`, `ota_trend_analysis_brief`, `ota_openclaw_tool_narration`, `ota_volatility_prediction_narration`, `ota_historical_volatility_snapshot`, `ota_risk_assessment_brief`, `ota_signal_watch_narration`, `ota_market_regime_checklist`, `ota_cache_read_discipline`, `ota_etf_rotation_research`, `ota_strategy_research_loop`, `ota_quantitative_screening_brief`, `tavily`, `topic-monitor`, `qmd`

### `ops_agent`

`ota_openclaw_token_discipline`, `ota_llm_model_routing`, `ota_cmec_collaboration`, `ota_chart_console_pro`

### `code_maintenance_agent`

`ota_evolution_execution_contract`, `ota_ci_autofix_runbook`, `ota_cmec_collaboration`, `ota_openclaw_token_discipline`, `ota_chart_console_pro`

## 覆盖性（24 个自研 `ota_*`）

以下每个 **`name:`** 至少在 **一个** Agent 的 `skills` 中出现：

`ota_cache_read_discipline`, `ota_chart_console_pro`, `ota_ci_autofix_runbook`, `ota_cmec_collaboration`, `ota_cn_market_data_discipline`, `ota_daily_session_routine`, `ota_etf_rotation_research`, `ota_evolution_execution_contract`, `ota_historical_volatility_snapshot`, `ota_llm_model_routing`, `ota_market_regime_checklist`, `ota_notification_soul_routing`, `ota_openclaw_tool_narration`, `ota_openclaw_token_discipline`, `ota_quantitative_screening_brief`, `ota_risk_assessment_brief`, `ota_signal_risk_inspection`, `ota_signal_watch_narration`, `ota_strategy_fusion_playbook`, `ota_strategy_research_loop`, `ota_technical_indicators_brief`, `ota_trend_analysis_brief`, `ota_volatility_prediction_narration`, `ota_volatility_range_brief`

## 修改后

1. 编辑 `~/.openclaw/openclaw.json` 对应 **`agents.defaults.list[]`** 条目的 `skills`（或仅在 UI 中调整，若你的版本会回写该文件）。  
2. `python3 -m json.tool ~/.openclaw/openclaw.json` 校验 JSON。  
3. **重启 Gateway**，再打开 Agent 技能页确认开关与 **Save** 后状态一致。

## 说明

- **Allowlist**：未写入 `skills` 的已安装 Skill **不会**注入该 Agent。  
- **第三方**：`etf_main` / `etf_analysis_agent` / `etf_business_core_agent` 已含 `tavily`、`topic-monitor`、`qmd`（以本机包 `name:` 为准）。  
- **进化类第三方**（`github`、`agent-team-orchestration`、`capability-evolver` 等）：若某 Agent 需要，须在对应 `skills` 数组中 **追加** 各包 `SKILL.md` 的 `name:`。详见 [`third-party-skills.md`](../getting-started/third-party-skills.md)。

---

## 与「工作流 / 仓库 Agent YAML / 日常交互」是否要改？

| 层面 | 是否要因 `ota-*` Skill 而改 | 说明 |
|------|----------------------------|------|
| **`workflows/*.yaml`** | **一般不必** | 步骤里写的是 **`tool`** 名与参数；Skill 不改变工具契约。若某条工作流**强依赖**模型按固定顺序解读（如巡检铁律），逻辑已在 YAML 文本或 `docs/openclaw/*`；`ota-signal-risk-inspection` 等与文档同源，**无需在 YAML 里重复列 Skill 名**。 |
| **仓库 `agents/*.yaml`** | **不强制** | 该目录主要是 **工具白名单 + 定时任务名** 的参考/历史对齐；OpenClaw 运行时以 **`openclaw.json` 的 `agentDir` + Gateway 工具注册** 为准。可选在注释中指向本文，避免读者以为「只改 YAML 就能加载 Skill」。 |
| **`~/.openclaw/agents/.../SOUL.md` / `WORKFLOW.md`** | **可选** | 若希望子 Agent 会话**显式提醒**「已加载 ota_*」，可加一句并链到本文；**不是**加载 Skill 的必要条件（加载由 **`openclaw.json` + Gateway UI Save** 决定）。 |
| **`Prompt_config.yaml`** | **legacy（llm_enhancer）** | 头部已标明与 `ota_*_narration` Skill 对照；默认不在进程内读此文件生成用户可见摘要。策略路由等其它用途仍以 manifest / 架构文档为准。 |
| **Cron `jobs.json`** | **一般不必** | 绑定的是 **Agent / 工作流 id**，不直接列 Skill。改 Skill allowlist 后**无需**改 Cron，除非换了 Agent。 |
| **日常聊天 / 钉钉 / 飞书** | **建议核对** | 入口 Agent（多为 **`etf_main`**）须在 **`openclaw.json` + UI** 中启用对应 `ota_*`，否则模型少了规程但仍可调工具；体验上可能「能跑但口径飘」。 |

**Skill 变更后的最小检查单**：`sync_repo_skills_to_openclaw.sh` → 重启 Gateway → `openclaw.json` 与 [`config/snippets/openclaw_agents_ota_skills.json`](../../config/snippets/openclaw_agents_ota_skills.json) 一致 → Agent 页 **Save** 与 JSON 一致 → 抽一条主工作流或对话 smoke。
