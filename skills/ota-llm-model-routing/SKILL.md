---
name: ota_llm_model_routing
description: 哪类任务用哪档模型、与 OpenClaw 路由 JSON 同步；维护者向。
---

# OTA：模型分档与路由

## 何时使用

- 调整 **主备模型**、分场景路由（研究 vs 巡检 vs 工具调用）。
- 同步本机 `openclaw.json` / 模型路由脚本产出。

## 规程

1. **读实施文档**：按任务类型选择档位，避免高成本模型跑纯工具编排。
2. **脚本**：仓库内 `scripts/sync_openclaw_model_routes.py`（见 `scripts/README.md`）。
3. **变更后**：重启 Gateway 并抽样跑一条工作流。

## 权威文档

- `docs/openclaw/LLM_模型分档与路由实施方案.md`

## 运行时探活（不写配置）

- 任意 agent 可使用技能 **`ota_agent_model_probe`**，通过 CLI backend **`probe_agent_models`** 对指定 `agent` id 做主备链最小探活；详见该技能说明。
