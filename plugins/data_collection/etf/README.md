# ETF数据采集插件

本目录包含ETF数据采集相关的插件工具，融合了 Coze 插件的核心逻辑。

## 插件列表

### 1. fetch_historical.py - ETF历史数据

**功能说明**：
- 获取ETF的历史日线数据
- 融合 Coze `get_etf_historical.py` 的核心逻辑
- 支持多ETF批量查询
- 支持缓存机制，提高数据获取效率

**使用方法**：
```python
from plugins.data_collection.etf.fetch_historical import tool_fetch_etf_historical

# 获取单个ETF历史数据
result = tool_fetch_etf_historical(
    etf_code="510300",              # ETF代码
    period="daily",                 # 数据周期："daily"
    start_date="20250101",          # 开始日期（可选）
    end_date="20250115"             # 结束日期（可选）
)

# 获取多个ETF历史数据
result = tool_fetch_etf_historical(
    etf_code="510300,510050,510500"  # 多个ETF代码，用逗号分隔
)
```

**输入参数**：
- `etf_code` (str): ETF代码，支持单个或多个（用逗号分隔），如 "510300" 或 "510300,510050"
  - 支持的ETF：510300(沪深300ETF), 510050(上证50ETF), 510500(中证500ETF), 159919(沪深300ETF), 159915(创业板ETF)
- `period` (str): 数据周期，目前仅支持 "daily"
- `start_date` (str, optional): 开始日期（YYYYMMDD 或 YYYY-MM-DD），默认回看30天
- `end_date` (str, optional): 结束日期（YYYYMMDD 或 YYYY-MM-DD），默认当前日期
- `use_cache` (bool): 是否使用缓存，默认 True
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched ETF historical data",
    "data": {
        "510300": {
            "etf_code": "510300",
            "etf_name": "沪深300ETF",
            "count": 250,
            "klines": [
                {
                    "date": "2025-01-15",
                    "open": 4.85,
                    "close": 4.87,
                    "high": 4.90,
                    "low": 4.82,
                    "volume": 50000000,
                    "amount": 243500000,
                    "change": 0.02,
                    "change_percent": 0.41
                }
            ],
            "source": "tushare"
        }
    },
    "count": 1,
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 优先使用 Tushare 接口（如果提供了 token）
- 降级使用新浪财经接口（`stock_zh_a_hist`）
- 支持缓存机制：自动检查缓存，只获取缺失数据
- 支持部分缓存命中：自动合并缓存和新获取的数据
- 自动计算成交额和涨跌幅
- 支持日期格式自动转换（YYYYMMDD 和 YYYY-MM-DD）

**缓存机制**：
- ✅ **支持缓存**：历史数据支持Parquet格式缓存（按日期拆分保存）
- ✅ **缓存合并**：支持部分缓存命中时自动合并缓存和新获取的数据
- ✅ **缓存路径**：`data/cache/etf_daily/{ETF代码}/{YYYYMMDD}.parquet`
- ✅ **自动保存**：获取数据后自动保存到缓存
- ✅ **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存（默认True）

**使用场景**：
- **历史分析**：获取ETF历史价格数据，用于技术分析
- **回测**：为策略回测提供历史数据
- **趋势判断**：分析ETF长期趋势
- **数据补全**：补充缺失的历史数据

---

### 2. fetch_minute.py - ETF分钟数据

**功能说明**：
- 获取ETF的分钟K线数据
- 融合 Coze `get_etf_minute.py` 的核心逻辑
- 支持多种周期：5分钟、15分钟、30分钟、60分钟
- 支持缓存机制

**使用方法**：
```python
from plugins.data_collection.etf.fetch_minute import tool_fetch_etf_minute

# 获取ETF分钟数据
result = tool_fetch_etf_minute(
    etf_code="510300",              # ETF代码
    period="30",                    # 周期："1", "5", "15", "30", "60"
    lookback_days=5,                # 回看天数，默认5天
    start_date="20250115",          # 开始日期（可选）
    end_date="20250115"             # 结束日期（可选）
)
```

**输入参数**：
- `etf_code` (str): ETF代码，如 "510300"
- `period` (str): 分钟周期，可选 "1", "5", "15", "30", "60"，默认 "30"
- `lookback_days` (int): 回看天数，默认 5
- `start_date` (str, optional): 开始日期（YYYYMMDD 或 YYYY-MM-DD）
- `end_date` (str, optional): 结束日期（YYYYMMDD 或 YYYY-MM-DD）
- `use_cache` (bool): 是否使用缓存，默认 True
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched ETF minute data",
    "data": {
        "etf_code": "510300",
        "etf_name": "沪深300ETF",
        "period": "30",
        "count": 120,
        "klines": [
            {
                "datetime": "2025-01-15 09:30:00",
                "open": 4.85,
                "close": 4.86,
                "high": 4.87,
                "low": 4.84,
                "volume": 5000000
            }
        ],
        "source": "sina"
    },
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 优先使用新浪财经接口（`stock_zh_a_hist_min_em`）
- 降级使用东方财富接口
- 支持缓存机制：自动检查缓存，只获取缺失数据
- 支持部分缓存命中：自动合并缓存和新获取的数据
- 自动处理非交易日，确保数据连续性

**缓存机制**：
- ✅ **支持缓存**：分钟数据支持Parquet格式缓存（按日期拆分保存）
- ✅ **缓存合并**：支持部分缓存命中时自动合并缓存和新获取的数据
- ✅ **缓存路径**：`data/cache/etf_minute/{ETF代码}/{period}/{YYYYMMDD}.parquet`
- ✅ **自动保存**：获取数据后自动保存到缓存
- ✅ **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存（默认True）

**使用场景**：
- **日内分析**：获取ETF日内分钟数据，用于日内交易分析
- **技术指标**：为技术指标计算提供分钟级数据
- **波动率预测**：为波动率预测提供分钟级数据
- **实时监控**：实时获取ETF价格变化

---

### 3. fetch_realtime.py - ETF实时数据

**功能说明**：
- 获取ETF的实时行情数据
- 融合 Coze `get_etf_realtime.py` 的核心逻辑
- 支持多ETF批量查询
- 实时获取最新价格、涨跌幅等信息

**使用方法**：
```python
from plugins.data_collection.etf.fetch_realtime import tool_fetch_etf_realtime

# 获取单个ETF实时数据
result = tool_fetch_etf_realtime(etf_code="510300")

# 获取多个ETF实时数据
result = tool_fetch_etf_realtime(etf_code="510300,510050,510500")
```

**输入参数**：
- `etf_code` (str): ETF代码，支持单个或多个（用逗号分隔），如 "510300" 或 "510300,510050"
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched ETF realtime data",
    "data": {
        "510300": {
            "etf_code": "510300",
            "etf_name": "沪深300ETF",
            "current_price": 4.85,
            "change": 0.02,
            "change_percent": 0.41,
            "open": 4.83,
            "high": 4.87,
            "low": 4.82,
            "prev_close": 4.83,
            "volume": 50000000,
            "amount": 242500000,
            "timestamp": "2025-01-15 14:30:00"
        }
    },
    "count": 1,
    "source": "akshare",
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 使用 AKShare 接口（`fund_etf_spot_em`）
- 支持多ETF批量查询，提高效率
- 自动匹配ETF代码格式（sh510300, sz159919等）
- 包含错误处理和降级机制

**使用场景**：
- **实时监控**：交易时间内实时获取ETF行情
- **价格查询**：快速查询ETF当前价格
- **信号生成**：作为信号生成的基础数据
- **风险控制**：实时监控ETF价格变化

---

## 支持的ETF

### 上海ETF（51xxxx）
- 510300: 沪深300ETF
- 510050: 上证50ETF
- 510500: 中证500ETF
- 510880: 红利ETF
- 512000: 券商ETF

### 深圳ETF（159xxx）
- 159919: 沪深300ETF
- 159915: 创业板ETF
- 159901: 深证100ETF

## 数据源

- **Tushare**：历史日线数据（需要token，优先使用）
- **新浪财经**：历史日线、分钟数据、实时数据
- **东方财富**：分钟数据（降级使用）

## 缓存机制

所有ETF数据采集插件都支持缓存机制：
- 自动检查缓存，只获取缺失数据
- 支持部分缓存命中，自动合并数据
- 缓存格式：Parquet文件
- 缓存路径：`data/cache/etf_{type}/{ETF代码}/{日期}.parquet`

## 注意事项

1. **数据源优先级**：Tushare > 新浪财经 > 东方财富
2. **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存
3. **日期格式**：支持 YYYYMMDD 和 YYYY-MM-DD 两种格式
4. **网络稳定性**：数据采集依赖网络，建议在网络稳定时执行
5. **API限制**：注意第三方API的调用频率限制
