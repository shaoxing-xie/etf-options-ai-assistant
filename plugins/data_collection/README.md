# 数据采集插件

本目录为 **etf-options-ai-assistant** 的数据采集层：以宽基 ETF 与上交所 ETF 期权行情为主，并扩展 A 股个股、板块、涨停、资金流向、龙虎榜、财务指标等数据，供 OpenClaw / Agent 工作流调用。多数模块融合原 Coze 插件逻辑，通过 AkShare、新浪、东方财富等公开接口拉取数据，部分能力支持写入原系统缓存（Parquet）或项目内 JSON 报告。

**详细路线图与 Provider 矩阵**见 [ROADMAP.md](./ROADMAP.md)（与本文档互链）。

## OpenClaw 工具索引（标的物 → 数据域 → 周期）

下列 `tool_*` 与项目根目录 [`tool_runner.py`](../../tool_runner.py) 中 `TOOL_MAP` / `COPILOT_TOOLS` 的注册名对照，便于 Agent 与运维统一检索。

### 标的物：A 股股票（`stock/`）

| 数据域 | 周期/子类 | 模块 | `tool_*` | `TOOL_MAP` 注册名 |
|--------|-----------|------|----------|-------------------|
| 行情 | 实时 | `stock/fetch_realtime.py` | `tool_fetch_stock_realtime` | `tool_fetch_stock_realtime` |
| 行情 | 分钟 | `stock/fetch_minute.py` | `tool_fetch_stock_minute` | `tool_fetch_stock_minute` |
| 行情 | 日线 | `stock/fetch_historical.py` | `tool_fetch_stock_historical` | `tool_fetch_stock_historical` |
| 基础/聚合 | — | `stock/stock_data_fetcher.py` | `tool_stock_data_fetcher`，`tool_stock_monitor` | 同左 |
| 财务/估值 | — | `financials.py` | `tool_fetch_stock_financials` | `tool_fetch_stock_financials` |

**与 Coze「AKShare 股票行情」插件对照**：本平台股票日线已含新浪、东财、`stock_zh_a_hist_tx`（腾讯）及置后的 Tushare(EOD)；分钟线支持 `minute_source_preference`（auto/sina/eastmoney/efinance）；实时为 mootdx → 东财五档（单票可选）→ 腾讯 HTTP → `stock_zh_a_spot`。详见 [ROADMAP.md](./ROADMAP.md)。

### 标的物：ETF（`etf/`）

| 数据域 | 周期 | 说明 | `TOOL_MAP` |
|--------|------|------|------------|
| 行情 | 日/分/实时 | 见 [etf/README.md](./etf/README.md)，根目录另有 `merged.fetch_etf_data` | `tool_fetch_etf_data`，`tool_fetch_etf_minute_direct` |
| 行情扩展 | IOPV/折价 | `etf/fetch_realtime.fetch_etf_iopv_snapshot` | `tool_fetch_etf_iopv_snapshot` |

### 标的物：指数 / 期权 / 期货

| 标的物 | 数据域 | 入口 | `TOOL_MAP`（节选） |
|--------|--------|------|-------------------|
| 指数 | 行情 | `index/*`，`merged.fetch_index_data` | `tool_fetch_index_data` |
| 期权 | 行情/Greeks | `option/*`，`merged.fetch_option_data` | `tool_fetch_option_data` |
| 期货 | A50 | `futures/fetch_a50.py` | `tool_fetch_a50_data` |

### 板块 / 资金 / 涨停 / 工具

| 场景 | `tool_*` | `TOOL_MAP` 注册名 |
|------|----------|-------------------|
| 涨停与板块热度 | `tool_fetch_limit_up_stocks`，`tool_sector_heat_score`，`tool_write_limit_up_with_sector`，`tool_limit_up_daily_flow` | 同左 |
| 龙虎榜 / 资金 / 北向 | `tool_dragon_tiger_list`，`tool_capital_flow`，`tool_fetch_northbound_flow` | 同左 |
| 交易状态 / 可交易性 | `tool_check_trading_status`，`tool_get_a_share_market_regime`，`tool_filter_a_share_tradability` | 同左 |
| 期权合约列表 | `tool_get_option_contracts` | `tool_get_option_contracts` |

### 标的映射配置

ETF ↔ 指数 ↔ 期权标的的静态对照见 [config/symbol_mapping.yaml](./config/symbol_mapping.yaml)，供策略层解析代码时减少魔法字符串。

## 功能地图（按场景）

| 场景 | 主要入口 |
|------|----------|
| 指数 / ETF / 期权 / A50 期货行情 | `index/`、`etf/`、`option/`、`futures/`；或根目录 `fetch_*_data.py` 简版工具 |
| 个股实时、日线、分钟、聚合拉取 | `stock/`、`financials.py` |
| 涨停、板块热度、盘后 JSON / 报告 | `limit_up/`、`sector.py` |
| 北向资金、个股资金流向、龙虎榜 | `northbound.py`、`capital_flow.py`、`dragon_tiger.py` |
| 交易时段 / 可交易性 / 批量并行 | `utils/` |
| Tick（需项目 `tick_client` + `config.yaml`） | `tick/fetch_tick.py` |

子目录中更细的字段说明见：`index/README.md`、`etf/README.md`、`option/README.md`、`futures/README.md`、`utils/README.md`。

## 目录结构

```
data_collection/
├── ROADMAP.md               # 路线图：分类框架、Provider 矩阵、附录（与本文互链）
├── __init__.py
├── config/                  # 标的映射等静态配置（symbol_mapping.yaml）
├── providers/               # Provider 链再导出（如 A 股实时）
├── fetch_index_data.py      # OpenClaw 简版：指数日线/分钟 + 写缓存
├── fetch_etf_data.py        # OpenClaw 简版：ETF 日线/分钟 + 写缓存
├── fetch_option_data.py     # OpenClaw 简版：期权 Greeks/分钟 + 写缓存
├── financials.py            # A 股财务指标（PE/PB/ROE/股息率等）
├── sector.py                # 板块轮动（行业/概念）
├── northbound.py            # 北向资金流向
├── capital_flow.py          # 个股资金流向
├── dragon_tiger.py          # 龙虎榜 + 涨停池联动（短线研究）
├── index/
│   ├── fetch_realtime.py / fetch_opening.py / fetch_global.py
│   ├── fetch_historical.py / fetch_minute.py
│   └── 指数采集工具与原始接口说明.md
├── etf/
│   ├── fetch_historical.py / fetch_minute.py / fetch_realtime.py
├── option/
│   ├── fetch_realtime.py / fetch_minute.py / fetch_greeks.py
├── futures/
│   └── fetch_a50.py
├── stock/
│   ├── fetch_realtime.py / fetch_historical.py / fetch_minute.py
│   └── stock_data_fetcher.py   # 聚合拉取 + 可选技术指标
├── limit_up/
│   ├── fetch_limit_up.py       # 涨停池
│   ├── sector_heat.py            # 板块热度评分
│   └── daily_report.py           # 盘后 JSON / Markdown 报告
├── tick/
│   └── fetch_tick.py             # Tick + 质量报告（依赖 tick_client）
└── utils/
    ├── get_contracts.py
    ├── check_trading_status.py
    ├── batch_fetch.py            # 批量并行 ETF/指数/期权
    ├── a_share_market_regime.py  # A 股细分时段（集合竞价/连续竞价等）
    └── a_share_tradability_filter.py  # 可交易性启发式过滤
```

## 插件列表

### 指数数据采集

#### 指数代码约定（`index/index_code_utils.py`）

- **无白名单**：任意 **6 位数字**指数代码（及 `sh`/`sz` 前缀、`.SH`/`.SZ` 后缀）均可进入查询；能否取到数据取决于各数据源是否收录该指数。
- **新浪 / 东财 等 symbol**：以 **39** 开头 → `sz` + 代码（深证）；否则 → `sh` + 代码（上证及北证等按同一规则映射，实际可用性因源而异）。
- **ETF**：代码以 **5** 或 **1** 开头的 6 位在 `fetch_realtime` / `fetch_historical` / `fetch_minute` 中会**自动改调 ETF 专用模块**，不走路径内的「纯指数」逻辑。

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
- `index_code` (str): 指数代码，支持单个或多个（用逗号分隔）；规则见本节「指数代码约定」

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
- 顺序：**mootdx quotes（批量）** → AkShare 全量指数快照（新浪/东财，短缓存）→ **mootdx 1 分钟 K** 兜底
- 无指数白名单；名称展示用 `index_display_name`（常见代码有中文名）
- 支持多指数批量查询；代码统一规范为 6 位数字
- 包含降级数据机制，单代码全失败时返回占位信息

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
- `index_codes` (str, optional): 指数代码字符串，用逗号分隔，如 "000001,000300"；支持 6 位代码或 `sh/sz` 前缀（与 `index_code_utils` 一致）
  - 如果不提供，使用默认配置：`000001,399006,399001,000688,000300,899050`

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
- 优先新浪/东财（akshare），自动切换
- 若 akshare 不可用，则降级用 mootdx quotes 返回开盘近似/快照
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
- `index_code` (str): 指数代码，支持单个或多个（用逗号分隔）；规则见「指数代码约定」
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
- 获取指数分钟 K 线数据
- 融合 Coze `get_index_minute.py` 的核心逻辑
- 支持多种周期：1/5/15/30/60 分钟；数据源：缓存 → mootdx → 新浪 HTTP → 东财（akshare 可选），**不强制安装 akshare**
- 支持缓存机制；指数代码规则见「指数代码约定」

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
- `index_code` (str): 指数代码（6 位或 sh/sz），支持逗号多代码
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
- 优先 **mootdx** 与 **新浪 HTTP** `CN_MarketData.getKLineData`；再可选 **akshare** `index_zh_a_hist_min_em`
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

### OpenClaw 根目录快捷入口（简版采集）

与 `index/`、`etf/`、`option/` 下功能更完整的 `tool_*` 并存：以下三个文件提供 **单标的、AkShare 直连、可选 POST 原系统缓存** 的薄封装，便于在 OpenClaw 中快速注册工具。

| 文件 | 核心函数 | 说明 |
|------|----------|------|
| `fetch_index_data.py` | `fetch_index_data`，`tool_fetch_index_daily`，`tool_fetch_index_minute` | 指数日线（`index_zh_a_hist`）或分钟（`index_zh_a_hist_min_em`） |
| `fetch_etf_data.py` | `fetch_etf_data`，`tool_fetch_etf_daily`，`tool_fetch_etf_minute` | ETF 日线（`fund_etf_hist_em`）或分钟（`fund_etf_hist_min_em`） |
| `fetch_option_data.py` | `fetch_option_data`，`tool_fetch_option_greeks`，`tool_fetch_option_minute` | 期权 spot/greeks/minute（AkShare 上交所接口）；简版工具目前导出 Greeks 与分钟 |

```python
from plugins.data_collection.fetch_index_data import tool_fetch_index_daily
from plugins.data_collection.fetch_etf_data import tool_fetch_etf_daily
from plugins.data_collection.fetch_option_data import tool_fetch_option_greeks
```

---

### 股票数据采集（`stock/`）

| 模块 | 工具函数 | 说明 |
|------|----------|------|
| `stock/fetch_realtime.py` | `tool_fetch_stock_realtime` | 个股实时行情（支持多代码） |
| `stock/fetch_historical.py` | `tool_fetch_stock_historical` | 个股日线历史 |
| `stock/fetch_minute.py` | `tool_fetch_stock_minute` | 个股分钟 K 线 |
| `stock/stock_data_fetcher.py` | `tool_stock_data_fetcher`，`tool_stock_monitor` | 聚合拉取实时/日线/分钟/财务，可选技术指标与 watchlist 检查 |

财务指标另见根目录 **`financials.py`** → `tool_fetch_stock_financials`（东方财富主要财务指标，供估值因子使用）。

---

### 涨停、板块与短线研究（`limit_up/` 与相关）

| 模块 | 工具函数 | 说明 |
|------|----------|------|
| `limit_up/fetch_limit_up.py` | `tool_fetch_limit_up_stocks` | 涨停池（AkShare `stock_zt_pool_em`），支持单日或区间；可过滤 ST、尾盘涨停等 |
| `limit_up/sector_heat.py` | `tool_sector_heat_score` | 结合涨停列表与板块数据计算热度 0–100 与周期阶段（启动/发酵/等） |
| `limit_up/daily_report.py` | `tool_write_limit_up_with_sector`，`tool_limit_up_daily_flow` | 盘后写入 `data/limit_up_research/`，可选 Markdown 报告与飞书通知 |
| `sector.py` | `tool_fetch_sector_data` | 行业/概念板块涨跌与轮动（东方财富优先，AkShare 备用） |
| `dragon_tiger.py` | `tool_dragon_tiger_list` | 涨停池 ∩ 龙虎榜明细，输出游资相关摘要（依赖 AkShare） |
| `capital_flow.py` | `tool_capital_flow` | 个股主力/散户资金流向与简单风险标签 |
| `northbound.py` | `tool_fetch_northbound_flow` | 沪深港通北向资金（东方财富接口） |

插件内导入已统一为 `from plugins.data_collection...`（以项目根目录在 `PYTHONPATH` 中为前提）。

---

### Tick 行情（`tick/fetch_tick.py`）

- **函数**：`fetch_tick_with_quality`（非 `tool_` 前缀），供 `etf_data_collector_agent` 等调用。
- **依赖**：项目根目录的 `tick_client.get_best_tick` 与 `config.yaml`；仅支持指数/股票逻辑标的，文档建议关注 `000300`、`399006` 等。
- **返回**：`symbol`、`ok`、`tick`、`quality`（延迟、provider、错误等）。

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

#### 9. utils/batch_fetch.py - 批量并行采集

**功能说明**：

- `batch_fetch_parallel`：对任意列表并行调用 `fetch_func`，汇总成功/失败与耗时。
- `tool_fetch_multiple_etf_realtime` / `tool_fetch_multiple_index_realtime` / `tool_fetch_multiple_option_realtime` / `tool_fetch_multiple_option_greeks`：基于 `ThreadPoolExecutor` 批量拉取 ETF/指数/期权实时或 Greeks，适合监控多标的。

**使用方法**：

```python
from plugins.data_collection.utils.batch_fetch import tool_fetch_multiple_etf_realtime

result = tool_fetch_multiple_etf_realtime(
    etf_codes=["510300", "510050", "510500"],
    max_workers=5,
    timeout=30.0,
)
```

---

#### 10. utils/a_share_market_regime.py - A 股细分时段

**功能说明**：

- `tool_get_a_share_market_regime`：在 `tool_check_trading_status` 粗粒度状态之外，细分集合竞价、连续竞价、午休、收盘集合竞价、盘后等，并给出策略降级建议（避免非连续竞价时段误用波动率信号）。
- 节假日与 `check_trading_status` 共用环境变量 `TRADING_HOURS_HOLIDAYS_2026`。

---

#### 11. utils/a_share_tradability_filter.py - 可交易性过滤

**功能说明**：

- `tool_filter_a_share_tradability`：基于 `tool_fetch_stock_realtime` 快照做启发式判断（停牌、涨跌停等），用于上层 Guard；非权威停复牌数据源，输出结构便于扩展。

---

## 数据流

```
数据采集插件
    ↓
调用第三方 API（AkShare / 新浪 / 东方财富 / Tushare 等，按模块而定）
    ↓
获取市场数据
    ↓
可选：通过 HTTP API 写入原系统缓存（根目录 fetch_*_data、部分 index/etf/option 工具）
    ↓
可选：本地 Parquet / JSON（如 index 日线缓存、limit_up 研究报告）
```

## 依赖包

- `akshare`: 主要数据源封装
- `requests`: HTTP 请求（东方财富、新浪等）
- `pandas`: 数据处理
- `pytz`: 时区处理

Tick 与部分部署另需：项目内 `tick_client`、根目录 `config.yaml`；若使用原系统缓存写入，需远端 API 可用。

## 环境变量

- `OPENCLAW_API_KEY`: API Key，用于访问原系统 API（`fetch_*_data.py` 及部分写缓存逻辑）
- `TRADING_HOURS_HOLIDAYS_2026`: 节假日列表（JSON 数组，元素为 `YYYYMMDD` 字符串），供 `check_trading_status` 与 `a_share_market_regime` 使用
- `TIMEZONE_OFFSET`（可选）：`check_trading_status` 使用的时区偏移，见 `utils/README.md`

## 注意事项

1. **两套入口**：同一类数据既有「根目录 `fetch_*_data` + `tool_fetch_*`」简版，也有 `index/`、`etf/`、`option/` 下带缓存合并、多标的、多数据源的完整实现，按场景选择。
2. **数据源与限频**：公开接口可能变更或限流；生产环境建议加重试、缓存与降级。
3. **写入缓存**：需原系统 API 与 `OPENCLAW_API_KEY` 配置正确；Parquet 路径以各模块实现为准（如 `data/cache/index_daily/...`）。
4. **包导入**：以项目根加入 `PYTHONPATH`，统一使用 `from plugins.data_collection...`。

## 迁移说明

- 数据采集逻辑融合了 Coze 插件的核心功能。
- 通过 API 写入原系统缓存的模块保持与主系统数据格式一致。
- 插件目录相对独立；新增 A 股扩展（涨停、资金、龙虎榜等）与期权主链路解耦，可按需引用。