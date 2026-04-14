# 策略引擎与信号融合（`strategy_engine`）

统一多路规则/（可选）LLM 输出为 **`SignalCandidate`**，按配置做 **Fusion（v1 / v1.1 / v1.2）**，对外通过 OpenClaw 工具 **`tool_strategy_engine`** 暴露。

详细架构、与 `strategy_config` / 风控边界说明见：[`docs/architecture/strategy_engine_and_signal_fusion.md`](../../docs/architecture/strategy_engine_and_signal_fusion.md)。

## OpenClaw 识别与「自觉使用」

- **工具清单**：`config/tools_manifest.yaml` 中 `tool_strategy_engine` 的 `description` 含「何时优先调用」，会进入插件生成的工具 schema，供模型选题。
- **Agent 白名单**：[`agents/analysis_agent.yaml`](../../agents/analysis_agent.yaml) 已列入 `tool_strategy_engine`，并增加定时任务 **`strategy_fusion`**（交易时段每 30 分钟）。
- **Skill（解读与路由）**：[`skills/ota-strategy-fusion-playbook/SKILL.md`](../../skills/ota-strategy-fusion-playbook/SKILL.md)（`ota_strategy_fusion_playbook`）— 何时调用、如何读 `fused` / `fused_by_symbol` / `summary`、多 ETF 参数、与风控衔接；建议在 **`etf_analysis_agent`** / **`etf_business_core_agent`** 等分析类 Agent 中勾选。
- **工作流模板**：[`workflows/strategy_fusion_routine.yaml`](../../workflows/strategy_fusion_routine.yaml) — 融合 → 可选 `tool_assess_risk` → 可选通知；与仓库定时任务同源参数，可按注释改为多标的。
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
| `fusion.py` | 读取 `config/strategy_fusion.yaml`；`fuse_all_by_symbol` / `fuse_all` / `merge_weights` |
| `llm_strategy.py` | LLM 占位（默认关闭）；`MLStrategy` 预留 |
| `tool_strategy_engine.py` | **主入口**：聚合候选 → 融合 → 返回结构化结果；可选写 Journal；**禁止**子进程调 `tool_runner` |

## 配置

### 两个 YAML 的职责（勿混用）

| 文件 | 职责 |
|------|------|
| [`config/strategy_fusion.yaml`](../../config/strategy_fusion.yaml) | **融合数学与数据源**：`version`、`policy` 阈值、`strategy_weights`、`providers`（含是否启用 `llm`）。决定怎么算分、哪些路上场。 |
| [`config/openclaw_strategy_engine.yaml`](../../config/openclaw_strategy_engine.yaml) | **OpenClaw / Agent 衔接**：`enabled`、`default_tool_args`、路由提示 `agent_routing_hints`、**进化** `evolution`（落盘 `weights_effective` 路径等）。**不改变** fusion 公式本身。 |

`tool_strategy_engine` 读前者做融合；读后者仅用于进化落盘等与 OpenClaw 相关的副作用。

### strategy_fusion.yaml 字段

- **融合策略与默认权重**：[`config/strategy_fusion.yaml`](../../config/strategy_fusion.yaml)  
  - `policy`：`score_threshold`、`agree_ratio_min`、`strong_abs_score`  
  - `strategy_weights`：键与 **`SignalCandidate.strategy_id`**（适配器产出）一致  
  - `providers`：`src_signal_generation`、`etf_trend_following`、`llm`（默认 `llm: false`）

## 调用方式（工具）

在仓库根目录、已配置 `PYTHONPATH` 的前提下，经 `tool_runner` 调用（名称以 `config/tools_manifest.yaml` 为准），例如：

```bash
python tool_runner.py tool_strategy_engine underlying=510300 index_code=000300
# 多 ETF：逗号分隔标的；指数可单列（复用）或与标的同序
python tool_runner.py tool_strategy_engine underlying=510300,510500 index_code=000300,000905
```

### `tool_strategy_engine` 参数摘要

| 参数 | 说明 |
|------|------|
| `underlying` | ETF 标的，默认 `510300`；多标的英文逗号分隔，如 `510300,510500` |
| `index_code` | 趋势用指数代码，默认 `000300`；单个则所有标的复用，或多个与 `underlying` 同序 |
| `mode` | 传给 `src` 信号生成，默认 `production` |
| `use_dynamic_weights` | 是否尝试合并动态权重（见 `analysis.strategy_weight_manager`） |
| `write_journal` | 是否追加 `strategy_fusion` 事件到 trading journal |
| `config_path` | 可选，自定义 fusion yaml 路径 |

### 返回 `data` 字段（成功时）

- `candidates`：各策略原始 `SignalCandidate` 列表（dict）  
- `fused`：主标的融合结果（多标的时为 `underlying` 列表顺序中首个有结果的标的；兼容旧消费者）  
- `fused_by_symbol`：各标的 `symbol -> FusionResult`（dict）  
- `underlyings` / `index_codes`：本次解析后的标的与指数列表  
- `weights_effective`：本次使用的权重  
- `policy_version`：配置版本号  
- `summary`：运行摘要（`total_candidates`、`fused_symbols`、`strong_fused_count` 等；强信号阈值与 `policy.strong_abs_score` 一致）  
- `inputs_hash`：本次运行的 **SHA256**（规范 JSON 快照；含 `engine_inputs_hash_schema`、`policy_version`、`fusion_policy`、`strategy_weights_yaml` 与标的/日期等，避免改阈值或 YAML 默认权重后仍与旧 hash 混淆）  
- `provider_errors`：各 provider 异常信息列表  
- `policy_applied`：实际使用的阈值字典  

## Fusion 规则（简述）

1. **v1**：按 `symbol` 分组；加权 \(\sum score \cdot confidence \cdot weight / \sum weight\)；与阈值比较得方向。  
2. **v1.1**：同向比例低于 `agree_ratio_min` → `neutral`。  
3. **v1.2**：强多与强空同时存在 → `neutral`。

## 设计边界（与仓库约定一致）

- **`strategy_config.py`**：配置/元数据；**不是**可执行触发器循环；Rule 主路径在适配器所调用的现有模块。  
- **`risk_engine`**：面向订单/账户状态；**不在此包内**把融合硬塞进 `evaluate_order_request`；工作流在拿到 `fused` 后再走现有风控工具。  
- **`tool_generate_option_trading_signals`**（别名 **`tool_generate_signals`**）：语义保持不变；融合为**新增**工具路径。适配器见 `rule_adapters.run_src_signal_generation`。  
- **`inputs_hash`**：使用 **hashlib SHA256** + 规范序列化，保证可复现审计。

## 测试

```bash
pytest tests/test_strategy_engine.py -q
```

## 相关文档与示例

- Journal：`docs/trading_journal_schema.md`（`strategy_fusion` 事件）  
- Cron 示例：`CRON_JOBS_EXAMPLE.json`（`strategy-fusion-example`，默认不启用生产）  
- LLM 提示片段：根目录 `Prompt_config.yaml` → `strategy_engine_llm`

## 联系与反馈

若你阅读本模块后希望**提问、建议、报告缺陷或讨论设计**，推荐按下面方式联系维护者（公开、可检索，便于他人受益）：

| 场景 | 建议做法 |
|------|----------|
| **使用问题 / 功能建议 / Bug** | 到本仓库 [**Issues**](https://github.com/shaoxing-xie/etf-options-ai-assistant/issues) 新建一条，标题或正文注明 `strategy_engine` 或 `tool_strategy_engine`，并尽量附上复现步骤、环境（Python/OpenClaw 版本）与相关日志片段。 |
| **代码贡献** | 先阅读仓库根目录 [`CONTRIBUTING.md`](../../CONTRIBUTING.md)，再提交 **Pull Request**；改动涉及融合逻辑或契约时，请同步更新 [`docs/architecture/strategy_engine_and_signal_fusion.md`](../../docs/architecture/strategy_engine_and_signal_fusion.md) 与单测。 |
| **安全漏洞** | **不要**在公开 Issue 中贴利用细节；请按 [`SECURITY.md`](../../SECURITY.md) 中的说明私下或最小化披露方式报告。 |

若仓库已启用 **GitHub Discussions**，也可在讨论区开帖（同样建议打上与策略引擎相关的标题关键词）。  
Fork 本仓库开发时，可在你的 Fork 上提 Issue，或向上游发 PR 合并改进。
