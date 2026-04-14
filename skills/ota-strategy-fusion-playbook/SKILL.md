---
name: ota_strategy_fusion_playbook
description: 何时优先调用 tool_strategy_engine、如何解读 Fusion（fused / fused_by_symbol / summary）、多 ETF 参数、inputs_hash 与动态权重；依赖 option-trading-assistant 与 config/openclaw_strategy_engine.yaml。勿与进化流水线 Skill 混用同一对话上下文。
---

# OTA：策略融合 — 调用与解读

## 何时使用

- 用户要 **多源信号一致性**、合成方向、可审计的加权结论。
- 需要 **`candidates` + `fused`**（及多标的时的 **`fused_by_symbol`**）结构化输出，而非单路 `tool_generate_option_trading_signals`（别名 `tool_generate_signals`）叙事。
- 监控或报表需要一眼扫：**`data.summary`**（候选数、已融合标的、非 neutral 数量、强信号计数及 `strong_abs_score_threshold`）。

## 先决条件

- 插件 **`option-trading-assistant`** 已加载；工具名以 `config/tools_manifest.yaml` 为准。
- **双配置**：融合数学在 **`config/strategy_fusion.yaml`**（`policy`、`strategy_weights`、`providers`）；OpenClaw / 进化在 **`config/openclaw_strategy_engine.yaml`**（默认参数、权重落盘路径、路由提示）。

## 参数要点

- **单标的**：`underlying`、`index_code` 各一个代码（与 `default_tool_args` 一致）。
- **多 ETF 组合**：`underlying` 与 `index_code` 用**英文逗号**分隔且**同序**对齐，例如 `510300,510500` 与 `000300,000905`；单指数可只写一项以复用到所有标的。
- **命令行 `tool_runner`**：支持多个 `key=value` 参数（值内可含逗号），例如：  
  `python tool_runner.py tool_strategy_engine underlying=510300,510500 index_code=000300,000905`

## 规程

1. **路由**：当问题属于「多策略合成 / 一致性」时，**优先** `tool_strategy_engine`，再结合 `tool_assess_risk`（单标的、多资产类型；口径见 Skill **`ota_risk_assessment_brief`**）；不要只用 `tool_generate_option_trading_signals`（或别名 `tool_generate_signals`）冒充融合结论。
2. **单路例外**：用户明确只要某一模块时，可单独 `tool_generate_option_trading_signals` / `tool_generate_etf_trading_signals` / `tool_generate_stock_trading_signals`（或期权别名 `tool_generate_signals`）或 `tool_generate_trend_following_signal`。
3. **解读（按优先级）**  
   - **主结论**：`data.fused`（多标的时为列表顺序中**首个有结果**的主标的；兼容旧消费者）。  
   - **按标的明细**：`data.fused_by_symbol`（每 ETF 一条 `FusionResult`）。  
   - **摘要**：`data.summary`（`total_candidates`、`fused_symbols`、`non_neutral_fused_count`、`strong_fused_count` 等）。  
   - **原始候选**：`data.candidates`（含各策略 `features`，便于调试）。  
   - **审计**：`data.inputs_hash`（SHA256，含 `policy_version`、`fusion_policy`、`strategy_weights_yaml`、标的/指数列表等；与 Journal `strategy_fusion` 对齐）。  
4. **动态权重**：`use_dynamic_weights=true` 时优先读 `data/strategy_fusion_effective_weights.json`（可由 `STRATEGY_FUSION_WEIGHTS_PATH` 覆盖）；键须与 `strategy_id` / `strategy_fusion.yaml` 一致。路由提示片段见 `Prompt_config.yaml` → `openclaw_strategy_engine_routing`。
5. **工作流衔接**：定时任务见 `agents/analysis_agent.yaml` → `strategy_fusion`；步骤模板 `workflows/strategy_fusion_routine.yaml`。融合后若需下单前校验再调 `tool_assess_risk`；通知可带 `summary` / `fused` 摘要。

## 工具（核对 manifest）

- `tool_strategy_engine`
- `tool_assess_risk`
- （上下文）`tool_generate_option_trading_signals`（别名 `tool_generate_signals`）、`tool_generate_etf_trading_signals`、`tool_generate_stock_trading_signals`、`tool_generate_trend_following_signal`

## 权威文档

- `plugins/strategy_engine/README.md`
- `docs/architecture/strategy_engine_and_signal_fusion.md`
- `config/openclaw_strategy_engine.yaml`
- `docs/openclaw/能力地图.md`

## 禁止

- 在无权证下改写 `data/strategy_fusion_effective_weights.json` 或 `strategy_fusion.yaml`。
- 将本 Skill 与 **进化 / PR / evolver** 流程混在同一任务里（改用 `ota-evolution-execution-contract`）。
