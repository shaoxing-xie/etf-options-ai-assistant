etf-options-ai-assistant 系统扩展思路

总体设计思路





目标：在不推翻现有 OpenClaw 多 Agent + option_trader.py 结构的前提下，把阶段1的 6 大策略沉淀为“可配置、可回测、可监控”的交易系统，支持 510300 ETF 现货 + 期权，并适配 2026 年最新规则。



核心原则：





分层解耦：数据采集 / 策略决策 / 交易执行 / 风控 / 监控告警 分层，各层只通过清晰的 JSON 协议交互，便于以后替换回测框架或券商接口。



先 ETF、后期权：一期优先落地策略 1 + 2 + 4 + 6 在 ETF 层面，期权（策略 3）用同一接口标准预留“腿”，等账户与数据准备好再接入。



“策略即配置”：把 6 个策略固化成统一的策略配置结构（指标、触发条件、目标周期、风控参数），由业务 Core Agent 解释执行，而不是散落在 Prompt 里。



风控优先于收益：所有下单请求先经过硬风控层（2% 仓位、日内最大回撤、IV 90 分位等），风控通过后才交给 option_trader.py 执行。

与现有架构的对齐





现状梳理：





已有多个 ETF 相关 Agent：etf_main、etf_business_core_agent、etf_data_collector_agent、etf_analysis_agent、etf_notification_agent。



已有 CLI Backend：option_trader（Python 脚本），以及 feishu_webhook 等通知通道。



已接入 Tavily、Mem0 等插件，适合做最新规则检索与“经验记忆”。



对齐策略：





数据采集职责：由 etf_data_collector_agent 统一封装所有 tool_fetch_* 调用，负责缓存、清洗和数据质量监控（缺失、延迟、异常波动）。



策略与风控职责：由 etf_business_core_agent 解释策略配置，生成“信号对象”和“下单请求对象”，并与集中风控模块交互。



分析与报告职责：etf_analysis_agent 负责回测结果解读、策略评分（夏普、回撤、胜率）和阶段性总结。



通知职责：etf_notification_agent 通过 feishu_webhook / 钉钉，把信号、成交、风控触发等事件推送到 IM 群。

flowchart TD
  user[User] --> etfMain[etf_main Agent]
  etfMain --> core[etf_business_core_agent]
  core --> dataAgent[etf_data_collector_agent]
  core --> risk[RiskEngine]
  core --> analysis[etf_analysis_agent]
  core --> trader[option_trader.py]
  core --> notif[etf_notification_agent]
  dataAgent -->|fetch_etf/index/option| Data[MarketData]
  risk --> trader
  trader --> notif
  analysis --> notif

分层扩展思路





1）数据与回测层





在 etf_data_collector_agent 中固化 510300/000300/A50 等关键标的的数据接口封装：日线、分钟线、Tick、期权链和 IV。



增加“数据质量检查脚本接口”，生成简单 JSON 报告（缺失率、延迟、极端跳变），供业务 Core Agent 决定是否“暂停当日交易”。



预留与 KHQuant / Backtrader 的桥接：使用统一的“历史数据拉取 + 订单执行模拟”协议，未来只需替换适配层，不改高层策略逻辑。



2）策略引擎层





设计统一的“策略配置 Schema”，涵盖：





标的（510300、期权合约）、周期（日线/30 分钟/5 分钟/Tick 聚合）。



指标与触发条件（Aroon/MACD/ATR/RSI、波动率锥分位等）。



仓位规则（默认 2% 硬锁，期权腿 1.5%，组合上限）。



止盈止损逻辑（ATR、MA 回归、IV 分位）。



用该 Schema 实现：





策略 1：趋势跟踪 + 一致性增强。



策略 2：均值回归 + 波动率锥过滤。



策略 4：日内波动率突破。



策略 5：事件驱动 + A50 联动（作为“外部信号源”插件对接）。



策略 3：Delta-Neutral 期权策略，仅先落地配置与回测接口，执行部分在后续阶段接入。



3）风控与仓位管理层





建立独立的 RiskEngine：





接收“下单请求对象”（含策略 ID、方向、目标仓位、价格区间）。



调用“仓位工具”和“账户快照”（账户权益、已用保证金、当前持仓）。



执行规则：





单笔 2% 硬限制、期权单腿 1.5%。



当日浮亏超过 -1.5% 时触发“全平/暂停交易”信号。



期权：检查合约单位 10260、备兑持仓数量是否充足。



输出审核结果：approved / rejected + 原因，并记录到审计日志，供 etf_analysis_agent 回溯。



4）执行与仿真实盘层





封装 option_trader.py 为统一“交易执行网关”：





支持 mode: backtest / paper / live，参数由 Core Agent 决定。



所有真实下单前必须先走 RiskEngine，仿真模式可选择“宽松风控”用于实验性策略。



对期权交易增加“合约规则检查模块”，包含 2026-01-16 后的 510300 期权调整逻辑。



5）监控、通知与报告层





etf_notification_agent 标准化三类通知：





信号级：策略触发、但未必下单（含置信度、触发条件快照）。



交易级：下单/成交/撤单、风控拒单原因。



绩效级：日/周/30 天策略表现与权重调整建议。



利用 Feishu/钉钉插件实现“图文并茂”的回顾报告（含简单图表链接或截图）。



6）策略组合与动态权重层





由 etf_analysis_agent 定期计算：每个策略的胜率、夏普比率、最大回撤、信号频率。



etf_business_core_agent 基于上述指标，调用“权重调整逻辑”，生成推荐权重，或直接更新“在线权重配置”，用于策略 6 的多策略组合执行。

渐进式落地路线（不展开到实现细节）





阶段 A：把 ETF 现货策略和风控跑通（策略 1+2+4+6，仿真或小资金）。



阶段 B：接入回测框架与正式的策略评分机制，形成“从回测到实盘”的闭环。



阶段 C：上线 Delta-Neutral 期权策略执行层，重点围绕新合约单位和备兑规则做风控和回测。



阶段 D：强化监控与可视化报告，让大部分日常运维通过 IM 和定期报告完成。