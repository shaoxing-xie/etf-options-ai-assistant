# 数据访问（本地缓存读取）

本目录提供 **`read_cache_data()`**：从项目配置的 **Parquet 本地缓存** 读取指数 / ETF / 期权数据，是「读缓存」能力的**唯一实现层**（不是独立 HTTP 微服务）。

## 在工程中的位置

| 层级 | 说明 |
|------|------|
| OpenClaw 对外工具 | `plugins/merged/read_market_data.py` → `tool_read_market_data`（支持 `data_type` / `data_types` 多类型） |
| 别名 | `tool_read_index_daily` 等在 `tool_runner.py` 中映射到 `tool_read_market_data` + 注入 `data_type` |
| 实现 | **`plugins/data_access/read_cache_data.py`** → `read_cache_data()`，内部调用 **`src.data_cache`** |

分析插件（如技术指标、风险评估）可直接 `from plugins.data_access.read_cache_data import read_cache_data`，需要 DataFrame 时传 **`return_df=True`**。

## `read_cache_data` 行为摘要

- **数据源**：`src.data_cache`（`get_cached_index_daily` / `etf_*` / `option_*` 等），路径与根目录由系统配置中的数据目录决定。
- **工具输出**：默认 **`return_df=False`**，将 DataFrame 转为 **records**（时间列转字符串），便于 JSON 序列化；分析代码可设 **`return_df=True`** 直接拿 **`df`**。
- **分钟线补数**（仅 `index_minute` / `etf_minute`）：若按日期范围读缓存存在 **缺失日**，会尝试通过 **`src.data_collector`**（新浪优先，失败则东财等）拉取并写回缓存后再读；仍不完整时 **`success=False`**，并可能带 **`source: cache_partial`** 与已有 `records`。
- **日线**：缺日期时同样可能 **`success=False`** + 部分数据 + `missing_dates`。
- **期权**：`option_greeks` 支持 **`use_closest=True`**（缺当日缓存时回退最近交易日）。

当前实现**不**经 `localhost:5000` HTTP 读缓存；若文档其它处仍写「原系统 API 回退」，以 **`read_cache_data.py` 源码为准**。

## 参数与 `data_type`

| `data_type` | 必填参数 | 说明 |
|-------------|----------|------|
| `index_daily` / `etf_daily` | `symbol`, `start_date`, `end_date`（YYYYMMDD） | 日线区间 |
| `index_minute` / `etf_minute` | `symbol`, `period`, `start_date`, `end_date` | 分钟周期如 `5`、`15`；缺数据时会尝试补拉 |
| `option_minute` | `symbol`（合约代码）, `date`；可选 `period` | `date` 可取前 8 位 YYYYMMDD |
| `option_greeks` | `symbol`, `date` | 见 `use_closest` |

## 调用示例

```python
from plugins.data_access.read_cache_data import read_cache_data

# 工具风格：返回 records
out = read_cache_data(
    data_type="etf_daily",
    symbol="510300",
    start_date="20250101",
    end_date="20250131",
)
# out["success"], out["data"]["records"], out.get("source")

# 分析风格：要 DataFrame
out_df = read_cache_data(
    data_type="etf_daily",
    symbol="510300",
    start_date="20250101",
    end_date="20250131",
    return_df=True,
)
# out_df["df"] 为 pandas.DataFrame 或 None
```

合并工具侧（Agent 调用名）示例见 `tool_read_market_data` / `config/tools_manifest.yaml`。

## 依赖

- **缓存层**：`src.data_cache`（pandas / parquet）
- **分钟补数**（可选路径）：`src.data_collector` 中指数/ETF 分钟拉取函数

## 相关测试与文档

- 冒烟：`tests/test_smoke_tool_runner.py`（`tool_read_market_data`）
- 集成：`tests/integration/run_merged_tools_smoke.py`（别名 → 合并工具）

## 工作流引用（读缓存类）

以下工作流通过 **`tool_read_*`**（别名指向 `tool_read_market_data`）读本地缓存，与本模块一致：

- `workflows/signal_generation.yaml` — `tool_read_etf_daily`
- `workflows/etf_510300_intraday_monitor.yaml` — `tool_read_etf_minute`、`tool_read_index_minute`

更全的工作流索引见 `workflows/README.md`。
