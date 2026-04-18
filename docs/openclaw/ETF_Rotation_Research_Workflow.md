## ETF 轮动研究工作流设计（etf_rotation_research）

### 1. 目标与定位

- 为宽基及行业/主题 ETF 建立**研究级**轮动分析：
  - 每个交易日盘后或晚间，对配置池内 ETF 做强弱评估与轮动方向参考；
  - 输出结构化「ETF 轮动研究」报告，经钉钉等渠道推送；
  - **不直接驱动交易或仓位调整**，仅作研究与决策辅助。
- 与现有主线（如 510300 + 期权日内）关系：补充「相对强弱与风险刻度」视角，不替代日内信号与风控链路。

### 2. 工作流文件与调度建议

- **工具管道版**：`workflows/etf_rotation_research.yaml`  
  - 步骤：`tool_etf_rotation_research` → `tool_send_analysis_report`（`report_data` 来自上一步）。
  - 默认 `etf_pool: ""`，标的池由 **`config/rotation_config.yaml`**（`pool.symbol_groups` + `extra_etf_codes`）与 **`config/symbols.json`** 解析。
- **Agent 版**：`workflows/etf_rotation_research_agent.yaml`（按 `research.md` + 钉钉长文；与管道版**并存**，Cron 择一绑定）。
- 建议调度：工作日 **18:00**（管道版 YAML 内 `schedule: "0 18 * * 1-5"`）；若与 Cron 对齐 **18:10**，以 `~/.openclaw/cron/jobs.json` 为准。
- 手动触发：可通过 OpenClaw `cron run` 或本地 `tool_runner.py` 调用工具。

### 3. 标的池与配置（单一入口）

- **轮动专用配置**：`config/rotation_config.yaml`  
  - `pool.symbol_groups`：通常为 `core`、`industry_etf`（与 `symbols.json` 的 `groups` 名称一致）。  
  - `pool.extra_etf_codes`：轮动补集（如历史上默认池中的行业主题代码），避免仅合并 `symbols.json` 时遗漏。  
- **集中标的清单**：`config/symbols.json`（指数/ETF 分组）；采集优先级仍按各组 `priority` 执行。
- **显式覆盖**：工作流或工具参数传入非空 `etf_pool`（逗号分隔）时，**不再**合并上述默认池，便于测试或缩池。

### 4. 核心实现与数据（与旧版「多工具链」设计对齐后的实际形态）

当前实现已**收敛为单工具 + 共享核心库**，不再依赖独立的 `tool_read_etf_daily` / `tool_calculate_technical_indicators` 链式步骤（若文档其它处仍提及，以本节为准）。

1. **数据**  
   - `plugins/data_access/read_cache_data`：`etf_daily`，需 **start_date / end_date**，支持缓存全量或部分命中（部分命中时仍尽量使用已有 K 线）。  
   - 核心模块：`plugins/analysis/etf_rotation_core.py` 内根据 `data_need`（`lookback_days` 与 MA、相关性、R² 窗口取 max）决定尾部截取，避免长窗被过短 `lookback` 误截断。

2. **因子与评分**（均在 `rotation_config.yaml` 可调）  
   - 动量：20 日 / 60 日；波动：20 日年化；回撤：约 60 日窗口最大回撤。  
   - 趋势稳定性：对数收盘价线性回归 **R²**（`numpy`，非 scipy）。  
   - 相关性：对齐收益后 Pearson 矩阵，**mean_abs_corr**；模式含 `penalize` / `filter` / `off` / `filter_greedy`（见 YAML）。  
   - 均线：默认 MA200，`ma_mode`：`soft`（低于均线降权）/ `hard` / `off`。  
   - **legacy_score**：保留旧口径（0.45/0.35/0.15/0.05）便于对比；综合分含新权重时可与 legacy 并列展示。

3. **工具**  
   - `tool_etf_rotation_research`：`plugins/analysis/etf_rotation_research.py`。  
   - 输出：`report_data.llm_summary`、排名、`correlation_matrix`、`config_snapshot`、`errors`；可选 **JSONL 历史**（默认 `data/etf_rotation_runs.jsonl`）。  

4. **发送报告**  
   - 管道版：`tool_send_analysis_report` 投递钉钉（与仓库内通知工具映射一致）。  
   - 自然语言输出仍建议遵守 `research.md`「研究模式一」与免责声明。

### 5. 与 Market Regime 的衔接

- 工具内可调用 `tool_detect_market_regime`（如基于 510300）在报告中补充 Regime 一行说明；Regime **不覆盖**轮动排名逻辑，仅作上下文。

### 6. 钉钉输出与研究模式一

- 遵守 `~/.openclaw/prompts/research.md` 中 ETF 轮动相关步骤与 Markdown 约束。  
- 明确标注「研究级，不构成交易指令」；说明数据来自本地缓存及可能缺失情形。

### 7. 报告结构（近期）

`tool_etf_rotation_research` 生成的 `llm_summary` 建议按以下顺序阅读：

- **核心结论**：Top 与 Top5 换手率一句话摘要；  
- **分层轮动榜**、**Market Regime**、**相关性/均线**（含技术告警与人话解读）；  
- **数据覆盖与降级**；  
- **近期板块轮动操作指引（研究用）**：流程化观察清单（非买卖价位）；  
- **最近轮动记录**、**风险提示**、**数据与来源**；  
- **高密度要点**、**轮动状态**、因子明细表。

「是否继续加指标、如何防过拟合」等**方法论原则**不在报告内展开，由维护者与团队单独对齐；报告仍可在**因子说明**中体现当前已用的技术映射口径（如 P0/58）。
