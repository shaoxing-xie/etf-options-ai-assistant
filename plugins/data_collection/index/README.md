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

## 指数代码约定

与 `index_code_utils.py` 一致：**无指数白名单**；统一为 6 位数字（支持 `sh`/`sz`、`.SH`/`.SZ`）；**39 开头 → 深证 `sz`**，**其余 → 上证 `sh`**（第三方是否收录该代码决定能否取数）。常见示例：000001、399001、000300、000688、899050 等。

### 全球指数（`fetch_global`）
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