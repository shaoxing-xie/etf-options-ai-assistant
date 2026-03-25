## 项目目录结构总览（etf-options-ai-assistant）

> 本文用于快速了解项目的目录划分和关键文件，方便后续维护与扩展。

### 根目录（项目根目录）

- `README.md`：项目总体说明（A股 / ETF 交易助手系统介绍、功能概览）。
- `config.yaml`：系统主配置（市场数据、通知、日志、系统参数等）。
- `Prompt_config.yaml`：LLM 提示词模板与分析类型配置（含 `openclaw_strategy_engine_routing` 等可选 OpenClaw 路由片段）。
- `config/strategy_fusion.yaml`：多策略融合阈值与默认权重（`tool_strategy_engine`）。
- `config/openclaw_strategy_engine.yaml`：OpenClaw 与策略引擎衔接（路由提示、权重落盘进化、默认工具参数）。
- `CRON_JOBS_EXAMPLE.json`：Cron 任务示例（含 `strategy-fusion-example`，`*/30 9-15 * * 1-5`，默认关闭）。
- `index.ts`：OpenClaw 插件入口（注册所有工具，调用 `tool_runner.py`）。
- `tool_runner.py`：Python 工具路由入口（统一分发到 `plugins/` 和 `src/` 中的各个工具）。
- `install_plugin.sh`：将本项目安装为 OpenClaw 插件的自动安装脚本。
- `setup_openclaw_plugin.sh`：在 Remote-WSL 环境下快速配置 OpenClaw 插件结构的脚本。
- `setup_wsl_access.sh`：在 WSL 中为项目创建符号链接、workspace 目录等的辅助脚本。
- 集成/冒烟测试脚本见 `tests/README.md`（如 `tests/integration/run_all_workflow_tests.py`、`verify_data_pipeline.py`）。

### 1. 核心代码：`src/`

- `src/data_collector.py`：原系统数据采集核心模块  
  - 负责股票、指数、ETF、A50 期指等多数据源采集（期权能力可扩展）。
- `src/data_cache.py`：数据缓存模块  
  - 统一管理 parquet/本地文件缓存，供插件与分析模块复用。
- `src/trend_analyzer.py`：趋势分析模块  
  - 盘后分析、盘前分析、开盘分析等核心逻辑。
- `src/signal_generation.py`：信号生成核心逻辑  
  - 多策略信号生成、信号过滤等。
- `src/config_loader.py`：统一配置加载模块  
  - 负责加载 `config.yaml`，并提供数据存储、调度、节假日等子配置。
- `src/llm_enhancer.py`：LLM 增强模块  
  - 封装与 LLM 的调用与增强逻辑，用于趋势分析、波动预测、信号说明等。

> 说明：`src/` 目录主要承载“原系统”的业务逻辑，插件与工作流通过 `tool_runner.py` 间接调用这些模块。

### 2. OpenClaw 插件：`plugins/`

- `plugins/data_collection/`：数据采集插件
  - `README.md`：OpenClaw 工具索引（标的物 → 数据域 → 周期）与 `TOOL_MAP` 对照。
  - `ROADMAP.md`：路线图、双层降级（多 Provider × 包内多路由）、附录 DTO/标的映射等。
  - `config/`：静态配置（如 `symbol_mapping.yaml`）。
  - `providers/`：Provider 链再导出（如 A 股实时），供单测与文档 import。
  - `stock/`：A股股票数据采集（实时、日线、分钟、聚合等）。
  - `index/`：指数数据采集（实时、历史、分钟、开盘等）。
  - `etf/`：ETF 实时/历史/分钟数据采集（含 IOPV/折价快照工具）。
  - `option/`：期权实时、Greeks、分钟数据采集（扩展能力）。
  - `futures/`：A50 期指数据采集。
  - `utils/`：批量采集、交易时间判断、期权合约列表等通用工具。
- `plugins/analysis/`：分析类插件
  - `technical_indicators.py`：技术指标计算（MACD、RSI、MA、ATR 等）。
  - `trend_analysis.py`：盘后/盘前/开盘趋势分析的插件封装。
  - `volatility_prediction.py`：波动率预测工具。
  - `intraday_range.py` / `historical_volatility.py` 等：日内区间、历史波动率分析。
  - `etf_trend_tracking.py`：ETF-指数趋势一致性与趋势跟随信号。
  - `etf_position_manager.py` / `etf_risk_manager.py` / `risk_assessment.py`：仓位管理、止盈止损、整体风险评估。
  - `strategy_tracker.py` / `strategy_evaluator.py` / `strategy_weight_manager.py`：策略效果记录、评分与权重管理（`get_strategy_weights` 可优先读 `data/strategy_fusion_effective_weights.json`）。  
- `plugins/strategy_engine/`：**策略引擎与信号融合**（`SignalCandidate`、Fusion v1/v1.1/v1.2、`tool_strategy_engine`）；说明见 [`plugins/strategy_engine/README.md`](../plugins/strategy_engine/README.md)。
- `plugins/notification/`：通知类插件
  - `send_feishu_message.py`：飞书文本/卡片消息发送。
  - `send_signal_alert.py`：交易信号告警。
  - `send_daily_report.py`：盘后/日报通知。
- `plugins/data_access/`：数据访问插件
  - `read_cache_data.py`：统一从本地缓存读取指数/ETF/期权数据（支持 DataFrame / JSON）。
  - 其他 `README.md`：说明各数据访问工具的使用方式。
- `plugins/utils/`：通用工具
  - `trading_day.py`：交易日判断与节假日配置支持。
  - `logging_utils.py`：统一日志封装，兼容原系统日志配置。
- `plugins/merged/`：合并工具
  - `fetch_index_data.py` / `fetch_etf_data.py` / `fetch_option_data.py` / `read_market_data.py`：对原有多工具的统一封装。
  - `send_feishu_notification.py`：统一的飞书通知入口（message, signal_alert, daily_report, risk_alert）。
  - `volatility.py`：波动率预测/历史波动率的统一入口。
  - `strategy_analytics.py` / `strategy_weights.py` / `position_limit.py` / `stop_loss_take_profit.py`：策略与风险管理相关的合并工具。

> 说明：`plugins/` 是 OpenClaw 直接可见的工具层，通过 `index.ts` → `tool_runner.py` 调用。

### 3. 工作流与结果：`workflows/`

- `workflows/*.yaml`：OpenClaw 工作流定义（盘后分析、盘前分析、开盘分析、信号生成、策略评估等）。
- `workflows/*_step_by_step.py`：工作流分步测试脚本。
- `workflows/data/`：工作流运行时产生的中间 JSON 结果  
  - `trend_analysis/after_close/` / `before_open/`  
  - `volatility_ranges/`  
  - `prediction_records/` 等。
- `workflows/logs/`：通过工作流执行时产生的日志文件。

> 建议：日常只读 `workflows/*.yaml` 和 `docs/openclaw/*` 来理解工作流逻辑，JSON 结果主要用于调试与回溯。

### 4. 脚本与运维：`scripts/`

- 用途与命令见 **`scripts/README.md`**（发布门禁、JSON 校验、工具清单生成、Cron/OpenClaw 辅助、预警轮询、数据库索引等）。
- 说明：若仓库中已无 `run_yfinance_test.sh` / `test_yfinance_global_index.py` / `test_sina_stock_zh_a_spot.py` 等文件，以 `scripts/` 目录实际内容为准。

> 这些脚本主要面向运维/发布/排障，不属于 OpenClaw 插件日常调用路径。

### 5. 数据与日志：`data/` 与 `logs/`

- `data/`：运行时数据
  - `signal_records/`：信号记录数据库与 JSON。
  - `prediction_records/`：预测记录数据库与 JSON。
  - `trend_analysis/`：趋势分析结果。
  - `volatility_ranges/`：波动区间预测结果（已在生成源头统一收敛：`range_pct` 夹紧、`confidence` 上限等）。
  - `cache/`：LLM 上下文、市场广度缓存等。
- `logs/`：统一日志目录
  - `option_trading_{date}.log`：主交易助手运行日志。
  - `logs/option_trading_/`：带子目录的历史/分组日志。

> 说明：`data/` 与 `logs/` 由运行时自动写入，通常不手工编辑，只用于分析和排错。

### 6. 文档：`docs/`

- `docs/overview/`
  - `5分钟快速开始指南.md`：项目快速上手指南。
- `docs/openclaw/`
  - `README_WSL_ACCESS.md`：在 Remote-WSL + Cursor 场景下访问项目的说明。
  - `OpenClaw配置指南.md`：在 OpenClaw 中配置插件的详细步骤。
  - `插件集成到OpenClaw指南.md`：与 OpenClaw Gateway、Agent、工作流的集成说明。
  - `工作流参考手册.md`：工作流设计与使用参考。
- `docs/architecture/`
  - `README.md`：架构文档索引与阅读顺序。
  - `架构与工具审查报告.md`：工具分层、清单与可维护性等系统性审查与建议。
- `docs/reference/`
  - `工具参考手册.md`：所有工具（插件）的详细参数与返回值说明。
  - `akshare/`：数据源库 AKShare 的接口说明（本地镜像，按股票/指数/基金/期货/期权分文件），入口见 `akshare/README.md`。
- `docs/ops/`
  - `常见问题库.md`：FAQ 与排障方案。
  - `需要添加交易日判断跳过参数的工具清单.md`：需要补充交易日判断的工具清单。
- `docs/legacy/`
  - 历史迁移说明、测试报告、讨论稿等（含早期期权导向文档），用于追溯设计与迁移过程，不作为当前权威指南。
- 原始归档快照（历史文档，仅用于查阅背景，不参与当前运行）
  - 从历史快照迁移过来的原始文档与说明（`docs/`, `coze/`, `feishu_src/`, `openclaw_migration/` 等快照），仅用于查阅原始设计与历史背景，不参与当前运行。

> 说明：新文档建议按 “overview / openclaw / architecture / reference / ops / legacy” 分类，避免混乱。

### 7. 其他

- `agents/README.md`：OpenClaw Agent 配置说明（Agent 角色与任务；**`analysis_agent.yaml`** 含 `tool_strategy_engine` 与 **`strategy_fusion`** 定时，交易时段每 **30** 分钟）。
- `plugins/**/README.md` / `workflows/README.md` / `plugins/data_collection/**/README.md` 等：  
  - 各子模块的本地说明文件，补充 `工具参考手册.md`。

---

如需扩展/新增模块，建议：

1. **代码**：放入相应的 `src/` 或 `plugins/` 子目录（分析类→`plugins/analysis/`，采集类→`plugins/data_collection/`）。  
2. **工作流**：在 `workflows/` 下新增 YAML，并在 `docs/openclaw/` 中补充说明。  
3. **文档**：按主题放入 `docs/overview | openclaw | reference | ops | legacy`。  
4. **脚本/运维工具**：统一放入 `scripts/` 并在 `docs/ops/` 中补充用途说明。

