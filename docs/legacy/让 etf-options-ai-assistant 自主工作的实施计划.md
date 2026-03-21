让 etf-options-ai-assistant 自主工作的实施计划

目标与范围





目标：在现有阶段 1 基础上，把你已经落地的代码能力（option_trader.py、broker_and_data_config、strategy_config、risk_engine 等）真正接入各个 ETF Agent，让 OpenClaw 能：





自动识别环境与数据能力；



依据 510300 策略配置自动生成交易信号；



在统一风控审核后，给出执行/拒绝决策，并通过 IM 主动汇报。



范围：





不新增新的策略，只把已有 6 个策略“用起来”；



先聚焦 ETF 层（策略 1/2/4/6）+ 自动风控 + 报告，期权组合（策略 3）执行层在后续阶段单独做深度集成；



回测引擎接入只规划接口，不绑定具体框架（KHQuant/Backtrader 二选一由你后续确认）。

总体架构回顾





相关核心文件：





配置与工具：





[.openclaw/workspaces/etf-options-ai-assistant/option_trader.py]



[.../broker_and_data_config.py]



[.../strategy_config.py]



[.../risk_engine.py]



Agent 与插件：





etf_main / etf_business_core_agent / etf_data_collector_agent / etf_analysis_agent / etf_notification_agent（位于 [.openclaw/agents/etf-options-ai-assistant/**/agent]）。

flowchart TD
  user[User] --> etfMain[etf_main]
  etfMain --> core[etf_business_core]
  core --> dataAgent[etf_data_collector]
  core --> riskEngine[RiskEngine]
  core --> analysis[etf_analysis]
  core --> trader[option_trader]
  core --> notif[etf_notification]
  dataAgent -->|market data| riskEngine
  dataAgent -->|history| analysis
  riskEngine --> trader
  trader --> notif
  analysis --> notif

实施步骤

步骤 1：规范环境与数据能力视图（供所有 Agent 共用）





1.1 整理环境视图接口





明确 broker_and_data_config.get_runtime_environment_view() 的返回结构：





broker: 名称、是否允许实盘、是否已开通期权；



execution_mode: signal_only | paper | live（全局开关，默认 signal_only，用于一键切换“只报信号/模拟盘/实盘”）；



data_feeds: 对 510300/000300/A50/510300 期权的 daily/minute/tick/realtime/iv 能力标记；



assumptions: 说明当前哪些是保守假设、哪些是已确认能力。



在计划中约定：各 Agent 不得自行假设 Tick/IV 能力，一律通过调用 option_trader.py env 获得视图后再决策。



1.2 为 Agent 设计使用约定





etf_data_collector_agent：每次拉行情前，都先检查环境视图中相应数据源是否可用，不可用则降级为更粗粒度数据（如无法 Tick 则退回 1/5 分钟）。



etf_business_core_agent：根据环境视图决定当日是否启用日内高频策略（如 Tick/低延迟不足，则关闭策略 4）。



数据质量降级铁律：若某策略明确“需要 Tick/IV”，但环境视图表明不可用，则该策略当日自动 暂停，并由 etf_notification_agent 输出“暂停原因 + 降级建议”。（示例：策略 4 缺 Tick/低延迟则仅输出观察信号，不自动执行。）。



1.3 Tick 数据源与 config.yaml 整合





在 etf-options-ai-assistant 工作空间下维护统一的 config.yaml，其中 data_sources.tick 段用于配置：





Tick 数据源优先级：primary/secondary（如 iTick 为主、Alltick 为备）；



标的映射：逻辑代码（如 510300、000300）到各厂商代码（如 510300.SH）；



各 provider 的 REST/WS 基础地址、超时时间与 API Key 环境变量名（例如 iTick 免费环境：股票 https://api-free.itick.org/stock，指数 https://api-free.itick.org/indices，参考文档）。



broker_and_data_config 在构造 data_feeds 时读取 config.yaml，如果发现：





至少有一个开启的 Tick provider（如 iTick），且标的已在 symbols 中映射；



则将 etf_510300、index_000300 等对应项的 tick 能力标记为 true。



具体 Tick 请求由 tick_client.py 完成：从 config.yaml 读取配置，按优先级依次请求 iTick/Alltick，输出统一的 Tick 结构；etf_data_collector_agent 调用该客户端并结合返回结果与延迟信息生成“数据质量报告”。

步骤 2：把 6 个策略完全“配置化”并暴露给业务 Agent





2.1 统一策略配置 Schema





在 strategy_config.py 中：





明确 StrategyConfig 字段含义：instrument/timeframe/indicators/triggers/positioning/risk/meta；



用简短注释说明哪些字段给数据层用（如 timeframe/indicators），哪些给决策层用（如 triggers/positioning/risk）。



2.2 为每个策略提供获取函数





确保对 6 个核心策略均有：<strategy_name>() -> StrategyConfig；



提供 list_all_strategies() 与 get_strategy_config(strategy_id) 两个入口，约定：





业务 Agent 严禁在 Prompt 中硬编码策略规则，一切从这两个函数获取。



2.3 设计多策略组合视图





在组合策略配置中，明确：





每个子策略的 initial_weight；



调权规则：frequency_days/min_score/on_score_below_min；



约定：etf_analysis_agent 计算出评分后，将更新建议反馈给 etf_business_core_agent，由后者更新在线权重配置（而不是直接改策略配置文件）。

步骤 3：定义统一风控 JSON 协议并接入执行网关





3.1 标准化风控输入/输出结构





在 risk_engine.py 中约定：





输入：order_request（策略 ID、标的、方向、目标仓位占比、价格、time_in_force、meta）+ account_state（equity、day_pnl_pct、positions）；



输出：approved（bool）、reasons（list）、normalized_order_request（标准化后的下单请求）。



补充字段（用于“信号阶段也可解释成本”）：





estimated_slippage_pct：预估滑点比例（按标的类型/流动性/盘口宽度估计，先用保守默认值也可）；



total_cost_pct：预估总交易成本比例（手续费 + 交易费 + 滑点的合计估计值）。



3.2 明确核心硬规则





单笔仓位上限：默认 2%。



期权单腿上限：默认 1.5%。



当日最大浮亏：默认 -1.5%，触发后禁止新增风险敞口（但允许减仓/平仓）。



510300 期权：在期权策略阶段，额外增加合约单位 10260 与备兑持仓检查（在后续期权集成阶段启用）。



3.3 将风控对外暴露为工具网关入口





通过 option_trader.py 提供：





env：返回环境与数据视图（步骤 1）;



risk_check：从 stdin 读 JSON，调用风控引擎返回审核结果；



保留 status/signal 以兼容早期调用，但在 Agent 规则中声明推荐走 env + risk_check 流程。



审计日志（必做）：





option_trader.py 增加 log_risk_check()：每次风控请求/结果都落地为 JSON 文件（包含时间戳、策略 ID、输入摘要、输出 approved/reasons、成本预估字段），用于后续追责与复盘。

步骤 4：为各 ETF Agent 设计“行为准则”





4.1 etf_main（入口主 Agent）





在其配置中写入规则：





用户涉及“510300 策略 / 回测 / 实盘 / 仿真”的自然语言请求，一律翻译为对 etf_business_core_agent、etf_data_collector_agent、etf_analysis_agent、etf_notification_agent 的调用，而不直接计算指标或构造订单。



对于“每天/每周自动执行”类需求，记录为长期任务说明（由你或外部调度调用），自身只负责解读结果与汇总反馈。



4.2 etf_data_collector_agent（数据采集）





规则要点：





所有行情获取请求先调用 option_trader.py env 确认数据能力，再选择工具（如 Tick vs 分钟 vs 日线）。



输出给上层的结果应包含：行情数据 + 简要的数据质量报告（缺失率、延迟、异常值标记）。



4.3 etf_business_core_agent（策略与风控编排）





规则要点：





所有策略信息从 strategy_config 读取：





根据 timeframe/indicators 决定调用数据层获取哪些数据；



根据 triggers 解释生成信号对象（策略 ID、方向、置信度、触发条件摘要）。



任意下单前：





构造 order_request + account_state；



调用 option_trader.py risk_check，不得跳过风控直接执行；



根据 approved/reasons 决定是否生成执行请求。



多策略组合：执行前根据 analysis_agent 提供的评分结果调整在线权重，对得分低于阈值的策略自动减权或暂停。



4.4 etf_analysis_agent（回测与评分）





规则要点：





回测参数、周期、标的等全部从 strategy_config 获取，保持与实盘逻辑一致；



输出：每个策略的年化收益、夏普、最大回撤、胜率、信号频率和综合评分；



定期（如每 30 天）将评分与建议权重调整结果以结构化形式返回给 etf_business_core_agent 以及汇总给 etf_notification_agent。



4.5 etf_notification_agent（通知与报告）





规则要点：





统一三类通知模板：





信号级：策略信号 + 风控审核结果（通过/拒绝 + 原因摘要）。



交易级：下单/成交/撤单/异常 + 关键参数（价格、数量、滑点等）。



绩效级：日/周/30 天策略表现、组合调权情况与建议。



通过 Feishu/钉钉插件发送 Markdown 报告，并在关键阈值事件（如触发日内 -1.5% 熔断）时高亮提示。

步骤 5：设计三条标准工作流（供 OpenClaw 长期重复执行）





5.1 日常信号 + 风控巡检工作流





场景：工作日盘前/盘中，由你或外部调度触发。



流程：





etf_main 接到“生成今日 510300 策略信号报告”的任务。



调用 etf_data_collector_agent 拉数据 + 出数据质量报告。



etf_business_core_agent：按策略配置生成信号，构造 order_request + account_state 调用 risk_check；



etf_notification_agent：将每条信号及风控审核结果以表格化 Markdown 推送。



5.2 回测与策略评分工作流





场景：每周或每 30 天一次。



流程：





etf_main 接到“对 6 个策略做回测与评分”的任务。



etf_analysis_agent：调用历史数据 + 回测引擎，算指标与评分；



向 etf_business_core_agent 提供更新后的推荐权重；



etf_notification_agent 生成“月度策略报告”推送。



5.3 模拟盘 / 小资金实盘执行工作流





场景：你确认策略与风控后，开放自动执行。



流程：





复用“日常信号 + 风控巡检”的前 3 步；



对 approved=True 的信号，根据阶段（paper/live）构造执行请求（未来通过扩展 option_trader.py 的 trade 类 action 实现）；



执行结果记录交给 etf_analysis_agent 做“实盘 vs 回测”对比，并由 etf_notification_agent 实时汇报。

后续可选扩展





接入具体回测框架（KHQuant 或 Backtrader），在 etf_analysis_agent 中实现适配层。



为 510300 期权 Delta-Neutral 策略落地期权腿构建与 GARCH/ARIMA 波动率预测模块，启用合约单位 10260 与备兑规则检查。



增加简单的调度层（如外部定时任务调用 OpenClaw Gateway API），让上述三条工作流按时间自动触发。

