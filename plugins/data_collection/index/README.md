# 指数数据采集插件

本目录包含指数数据采集相关的插件工具。

## 插件列表

### 1. fetch_realtime.py - 指数实时数据

**功能说明**：获取主要指数的实时行情数据

**使用方法**：见 [data_collection/README.md](../README.md#1-indexfetch_realtimepy---指数实时数据)

### 2. fetch_opening.py - 指数开盘数据

**功能说明**：获取主要指数的开盘数据（9:28集合竞价数据）

**使用方法**：见 [data_collection/README.md](../README.md#2-indexfetch_openingpy---指数开盘数据)

### 3. fetch_global.py - 全球指数数据

**功能说明**：获取全球主要指数的实时行情数据

**使用方法**：见 [data_collection/README.md](../README.md#3-indexfetch_globalpy---全球指数数据)

## 支持的指数

### 国内指数
- 000001: 上证指数
- 000016: 上证50
- 000300: 沪深300
- 000905: 中证500
- 000852: 中证1000
- 399001: 深证成指
- 399006: 创业板指
- 000688: 科创综指

### 全球指数
- int_dji: 道琼斯指数
- int_nasdaq: 纳斯达克指数
- int_sp500: 标普500指数
- int_nikkei: 日经225指数
- rt_hkHSI: 恒生指数

## 使用场景

- **实时监控**：交易时间内实时获取指数行情
- **开盘分析**：9:28集合竞价时获取开盘数据
- **盘后分析**：分析外盘表现，预测次日A股走势
- **趋势判断**：结合实时数据判断市场趋势