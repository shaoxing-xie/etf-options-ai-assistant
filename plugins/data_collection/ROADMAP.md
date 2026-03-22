# data_collection 插件路线图与数据契约

本文档与 [README.md](./README.md) **互指**：README 侧重工具用法与示例；本文档侧重 **OpenClaw 分类**、**Provider 双层降级**、**不支持项**与 **DTO 字段约定**。

## OpenClaw 分类框架

### 第一维：标的物（Underlying）

| 标的物 | 目录 / 模块 |
|--------|-------------|
| A 股股票 | `stock/` |
| ETF | `etf/` |
| 指数 | `index/` |
| 期权 | `option/` |
| 期货 / 外围 | `futures/`、`index/fetch_global.py` |
| 板块 / 情绪 | `sector.py`、`limit_up/`、`dragon_tiger.py` |
| 资金流向 | `northbound.py`、`capital_flow.py` |
| 基础 / 财务 | `financials.py` |
| 工具 | `utils/`、`tick/` |

### 第二维：数据域

| 数据域 | 含义 |
|--------|------|
| 基础数据 | 证券信息、财务快照、估值等 |
| 行情数据 | OHLCV、快照、盘口（按周期再分） |
| 板块数据 | 行业/概念涨跌与热度 |
| 资金流向数据 | 北向、个股主力散户等 |
| 其他 | 交易日、合约列表、可交易性等 |

### 第三维：行情周期（仅行情域）

日线（含周/月若扩展）、分钟线、实时快照（可选五档）。

## 双层降级（稳定性）

1. **跨软件包（Provider）**：对同一「标的物 + 数据域 + 周期」，按配置依次尝试 Mootdx、Baostock、AkShare、Tushare（日线 EOD 且通常置后）等。
2. **包内多路由（AkShare）**：新浪、东方财富、腾讯等接口顺序在实现中固定，并在返回中标注 `source` / `route`。

**说明**：商业源（如 iFin）当前**不实现**；远期若接入，在本文档单独立表。

## A 股股票 · 日线 Provider 顺序（实现目标）

高 → 低（与 `stock/fetch_historical.py` 对齐，以代码为准）：

1. 本地缓存（若命中完整区间）
2. **mootdx**（通达信，可选）
3. **Baostock**（无 token，长历史；无 TDX 时作为主要免费兜底之一）
4. AkShare **新浪** `stock_zh_a_daily`
5. AkShare **东财** `stock_zh_a_hist`
6. AkShare **腾讯** `stock_zh_a_hist_tx`
7. **Tushare** `pro.daily`（EOD，需 token，**置后**）

## A 股股票 · 分钟 Provider 顺序

1. 缓存  
2. **mootdx**  
3. AkShare 新浪分钟  
4. AkShare 东财 `stock_zh_a_hist_min_em`  
5. **efinance**（可选，参数 `minute_source_preference=efinance` 或自动回退时启用）

## A 股股票 · 实时 Provider 顺序（双层链入口）

实现见 `providers/stock_realtime.py`（`fetch_stock_realtime` 调用同一顺序）：

1. **mootdx**（通达信远程，非纯 HTTP）  
2. **东财五档** `stock_bid_ask_em`（可选深度，失败则跳过）  
3. **腾讯** `qt.gtimg.cn`  
4. AkShare **新浪** `stock_zh_a_spot`

## 不支持项（默认）

- 全市场 WebSocket 推送、交易所 **L2 逐笔**（需专门授权 / DataFeed）。
- 绑定某一商业终端文档表述；行业缩写（BD/HQ/HF 等）仅作附录对照。

## 附录 A：行业术语对照（非规范）

| 常见缩写 | 含义 |
|----------|------|
| BD | 基础数据 |
| HQ | 历史行情 |
| HF | 高频 / 分钟 |
| RQ | 实时行情 |

## 附录 B：最小返回字段（DTO · 文档层）

| 字段 | 说明 |
|------|------|
| `success` | 是否成功 |
| `message` | 人类可读信息 |
| `data` | 主数据（列表或字典） |
| `source` / `provider` | 实际使用的数据源或 Provider 名 |
| `count` | 条数（若适用） |

Pydantic 模型在 Provider 代码落地（Phase B）时与工具入参一并引入。

## 附录 C：ETF ↔ 指数 ↔ 期权标的映射

见 [config/symbol_mapping.yaml](./config/symbol_mapping.yaml)。代码侧可 `from plugins.data_collection.config import load_symbol_mapping`。用于 510300↔000300 等关联，避免魔法字符串。

## 附录 D：期权合约主数据

合约列表与到期月份以 [utils/get_contracts.py](./utils/get_contracts.py) 为准；完整「行权价阶梯 / 最后交易日」以交易所规则 + 缓存为准，详见 `option/README.md`。

## 附录 E：IOPV / 折溢价

已实现轻量工具：`etf/fetch_realtime.fetch_etf_iopv_snapshot` / `tool_fetch_etf_iopv_snapshot`（`fund_etf_spot_em`，含 IOPV 与折价率字段）。亦可结合 ETF 日线 + 指数日线间接估算，见 `etf/README.md`。
