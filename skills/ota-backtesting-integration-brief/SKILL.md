---
name: ota_backtesting_integration_brief
description: 回测能力与 openclaw-data-china-stock 融合规程；优先本地A股/ETF采集与缓存，不走默认 yfinance 口径。
---

# OTA：回测能力融合口径（Backtesting × China Market Data）

## 何时使用

- 用户提到「回测策略」「历史验证」「参数优化」「信号有效性复盘」。
- 需要把第三方 `backtesting-trading-strategies` 与本地 `openclaw-data-china-stock` 数据能力结合。

## 核心原则

1. **数据优先级**：A股/ETF 场景优先使用 `openclaw-data-china-stock` 的 `tool_fetch_*` / `tool_read_market_data` / `tool_calculate_technical_indicators`；不要直接采用第三方 skill 示例中的 yfinance 默认路径。
2. **缓存优先**：可复用场景先读 `data/cache/`（通过 merged/data_access 工具），减少重复抓取与口径漂移。
3. **指标口径统一**：技术指标统一走 `tool_calculate_technical_indicators`（已覆盖 58 指标），避免在回测脚本里重复实现不一致版本。
4. **研究与实盘分离**：回测结果用于研究评分与参数建议，不直接替代盘中风控和执行链路。

## 推荐执行顺序

1. **确定标的与周期**：先按 `ota_cn_market_data_discipline` 选择 ETF/index/stock 与周期（日线/分钟）。
2. **拉取或确认缓存**：通过 `tool_fetch_*` 采集，随后优先 `tool_read_market_data` 读取缓存数据。
3. **指标补齐**：必要时调用 `tool_calculate_technical_indicators`，确保特征口径与主链路一致。
4. **回测与参数优化**：再进入 `backtesting-trading-strategies` 的 backtest/optimize 步骤。
5. **结果落地**：输出指标（收益、回撤、Sharpe、胜率、参数）并与 `tool_strategy_research` 结论互证。

## Agent 分工建议

- `etf_analysis_agent`：交互式回测、参数试验、信号验证。
- `etf_business_core_agent`：把回测结论转成可执行建议（仍需风控门禁）。
- `etf_cron_research_agent`：定时研究回测与周度参数复盘。
- `etf_cron_analysis_agent`：按需轻量验证（不做重型大网格）。
- `etf_main`：用户入口路由与摘要解释。

## 禁止

- 在 A股/ETF 研究中直接声称「以 yfinance 为准」并覆盖本地数据插件结果。
- 绕过缓存/工具直接手搓数据路径写入生产缓存。
- 仅凭单次回测结果给出确定性实盘指令。

## 参考

- `skills/backtesting-trading-strategies/SKILL.md`（第三方能力说明）
- `skills/ota-cn-market-data-discipline/SKILL.md`
- `skills/ota-cache-read-discipline/SKILL.md`
- `plugins/data_collection/README.md`
- `docs/openclaw/跨插件数据契约.md`
