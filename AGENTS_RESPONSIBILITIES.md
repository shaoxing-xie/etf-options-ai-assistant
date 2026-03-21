## ETF / 期权多 Agent 职责边界说明（etf-options-ai-assistant）

**目标**：明确每个 Agent 在“数据 / 策略 / 风控 / 通知”四个维度的职责，便于后续扩展与调试。

### 1. `etf_main`（入口主 Agent）
- **定位**：对外统一入口，接收用户自然语言指令。
- **职责**：
  - 解析用户意图（如“运行趋势策略回测”“查看今日信号”等）。
  - 协调调用其它子 Agent（business_core / data_collector / analysis / notification）。
  - 负责高层次对话和结果总结。

### 2. `etf_business_core_agent`（业务核心 Agent）
- **定位**：策略与风控编排中心。
- **职责**：
  - 读取 `strategy_config.py` 中的策略配置（“策略即配置”）。
  - 调用 `etf_data_collector_agent` 获取所需 ETF / 指数 / 期权行情数据。
  - 生成标准化“信号对象”和“下单请求对象”：
    - 信号包含：策略 ID、方向、置信度、触发条件快照等。
    - 下单请求包含：目标仓位比例、价格区间、时间限制等。
  - 调用 `option_trader.py risk_check` 完成集中风控审核。
  - 审核通过后，再调用 `option_trader.py` 进入实际执行（未来对接回测 / 模拟盘 / 实盘）。
  - 对策略 6 多策略组合：根据分析结果动态调整在线权重配置。

### 3. `etf_data_collector_agent`（数据采集 Agent）
- **定位**：统一的数据访问与质量监控层。
- **职责**：
  - 封装所有与行情相关的工具调用（如本地 tool_fetch_etf_realtime / tool_fetch_index_realtime / tool_fetch_option_realtime 等）。
  - 为 510300 / 000300 / A50 期指 等关键标的提供：
    - 日线 / 分钟线 / Tick（如有）/ 期权链 / IV。
  - 维护本地缓存与基础清洗逻辑（缺失值填补、异常点过滤）。
  - 输出“数据质量报告”给业务核心 Agent：
    - 缺失率、延迟情况、极端跳变等；
    - 当数据不可靠时给出“当日暂停自动交易”的建议信号。

### 4. `etf_analysis_agent`（分析与回测 Agent）
- **定位**：回测评估与策略评分中心。
- **职责**：
  - 与本地回测框架（KHQuant / Backtrader / TQuant Lab 等）对接：
    - 从 `etf_data_collector_agent` 获取历史数据；
    - 根据 `strategy_config.py` 中配置执行回测。
  - 计算并输出关键指标：
    - 年化收益、夏普比率、最大回撤、胜率、信号频率等。
  - 计算策略评分（score），用于多策略组合：
    - 按约定（如每 30 天）生成各策略评分；
    - 将评分结果反馈给 `etf_business_core_agent`，驱动权重调整。
  - 为 `etf_notification_agent` 提供结构化报告数据（日/周/月报）。

### 5. `etf_notification_agent`（通知与报告 Agent）
- **定位**：对接钉钉 / 飞书等 IM 通道的消息中枢。
- **职责**：
  - 通过 `feishu_webhook` / 钉钉插件发送：
    - 信号级通知：策略触发但未必下单（含置信度、触发条件摘要）。
    - 交易级通知：下单 / 成交 / 撤单 / 风控拒单原因。
    - 绩效与回顾：日 / 周 / 30 天策略表现与权重调整建议。
  - 负责消息格式化（Markdown / 图表链接等），保证在 IM 端可读性良好。

### 6. `option_trader.py`（交易执行网关 CLI）
- **定位**：统一的“交易执行与风控入口”，由各 Agent 通过 CLI 调用。
- **职责**：
  - 提供基础状态与环境探测：
    - `status`：工具网关就绪情况；
    - `env`：调用 `broker_and_data_config.get_runtime_environment_view` 输出券商与数据源能力。
  - 提供风控检查入口：
    - `risk_check`：接收下单请求与账户状态（stdin JSON），调用 `risk_engine.evaluate_order_request` 给出集中风控结论。
  - 保留 `signal` 占位接口，兼容早期“从工具层直接拉信号”的调用方式，但推荐由 `etf_business_core_agent` 统一生成信号。
  - 未来扩展：根据模式（backtest / paper / live）对接具体回测框架或券商 API。

