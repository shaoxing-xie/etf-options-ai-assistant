# 工作流配置（`workflows/`）

本目录存放 **YAML 工作流定义**，供 OpenClaw Cron / Agent / 本地 step 脚本引用。  
**运行时产物**（日志、JSON 报告）在子目录 `logs/`、`data/` 下，与 `.yaml` 定义文件分开。

---

## 一览表

| 文件 | 调度（摘要） | 用途 |
|------|----------------|------|
| `before_open_analysis.yaml` | 工作日 9:00 | 盘前：交易状态、全球指数、A50、开盘、盘前分析、波动率、日报 |
| `before_open_analysis_enhanced.yaml` | 工作日 9:20 | 增强盘前：开盘数据、全球指数、分析、波动率、日内区间、日报 |
| `opening_analysis.yaml` | 工作日 9:30 | 开盘：指数/ETF 实时、指标、日内区间、开盘分析、信号 |
| `intraday_analysis.yaml` | 工作日 9–15 点每 15 分钟 | 日内：分钟/期权/Greeks、指标、波动、区间、信号、风控、告警 |
| `after_close_analysis_enhanced.yaml` | 工作日 15:30 | **唯一**盘后工作流：实时行情、盘后分析、历史波动率、信号、效果记录、日报（已替代原精简版 `after_close_analysis.yaml`） |
| `signal_generation.yaml` | 工作日 9–15 点每 30 分钟 | 读 **ETF 日线缓存** + 指标/波动/区间/信号/风控/告警 |
| `signal_generation_on_demand.yaml` | `schedule: null`（仅手动） | 按需信号：实时 ETF、指标、信号、风控、仓位、告警 |
| `etf_510300_intraday_monitor.yaml` | 工作日 9–15 点每 5 分钟（错开采集） | **仅读本地缓存** 510300/000300 分钟线；建议级提醒支持 **call/put 双向同发（研究级）**，阈值与日线过滤见 `config.yaml` |
| `etf_rotation_research.yaml` | 工作日 18:00 | ETF 轮动研究 + 日报 |
| `strategy_research.yaml` | 周五 19:00 | 策略研究/回放报告 + 日报 |
| `strategy_evaluation.yaml` | 周五 18:00（`schedule.cron` + `timezone`） | 多策略 `tool_calculate_strategy_score` |
| `strategy_weight_adjustment.yaml` | 周五 18:00（与上同时段） | 读权重并 `tool_adjust_strategy_weights`（依赖评分结果时请避免与 evaluation 步骤冲突或错开时间） |
| `strategy_fusion_routine.yaml` | 无内置 cron（随 Agent / 手动） | `tool_strategy_engine` → 可选风控/通知；与 `agents/analysis_agent.yaml` 的 `strategy_fusion` 呼应（交易时段 **每 30 分钟** `*/30 9-15 * * 1-5`） |
| `ci_autofix_triage_on_demand.yaml` | `schedule: null`（事件驱动） | CI 自动修复入口：Builder 取证、Reviewer 门禁、LOW 风险才可修复与 PR |
| `quality_backstop_audit.yaml` | 工作日 20:30 | 质量兜底巡检：Cron 异常、工具 BUG、预测漂移、运维问题 |
| `cron_error_autofix_on_demand.yaml` | `schedule: null`（事件驱动） | Cron 报错自动修复入口：仅 `TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true` 才允许修复并提 PR |
| `factor_evolution_on_demand.yaml` | `schedule: null`（按需） | 因子 / 指标演化工作流：三 Skill 编排，严格遵守 evolver_scope 边界，仅允许在 allowed_paths 内低风险自动创建 PR。 |
| `strategy_param_evolution_on_demand.yaml` | `schedule: null`（按需） | 策略参数 / 过滤器演化工作流：仅调整参数/阈值/过滤器/风控规则，不改核心信号逻辑与标的池，满足 TEAM_OK+RISK=LOW 才允许 PR。 |
| `research_checklist_evolution_on_demand.yaml` | `schedule: null`（按需） | 研究文档 / Checklist 演化工作流：只修改 docs/research/** 与研究相关 docs/openclaw/**，不改任何代码 |
| `volatility_range_evolution_on_demand.yaml` | `schedule: null`（按需） | 宽基 ETF **预测波动区间** 优化：`tool_predict_volatility` / `tool_predict_intraday_range` 与缓存同源逻辑；可结合 `prediction_records`、`volatility_ranges` 与 **网络检索** 做证据化调参与模型改进（见 `config/evolver_scope` 允许路径） |

---

## 按场景分组

**交易日主链路（采集 + 分析）**  
`before_open_analysis` / `opening_analysis` / `intraday_analysis` / `after_close_analysis_enhanced` — 以 **`tool_fetch_*`** 拉行情为主（盘后仅保留增强版 YAML）。

**依赖「读缓存」的工作流**（底层见 `plugins/data_access` → `read_cache_data` / `tool_read_market_data`）  
- `signal_generation.yaml`：`tool_read_etf_daily`  
- `etf_510300_intraday_monitor.yaml`：`tool_read_etf_minute`、`tool_read_index_minute`  

**增强 / 按需**  
- `before_open_analysis_enhanced.yaml`：相对基础盘前步骤更多。  
- `signal_generation_on_demand.yaml`：无定时，适合手动触发。

**研究 / 策略运维**  
- `etf_rotation_research`、`strategy_research`：研究输出 + 日报。  
- `strategy_evaluation`、`strategy_weight_adjustment`：周期性评分与权重（YAML 内为 **结构化 `schedule`**，见下节）。

**三 Skill 自动修复与兜底（新增）**
- `ci_autofix_triage_on_demand.yaml`：事件驱动（CI 失败触发），“先取证后判定”，仅 `RISK=LOW` 可进入修复+PR。
- `quality_backstop_audit.yaml`：定时兜底（工作日 20:30），覆盖 Cron、工具 BUG、预测漂移、运维问题。
- `cron_error_autofix_on_demand.yaml`：事件驱动（Cron 报错触发），仅 `TEAM_OK + RISK=LOW + AUTOFIX_ALLOWED=true` 可进入修复+PR，禁止自动 merge main。

**多策略融合（可选）**  
- 工具 **`tool_strategy_engine`**：不替代 `tool_generate_signals`；可在 Cron/按需流程中 **并行或单独** 调用，输出 `candidates` + `fused`（见 `docs/architecture/strategy_engine_and_signal_fusion.md`）。示例 Cron 见根目录 `CRON_JOBS_EXAMPLE.json` 中 `strategy-fusion-example`（**`*/30 9-15 * * 1-5`**，默认 `enabled: false`）。  
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

步骤字段在各文件中可能为 `params` 或 `parameters`，并以具体 YAML 为准。

通用约定（若文件内未写则以前端/OpenClaw 解析为准）：

- `tool`：工具名须与 `tool_runner.py` / `config/tools_manifest.yaml` 一致。  
- `depends_on`：步骤依赖。  
- `continue_on_error`：部分策略类步骤为 `true`，避免单步失败阻断后续。

---

## 子目录

| 路径 | 说明 |
|------|------|
| `logs/` | 工作流或脚本运行日志（如 `intraday_monitor_*.json`、历史 `option_trading_*.log`） |
| `data/` | 产物数据：趋势分析、波动区间、预测记录、市场广度等 JSON |

勿将 `logs/`、`data/` 下的生成物当作「工作流定义」；**源定义仅根目录 `*.yaml`**。

---

## 与 OpenClaw 的衔接

实际 Cron / Agent 绑定以 **`~/.openclaw/cron/jobs.json`** 与项目 **`docs/openclaw/`** 为准；本目录 YAML 可作为**步骤与工具名的参考模板**。

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

参见仓库 `tests/README.md`、`tests/integration/run_all_workflow_tests.py`。  
修改工具名后请同步 **`config/tools_manifest.yaml`** 并执行 `python scripts/generate_tools_json.py`。
