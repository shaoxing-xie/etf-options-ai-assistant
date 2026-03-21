# 期权数据采集插件

本目录包含期权数据采集相关的插件工具，融合了 Coze 插件的核心逻辑。

## 插件列表

### 1. fetch_realtime.py - 期权实时数据

**功能说明**：
- 获取期权合约的实时行情数据
- 融合 Coze `get_option_realtime.py` 的核心逻辑
- 支持单个合约查询或批量查询（按标的）
- 实时获取最新价格、涨跌幅、成交量等信息

**使用方法**：
```python
from plugins.data_collection.option.fetch_realtime import tool_fetch_option_realtime

# 获取单个期权合约实时数据
result = tool_fetch_option_realtime(contract_code="10010891")

# 获取指定标的所有期权实时数据
result = tool_fetch_option_realtime(underlying="510300")
```

**输入参数**：
- `contract_code` (str, optional): 期权合约代码（单个合约查询），如 "10010891"
- `underlying` (str, optional): 标的代码（批量查询该标的所有期权），如 "510300"
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched option realtime data",
    "data": {
        "10010891": {
            "contract_code": "10010891",
            "contract_name": "300ETF购2月4900",
            "current_price": 0.10,
            "change": 0.01,
            "change_percent": 11.11,
            "open": 0.09,
            "high": 0.11,
            "low": 0.08,
            "prev_close": 0.09,
            "volume": 100000,
            "amount": 10000,
            "strike_price": 4.90,
            "option_type": "call",
            "underlying": "510300",
            "timestamp": "2025-01-15 14:30:00"
        }
    },
    "count": 1,
    "source": "akshare",
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 使用 AKShare 接口（`option_sse_spot_price_sina`）
- 支持单个合约查询或按标的批量查询
- 自动解析字段/值格式的DataFrame
- 包含错误处理和降级机制

**使用场景**：
- **实时监控**：交易时间内实时获取期权行情
- **价格查询**：快速查询期权当前价格
- **信号生成**：作为信号生成的基础数据
- **风险控制**：实时监控期权价格变化

---

### 2. fetch_minute.py - 期权分钟数据

**功能说明**：
- 获取期权合约的分钟K线数据
- 融合 Coze `get_option_minute.py` 的核心逻辑
- 支持缓存机制，提高数据获取效率
- 用于日内分析和波动率预测

**使用方法**：
```python
from plugins.data_collection.option.fetch_minute import tool_fetch_option_minute

# 获取期权分钟数据
result = tool_fetch_option_minute(
    contract_code="10010891",       # 期权合约代码
    date="20250115",                 # 日期（可选，默认今天）
    use_cache=True                   # 是否使用缓存
)
```

**输入参数**：
- `contract_code` (str): 期权合约代码，如 "10010891"
- `date` (str, optional): 日期（YYYYMMDD 或 YYYY-MM-DD），默认今天
- `use_cache` (bool): 是否使用缓存，默认 True
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched option minute data",
    "data": {
        "contract_code": "10010891",
        "date": "20250115",
        "count": 120,
        "klines": [
            {
                "datetime": "2025-01-15 09:30:00",
                "open": 0.09,
                "close": 0.10,
                "high": 0.11,
                "low": 0.08,
                "volume": 10000
            }
        ],
        "source": "sina"
    },
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 使用新浪财经接口（`option_sse_minute_sina`）
- 支持缓存机制：自动检查缓存，只获取缺失数据
- 支持部分缓存命中：自动合并缓存和新获取的数据
- 自动处理非交易日

**缓存机制**：
- ✅ **支持缓存**：分钟数据支持Parquet格式缓存（按日期拆分保存）
- ✅ **缓存合并**：支持部分缓存命中时自动合并缓存和新获取的数据
- ✅ **缓存路径**：`data/cache/option_minute/{合约代码}/{YYYYMMDD}.parquet`
- ✅ **自动保存**：获取数据后自动保存到缓存
- ✅ **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存（默认True）

**使用场景**：
- **日内分析**：获取期权日内分钟数据，用于日内交易分析
- **技术指标**：为技术指标计算提供分钟级数据
- **波动率预测**：为波动率预测提供分钟级数据
- **实时监控**：实时获取期权价格变化

---

### 3. fetch_greeks.py - 期权Greeks数据

**功能说明**：
- 获取期权合约的Greeks数据（Delta、Gamma、Theta、Vega等）
- 融合 Coze `get_option_greeks.py` 的核心逻辑
- 支持缓存机制
- 用于期权定价和风险管理

**使用方法**：
```python
from plugins.data_collection.option.fetch_greeks import tool_fetch_option_greeks

# 获取期权Greeks数据
result = tool_fetch_option_greeks(
    contract_code="10010891",       # 期权合约代码
    date="20250115",                 # 日期（可选，默认今天）
    use_cache=True                   # 是否使用缓存
)
```

**输入参数**：
- `contract_code` (str): 期权合约代码，如 "10010891"
- `date` (str, optional): 日期（YYYYMMDD 或 YYYY-MM-DD），默认今天
- `use_cache` (bool): 是否使用缓存，默认 True
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched option greeks data",
    "data": {
        "contract_code": "10010891",
        "date": "20250115",
        "greeks": {
            "delta": 0.65,
            "gamma": 0.12,
            "theta": -0.05,
            "vega": 0.08,
            "iv": 0.25,              # 隐含波动率
            "rho": 0.02
        },
        "underlying_price": 4.85,
        "strike_price": 4.90,
        "option_type": "call",
        "source": "sina",
        "timestamp": "2025-01-15 14:30:00"
    },
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 使用新浪财经接口（`option_sse_greeks_sina`）
- 支持缓存机制：自动检查缓存，只获取缺失数据
- 自动解析Greeks字段
- 包含错误处理和降级机制

**缓存机制**：
- ✅ **支持缓存**：Greeks数据支持Parquet格式缓存（按日期拆分保存）
- ✅ **缓存路径**：`data/cache/option_greeks/{合约代码}/{YYYYMMDD}.parquet`
- ✅ **自动保存**：获取数据后自动保存到缓存
- ✅ **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存（默认True）

**Greeks说明**：
- **Delta**：期权价格对标的物价格变化的敏感度
- **Gamma**：Delta对标的物价格变化的敏感度
- **Theta**：期权价格随时间衰减的速度
- **Vega**：期权价格对波动率变化的敏感度
- **Rho**：期权价格对利率变化的敏感度
- **IV**：隐含波动率

**使用场景**：
- **期权定价**：使用Greeks进行期权定价和估值
- **风险管理**：评估期权持仓的风险敞口
- **策略优化**：根据Greeks调整交易策略
- **信号生成**：结合Greeks生成交易信号

---

## 支持的期权合约

### 标的ETF
- 510300: 沪深300ETF期权
- 510050: 上证50ETF期权
- 510500: 中证500ETF期权

### 合约代码格式
- 上交所期权合约代码：8位数字，如 "10010891"
- 合约代码规则：前3位为标的代码，后5位为合约信息

## 数据源

- **新浪财经**：实时数据、分钟数据、Greeks数据
- **AKShare**：实时数据（降级使用）

## 缓存机制

所有期权数据采集插件都支持缓存机制：
- 自动检查缓存，只获取缺失数据
- 支持部分缓存命中，自动合并数据
- 缓存格式：Parquet文件
- 缓存路径：`data/cache/option_{type}/{合约代码}/{日期}.parquet`

## 注意事项

1. **合约代码**：确保合约代码正确，否则无法获取数据
2. **数据源限制**：期权数据源相对有限，建议使用缓存机制
3. **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存
4. **日期格式**：支持 YYYYMMDD 和 YYYY-MM-DD 两种格式
5. **网络稳定性**：数据采集依赖网络，建议在网络稳定时执行
6. **API限制**：注意第三方API的调用频率限制

## 相关工具

- **get_contracts.py**：获取期权合约列表（见 `utils/get_contracts.py`）
- **fetch_etf_data.py**：获取标的ETF数据（见 `../etf/`）
