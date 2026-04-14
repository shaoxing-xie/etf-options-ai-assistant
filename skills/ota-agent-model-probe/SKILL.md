---
name: ota_agent_model_probe
description: 调用 CLI 探活任意 agent 在 openclaw.json 中的主备模型链（不写配置）；所有 agent 可用。
---

# OTA：Agent 模型链探活

## 何时使用

- 定时任务或长链路开始前，想确认**某个 agent** 的 `primary + fallbacks` 里**至少有一条**能尽快打通 LLM。
- 只作**最小 chat 探活**，不替代业务校验、不验证工具调用能力。

## 调用方式

1. **CLI Backend 名**：`probe_agent_models`（定义在 `agents.defaults.cliBackends`）。
2. **参数**：把 **OpenClaw 的 agent `id`** 作为脚本**第一个参数**传给该 backend（与 `python .../probe_agent_models.py <agent_id>` 一致）。
3. **可探活任意已配置 agent**：不限于当前会话身份；例如运维 agent 可探活 `etf_analysis_agent`。
4. **不写磁盘**：脚本只读 `openclaw.json`，不修改配置；返回的 `selected_model` 仅作**本会话**人工切换参考。

## 环境变量（可选）

- `OC_PROBE_AGENT` / `OPENCLAW_AGENT_ID`：未传参数时用作 agent id（便于包装脚本默认探活「当前 agent」）。
- `OC_OPENCLAW_JSON`、`OC_PROBE_TIMEOUT_SEC`、`OC_PROBE_MAX_TOKENS`：见脚本头部注释。

## 返回字段（JSON）

- `ok`：是否至少一条模型探活成功。
- `selected_model`：第一个成功的完整模型 id（与配置中字符串一致）。
- `model_chain`、`attempts`：顺序与各次错误/耗时。

## 与路由文档的关系

分档与主备编辑仍以 `ota_llm_model_routing` 与 `docs/openclaw/LLM_模型分档与路由实施方案.md` 为准；本技能只解决「当下能不能打通一条模型」的探活。
