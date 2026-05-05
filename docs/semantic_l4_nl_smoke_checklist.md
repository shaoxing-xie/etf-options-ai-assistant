# L4-semantic Agent 自然语言抽检清单（≥10 条）

在 OpenClaw 中加载 `ota-equity-valuation-brief`、`ota-flow-sentiment-brief`、`ota-market-regime-brief` 后，用下列问法验证工具调用与 `quality_status` 传播（记录 `evidence_tools`）。

1. 贵州茅台现在估值分位大概多少？
2. 510300 现在 PE 历史分位处于什么水平？
3. 沪深300 ETF 贵不贵？
4. 今天市场整体资金是流入还是流出？
5. 最近几天行业资金排名靠前的是哪些方向？
6. 大盘现在是什么状态，偏震荡还是偏趋势？
7. 上证指数今天大概涨跌幅多少（语义摘要里）？
8. 我想看市场 regime 和指数快照一句话总结。
9. 持仓里茅台三成、沪深三百 ETF 七成，组合集中度高吗？（走组合 brief + POST weights）
10. 北向和主力今天不想展开，只要资金情绪一句话。

验收：每条回答应引用对应 `tool_semantic_*_brief` 的字段或明确声明 `degraded`。
