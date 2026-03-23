# 工具列表

## 基础工具
- read: 读取文件内容
- write: 创建或覆盖文件
- edit: 精确编辑文件
- exec: 运行shell命令（**约定**：本 workspace 下执行 Python 时请用 `python3` 或 `/home/xie/etf-options-ai-assistant/.venv/bin/python`，系统 PATH 中无 `python` 命令）
- process: 管理后台执行会话

## Canvas工具
- canvas: Canvas显示/评估/快照

## 节点控制工具
- nodes: 发现和控制配对节点

## 消息工具
- message: 通过频道插件发送、删除和管理消息（**send 时必须提供 target**：使用当前会话的 channel/to，可从会话元数据或 session_status 获取，否则会报 "Action send requires a target"）

## 会话工具
- agents_list: 列出允许的代理ID
- sessions_list: 列出其他会话
- sessions_history: 获取会话历史
- sessions_send: 向另一个会话发送消息
- sessions_spawn: 生成子代理会话
- subagents: 列出、引导或终止子代理运行

## 会话状态工具
- session_status: 显示会话状态卡

## 期权交易工具
- option_trader: 执行期权交易相关操作

## 指数数据工具
- tool_fetch_index_realtime: 获取主要指数实时行情
- tool_fetch_index_historical: 获取指数历史K线数据
- tool_fetch_index_minute: 获取指数分钟K线数据
- tool_fetch_index_opening: 获取主要指数开盘数据
- tool_fetch_global_index_spot: 获取全球主要指数实时行情

## ETF数据工具
- tool_fetch_etf_realtime: 获取ETF实时行情数据
- tool_fetch_etf_historical: 获取ETF历史K线数据
- tool_fetch_etf_minute: 获取ETF分钟K线数据

## 期权数据工具
- tool_fetch_option_realtime: 获取期权实时行情数据
- tool_fetch_option_greeks: 获取期权Greeks数据
- tool_fetch_option_minute: 获取期权分钟K线数据
- tool_get_option_contracts: 获取期权合约信息列表

## A50期货数据工具
- tool_fetch_a50_data: 获取富时A50期指实时和历史数据

## 交易分析工具
- tool_check_trading_status: 判断当前是否是交易时间
- tool_get_a_share_market_regime: A股市场时段细分（集合竞价/连续竞价/午休/收盘集合竞价/盘后/非交易日）
- tool_trading_copilot: 交易助手统一入口（状态→时段→快扫→信号→持仓）
- tool_event_sentinel: 事件哨兵（外部事件检索/摘要→影响提示→是否触发再分析）
- tool_calculate_technical_indicators: 计算技术指标
- tool_analyze_after_close: 执行盘后趋势分析
- tool_analyze_before_open: 执行开盘前趋势分析
- tool_analyze_opening_market: 执行开盘行情分析
- tool_predict_volatility: 预测波动率
- tool_calculate_historical_volatility: 计算历史波动率
- tool_generate_signals: 根据多种策略生成买卖信号
- tool_generate_trend_following_signal: 基于ETF与指数趋势一致性生成趋势跟踪交易信号
- tool_calculate_position_size: 计算建议仓位
- tool_calculate_stop_loss_take_profit: 计算止盈止损价格
- tool_assess_risk: 评估交易风险
- tool_predict_intraday_range: 预测日内价格波动区间

## 一致性检查工具
- tool_check_etf_index_consistency: 检查ETF与指数趋势一致性
- tool_check_position_limit: 检查仓位是否超过指定比例上限（需传入上限，无系统硬锁定）
- tool_check_stop_loss_take_profit: 检查是否触发止盈止损
- tool_record_signal_effect: 记录交易信号执行效果

## A股制度/可交易性守卫工具
- tool_filter_a_share_tradability: A股可交易性过滤（停牌/涨跌停等启发式）

## 策略工具
- tool_get_strategy_performance: 获取策略历史表现统计
- tool_calculate_strategy_score: 计算策略综合评分
- tool_adjust_strategy_weights: 动态调整策略权重
- tool_get_strategy_weights: 获取策略权重配置

## 通知工具
- tool_send_feishu_message: 发送到飞书
- tool_send_signal_alert: 发送交易信号提醒
- tool_send_daily_report: 发送每日市场分析报告（钉钉）
- tool_send_risk_alert: 发送风险预警通知
- tool_send_feishu_card_webhook: 发送飞书交互卡片（interactive）到 webhook

## 缓存读取工具
- tool_read_index_daily: 从缓存读取指数日线数据
- tool_read_index_minute: 从缓存读取指数分钟数据
- tool_read_etf_daily: 从缓存读取ETF日线数据
- tool_read_etf_minute: 从缓存读取ETF分钟数据
- tool_read_option_minute: 从缓存读取期权分钟数据
- tool_read_option_greeks: 从缓存读取期权Greeks数据