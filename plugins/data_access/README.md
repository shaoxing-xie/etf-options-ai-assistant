# 数据访问工具

本目录包含从原系统读取缓存数据的工具插件。

## 插件列表

### read_cache_data.py - 读取缓存数据

**功能说明**：
- 从原系统（Windows）读取缓存数据
- 支持所有数据类型：指数日线/分钟、ETF日线/分钟、期权分钟K、期权Greeks
- **优化**：优先直接读取缓存文件（利用 Windows/WSL 文件系统共享），无需启动缓存服务
- 如果直接读取失败，自动回退到 HTTP API
- 自动处理数据序列化和反序列化（JSON ↔ DataFrame）

**使用方法**：
```python
from plugins.data_access.read_cache_data import read_cache_data

# 读取ETF日线数据
result = read_cache_data(
    data_type="etf_daily",
    symbol="510300",
    start_date="20250601",
    end_date="20260215"
)

# 读取指数分钟数据
result = read_cache_data(
    data_type="index_minute",
    symbol="000300",
    period="5",              # 周期：支持 "5" 或 "5m"（会自动规范化）
    start_date="20250115",
    end_date="20250115"
)

# 读取期权Greeks数据
result = read_cache_data(
    data_type="option_greeks",
    symbol="10010891",
    date="20260115"
)
```

**输入参数**：
- `data_type` (str, required): 数据类型，可选值：
  - `"index_daily"`: 指数日线数据
  - `"index_minute"`: 指数分钟数据
  - `"etf_daily"`: ETF日线数据
  - `"etf_minute"`: ETF分钟数据
  - `"option_minute"`: 期权分钟数据
  - `"option_greeks"`: 期权Greeks数据
- `symbol` (str, optional): 代码（指数/ETF代码或期权合约代码）
- `period` (str, optional): 周期（用于分钟数据），如 "5", "15", "30", "60"（也支持 "5m", "15m" 格式，会自动规范化）
- `start_date` (str, optional): 开始日期（YYYYMMDD格式）
- `end_date` (str, optional): 结束日期（YYYYMMDD格式）
- `date` (str, optional): 单日期（YYYYMMDD格式，用于期权数据）
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"（仅用于回退）
- `api_key` (str, optional): API Key，从环境变量 `OPENCLAW_API_KEY` 获取（仅用于回退）
- `prefer_direct` (bool): 是否优先使用直接读取，默认 True

**输出格式**：
```python
{
    "success": True,
    "message": "Data loaded successfully (direct cache access)",
    "data": {
        "df": [...],              # DataFrame 序列化为 JSON
        "columns": ["date", "open", "high", "low", "close", "volume"],
        "dtypes": {"date": "object", "close": "float64", ...},
        "shape": [100, 6]
    },
    "df": <pandas.DataFrame>,    # 重建的 DataFrame 对象
    "cache_hit": True,           # 是否命中缓存
    "missing_dates": [],          # 缺失的日期列表
    "access_method": "direct"     # 访问方式："direct" 或 "api"
}
```

**技术实现要点**：
- **直接文件访问**（优先）：
  - 利用 Windows/WSL 文件系统共享机制，直接读取缓存文件
  - 无需启动缓存服务（端口 5000）
  - 使用原系统的 `src.data_cache` 模块函数
  - 支持所有数据类型的日期范围查询
- **HTTP API 回退**：
  - 如果直接读取失败，自动回退到 HTTP API
  - 通过 HTTP GET 请求访问原系统 API
  - 支持 API Key 认证（通过 `X-API-Key` 请求头）
  - 自动处理 JSON 序列化和反序列化
- **数据处理**：
  - 从 JSON 重建 pandas DataFrame
  - 处理数据类型转换（dtypes）
  - 包含完整的错误处理

**使用场景**：
- **分析插件**：为分析插件提供数据源
- **信号生成**：读取历史数据生成交易信号
- **技术指标**：读取价格数据计算技术指标
- **趋势分析**：读取历史数据判断趋势
- **波动率预测**：读取历史数据预测波动率

**示例代码**：
```python
# 在分析插件中使用
from plugins.data_access.read_cache_data import read_cache_data

def calculate_technical_indicators(symbol="510300"):
    # 读取ETF日线数据
    cache_result = read_cache_data(
        data_type="etf_daily",
        symbol=symbol,
        start_date="20250101",
        end_date="20250115"
    )
    
    if not cache_result['success'] or cache_result['df'] is None:
        return {'success': False, 'message': 'Failed to load data'}
    
    df = cache_result['df']
    closes = df['close'].tolist()
    
    # 计算技术指标
    # ...
```

## 数据流

### 优化后的数据流（优先直接读取）

```
OpenClaw 分析插件
    ↓
调用 read_cache_data
    ↓
尝试直接读取缓存文件（Windows/WSL 共享）
    ├─ 成功 → 返回 DataFrame
    └─ 失败 → 回退到 HTTP API
            ↓
        HTTP GET 请求原系统 API
            ↓
        原系统返回 JSON 格式数据
            ↓
        反序列化为 pandas DataFrame
            ↓
        返回给分析插件使用
```

### 直接文件访问的优势

1. **无需启动服务**：不需要运行缓存服务（端口 5000），直接读取文件
2. **性能更好**：文件 I/O 比 HTTP 请求更快
3. **更稳定**：不依赖网络连接和服务状态
4. **自动降级**：如果直接读取失败，自动回退到 HTTP API

## API 端点

原系统提供的 API 端点：
- `GET /api/cache/index_daily` - 读取指数日线缓存
- `GET /api/cache/index_minute` - 读取指数分钟缓存
- `GET /api/cache/etf_daily` - 读取ETF日线缓存
- `GET /api/cache/etf_minute` - 读取ETF分钟缓存
- `GET /api/cache/option_minute` - 读取期权分钟缓存
- `GET /api/cache/option_greeks` - 读取期权Greeks缓存

## 依赖包

- `requests`: HTTP 请求
- `pandas`: DataFrame 处理

## 环境变量

- `OPENCLAW_API_KEY`: API Key，用于访问原系统 API

## 注意事项

1. **直接文件访问**：
   - 优先使用直接文件访问，利用 Windows/WSL 文件系统共享
   - 需要确保原系统的 `src.data_cache` 和 `src.config_loader` 模块可导入
   - 如果无法导入，会自动回退到 HTTP API
2. **HTTP API 回退**：
   - 如果直接读取失败，会自动回退到 HTTP API
   - 确保 OpenClaw（WSL）可以访问原系统（Windows）的 API
   - API 地址默认 `http://localhost:5000`，如果不同需要配置
3. **数据格式**：确保原系统返回的数据格式正确
4. **错误处理**：包含完整的错误处理，失败时会返回错误信息
5. **性能考虑**：大数据量时建议使用日期范围限制，避免一次性加载过多数据
6. **访问方式标识**：返回结果中包含 `access_method` 字段（`'direct'` 或 `'api'`），用于调试

## 迁移说明

- 数据访问工具是 OpenClaw 和原系统之间的桥梁
- 通过 HTTP API 访问，保持系统解耦
- 支持所有数据类型，满足分析插件的数据需求