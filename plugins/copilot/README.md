# copilot — 交易助手

`trading_copilot.py` 提供单一 OpenClaw 工具 **`tool_trading_copilot`**：把「交易状态 → A 股时段细分 → 市场快扫 →（条件触发）期权信号 → 持仓检查」编排为一次调用，输出低上下文摘要，并可生成/发送飞书交互卡片。

在 `tool_runner.py` 中注册为 `tool_trading_copilot`（`module_path=copilot.trading_copilot`）。

## 依赖（本模块不重复实现行情逻辑）

| 能力 | 模块 |
|------|------|
| 指数 / ETF / 全球指数 | `plugins.merged.fetch_index_data`、`plugins.merged.fetch_etf_data` |
| A50 | `plugins.data_collection.futures.fetch_a50` |
| 交易时段、A 股阶段 | `plugins.data_collection.utils.check_trading_status`、`a_share_market_regime` |
| 期权信号 | `src.signal_generation.tool_generate_option_trading_signals` |
| 股票现价（持仓） | `plugins.data_collection.stock.fetch_realtime` |
| 飞书卡片发送（可选） | `plugins.notification.send_feishu_card_webhook`（不可用时占位，不阻塞主流程） |
| 配置 | `src.config_loader.load_system_config` |

## 工具：`tool_trading_copilot`

### 参数概要

| 参数 | 说明 |
|------|------|
| `focus_etfs` | 逗号分隔 ETF 代码，覆盖快扫 ETF 列表 |
| `focus_stocks` | 逗号分隔股票代码；当前主要写入返回 `meta.focus`，默认快扫仍以配置内指数 + ETF 为主 |
| `mode` | `light` \| `normal` \| `deep`；`deep` 时更易触发信号分支 |
| `run_signal` | `True` / `False` / `None`；`None` 时在情绪极值（约 ≤25 或 ≥75）或 `mode=deep` 时自动尝试跑信号 |
| `signal_etf` | 生成信号用的标的，默认取快扫列表首只或 `510300` |
| `throttle_minutes` | 信号节流窗口（分钟），与 `copilot_state.json` 配合 |
| `timezone` | 默认 `Asia/Shanghai` |
| `disable_network_fetch` | 为沙箱/离线跳过所有联网快扫与信号（情绪分降级） |
| `output_format` | `feishu_card`（默认）或 `json`；前者在 `data` 中同时包含 `feishu_card` 与 `summary` |
| `include_snapshot` | 为 `true` 时在 `summary.snapshot` 附带指数/ETF/A50/全球原始片段 |
| `send_feishu_card` | 是否调用 webhook 发送卡片 |
| `feishu_webhook_url` | 可选覆盖默认 webhook |

### 配置驱动的快扫列表

- **指数**：优先 `opening_analysis.indices`（值为代码列表）；否则使用内置默认（如上证、沪深300、创业板、中证500 等）。
- **ETF**：优先 `etf_trading.enabled_etfs`；否则使用内置默认（如 510300、510500、159915）。

### 本地状态与持仓路径（OpenClaw workspace）

根目录：`~/.openclaw/workspaces/etf-options-ai-assistant/memory/`

| 文件 | 用途 |
|------|------|
| `copilot_state.json` | 记录 `last_signal_ts` 等，用于信号节流 |
| `positions.json` | 持仓列表（`position-monitor` 约定）；仅 `status == "open"` 的条目参与检查 |

### 返回结构（成功时）

- `success`、`message`
- `data`：`output_format` 为 `feishu_card` 时含 `feishu_card` + `summary`；否则以结构化 `summary` 为主（含 `market_status`、`signal`、`positions`、`feishu_card` 等）
- `meta`：`timestamp`、`mode`、`focus`（当前 ETF/股票代码列表）

### 情绪分（v2）

综合指数涨跌、ETF 成交额相对近 5 日均量、A50 涨跌幅等；北向资金因子预留为 `None`。若数据不足会带 `sentiment_note`（如 `network_fetch_disabled`、`insufficient_factors`）。

## 扩展与注意

- 主流程对 ETF 实时请求有数量上限（如前 6 只），避免单次调用过慢。
- 持仓现价：代码以 `5`/`1` 开头走 ETF 实时，否则走 A 股股票实时（简单规则，复杂标的需自行核对）。
