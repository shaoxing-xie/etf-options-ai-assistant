---
name: ota_strategy_research_loop
description: 策略研究、回放与评估在主链路中的位置；tool_strategy_research 与 config/strategy_research.yaml 入口。
---

# OTA：策略研究闭环

## 何时使用

- 周五研究任务、`strategy_research*.yaml`、回放与 WFE 口径问题。

## 规程

1. **工具管道**：`tool_strategy_research`，默认读 **`config/strategy_research.yaml`**（切分、成本、Holdback 等）。
2. **输出**：常接日报/钉钉；与 `strategy_research_playback.yaml`（agentTurn）**并存**，勿重复调度。
3. **与主链路关系**：研究输出不替代盘中风控与信号巡检；实盘执行仍须遵守巡检 Skill 铁律。

## 权威文档

- `docs/openclaw/Strategy_Research_Loop.md`
- `workflows/README.md`
