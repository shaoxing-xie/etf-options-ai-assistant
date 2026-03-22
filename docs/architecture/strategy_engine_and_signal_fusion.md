# 策略引擎与信号融合实施方案 v1.0

本文档描述 **SignalCandidate** 统一契约、**Fusion** 规则、与现有工具（`tool_generate_signals`、`tool_generate_trend_following_signal`、`tool_strategy_weights`）的边界。实现代码位于 [`plugins/strategy_engine/`](../../plugins/strategy_engine/)，对外入口为 **`tool_strategy_engine`**。OpenClaw 侧衔接（定时任务、路由提示、权重落盘进化）见 [`config/openclaw_strategy_engine.yaml`](../../config/openclaw_strategy_engine.yaml)。

## 目标（收敛）

1. **统一信号结构**：多路策略输出同一 schema，便于审计与后续回测对齐。  
2. **显式融合**：加权分数 + 一致性门槛 + 强冲突降级，参数在 `config/strategy_fusion.yaml`。  
3. **不破坏默认路径**：`tool_generate_signals` 语义不变；风控仍通过现有 `tool_assess_risk` / `risk_engine.evaluate_order_request`（**不**在 `risk_engine` 内嵌融合）。

## 与 `strategy_config.py` 的关系

- [`strategy_config.py`](../../strategy_config.py) 提供 **策略配置 Schema** 与 `list_all_strategies()`，**不是**可执行求值引擎。  
- v1 可执行 Rule 源为：**`src.signal_generation.tool_generate_signals`**、**`etf_trend_tracking.tool_generate_trend_following_signal`**。  
- 架构上可将 `get_strategy_config(id)` 的 `triggers.entry` 等挂到 `rationale_refs` 作解释性元数据（可选）。

## SignalCandidate 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | str | 如 `src_signal_generation`、`etf_trend_following` |
| `symbol` | str | 标的，如 `510300` |
| `direction` | str | `long` \| `short` \| `neutral`（Grok 的 `hold` 映射为 `neutral`） |
| `score` | float | -1～1，融合主用 |
| `confidence` | float | 0～1 |
| `rationale` | str | 短摘要（通知/卡片） |
| `rationale_refs` | list[str] | 依据条目（指标、配置文案等） |
| `inputs_hash` | str | SHA256，规范序列化输入快照（**禁止** `hash(str)`） |
| `features` | dict | 可选，供未来 ML/回测 |
| `metadata` | dict | 来源、`source`=rule/llm/ml/ensemble、timeframe 等 |
| `timestamp` | str | ISO8601 |

### 与 `tool_generate_signals` 返回的映射（摘要）

- `data.signal_type`：`buy`/偏多 → `long`；`sell`/偏空 → `short`；空或未知 → `neutral`。  
- `data.signal_strength` / `signal_confidence`：归一化到 `score` / `confidence`（见 `rule_adapters._normalize_strength`）。  
- `data.signals[]`：取主信号或首条生成候选。

### 与 Journal

- [`docs/trading_journal_schema.md`](../trading_journal_schema.md) 保持 **additive**。  
- 融合运行可写 `event_type: strategy_fusion`（见 `tool_strategy_engine`）。  
- `tool_record_signal_effect` 可选 `journal_extra`：合并进 `signal_recorded` 的 journal payload。

## Fusion 规则（v1 / v1.1 / v1.2）

- **v1**：按 `symbol` 分组；\( \text{acc} = \sum_i score_i \cdot confidence_i \cdot w_i / \sum w_i \)；`|acc| < score_threshold` → `neutral`。  
- **v1.1**：同向比例 `< agree_ratio_min` → `neutral`。  
- **v1.2**：同时存在 `score ≥ strong_abs_score` 的多与 `score ≤ -strong_abs_score` 的空 → `neutral`。

权重：**动态** `tool_get_strategy_weights` 返回的 `data`（若成功且为 dict）覆盖 yaml 中缺省；否则用 `config/strategy_fusion.yaml` 的 `strategy_weights`。

### 权重键与 `strategy_config.id`、`tool_strategy_weights` 的对齐

- **Fusion 使用的 `strategy_id`** 与 `SignalCandidate.strategy_id` 一致，当前 v1 为：`src_signal_generation`、`etf_trend_following`（与**可执行适配器**一一对应）。  
- [`strategy_config.py`](../../strategy_config.py) 中的 id（如 `trend_following_510300`）是**配置文档/元数据** id；若希望 yaml 权重与某条配置 id 同名，可自行改 `strategy_weights` 的键，并同步修改 `rule_adapters` 中产出的 `strategy_id`（或增加别名映射），否则保持现键即可。  
- `tool_get_strategy_weights` 默认返回的键（如 `trend_following` / `mean_reversion`）与上述 fusion 键**未必相同**；仅当返回 dict 的 **key 与 yaml 中 strategy_id 一致** 时才会覆盖该路权重。需要动态调权时，建议 Cron/Agent 传入与 yaml 一致的策略键或扩展合并逻辑。

## Grok 纠偏摘要（避免误用）

- **`strategy_config` 不可直接当可执行引擎**：无 `check_triggers(config, market)`；主路径仍是 `src` 信号与 `etf_trend_tracking`。  
- **`risk_engine` 不吃 SignalCandidate 列表**：勿在 `evaluate_order_request` 前硬塞融合；由工作流在 `tool_strategy_engine` 之后再调风控工具。

## LLM / ML

- **LLMStrategy**：占位模块；结构化 JSON → `SignalCandidate`；**默认 `providers.llm: false`**。  
- **ML**：预留接口，不进主链路。

## Prometheus（可选）

若未来接入监控，可暴露 `strategy_fusion_runs_total`、`strategy_fusion_neutral_total`；本仓库 v1 **不**实现 exporter。

## OpenClaw 与本机 Cron（项目级约定）

- **仓库内**  
  - Agent 工具白名单：[`agents/analysis_agent.yaml`](../../agents/analysis_agent.yaml) 含 `tool_strategy_engine`；定时任务 **`strategy_fusion`** 为 **工作日 9:00–15:00 每 30 分钟**（`*/30 9-15 * * 1-5`）。  
  - 步骤模板：[`workflows/strategy_fusion_routine.yaml`](../../workflows/strategy_fusion_routine.yaml)。  
  - 示例 Cron（简化格式）：根目录 [`CRON_JOBS_EXAMPLE.json`](../../CRON_JOBS_EXAMPLE.json) → `strategy-fusion-example`（默认 `enabled: false`，调度 `*/30 9-15 * * 1-5`）。  
  - 路由与进化参数：[`config/openclaw_strategy_engine.yaml`](../../config/openclaw_strategy_engine.yaml)；可复制到 Agent 的提示：[`Prompt_config.yaml`](../../Prompt_config.yaml) → `openclaw_strategy_engine_routing.system_addon`。  
  - 模块说明：[`plugins/strategy_engine/README.md`](../../plugins/strategy_engine/README.md)。

- **本机 OpenClaw（`~/.openclaw`）**（需自行维护，不纳入 git）  
  - 分析 Agent（`etf_analysis_agent`）的 **SOUL** 通常位于  
    `~/.openclaw/agents/etf-options-ai-assistant/analysis_agent/agent/SOUL.md`，建议包含与上文 `system_addon` 一致的「策略引擎与信号融合」条款。  
  - 实际调度以 **`~/.openclaw/cron/jobs.json`** 为准；可新增/启用名为 **「etf: 策略引擎与信号融合」** 的任务，`expr` 与仓库保持一致 **`*/30 9-15 * * 1-5`**，`agentId` 为 `etf_analysis_agent`，`delivery.mode` 多为 `none`。  
  - 修改 `jobs.json` 后建议 `python3 -m json.tool ~/.openclaw/cron/jobs.json` 校验并重载 Gateway / Cron。

## 参考

- [架构 README](./README.md)  
- [工具参考手册](../reference/工具参考手册.md)（`tool_strategy_engine`）
