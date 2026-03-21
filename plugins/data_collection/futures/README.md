# 期货数据采集插件

本目录包含期货数据采集相关的插件工具。

## 插件列表

### fetch_a50.py - A50期指数据

**功能说明**：
- 获取富时A50期指（期货）的实时和历史数据
- 融合 Coze `get_a50_index_data.py` 的逻辑
- 用于盘后分析

**使用方法**：
```python
from plugins.data_collection.futures.fetch_a50 import tool_fetch_a50_data

# 获取A50期指数据（实时+历史）
result =  (
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
- 历史数据使用新浪财经接口（`futures_foreign_hist`，使用 "CHA50CFD" 代码）
- 支持日期格式自动转换（YYYYMMDD 和 YYYY-MM-DD）
- 包含错误处理和降级机制

**缓存机制**（历史数据）：
- ✅ **支持缓存**：历史数据支持Parquet格式缓存（按日期拆分保存）
- ✅ **缓存合并**：支持部分缓存命中时自动合并缓存和新获取的数据
- ✅ **缓存路径**：`data/cache/futures_daily/A50/{YYYYMMDD}.parquet`
- ✅ **自动保存**：获取数据后自动保存到缓存
- ✅ **缓存控制**：可通过 `use_cache` 参数控制是否使用缓存（默认True）

**合约选择策略**（采用Coze版本的详细策略）：
- **去重处理**：按合约代码去重，避免重复合约
- **自动识别列**：自动识别价格列和成交量列（支持多种列名变体）
- **三级筛选策略**：
  1. 优先选择有价格数据且成交量最大的合约（主力合约）
  2. 如果没有有价格的合约，选择成交量最大的合约
  3. 如果都没有交易数据，按代码排序选择最近月份的合约
- **严格NaN处理**：逐个尝试多个可能的列名，严格处理NaN值
- **返回完整信息**：返回合约代码、名称、价格、涨跌幅、成交量等完整信息

**使用场景**：
- **盘后分析**：分析A50期指表现，预测次日A股走势
- **外盘监控**：实时监控A50期指价格变化
- **趋势判断**：结合A50期指判断市场趋势

## 注意事项

- 本工具仅支持A50期指（期货），不支持股票指数
- 数据源：实时数据使用东方财富期货接口，历史数据使用新浪财经接口