# market-sentinel

## 能力说明

- 聚合涨停生态、A 股资金流向、北向资金、板块结构四类工具，输出**情绪综合评分**与**阶段判定**（非交易指令）。
- 与 `market-scanner` 区分：本 Skill 回答「整体情绪阶段与仓位倾向框架」，不承担异动扫描与时段监控主责。

## 与 market-scanner 如何选

| 场景 | 使用 |
|------|------|
| 想看今日强势板块、异动、盘前/盘中扫描 | `market-scanner` |
| 想评估整体市场情绪阶段、综合分与反证 | `market-sentinel` |

## 触发示例

- 当前市场情绪处于什么阶段
- 今天情绪综合分大概多少、有没有明显反证
- 北向休市时还适合做情绪全景吗（应体现降级与完整性）

## 依赖工具

- `tool_fetch_limit_up_stocks`
- `tool_fetch_a_share_fund_flow`
- `tool_fetch_northbound_flow`
- `tool_fetch_sector_data`
