# 工具函数插件

本目录包含数据采集相关的工具函数插件。

## 插件列表

### 1. get_contracts.py - 期权合约列表

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

### 2. check_trading_status.py - 交易状态检查

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

## 环境变量

- `TRADING_HOURS_HOLIDAYS_2026`: 节假日列表（JSON格式），如 `["20250101", "20250210", ...]`
- `TIMEZONE_OFFSET`: 时区偏移（默认 8，即 UTC+8）

## 注意事项

- 交易状态检查依赖系统时间，确保系统时区设置正确
- 节假日列表需要定期更新
- 交易时间段为：上午 9:30-11:30，下午 13:00-15:00