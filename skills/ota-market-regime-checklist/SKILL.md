---
name: ota_market_regime_checklist
description: 短清单：分析市场状态与 AI 决策层时的必查维度；细节见 Market_Regime_and_AI_Decision_Layer.md。易变叙事，Skill 保持薄。
---

# OTA：市场体制与决策层（检查清单）

## 何时使用

- 调用 `tool_detect_market_regime` 或讨论 **体制 / 决策层 / 风险预算** 时，先过一遍清单再下结论。

## 清单（按需选用）

1. **数据层**：当前可观测标的、频率（日/分钟/Tick）是否支撑结论？
2. **体制层**：趋势/震荡/事件冲击等标签是否与工具输出一致？
3. **决策层**：建议动作是否落在风控与仓位规则内？
4. **可证伪**：用哪些后续数据可验证本次判断？

## 权威文档

- `docs/openclaw/Market_Regime_and_AI_Decision_Layer.md`

## 工具

- `tool_detect_market_regime`（参数见 manifest / 工具参考手册）
