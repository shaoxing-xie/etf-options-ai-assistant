---
name: ota_technical_indicators_brief
description: tool_calculate_technical_indicators 的引擎（standard/legacy）、指标列表、合并后配置与依赖；向用户解读时只引用返回的 message/data，禁止编造数值。
---

# OTA：技术指标工具（`tool_calculate_technical_indicators`）

## 何时使用

- 调用或解释 **MA / MACD / RSI / 布林带** 及扩展指标（KDJ、CCI、ADX、ATR）时。
- 用户问「为什么 RSI 和以前不一样」「要不要装 pandas_ta」。

## 工具行为（摘要）

| 项 | 说明 |
|----|------|
| **默认引擎** | `standard`：`pandas_ta` 向量化；RSI 为 **Wilder**；MACD 柱为 **DIF−DEA**（与常见 TA 库一致，**非** 旧版 `2×(DIF−DEA)`）。 |
| **legacy** | 原 Coze 列表实现，**数值与历史版本对齐**；**不含** kdj/cci/adx/atr。 |
| **配置** | 合并后配置 → **`technical_indicators`**（域文件：`config/domains/analytics.yaml`）：`engine`、`ma_periods`、`macd`/`rsi`/`bollinger`、`default_indicators` 等。 |
| **参数** | `indicators` 为小写键：`ma`、`macd`、`rsi`、`bollinger`、`kdj`、`cci`、`adx`、`atr`；未传时用配置中的 `default_indicators`。 |
| **可选** | `lookback_days`、`period`（分钟）、`klines_data`（工作流直传 K 线）、`engine`、`timeframe_minutes`（如 5m→30m 聚合）、`ma_periods` / `rsi_length`（单次覆盖配置）。 |
| **依赖** | `standard` 需安装 **`pandas-ta`**（见 `requirements.txt`）；**numba** 要求 **numpy 版本低于 2.3**（仓库当前锁定 **numpy 2.2.6**）。未安装 `pandas-ta` 时会 **回退 legacy** 并在 `data.notes` 中说明。 |
| **缓存** | 结果 TTL **5 分钟**（`@cache_result`）。 |

## 叙事约束（与 `ota_openclaw_tool_narration` 一致）

1. **只引用** 工具返回的 `message`、`data.indicators`、`data.signal.summary` 中出现的数值与文案；不得捏造金叉/超买点位。
2. 若 `success: false`，根据 `message` 说明（常见：缓存 K 线不足、未装 `pandas_ta` 却用了重采样/自定义均线、MACD 需约 **34+** 根有效收盘等），可建议增大 `lookback_days` 或安装依赖。
3. 不要在用户可见回复中堆砌「pandas_ta」「Wilder」除非用户追问实现细节。

## 权威文档与代码

- [`plugins/analysis/README.md`](../../plugins/analysis/README.md)（第一节）
- [`config/tools_manifest.yaml`](../../config/tools_manifest.yaml) 中 `tool_calculate_technical_indicators`
- 实现：[`plugins/analysis/technical_indicators.py`](../../plugins/analysis/technical_indicators.py)

## 相关 Skill

- 通用工具叙事：`ota_openclaw_tool_narration`
