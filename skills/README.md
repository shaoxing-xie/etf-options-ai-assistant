# 本仓库 Skill 源目录（仅项目自研）

本目录 **只存放本项目自行编写、版本随仓库发布的 Skill**（每个 Skill 为独立子目录，内含 `SKILL.md` 等）。

## 命名空间：`ota-*`

- **`ota`**：Option Trading Assistant（与插件 `option-trading-assistant` 对齐，避免与 Clawhub 全局 Skill 撞名）。
- 目录名 **kebab-case**，与 `_meta.json` 中 **`slug`** 一致；`SKILL.md`  frontmatter 的 **`name`** 为下划线形式（OpenClaw 常见约定）。

## 索引（自研 `ota-*` 包见下表；新增/删除子目录时请同步本表行数与 `docs/openclaw/OpenClaw-Agent-ota-skills.md` 覆盖性说明；版本标签 v0.1.0+）

| 目录 / slug | 场景 | 说明 |
|-------------|------|------|
| `ota-strategy-fusion-playbook` | A. 主链路 | 策略融合调用与解读 |
| `ota-signal-risk-inspection` | A. 主链路 | 信号与风控巡检铁律；钉钉快报与 `signal_risk_inspection.yaml` 对齐 |
| `ota-daily-session-routine` | A. 主链路 | 盘前/开盘/盘中/盘后工作流顺序 |
| `ota-volatility-range-brief` | A. 主链路 | 波动区间与快报字段口径 |
| `ota-openclaw-tool-narration` | A. 主链路 | 工具结果通用叙事（盘前/开盘/盘后/盘中）；**每日市场日报 `llm_summary`** 与盘后同构，见 SKILL 内专节 |
| `ota-technical-indicators-brief` | A. 主链路 | `tool_calculate_technical_indicators`：standard/legacy、指标与 config、依赖与叙事约束 |
| `ota-trend-analysis-brief` | A. 主链路 | 盘后/盘前/开盘三工具：`report_meta`、`daily_report_overlay`、落盘、`trend_analysis_plugin`；A50/HXC 仅盘前；`after_close_basis` |
| `ota-volatility-prediction-narration` | A. 主链路 | `tool_predict_volatility` 等解读约束 |
| `ota-historical-volatility-snapshot` | A. 主链路 | 单窗 `tool_calculate_historical_volatility` vs `tool_underlying_historical_snapshot`；与预测/区间工具 horizon 区分 |
| `ota-risk-assessment-brief` | A. 主链路 | `tool_assess_risk`：ETF/指数/A 股、HV 口径、合并后配置 → `risk_assessment`（域文件：`config/domains/risk_quality.yaml`）；与组合风控区分 |
| `ota-signal-watch-narration` | A. 主链路 | 信号巡检叙事与风险边界 |
| `ota-notification-soul-routing` | A. 主链路 | 钉钉/飞书工具分层、Runner 别名、`plugins/notification/README` |
| `ota-cn-market-data-discipline` | B. 数据 | A 股数据域与 Provider 降级 |
| `ota-cache-read-discipline` | B. 数据 | 本地缓存只读与路径约定 |
| `ota-etf-rotation-research` | C. 研究 | ETF 轮动研究工作流 |
| `ota-strategy-research-loop` | C. 研究 | 策略研究闭环 |
| `ota-evolution-execution-contract` | D. 进化 | 执行契约摘要（长文见 docs） |
| `ota-ci-autofix-runbook` | D. 进化 | CI 日志与自动修复 Runbook |
| `ota-openclaw-token-discipline` | E. 运维 | 工具暴露与 Token 纪律 |
| `ota-llm-model-routing` | E. 运维 | 模型分档与路由 |
| `ota-cmec-collaboration` | E. 运维 | CMEC 协作 |
| `ota-market-regime-checklist` | F. 高阶 | 市场体制与决策层短清单 |
| `ota-quantitative-screening-brief` | C. 研究 / 主链路 | `tool_quantitative_screening`：`status` 契约、四因子默认权重、与轮动工具边界 |
| `ota-chart-console-pro` | E. 运维 / 图表台 | TradingView 对标二期图表研究台运行规程：启动、健康检查、UI验收、常见报错与回退 |

**推荐优先加载（主链路）**：`ota-strategy-fusion-playbook` → `ota-signal-risk-inspection` → `ota-daily-session-routine`。  
涉及 **`tool_calculate_technical_indicators`** 的分析 Agent 建议同时启用 **`ota-technical-indicators-brief`**（与 `ota-volatility-range-brief` 并列的专项口径）。  
涉及 **`tool_calculate_historical_volatility` / `tool_underlying_historical_snapshot`** 时建议启用 **`ota-historical-volatility-snapshot`**（与 `ota_volatility_prediction_narration` 互补）。  
涉及 **`tool_assess_risk`**（单标的仓位/止损/波动率评估）时建议启用 **`ota-risk-assessment-brief`**（与 `ota-signal-risk-inspection` / `ota-strategy-fusion-playbook` 衔接）。  
涉及 **`tool_analyze_after_close` / `before_open` / `opening_market`** 的 Agent 建议启用 **`ota-trend-analysis-brief`**。  
涉及 **`tool_quantitative_screening`**（候选列表多因子排序）时建议启用 **`ota-quantitative-screening-brief`**（与 **`tool_etf_rotation_research`** + **`ota-etf-rotation-research`** 分工：前者用户指定 candidates，后者池来自配置/文件）。  
**入口主 Agent（`etf_main`）与业务核（`etf_business_core_agent`）**若需直接回答轮动、策略研究闭环、量化筛池类问题，建议与 **`etf_analysis_agent`** 同样勾选 **`ota-etf-rotation-research`**、**`ota-strategy-research-loop`**、**`ota-quantitative-screening-brief`**，避免「能调工具但无规程 Skill」导致口径漂移。  
**通知 Agent** 推送中含体制/波动环境摘要时，建议勾选 **`ota-market-regime-checklist`**、**`ota-historical-volatility_snapshot`**（与 `OpenClaw-Agent-ota-skills.md` 片段一致）。
涉及图表研究台二期（`127.0.0.1:8611`）排障/验收时，建议勾选 **`ota-chart-console-pro`**，统一处理 `HEAD 501`、`NaN JSON`、`slice is not a function` 等典型问题。

**Gateway 里给哪个 Agent 勾选哪些技能**：见 [`docs/openclaw/OpenClaw-Gateway-Agent与Skills勾选指南.md`](../docs/openclaw/OpenClaw-Gateway-Agent与Skills勾选指南.md)（含 `http://127.0.0.1:18789/skills`）；可复制 [`config/snippets/openclaw_agents_ota_skills.json`](../config/snippets/openclaw_agents_ota_skills.json) 与 openclaw 主配置对齐。

## 与 OpenClaw Agent 的绑定

本机已在 **openclaw 主配置** 的 **`agents.defaults.list[].skills`** 中为 `etf_main`、`etf_*_agent`、`ops_agent`、`code_maintenance_agent` 配置了与角色匹配的 allowlist；**数组元素须与各 `SKILL.md` 中 `name:` 一致（下划线）**，而非目录名 kebab-case。明细与 Gateway 链接见 **[`docs/openclaw/OpenClaw-Agent-ota-skills.md`](../docs/openclaw/OpenClaw-Agent-ota-skills.md)**（技能浏览：[http://localhost:18789/skills](http://localhost:18789/skills)）。

## 与第三方 Skill 的边界

- **第三方 Skill**（如 Clawhub 安装的 `agent-team-orchestration`、`capability-evolver`、`mx-data`、`tavily-search` 等）**不要放在本目录**，应安装到 OpenClaw 运行时技能目录，见 [`docs/getting-started/third-party-skills.md`](../docs/getting-started/third-party-skills.md)。
- 历史曾将部分 Clawhub 包置于 `skills/` 下，已清理；避免再次出现「仓库即技能市场」的混放。

## 调通后同步到 OpenClaw

### 工作流（新增或修改自研 Skill 后）

1. 在本仓库创建或编辑 **`skills/<slug>/SKILL.md`**。
2. 在**仓库根目录**执行：

```bash
cd /path/to/etf-options-ai-assistant
bash scripts/sync_repo_skills_to_openclaw.sh
```

3. **重启或重载 OpenClaw Gateway**，并用 `openclaw doctor` 或实际 Agent/工作流验收。

脚本会把自研包推送到 Gateway 常见加载路径（默认两处都推；若某路径不存在则跳过）：

- 系统级 skills 目录
- shared workspace skills 目录

**说明**：脚本**只**同步「本目录下含 `SKILL.md` 的子目录」；**不会删除**目标目录里已安装的第三方 Skill（如 `capability-evolver`、`tavily-search` 等）。第三方 Skill 的安装与自检见 [`docs/getting-started/third-party-skills.md`](../docs/getting-started/third-party-skills.md)（含进化流水线必备三项的 **文件层检查命令**）。

环境变量（可选）：

- `OPENCLAW_SKILLS_DIR`：默认 `$HOME/.openclaw/skills`
- `OPENCLAW_SHARED_SKILLS_DIR`：默认 `$HOME/.openclaw/workspaces/shared/skills`；若目录不存在会跳过
- `SYNC_SHARED_SKILLS=0`：不同步 shared 路径
