# 数据采集插件

本目录包含宽基ETF及其期权交易助手的数据采集插件，融合了 Coze 插件的核心逻辑。

## 目录结构

```
data_collection/
├── index/              # 指数数据采集
│   ├── fetch_realtime.py      # 实时数据
│   ├── fetch_opening.py        # 开盘数据
│   ├── fetch_global.py         # 全球指数
│   ├── fetch_historical.py     # 历史数据
│   └── fetch_minute.py         # 分钟数据
├── etf/                # ETF数据采集
│   ├── fetch_historical.py    # 历史数据
│   ├── fetch_minute.py         # 分钟数据
│   └── fetch_realtime.py      # 实时数据
├── option/             # 期权数据采集
│   ├── fetch_realtime.py      # 实时数据
│   ├── fetch_minute.py        # 分钟数据
│   └── fetch_greeks.py        # Greeks数据
├── futures/            # 期货数据采集
│   └── fetch_a50.py            # A50期指
├── utils/              # 工具函数
│   ├── get_contracts.py       # 期权合约列表
│   └── check_trading_status.py # 交易状态检查
└── fetch_index_data.py # 指数数据（基础框架）
└── fetch_etf_data.py   # ETF数据（基础框架）
└── fetch_option_data.py # 期权数据（基础框架）
```

## 插件列表

### 指数数据采集

#### 1. index/fetch_realtime.py - 指数实时数据

**功能说明**：
- 获取主要指数的实时行情数据
- 融合 Coze `get_index_realtime.py` 的核心逻辑
- 支持多指数批量查询
- 支持新浪和东方财富接口，自动切换

**使用方法**：
```python
from plugins.data_collection.index.fetch_realtime import tool_fetch_index_realtime

# 获取单个指数实时数据
result = tool_fetch_index_realtime(index_code="000001")

# 获取多个指数实时数据
result = tool_fetch_index_realtime(index_code="000300,000001,399001")
```

**输入参数**：
- `index_code` (str): 指数代码，支持单个或多个（用逗号分隔）
  - 支持的指数：000001(上证指数), 399001(深证成指), 399006(创业板指), 000300(沪深300), 000016(上证50), 000905(中证500), 000852(中证1000)

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched index realtime data",
    "data": {
        "code": "000001",
        "name": "上证指数",
        "current_price": 3100.50,
        "change": 15.20,
        "change_percent": 0.49,
        "open": 3085.30,
        "high": 3105.80,
        "low": 3080.10,
        "prev_close": 3085.30,
        "volume": 2500000000,
        "amount": 35000000000,
        "timestamp": "2025-01-15 14:30:00"
    },
    "source": "stock_zh_index_spot_sina",
    "count": 1
}
```

**技术实现要点**：
- 优先使用新浪接口（`stock_zh_index_spot_sina`）
- 失败时自动切换到东方财富接口（`stock_zh_index_spot_em`）
- 支持多指数批量查询，提高效率
- 自动匹配指数代码格式（sh000001, sz399001等）
- 包含降级数据机制，确保接口失败时也能返回基本信息

**使用场景**：
- 实时监控：交易时间内实时获取指数行情
- 开盘分析：9:28集合竞价时获取开盘数据
- 趋势判断：结合实时数据判断市场趋势
- 信号生成：作为信号生成的基础数据

---

#### 2. index/fetch_opening.py - 指数开盘数据

**功能说明**：
- 获取主要指数的开盘数据（9:28集合竞价数据）
- 融合 Coze `get_index_opening_data.py` 的逻辑
- 用于开盘行情分析

**使用方法**：
```python
from plugins.data_collection.index.fetch_opening import tool_fetch_index_opening

# 获取默认指数的开盘数据
result = tool_fetch_index_opening()

# 获取指定指数的开盘数据
result = tool_fetch_index_opening(index_codes="000001,000300,399001")
```

**输入参数**：
- `index_codes` (str, optional): 指数代码字符串，用逗号分隔，如 "000001,000300"
  - 如果不提供，使用默认配置：000001(上证指数), 000016(上证50), 399001(深证成指), 399006(创业板指), 000688(科创综指), 000300(沪深300)

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched index opening data",
    "data": [
        {
            "name": "上证指数",
            "code": "000001",
            "open_price": 3085.30,
            "close_yesterday": 3085.30,
            "change_pct": 0.15,
            "volume": 500000000,
            "timestamp": "2025-01-15 09:28:00"
        }
    ],
    "count": 6
}
```

**技术实现要点**：
- 在9:28集合竞价时间调用，获取开盘价和开盘涨跌幅
- 支持新浪和东方财富接口，自动切换
- 返回列表格式，包含多个指数的开盘数据
- 注意：非9:28时调用，涨跌幅和成交量为实时值

**使用场景**：
- **开盘分析（9:28）**：获取集合竞价数据，用于开盘行情分析
- **开盘策略**：基于开盘数据调整交易策略
- **风险控制**：开盘异常时及时预警

---

#### 3. index/fetch_global.py - 全球指数数据

**功能说明**：
- 获取全球主要指数的实时行情数据
- 融合 Coze `get_index_global_spot.py` 的逻辑
- 用于盘后分析和开盘前分析

**使用方法**：
```python
from plugins.data_collection.index.fetch_global import tool_fetch_global_index_spot

# 获取默认全球指数数据
result = tool_fetch_global_index_spot()

# 获取指定全球指数数据
result = tool_fetch_global_index_spot(index_codes="int_dji,int_nasdaq,int_sp500")
```

**输入参数**：
- `index_codes` (str, optional): 指数代码列表（用逗号分隔）
  - 如果不提供，默认返回：int_dji(道琼斯), int_nasdaq(纳斯达克), int_sp500(标普500), int_nikkei(日经225), rt_hkHSI(恒生指数)
  - 支持的指数代码：int_dji, int_nasdaq, int_sp500, int_nikkei, rt_hkHSI

**输出格式**：
```python
{
    "success": True,
    "count": 5,
    "data": [
        {
            "code": "int_dji",
            "name": "道琼斯",
            "price": 38500.50,
            "change": 150.20,
            "change_pct": 0.39,
            "timestamp": "2025-01-15 14:30:00"
        }
    ],
    "source": "hq.sinajs.cn",
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 使用新浪财经 `hq.sinajs.cn` 接口
- 支持GBK编码解码
- 支持恒生指数多种代码格式自动匹配
- 包含错误处理和降级机制

**使用场景**：
- **盘后分析**：分析外盘表现，预测次日A股走势
- **开盘前分析**：结合外盘数据，给出开盘策略建议
- **全球市场监控**：实时监控全球主要指数表现

---

#### 4. index/fetch_historical.py - 指数历史数据

**功能说明**：
- 获取主要指数的历史日线数据
- 融合 Coze `get_index_historical.py` 的核心逻辑
- 支持多指数批量查询
- 支持缓存机制，提高数据获取效率

**使用方法**：
```python
from plugins.data_collection.index.fetch_historical import tool_fetch_index_historical

# 获取单个指数历史数据
result = tool_fetch_index_historical(
    index_code="000300",           # 指数代码
    start_date="20250101",         # 开始日期（可选）
    end_date="20250115"            # 结束日期（可选）
)

# 获取多个指数历史数据
result = tool_fetch_index_historical(
    index_code="000300,000001,399001"  # 多个指数代码，用逗号分隔
)
```

**输入参数**：
- `index_code` (str): 指数代码，支持单个或多个（用逗号分隔）
  - 支持的指数：000001(上证指数), 399001(深证成指), 399006(创业板指), 000300(沪深300), 000016(上证50), 000905(中证500), 000852(中证1000)
- `start_date` (str, optional): 开始日期（YYYYMMDD 或 YYYY-MM-DD），默认回看30天
- `end_date` (str, optional): 结束日期（YYYYMMDD 或 YYYY-MM-DD），默认当前日期
- `use_cache` (bool): 是否使用缓存，默认 True
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched index historical data",
    "data": {
        "000300": {
            "index_code": "000300",
            "index_name": "沪深300",
            "count": 250,
            "klines": [
                {
                    "date": "2025-01-15",
                    "open": 3850.50,
                    "close": 3870.20,
                    "high": 3880.00,
                    "low": 3845.30,
                    "volume": 1500000000,
                    "amount": 58000000000,
                    "change": 19.70,
                    "change_percent": 0.51
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
- 降级使用新浪财经接口（`stock_zh_index_daily`）
- 支持缓存机制：自动检查缓存，只获取缺失数据
- 支持部分缓存命中：自动合并缓存和新获取的数据
- 自动计算成交额和涨跌幅
- 支持日期格式自动转换（YYYYMMDD 和 YYYY-MM-DD）

**缓存机制**：
- ✅ **支持缓存**：历史数据支持Parquet格式缓存（按日期拆分保存）
- ✅ **缓存合并**：支持部分缓存命中时自动合并缓存和新获取的数据
- ✅ **缓存路径**：`data/cache/index_daily/{指数代码}/{YYYYMMDD}.parquet`
- ✅ **自动保存**：获取数据后自动保存到缓存
- ✅ **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存（默认True）

**使用场景**：
- **历史分析**：获取指数历史价格数据，用于技术分析
- **回测**：为策略回测提供历史数据
- **趋势判断**：分析指数长期趋势
- **数据补全**：补充缺失的历史数据

---

#### 5. index/fetch_minute.py - 指数分钟数据

**功能说明**：
- 获取主要指数的分钟K线数据
- 融合 Coze `get_index_minute.py` 的核心逻辑
- 支持多种周期：5分钟、15分钟、30分钟、60分钟
- 支持缓存机制

**使用方法**：
```python
from plugins.data_collection.index.fetch_minute import tool_fetch_index_minute

# 获取指数分钟数据
result = tool_fetch_index_minute(
    index_code="000300",           # 指数代码
    period="30",                    # 周期："1", "5", "15", "30", "60"
    lookback_days=5,               # 回看天数，默认5天
    start_date="20250115",         # 开始日期（可选）
    end_date="20250115"            # 结束日期（可选）
)
```

**输入参数**：
- `index_code` (str): 指数代码，如 "000300"
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
    "message": "Successfully fetched index minute data",
    "data": {
        "index_code": "000300",
        "index_name": "沪深300",
        "period": "30",
        "count": 120,
        "klines": [
            {
                "datetime": "2025-01-15 09:30:00",
                "open": 3850.50,
                "close": 3855.20,
                "high": 3858.00,
                "low": 3848.30,
                "volume": 50000000
            }
        ],
        "source": "sina"
    },
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 优先使用新浪财经接口（`stock_zh_index_min_em`）
- 降级使用东方财富接口
- 支持缓存机制：自动检查缓存，只获取缺失数据
- 支持部分缓存命中：自动合并缓存和新获取的数据
- 自动处理非交易日，确保数据连续性

**缓存机制**：
- ✅ **支持缓存**：分钟数据支持Parquet格式缓存（按日期拆分保存）
- ✅ **缓存合并**：支持部分缓存命中时自动合并缓存和新获取的数据
- ✅ **缓存路径**：`data/cache/index_minute/{指数代码}/{period}/{YYYYMMDD}.parquet`
- ✅ **自动保存**：获取数据后自动保存到缓存
- ✅ **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存（默认True）

**使用场景**：
- **日内分析**：获取指数日内分钟数据，用于日内交易分析
- **技术指标**：为技术指标计算提供分钟级数据
- **波动率预测**：为波动率预测提供分钟级数据
- **实时监控**：实时获取指数价格变化

---

### ETF数据采集

ETF数据采集插件位于 `etf/` 目录，包含以下工具：

- **fetch_historical.py** - ETF历史数据：获取ETF的历史日线数据
- **fetch_minute.py** - ETF分钟数据：获取ETF的分钟K线数据
- **fetch_realtime.py** - ETF实时数据：获取ETF的实时行情数据

详细说明请参考：[etf/README.md](./etf/README.md)

---

### 期权数据采集

期权数据采集插件位于 `option/` 目录，包含以下工具：

- **fetch_realtime.py** - 期权实时数据：获取期权合约的实时行情数据
- **fetch_minute.py** - 期权分钟数据：获取期权合约的分钟K线数据
- **fetch_greeks.py** - 期权Greeks数据：获取期权合约的Greeks数据（Delta、Gamma、Theta、Vega等）

详细说明请参考：[option/README.md](./option/README.md)

---

### 期货数据采集

#### 6. futures/fetch_a50.py - A50期指数据

**功能说明**：
- 获取富时A50期指（期货）的实时和历史数据
- 融合 Coze `get_a50_index_data.py` 的逻辑
- 用于盘后分析

**使用方法**：
```python
from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data

# 获取A50期指数据（实时+历史）
result = tool_fetch_a50_data(
    symbol="A50期指",
    data_type="both",              # "spot", "hist", "both"
    start_date="20250101",         # 可选，默认回看30天
    end_date="20250115"            # 可选，默认当前日期
)
```

**输入参数**：
- `symbol` (str): 指数名称，目前仅支持 "A50期指"
- `data_type` (str): 数据类型，"spot"（实时）, "hist"（历史）, "both"（两者）
- `start_date` (str, optional): 历史数据开始日期（YYYYMMDD 或 YYYY-MM-DD），默认回看30天
- `end_date` (str, optional): 历史数据结束日期（YYYYMMDD 或 YYYY-MM-DD），默认当前日期

**输出格式**：
```python
{
    "success": True,
    "symbol": "A50期指",
    "source": "mixed",
    "spot_data": {
        "current_price": 12500.50,
        "change_pct": 0.25,
        "volume": 50000,
        "timestamp": "2025-01-15 14:30:00"
    },
    "hist_data": {
        "count": 30,
        "klines": [
            {
                "date": "2025-01-15",
                "open": 12450.00,
                "close": 12500.50,
                "high": 12520.00,
                "low": 12430.00,
                "volume": 50000
            }
        ]
    },
    "timestamp": "2025-01-15 14:30:00"
}
```

**技术实现要点**：
- 实时数据使用东方财富期货接口（`futures_global_spot_em`）
- 历史数据使用新浪财经接口（`futures_foreign_hist`）
- 支持日期格式自动转换（YYYYMMDD 和 YYYY-MM-DD）
- 包含错误处理和降级机制

**使用场景**：
- **盘后分析**：分析A50期指表现，预测次日A股走势
- **外盘监控**：实时监控A50期指价格变化
- **趋势判断**：结合A50期指判断市场趋势

---

### 工具函数

#### 7. utils/get_contracts.py - 期权合约列表

**功能说明**：
- 获取指定标的的上交所（SSE）期权合约列表
- 融合 Coze `get_option_contracts.py` 的逻辑
- 包括认购和认沽期权

**使用方法**：
```python
from plugins.data_collection.utils.get_contracts import tool_get_option_contracts

# 获取期权合约列表
result = tool_get_option_contracts(
    underlying="510300",           # 标的代码
    option_type="all"              # "call", "put", "all"
)
```

**输入参数**：
- `underlying` (str): 标的代码，如 "510300"(300ETF), "510050"(50ETF), "510500"(500ETF)
- `option_type` (str): 期权类型 "call"(认购)/"put"(认沽)/"all"(全部)，默认 "all"

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully fetched 20 contracts",
    "data": {
        "underlying": "510300",
        "underlying_name": "沪深300ETF",
        "option_type": "all",
        "contracts": [
            {
                "contract_code": "10010891",
                "option_type": "call",
                "trade_month": "202502"
            },
            {
                "contract_code": "10010896",
                "option_type": "put",
                "trade_month": "202502"
            }
        ],
        "count": 20
    }
}
```

**技术实现要点**：
- 使用新浪接口（`option_sse_list_sina`, `option_sse_codes_sina`）
- 支持获取到期月份列表
- 遍历月份获取合约代码
- 只取最近2个月份，提高效率

**使用场景**：
- **合约管理**：动态获取可交易期权合约
- **信号生成**：为信号生成提供合约列表
- **数据采集**：批量采集期权数据时获取合约列表

---

#### 8. utils/check_trading_status.py - 交易状态检查

**功能说明**：
- 判断当前是否是交易时间
- 融合 Coze `check_trading_status.py` 的逻辑
- 返回市场状态信息

**使用方法**：
```python
from plugins.data_collection.utils.check_trading_status import tool_check_trading_status

# 检查交易状态
result = tool_check_trading_status()
```

**输入参数**：
- 无（自动获取当前时间）

**输出格式**：
```python
{
    "success": True,
    "data": {
        "status": "trading",              # "before_open", "trading", "lunch_break", "after_close", "non_trading_day"
        "market_status_cn": "交易中",
        "is_trading_time": True,
        "is_trading_day": True,
        "current_time": "2025-01-15 14:30:00",
        "next_trading_time": "2025-01-15 15:00:00",
        "remaining_minutes": 30,
        "timezone": "Asia/Shanghai"
    }
}
```

**技术实现要点**：
- 判断交易日（排除周末和节假日）
- 判断交易时间段（9:30-11:30, 13:00-15:00）
- 支持时区配置（默认 Asia/Shanghai）
- 支持节假日列表配置（从环境变量获取）
- 计算剩余交易时间和下次交易时间

**使用场景**：
- **定时任务**：判断是否在交易时间，决定是否执行任务
- **数据采集**：只在交易时间内采集实时数据
- **信号生成**：只在交易时间内生成交易信号
- **系统状态**：显示当前市场状态

---

## 数据流

```
数据采集插件
    ↓
调用第三方API（新浪、东方财富、Tushare）
    ↓
获取市场数据
    ↓
通过 API 写入原系统缓存
    ↓
原系统保存为 Parquet 文件
```

## 依赖包

- `akshare`: 数据采集库（主要数据源）
- `requests`: HTTP 请求
- `pandas`: 数据处理
- `pytz`: 时区处理

## 环境变量

- `OPENCLAW_API_KEY`: API Key，用于访问原系统 API
- `TRADING_HOURS_HOLIDAYS_2026`: 节假日列表（JSON格式）

## 注意事项

1. **数据源优先级**：按配置的优先级自动切换数据源
2. **错误处理**：包含完整的错误处理和重试机制
3. **数据格式**：确保写入缓存的数据格式符合原系统要求
4. **API 连接**：确保原系统 API 服务正常运行
5. **网络稳定性**：数据采集依赖网络，建议在网络稳定时执行

## 迁移说明

- 数据采集逻辑融合了 Coze 插件的核心功能
- 通过 API 写入原系统缓存，保持数据一致性
- 插件设计保持独立性，不直接依赖原系统代码