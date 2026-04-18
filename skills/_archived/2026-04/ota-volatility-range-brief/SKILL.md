---
name: ota_volatility_range_brief
description: 宽基 ETF 巡检快报中日內区间字段口径（range_pct、confidence）与 data/volatility_ranges 缓存对齐；解读时引用合并后配置收敛规则。
---

# OTA：波动区间与巡检快报口径

## 何时使用

- 解释或撰写 **宽基 ETF 巡检快报** 中的波动区间、置信度。
- 用户问「为什么区间变窄/置信度上限」。

## 核心约定

1. **快报数据源**：常读 `data/volatility_ranges/{date}.json`（列表，同日可多条）；与 `tool_predict_intraday_range` 直出可能不同路径，勿混用口径。
2. **收敛规则**：生成源头在 `src/volatility_range.py`；合并后配置 → `signal_params.intraday_monitor_510300.volatility`（域文件：`config/domains/signals.yaml`）的 `min_intraday_pct` / `max_intraday_pct`；**`confidence` 硬上限 0.6**；夹紧 `range_pct` 时对称重算上下界。

## 对用户说明时的检查清单

- 报 `range_pct` 时说明是否已按配置夹紧。
- 报 `confidence` 时不应超过文档约定上限；若区间很宽，置信度应偏低（避免矛盾组合）。

## 权威文档

- `docs/openclaw/宽基ETF巡检快报-日内波动区间收敛说明.md`
- 分层配置说明见 `docs/configuration/README.md`（域文件：`config/domains/signals.yaml`）

## 相关工具

- **`tool_predict_intraday_range`**、**`tool_predict_volatility`**：快报与巡检主路径；参数与返回值见 `docs/reference/工具参考手册.md`。
- **`tool_predict_daily_volatility_range`**：**日频全日**区间（多窗 HV + ATR），与上两者 horizon 不同；**叙事与期权侧补充解读**见 Skill **`ota_volatility_prediction_narration`**，勿与「仅 intraday 收敛」的快报字段混谈。
