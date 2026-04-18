# technical-analyst

## 能力说明

- 面向 `index|etf|stock` 的技术面分析。
- 以 58 指标为基础，输出趋势/动量/波动/形态四段结构。
- 输出包含风险反证与置信度分级。

## 推荐触发示例

- 分析一下 `510300` 的技术面
- 贵州茅台现在技术面偏强还是偏弱
- 给我一份 `000300` 日线技术指标解读

## 依赖工具

- `tool_calculate_technical_indicators`
- `tool_fetch_market_data`

## 输出契约

固定键：

- `summary`
- `trend`
- `momentum`
- `volatility`
- `pattern_signals`
- `scorecard`
- `risk_counterevidence`
- `evidence`
- `confidence_band`

