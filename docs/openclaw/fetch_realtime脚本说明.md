# fetch_realtime 脚本说明

> `plugins/data_collection/stock/fetch_realtime.py` 模块文档

---

## 一、模块职责

获取A股股票实时行情数据，提供多数据源降级链路，确保在单一数据源不可用时仍能获取行情。

---

## 二、结构

### 主要函数

| 函数 | 职责 | 对外可见 |
|------|------|----------|
| `fetch_stock_realtime()` | 主入口，获取股票实时数据 | ✅ 是 |
| `tool_fetch_stock_realtime()` | OpenClaw 工具封装层 | ✅ 是 |
| `run_stock_realtime_chain()` | Provider 链执行引擎 | ⚠️ 内部 |
| `_fetch_realtime_mootdx()` | mootdx/TDX 数据源 | ❌ 私有 |
| `_fetch_realtime_tencent()` | 腾讯 qt.gtimg.cn 数据源 | ❌ 私有 |
| `_fetch_realtime_akshare()` | AkShare 全市场快照 | ❌ 私有 |
| `_fetch_bid_ask_em_single()` | 东财五档盘口（单票） | ❌ 私有 |

### 辅助函数

- `_normalize_stock_code()` - 规范股票代码为6位数字
- `_safe_float()` / `_safe_int()` - 安全类型转换
- `_to_qt_symbol()` - 转换为腾讯行情 API 格式

---

## 三、Provider 链

### 数据源降级顺序

```
优先级1: mootdx/TDX (通达信远程)
    ↓ 失败
优先级2: 东财五档 (单票深度，仅当 codes.len==1 且 include_depth=True)
    ↓ 失败
优先级3: 腾讯 qt.gtimg.cn (HTTP)
    ↓ 失败
优先级4: AkShare stock_zh_a_spot (全市场快照)
    ↓ 失败
返回 None
```

### 各数据源特点

| 数据源 | 协议 | 特点 | 依赖 |
|--------|------|------|------|
| mootdx/TDX | TDX协议 | 最快、最全 | `mootdx`, `tdxpy` |
| 东财五档 | HTTP | 单票深度数据 | `akshare` |
| 腾讯 qt.gtimg.cn | HTTP | 兜底、稳定 | 无（urllib） |
| AkShare stock_zh_a_spot | HTTP | 全市场快照 | `akshare` |

---

## 四、对外 API

### `fetch_stock_realtime(stock_code, mode, include_depth)`

**参数：**
- `stock_code`: 股票代码，支持逗号分隔多票（如 `"600000,600519"`）
- `mode`: `"production"` | `"test"`
- `include_depth`: 是否包含东财五档深度（默认 `True`）

### `tool_fetch_stock_realtime(stock_code, mode, include_depth)`

OpenClaw 工具封装层，直接调用 `fetch_stock_realtime()`。

---

## 五、返回格式

### 成功时

```json
{
  "success": true,
  "message": "Successfully fetched stock realtime data",
  "data": {
    "stock_code": "600000",
    "name": "浦发银行",
