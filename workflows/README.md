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

---

## 测试与手动跑

参见仓库 `tests/README.md`、`tests/integration/run_all_workflow_tests.py`。  
修改工具名后请同步 **`config/tools_manifest.yaml`** 并执行 `python scripts/generate_tools_json.py`。
