# Agent 配置

本目录包含 OpenClaw Agent 配置文件。

## Agent 列表

1. **data_collector_agent.yaml** - 数据采集 Agent（工具白名单与 `plugins/data_collection` / `config/tools_manifest.yaml` 对齐，含合并入口 `tool_fetch_*_data`、`tool_read_market_data`、`tool_fetch_sector_data` 等）
2. **analysis_agent.yaml** - 分析 Agent（含 **tool_strategy_engine** 与定时 **strategy_fusion**，见 `config/openclaw_strategy_engine.yaml`）
3. **notification_agent.yaml** - 通知 Agent

## 配置说明

- **OpenClaw 插件注册**：项目根 `index.ts` 会加载 `config/tools_manifest.json` 中的全部工具（修改 `tools_manifest.yaml` 后请执行 `python scripts/generate_tools_json.py`）。
- **本目录 Agent**：若 OpenClaw 支持按 Agent 限制可用工具，请将 `data_collector_agent` 与上表同步维护。
- **Gateway 运行时**：各 Agent 的 **Skills 勾选** 与 `~/.openclaw/openclaw.json` 中 `agents.defaults.list[].skills` 维护；自研 **`ota_*`** 对照表与 Web UI（如 `http://127.0.0.1:18789/skills`）说明见 [`docs/openclaw/OpenClaw-Gateway-Agent与Skills勾选指南.md`](../docs/openclaw/OpenClaw-Gateway-Agent与Skills勾选指南.md)，可复制片段 [`config/snippets/openclaw_agents_ota_skills.json`](../config/snippets/openclaw_agents_ota_skills.json)。  
- **趋势三工具**：`analysis_agent.yaml` 对应 Gateway 上多为 **`etf_analysis_agent`**，须在 `skills` 中勾选 **`ota_trend_analysis_brief`**（与同片段中的 **`etf_main`**、**`etf_business_core_agent`**、**`etf_notification_agent`** 一致）；纯采集的 **`etf_data_collector_agent`** 无需此项。  
- **工作流**：`workflows/*.yaml` 不因 Skill 而必改；Skill 与 Cron 的衔接说明见 [`docs/openclaw/OpenClaw-Agent-ota-skills.md`](../docs/openclaw/OpenClaw-Agent-ota-skills.md)。
- 其余细节需与 OpenClaw 实际格式对齐时，请参考 OpenClaw 官方文档。

## 定时任务配置

- 盘后分析：15:30（工作日）
- 盘前分析：9:15（工作日）
- 开盘分析：9:28（工作日）
- 日内波动区间：每30分钟（交易时间内）
- 信号生成：每5分钟（交易时间内）
- **策略融合**：每30分钟（交易时间内，`tool_strategy_engine`）
- 数据采集：9:30, 10:00, 11:00, 13:00, 14:00, 15:00
