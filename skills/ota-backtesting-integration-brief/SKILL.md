---
name: ota_backtesting_integration_brief
description: |
  回测规程：OpenClaw 须先识别「脚本回测 vs 深度对账」两分支。宽基/技术指标类需求默认单条 exec 跑
  backtesting-trading-strategies（禁止先串 tool_fetch+指标）；仅当用户要对齐 58 指标与插件缓存时才走 MCP 数据链。
---

# OTA：回测能力融合口径（Backtesting × China Market Data）

## 速判（先读这几行）

| 用户意图（含钉钉） | 动作 |
| --- | --- |
| **回测 / optimize / backtest.py / 宽基+策略名 / price_loader** | **分支 A**：**仅**单条 `exec` 跑脚本；**不要**先 `tool_fetch_*` 或 `tool_calculate_technical_indicators`。 |
| **明确**要对齐 **58 指标** 或 **插件缓存** 再互证 | **分支 B**：先 MCP 数据链，再脚本或文字对账。 |
| **拿不准** | **默认 A**（宁可一次 exec，不要长工具链）。 |

**反模式（高概率触发上下文爆炸）**：分支 A 下先拉日线、再算 RSI/MACD、再拼 `python3 -c` — **禁止**。

## OpenClaw 必须先做的分支判断（自动识别）

在回答「回测」「历史验证」「RSI/SMA/MACD」「510300 回测」「参数优化」「跑 backtest」类需求前，**二选一**（不要两条路同时走）：

### 分支 A — **脚本回测优先**（默认，含钉钉 / 日常交互）

**触发特征**（命中任一即走本分支）：提到内置策略名（如 `rsi_reversal`、`sma_crossover`、`macd`）、`backtest.py` / `optimize.py` / `fetch_data.py`、`backtesting-trading-strategies`、宽基 ETF 代码 +「回测 / 近一年 / 夏普 / 回撤 / 交易次数」、用户要 **`price_loader`** 或「研究级脚本回测」等。

**硬约束**

1. **第一步且通常只需一步**：`exec` **单条** `python3 <绝对路径>/skills/backtesting-trading-strategies/scripts/backtest.py ...` 或 `python3 <绝对路径>/scripts/run_backtest_trading_strategies.py ...`（规则见 `docs/ops/回测使用指导-自动任务与日常交互.md` **§5**；禁止 `cd &&`、禁止把整段 K 线塞进 `python3 -c`）。
2. **禁止**在本分支内为「凑数据」而串联：`tool_fetch_etf_historical`、`tool_fetch_etf_data`、`tool_read_etf_daily`、`tool_calculate_technical_indicators` 等；脚本内已含策略与行情加载，重复拉数会导致 **工具链爆炸、上下文暴涨、`length` 截断与模型退化**（乱码、`TEAM???`）。
3. **数据源**：六代码标的由脚本默认走本仓库 **`plugins/data_collection`**（与 `openclaw-data-china-stock` 同源策略）；`price_loader` **以脚本终端输出的 `price_loader=` 为准**，不得臆造「接口只返回 35 条」等结论。
4. 失败时只根据 **stderr 最后一行** 调整 `--period`、`--data-source` 或配置，再 **第二次** 单条 `exec`；仍不要串 MCP 采集链。
5. **排他**：同一次需求在分支 A 下 **`exec` 已成功产出摘要/报告** 后，**不要**再补一轮 `tool_fetch_*`「核实数据」——脚本 stderr 与 `price_loader=` 已是依据。

### 分支 B — **深度研究 / 与主链路指标口径对账**

**触发特征**：用户明确要求「与 `tool_calculate_technical_indicators` 一致」「先读缓存再对账」「跨工具校验特征」「工作流 backtesting_research 的深度模式」等。

**执行顺序**（仅在本分支）

1. 按 `ota_cn_market_data_discipline` 定标的与周期。
2. `tool_fetch_*` / `tool_read_market_data` 确认或补齐缓存。
3. 需要时用 `tool_calculate_technical_indicators`（58 指标）。
4. 再进入 `backtesting-trading-strategies` 的 `backtest` / `optimize`，或做结论互证。
5. 输出须说明数据与指标口径来源。

**默认**：未出现分支 B 触发语时，**一律按分支 A**（避免误走工具链）。

---

## 核心原则（与两分支兼容）

1. **脚本侧数据**：`backtesting-trading-strategies` 已用 **`plugins/data_collection`** + `skill_settings.py` + `config/settings.yaml` 统一 `data.provider` 与缓存路径（CLI → `BACKTEST_DATA_SOURCE` → YAML → `auto`）。与「仅以 Yahoo 作为 CN 唯一源」相冲突时，以脚本默认 **CN 多源** 为准；仅美股/加密或显式 `--data-source yfinance` 用 Yahoo。
2. **缓存优先（分支 B）**：可复用场景先读 `data/cache/`（merged/data_access 工具），减少重复抓取。
3. **指标口径（分支 B）**：需要与生产 58 指标完全一致时，用 `tool_calculate_technical_indicators`；**分支 A 不要求先走该工具**。
4. **研究与实盘分离**：回测结论用于研究，不直接替代盘中风控与执行链路。

## Agent 分工建议

- `etf_analysis_agent`：交互式回测、参数试验；**默认按分支 A** 单条 `exec`。
- `etf_business_core_agent`：把回测结论转成可执行建议（仍需风控门禁）。
- `etf_cron_research_agent`：定时研究；可按工作流选择 A 或 B。
- `etf_main`：入口路由；识别用户是否在要「脚本回测」并避免误派生长工具链。

## 禁止

- **在分支 A** 用一长串 `tool_fetch_*` / `tool_calculate_technical_indicators` 代替一次 `backtest.py`。
- 在 A股/ETF 研究中直接声称「以 yfinance 为唯一权威」并否定本地多源脚本结果（除非用户显式要求 Yahoo）。
- 绕过缓存/工具直接手搓数据路径写入生产缓存。
- 仅凭单次回测给出确定性实盘指令。

## 参考

- `docs/ops/回测使用指导-自动任务与日常交互.md`（**§5 钉钉**、**§5.6 反例**、**§7 实测**）
- `skills/backtesting-trading-strategies/SKILL.md`
- `skills/ota-cn-market-data-discipline/SKILL.md`
- `skills/ota-cache-read-discipline/SKILL.md`
- `workflows/backtesting_research_on_demand.yaml`
- `plugins/data_collection/README.md`
- `docs/openclaw/跨插件数据契约.md`
