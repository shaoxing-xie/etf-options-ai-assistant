# 工作流配置

本目录包含 OpenClaw 工作流配置文件。

## 工作流列表

1. **after_close_analysis.yaml** - 盘后分析工作流（工作日 15:30）
2. **before_open_analysis.yaml** - 盘前分析工作流（工作日 9:00）
3. **opening_analysis.yaml** - 开盘分析工作流（工作日 9:30）
4. **intraday_analysis.yaml** - 日内分析工作流（工作日 9:00-15:00，每15分钟）
5. **signal_generation.yaml** - 信号生成工作流（工作日 9:00-15:00，每30分钟）

## 工作流格式说明

所有工作流使用统一的 YAML 格式：

```yaml
name: workflow_name
description: 工作流描述

schedule: "cron表达式"  # Cron格式：分钟 小时 日 月 星期

steps:
  - name: step_name
    tool: tool_function_name
    description: 步骤描述
    params:
      param1: value1
    depends_on: [previous_step]  # 可选：依赖的步骤
    condition: "condition_expression"  # 可选：执行条件
```

## 工作流详细说明

### 1. after_close_analysis（盘后分析）

**执行时间**：工作日 15:30  
**功能**：
- 执行盘后市场分析
- 技术指标计算
- 趋势判断
- LLM增强分析
- 发送分析报告

**步骤**：
1. `tool_analyze_after_close` - 盘后分析
2. `tool_send_daily_report` - 发送报告

### 2. before_open_analysis（盘前分析）

**执行时间**：工作日 9:00  
**功能**：
- 检查交易状态
- 获取全球指数数据
- 获取A50期货数据
- 获取指数开盘数据
- 盘前趋势分析
- 波动率预测
- 发送分析报告

**步骤**：
1. `tool_check_trading_status` - 检查交易状态
2. `tool_fetch_global_index_spot` - 全球指数
3. `tool_fetch_a50_data` - A50期货
4. `tool_fetch_index_opening` - 指数开盘数据
5. `tool_analyze_before_open` - 盘前分析
6. `tool_predict_volatility` - 波动率预测
7. `tool_send_daily_report` - 发送报告

### 3. opening_analysis（开盘分析）

**执行时间**：工作日 9:30（开盘后30分钟）  
**功能**：
- 获取实时指数和ETF数据
- 计算技术指标
- 预测日内波动区间
- 开盘市场分析
- 生成开盘信号

**步骤**：
1. `tool_fetch_index_realtime` - 实时指数数据
2. `tool_fetch_etf_realtime` - 实时ETF数据
3. `tool_calculate_technical_indicators` - 技术指标
4. `tool_predict_intraday_range` - 日内波动区间
5. `tool_analyze_opening_market` - 开盘分析
6. `tool_generate_signals` - 生成信号

### 4. intraday_analysis（日内分析）

**执行时间**：工作日 9:00-15:00，每15分钟  
**功能**：
- 获取分钟级数据（指数、ETF、期权）
- 技术指标分析
- 波动率预测
- 日内波动区间预测
- 生成交易信号
- 风险评估
- 发送信号

**步骤**：
1. `tool_fetch_index_minute` - 指数分钟数据
2. `tool_fetch_etf_minute` - ETF分钟数据
3. `tool_fetch_option_realtime` - 期权实时数据
4. `tool_fetch_option_greeks` - 期权Greeks数据
5. `tool_calculate_technical_indicators` - 技术指标
6. `tool_predict_volatility` - 波动率预测
7. `tool_predict_intraday_range` - 日内波动区间
8. `tool_generate_signals` - 生成信号
9. `tool_assess_risk` - 风险评估
10. `tool_send_signal_alert` - 发送信号（条件：信号强度 >= medium）

### 5. signal_generation（信号生成）

**执行时间**：工作日 9:00-15:00，每30分钟  
**功能**：
- 读取缓存数据
- 计算技术指标和历史波动率
- 预测波动率和日内区间
- 生成综合交易信号
- 风险评估
- 发送符合条件的信号

**步骤**：
1. `tool_read_etf_daily` - 读取缓存数据
2. `tool_calculate_technical_indicators` - 技术指标
3. `tool_calculate_historical_volatility` - 历史波动率
4. `tool_predict_volatility` - 波动率预测
5. `tool_predict_intraday_range` - 日内波动区间
6. `tool_generate_signals` - 生成信号
7. `tool_assess_risk` - 风险评估
8. `tool_send_signal_alert` - 发送信号（条件：信号强度 >= medium）

## Cron 表达式说明

格式：`分钟 小时 日 月 星期`

- `"30 15 * * 1-5"` - 工作日 15:30
- `"0 9 * * 1-5"` - 工作日 9:00
- `"*/15 9-15 * * 1-5"` - 工作日 9:00-15:00，每15分钟
- `"*/30 9-15 * * 1-5"` - 工作日 9:00-15:00，每30分钟

## 使用方式

1. **自动执行**：根据 schedule 配置自动触发
2. **手动触发**：通过 OpenClaw Agent 手动调用
3. **集成调用**：作为子工作流被其他流程调用

## 注意事项

1. **工具名称**：所有工具名称必须以 `tool_` 开头
2. **依赖关系**：使用 `depends_on` 定义步骤依赖
3. **执行条件**：使用 `condition` 定义条件执行
4. **参数配置**：根据实际需求配置工具参数
5. **时区设置**：确保 Cron 表达式使用正确的时区（Asia/Shanghai）

## 测试建议

1. **手动测试**：先手动触发工作流，验证每个步骤
2. **定时测试**：修改 Cron 表达式为近期时间，测试定时触发
3. **错误处理**：验证错误处理和依赖关系
4. **性能监控**：监控工作流执行时间和资源使用
