# 策略引擎与信号融合（`strategy_engine`）

统一多路规则/（可选）LLM 输出为 **`SignalCandidate`**，按配置做 **Fusion（v1 / v1.1 / v1.2）**，对外通过 OpenClaw 工具 **`tool_strategy_engine`** 暴露。

详细架构、与 `strategy_config` / 风控边界说明见：[`docs/architecture/strategy_engine_and_signal_fusion.md`](../../docs/architecture/strategy_engine_and_signal_fusion.md)。

## OpenClaw 识别与「自觉使用」

- **工具清单**：`config/tools_manifest.yaml` 中 `tool_strategy_engine` 的 `description` 含「何时优先调用」，会进入插件生成的工具 schema，供模型选题。
- **Agent 白名单**：[`agents/analysis_agent.yaml`](../../agents/analysis_agent.yaml) 已列入 `tool_strategy_engine`，并增加定时任务 **`strategy_fusion`**（交易时段每 30 分钟）。
- **路由提示词**：根目录 [`Prompt_config.yaml`](../../Prompt_config.yaml) → **`openclaw_strategy_engine_routing.system_addon`**，可复制到 OpenClaw Agent 的 system 或 Skill，引导优先用融合工具处理综合信号类问题。
- **衔接配置**：[`config/openclaw_strategy_engine.yaml`](../../config/openclaw_strategy_engine.yaml)（`enabled`、`default_tool_args`、`evolution`、`agent_routing_hints`）。

## 自动进化（轻量）

- `openclaw_strategy_engine.yaml` 中 **`evolution.persist_effective_weights: true`**（默认已开）时，每次融合后将 **`weights_effective`** 写入 `data/strategy_fusion_effective_weights.json`。
- 下次 `tool_strategy_engine(..., use_dynamic_weights=true)` 会经 `get_strategy_weights(strategies=[...])` **优先读取该文件**（键须与 `strategy_weights` / `SignalCandidate.strategy_id` 一致），形成「上次有效权重 → 本次融合」的闭环；再配合定时 **`strategy_reflection_task`** 与 `tool_adjust_strategy_weights` 做评分驱动调权（建议 `evolution.fusion_weight_keys` 与反思任务传入的 `current_weights` 键对齐）。
- 测试或沙箱可通过环境变量 **`STRATEGY_FUSION_WEIGHTS_PATH`** 覆盖落盘路径。

## 模块结构

| 文件 | 说明 |
|------|------|
| `schemas.py` | `SignalCandidate`、`FusionResult`；`direction` 为 `long \| short \| neutral`（`hold` 在适配层映射为 `neutral`） |
| `base.py` | `BaseStrategy` 抽象（`strategy_id` + `generate`） |
| `rule_adapters.py` | 可执行 Rule 源适配：`src` 信号生成、`etf_trend_tracking` 趋势信号 |
| `fusion.py` | 读取 `config/strategy_fusion.yaml`；`fuse_all` / `merge_weights` |
| `llm_strategy.py` | LLM 占位（默认关闭）；`MLStrategy` 预留 |
| `tool_strategy_engine.py` | **主入口**：聚合候选 → 融合 → 返回结构化结果；可选写 Journal；**禁止**子进程调 `tool_runner` |

## 配置

- **融合策略与默认权重**：[`config/strategy_fusion.yaml`](../../config/strategy_fusion.yaml)  
  - `policy`：`score_threshold`、`agree_ratio_min`、`strong_abs_score`  
  - `strategy_weights`：键与 **`SignalCandidate.strategy_id`**（适配器产出）一致  
  - `providers`：`src_signal_generation`、`etf_trend_following`、`llm`（默认 `llm: false`）

## 调用方式（工具）

在仓库根目录、已配置 `PYTHONPATH` 的前提下，经 `tool_runner` 调用（名称以 `config/tools_manifest.yaml` 为准），例如：

```bash
python tool_runner.py tool_strategy_engine underlying=510300 index_code=000300
```

### `tool_strategy_engine` 参数摘要

| 参数 | 说明 |
|------|------|
| `underlying` | ETF 标的，默认 `510300` |
| `index_code` | 趋势策略用指数代码，默认 `000300` |
| `mode` | 传给 `src` 信号生成，默认 `production` |
| `use_dynamic_weights` | 是否尝试合并动态权重（见 `analysis.strategy_weight_manager`） |
| `write_journal` | 是否追加 `strategy_fusion` 事件到 trading journal |
| `config_path` | 可选，自定义 fusion yaml 路径 |

### 返回 `data` 字段（成功时）

- `candidates`：各策略原始 `SignalCandidate` 列表（dict）  
- `fused`：按标的融合后的 `FusionResult`（dict）或 `null`  
- `weights_effective`：本次使用的权重  
- `policy_version`：配置版本号  
- `inputs_hash`：本次运行的 **SHA256**（规范 JSON 快照，非 `hash(str)`）  
- `provider_errors`：各 provider 异常信息列表  
- `policy_applied`：实际使用的阈值字典  

## Fusion 规则（简述）

1. **v1**：按 `symbol` 分组；加权 \(\sum score \cdot confidence \cdot weight / \sum weight\)；与阈值比较得方向。  
2. **v1.1**：同向比例低于 `agree_ratio_min` → `neutral`。  
3. **v1.2**：强多与强空同时存在 → `neutral`。

## 设计边界（与仓库约定一致）

- **`strategy_config.py`**：配置/元数据；**不是**可执行触发器循环；Rule 主路径在适配器所调用的现有模块。  
- **`risk_engine`**：面向订单/账户状态；**不在此包内**把融合硬塞进 `evaluate_order_request`；工作流在拿到 `fused` 后再走现有风控工具。  
- **`tool_generate_signals`**：语义保持不变；融合为**新增**工具路径。  
- **`inputs_hash`**：使用 **hashlib SHA256** + 规范序列化，保证可复现审计。

## 测试

```bash
pytest tests/test_strategy_engine.py -q
```

## 相关文档与示例

- Journal：`docs/trading_journal_schema.md`（`strategy_fusion` 事件）  
- Cron 示例：`CRON_JOBS_EXAMPLE.json`（`strategy-fusion-example`，默认不启用生产）  
- LLM 提示片段：根目录 `Prompt_config.yaml` → `strategy_engine_llm`
