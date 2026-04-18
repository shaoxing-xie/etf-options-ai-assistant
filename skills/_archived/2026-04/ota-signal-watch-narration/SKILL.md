---
name: ota_signal_watch_narration
description: 在信号/巡检工具输出后，用中性专业语气说明规则强度、Greeks 与波动区间依据；明确观望与跟进的边界，不夸大转折确认；不输出需机器解析的强制 JSON。
---

# OTA：信号巡检叙事与风险边界

## 何时使用

- 解读 `signal_watch` 类工具或巡检结果中的**多因子信号**（ETF 转折、Greeks、大盘辅助、波动区间等）。  
- 原进程内 `llm_enhancer` + `signal_watch` 的 **JSON 结构化输出**已移除；Agent 侧用自然语言即可，无需再产出固定 JSON schema。

## 原则

1. **只基于工具给出的规则分、阈值、字段**说明「为何触发 / 为何未触发」，不得虚构序列或数值。  
2. **转折与确认**：区分「规则层提示」与「高确定性信号」；未在工具中明示的，不得写成已确认转折。  
3. **风险**：强调假突破、量能不足、IV 与 Gamma 极端时的仓位与止损；避免具体价位与喊单。  
4. **语气**：券商研究所式、中性、谨慎。

## 相关 Skill

- 风控铁律：`ota_signal_risk_inspection`
- 通用叙事：`ota_openclaw_tool_narration`
