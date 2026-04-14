# 工作流配置（`workflows/`）

本目录存放 **YAML 工作流定义**，供 OpenClaw Cron / Agent / 本地 step 脚本引用。  
**运行时产物**（日志、JSON 报告）在子目录 `logs/`、`data/` 下，与 `.yaml` 定义文件分开。

**与自研 `ota-*` Skill 的关系**：工作流步骤只声明 **`tool`** 与参数，**不**声明 Skill；规程类 Skill（如巡检顺序、融合解读）由 **openclaw 主配置中 `agents.defaults.list[].skills`** 与 Gateway Agent 页加载。一般 **无需** 因新增或调整 `ota-*` 而修改本目录 YAML；若口径变更，优先改工具实现或 `docs/openclaw/*`，并保持 Skill 与文档同步。详见 [`docs/openclaw/OpenClaw-Agent-ota-skills.md`](../docs/openclaw/OpenClaw-Agent-ota-skills.md) §「与工作流 / 仓库 Agent YAML / 日常交互」。

---

## 一览表

| 文件 | 调度（摘要） | 用途 |
|------|----------------|------|
| `before_open_analysis.yaml` | 工作日 9:20 | **盘前机构晨报**（唯一盘前 YAML）；**`structured_message` 自包含**（不读 research.md）；Cron 推荐单次 `tool_run_before_open_analysis_and_send` |
| `opening_analysis.yaml` | 工作日 **9:28**（Cron 常见） | **开盘独立完整版**：含轻量开盘链路 + 机构晨报级采集 + 波动/预测回顾；`report_type=opening`；Cron 推荐单次 `tool_run_opening_analysis_and_send` |
| `tail_session_513880.yaml` | 工作日 **14:40** | **日经225ETF尾盘监控**：`report_type=tail_session`，输出分层建议与用户可选路径（不输出唯一结论）；Cron 推荐单次 `tool_run_tail_session_analysis_and_send` |
| `intraday_analysis.yaml` | 工作日 9–15 点每 15 分钟 | 日内：分钟/期权/Greeks、指标、波动、区间、信号、风控、告警 |
| `after_close_analysis_enhanced.yaml` | 工作日 15:30 | **唯一**盘后工作流：实时行情、盘后分析、历史波动率、信号、效果记录、日报（已替代原精简版 `after_close_analysis.yaml`） |
| `daily_market_report.yaml` | **工作日 16:30** | **每日市场分析报告**（钉钉）；与 `cron/jobs.json`「etf: 每日市场分析报告」对齐；章节对标见 [`docs/research/daily_market_report_web_benchmark.md`](../docs/research/daily_market_report_web_benchmark.md) |
| `limitup_pullback_after_close.yaml` | 工作日 **15:40** | **涨停回马枪盘后**（`report_type=limitup_after_close_enhanced`，钉钉）；先读 `research.md` 第七节/第十节；与 [`plugins/analysis/scenario_analysis.py`](../plugins/analysis/scenario_analysis.py) 等工具配合 |
| `etf_rotation_research_agent.yaml` | 工作日 **18:10** | **ETF 轮动研究（agentTurn）**：按 `research.md` + 钉钉；与下方 `etf_rotation_research.yaml`（工具管道版）**并存**，择一绑定 Cron |
| `strategy_research_playback.yaml` | 周五 **19:10** | **策略研究与回放（agentTurn）**：按 `research.md` + 钉钉；与 `strategy_research.yaml`（工具管道版）**并存** |
| `prediction_verification.yaml` | 工作日 15:35 | 收盘后对照 parquet 校验 `prediction_records`，写 `verified` / `actual_range`，可选 `--report`；与 `src/prediction_recorder` 标准化配套 |
| （脚本）`scripts/prediction_metrics_weekly.py` | 按需 / 例：周五 18:05 | 滚动命中率按 `(symbol, method)` 对比近两窗，`prediction_monitoring` 配置相对基线下滑告警 |
| （脚本）`scripts/prediction_fusion_experiment.py` | 仅手动 | 多模型区间融合离线试验；契约见 `docs/research/prediction_fusion_contract.md` |
| `signal_risk_inspection.yaml` | 见 `cron/jobs.json`（如 9:15/9:45 等） | **宽基 ETF 巡检快报**：推荐单次 `tool_run_signal_risk_inspection_and_send`（内含组合快照与模板发送）；排查见 `docs/ops/cron_signal_inspection_triage.md` |
| `signal_generation.yaml` | 工作日 9–15 点每 30 分钟 | 读 **ETF 日线缓存** + 指标/波动/区间/信号/风控/告警 |
| `signal_generation_on_demand.yaml` | `schedule: null`（仅手动） | 按需信号：实时 ETF、指标、信号、风控、仓位、告警 |
| `etf_510300_intraday_monitor.yaml` | 工作日 9–15 点每 5 分钟（错开采集） | **仅读本地缓存** 510300/000300 分钟线；建议级提醒支持 **call/put 双向同发（研究级）**，阈值与日线过滤见合并后配置（来源：`config/domains/signals.yaml`） |
| `etf_rotation_research.yaml` | 工作日 18:00 | ETF 轮动研究 + 通知：`tool_etf_rotation_research`（`etf_pool` 空则读 `rotation_config.yaml` + `symbols.json`）→ `tool_send_analysis_report` |
| `strategy_research.yaml` | 周五 19:00 | 策略研究/回放：`tool_strategy_research`（默认读 **`config/strategy_research.yaml`**：切分、务实版 WFE、成本、Holdback 门禁）→ 日报/钉钉 |
| `strategy_evaluation.yaml` | 周五 **18:00**（`schedule.cron` + `timezone`） | 多策略 `tool_calculate_strategy_score` |
| `strategy_weight_adjustment.yaml` | 周五 **18:15**（在 `strategy_evaluation` 之后） | 读权重并 `tool_adjust_strategy_weights`（与 18:00 评分错峰，见 YAML） |
| `strategy_fusion_routine.yaml` | 无内置 cron（随 Agent / 手动） | `tool_strategy_engine`（返回含 `fused`、`fused_by_symbol`、`summary`、`inputs_hash`）→ 可选风控/通知；与 `agents/analysis_agent.yaml` 的 `strategy_fusion` 呼应（交易时段 **每 30 分钟** `*/30 9-15 * * 1-5`）；多 ETF 参数见 YAML 内注释 |
| `ci_autofix_triage_on_demand.yaml` | `schedule: null`（事件驱动） | CI 自动修复入口：Builder 取证、Reviewer 门禁、LOW 风险才可修复与 PR |
| `quality_backstop_audit.yaml` | 工作日 20:30 | 质量兜底巡检：Cron 异常、工具 BUG、预测漂移、运维问题 |
| `cron_error_autofix_on_demand.yaml` | `schedule: null`（事件驱动） | Cron 报错自动修复入口：仅 `TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true` 才允许修复并提 PR |
| `factor_evolution_on_demand.yaml` | `schedule: null`（按需） | 因子 / 指标演化工作流：三 Skill 编排，严格遵守 evolver_scope 边界，仅允许在 allowed_paths 内低风险自动创建 PR。 |
| `strategy_param_evolution_on_demand.yaml` | `schedule: null`（按需） | 策略参数 / 过滤器演化工作流：仅调整参数/阈值/过滤器/风控规则，不改核心信号逻辑与标的池，满足 TEAM_OK+RISK=LOW 才允许 PR。 |
| `research_checklist_evolution_on_demand.yaml` | `schedule: null`（按需） | 研究文档 / Checklist 演化工作流：只修改 docs/research/** 与研究相关 docs/openclaw/**，不改任何代码 |
| `volatility_range_evolution_on_demand.yaml` | `schedule: null`（按需） | 宽基 ETF **预测波动区间** 优化：`tool_predict_volatility`、`tool_predict_intraday_range`、**`tool_predict_daily_volatility_range`（全日）** 与缓存同源逻辑；可结合 `prediction_records`、`volatility_ranges` 与 **网络检索** 做证据化调参与模型改进（见 `config/evolver_scope` 允许路径） |

**双轨证据（上述四个 `*_evolution_on_demand`）**：须满足 `config/evolution_invariants.yaml` → **`dual_evidence`** — Builder `[RAW_OUTPUT]` 含 **`[LOCAL_EVIDENCE]`** 与 **`[EXTERNAL_REFS]`**（至少一条 `https://`），Orchestrator **`EVIDENCE_REF`** 同时锚定本地与外链；缺一脚 → **`DUAL_EVIDENCE_INCOMPLETE`**。人读摘要见 `docs/openclaw/execution_contract.md` §9。

---

## 工作流与推荐 `ota-*` Skill（Gateway 勾选）

工作流 YAML **不写** Skill 名；以下为 **建议** 与主链路同 Agent 会话加载的 `ota_*`，避免「能调工具但缺规程」导致口径漂移（真源：openclaw 主配置中 `agents.defaults.list[].skills`，见 [`docs/openclaw/OpenClaw-Agent-ota-skills.md`](../docs/openclaw/OpenClaw-Agent-ota-skills.md)）。

| 工作流 / 场景 | 推荐 Skill（节选） |
|----------------|-------------------|
| 盘前 / 开盘 / 盘后 / 日报 | `ota_daily_session_routine`、`ota_volatility_range_brief`、`ota_volatility_prediction_narration`、`ota_notification_soul_routing` |
| 巡检 `signal_risk_inspection` | `ota_signal_risk_inspection`、`ota_risk_assessment_brief` |
| 策略融合 `strategy_fusion_routine` / Agent 定时融合 | `ota_strategy_fusion_playbook` |
| ETF 轮动 / 策略研究（agentTurn） | `ota_etf_rotation_research`、`ota_strategy_research_loop` |
| 读缓存类步骤 | `ota_cache_read_discipline`（collector / 分析 Agent 视角色） |

---

## 功能重复与互斥（摘要）

| 组 | 工作流 | 说明 |
|----|--------|------|
| 盘前两线 | `before_open_analysis`（9:20） vs `opening_analysis`（9:28） | 共享大量采集步；**不合并文件**。参数与指数列表请在 [`docs/openclaw/工作流参考手册.md`](../docs/openclaw/工作流参考手册.md) 与两 YAML 间对齐。 |
| 盘中三线 | `intraday_analysis` vs `signal_generation` vs `etf_510300_intraday_monitor` | 数据源与频率不同（实时拉取 / 日线缓存 / 本地分钟缓存）；**非简单重复**。权威业务信号源由你在 `jobs.json` 中择一或保留分层。 |
| 研究双轨 | `etf_rotation_research` vs `etf_rotation_research_agent`；`strategy_research` vs `strategy_research_playback` | **每对只启用一个** Cron，避免双跑。 |
| 盘后 vs 日报 | `after_close_analysis_enhanced`（15:30） vs `daily_market_report`（16:30） | 职责不同；**勿**用早盘/开盘产物代替 16:30 日报。 |

Cron 时间线（重叠与渠道）：[`docs/openclaw/workflow_cron_timeline.md`](../docs/openclaw/workflow_cron_timeline.md)。

机构级自检清单：[`docs/openclaw/institutional_alignment_checklist.md`](../docs/openclaw/institutional_alignment_checklist.md)。

钉钉长文投递全文（YAML 内为摘要）：[`docs/openclaw/dingtalk_delivery_contract.md`](../docs/openclaw/dingtalk_delivery_contract.md)。

---

## 按场景分组

**交易日主链路（采集 + 分析）**  
`before_open_analysis`（盘前） / `opening_analysis`（开盘） / `intraday_analysis` / `after_close_analysis_enhanced` — 以 **`tool_fetch_*`** 拉行情为主（盘后仅保留增强版 YAML）。

**依赖「读缓存」的工作流**（底层见 `plugins/data_access` → `read_cache_data` / `tool_read_market_data`）  
- `signal_generation.yaml`：`tool_read_etf_daily`  
- `etf_510300_intraday_monitor.yaml`：`tool_read_etf_minute`、`tool_read_index_minute`  

**增强 / 按需**  
- `before_open_analysis.yaml`：**唯一**盘前工作流 YAML（`structured_message` 自包含；**不再有** `before_open_analysis_enhanced.yaml`，已移除）。  
- `signal_generation_on_demand.yaml`：无定时，适合手动触发。

**研究 / 策略运维**  
- `etf_rotation_research`、`strategy_research`：研究输出 + 日报（工具管道版）。  
- `etf_rotation_research_agent`、`strategy_research_playback`：`research.md` 口径 + 钉钉长文（agentTurn 版，见上表）。  
- `strategy_evaluation`、`strategy_weight_adjustment`：周期性评分与权重（YAML 内为 **结构化 `schedule`**，见下节）。

**三 Skill 自动修复与兜底（新增）**
- `ci_autofix_triage_on_demand.yaml`：事件驱动（CI 失败触发），“先取证后判定”，仅 `RISK=LOW` 可进入修复+PR。
- `quality_backstop_audit.yaml`：定时兜底（工作日 20:30），覆盖 Cron、工具 BUG、预测漂移、运维问题。
- `cron_error_autofix_on_demand.yaml`：事件驱动（Cron 报错触发），仅 `TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true` 可进入修复+PR，禁止自动 merge main。

**多策略融合（可选）**  
- 工具 **`tool_strategy_engine`**：不替代 `tool_generate_option_trading_signals`（别名 `tool_generate_signals`）及 ETF/A 股信号工具；可在 Cron/按需流程中 **并行或单独** 调用，输出 `candidates`、`fused`、`fused_by_symbol`（多标的）、`summary`（见 `docs/architecture/strategy_engine_and_signal_fusion.md`）。示例 Cron 见根目录 `CRON_JOBS_EXAMPLE.json` 中 `strategy-fusion-example`（**`*/30 9-15 * * 1-5`**，默认 `enabled: false`）。  
- 步骤模板 **`strategy_fusion_routine.yaml`**；OpenClaw 衔接与进化参数见 **`config/openclaw_strategy_engine.yaml`**。

---

## YAML 格式说明

不同文件有两种常见写法：

1. **单行 Cron**（与旧文档一致）  
   `schedule: "30 15 * * 1-5"`

2. **结构化调度**（含时区）  
   ```yaml
   schedule:
     cron: "0 18 * * 5"
     timezone: "Asia/Shanghai"
   ```

### 步骤字段命名（仓库约定）

- **`params`**：推荐写法；`strategy_evaluation.yaml` / `strategy_weight_adjustment.yaml` 已与全库对齐。
- **`parameters`**：历史别名；若 OpenClaw 前端仅识别其一，以运行环境为准。
- **`continue_on_failure`**：推荐写法；表示单步失败时仍继续后续步骤（与 `continue_on_error` 同义择一，勿混用）。

### 扩展工具 id

行情类 `tool_fetch_*`、缓存类 `tool_read_*` 等多由扩展 **`openclaw-data-china-stock`** 注册。校验脚本将 `config/workflow_external_tool_ids.txt` 与 `config/tools_manifest.yaml` **合并** 作为允许列表；新增工作流步骤时请同步更新该 txt。

通用约定（若文件内未写则以前端/OpenClaw 解析为准）：

- `tool`：工具名须与 Gateway 合并 manifest 一致；本仓校验见 `scripts/validate_workflows.py`。  
- `depends_on`：步骤依赖。  
- `continue_on_failure` / `continue_on_error`：策略类步骤常为 `true`，避免单步失败阻断后续。

---

## 子目录

| 路径 | 说明 |
|------|------|
| `logs/` | 工作流或脚本运行日志（如 `intraday_monitor_*.json`、历史 `option_trading_*.log`） |
| `data/` | 产物数据：趋势分析、波动区间、预测记录、市场广度等 JSON |

勿将 `logs/`、`data/` 下的生成物当作「工作流定义」；**源定义仅根目录 `*.yaml`**。二者已在仓库根 `.gitignore` 中忽略，勿提交运行产物。

---

## 与 OpenClaw 的衔接

实际 Cron / Agent 绑定以 **cron/jobs.json** 与项目 **`docs/openclaw/`** 为准；本目录 YAML 可作为**步骤与工具名的参考模板**。

### 混合触发映射（事件优先 + 定时兜底）

- 事件触发（优先）：
  - CI/workflow 失败 -> `ci_autofix_triage_on_demand.yaml`
  - 运维告警/人工上报 BUG -> `ci_autofix_triage_on_demand.yaml`（先按证据协议分流）
- 定时兜底：
  - 每工作日 20:30 -> `quality_backstop_audit.yaml`
  - 每周策略评分/权重任务仍沿用 `strategy_evaluation.yaml` / `strategy_weight_adjustment.yaml`

建议在任务定义（如 `jobs.json`）里保持以下约束：

- 必须回传证据块 `[COMMAND]/[STDOUT]/[STDERR]/[RAW_OUTPUT]`
- Reviewer 无证据必须 `TEAM_FAIL: NO_EVIDENCE`
- 非 `TEAM_OK + RISK=LOW` 禁止自动修复

---

## 测试与手动跑

- **工作流工具名校验**（推荐纳入 CI）：`python scripts/validate_workflows.py`  
- **集成入口**：`python tests/integration/run_all_workflow_tests.py`（当前调用上述校验）

修改本仓 `tools_manifest` 内工具名后请同步 **`config/tools_manifest.yaml`** 并执行 `python scripts/generate_tools_json.py`；扩展注册的 id 请同步 **`config/workflow_external_tool_ids.txt`**。
