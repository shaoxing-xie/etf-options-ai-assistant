# OpenClaw 配置与 Token 消耗优化建议

基于对 `~/.openclaw` 配置与运行日志的梳理，针对「自定义工具过多导致性能与 token 浪费」的优化方案。

---

## 一、现状与根因

### 1.1 工具暴露方式

| 配置项 | 当前值 | 含义 |
|--------|--------|------|
| `agents.list[].tools` | `etf_main` / `etf_business_core_agent`: `allow: ["tavily_search", "group:plugins"]` | 允许 **所有插件** 的全部工具 |
| | `etf_data_collector_agent` / `etf_analysis_agent` / `etf_notification_agent`: `{}` | 继承默认，实际也拿到 **所有插件工具** |
| `plugins.allow` | 含 `option-trading-assistant` | option-trading-assistant 的 **67 个工具** 全部注册并参与下发 |

因此：**每个使用插件能力的 Agent 在每次请求时都会在 system prompt 中带上全部 67 个 option-trading 工具的 name + description + parameters schema**，外加其他插件（dingtalk、feishu、tavily 等）和内置工具。

### 1.2 实际消耗（来自会话与 cron）

- **单次会话 system prompt**（etf_data_collector_agent 示例）：
  - `systemPrompt.chars` ≈ 30k 字符（其中 projectContext ≈16k，nonProject ≈14k）
  - `tools.listChars` ≈ 7.7k，**tools.schemaChars ≈ 42k**（仅工具列表+ schema 即约 42k 字符）
- **Cron 单次 run 的 usage**（盘后分析等）：
  - `input_tokens` 常见在 **10 万～21 万**（如 105392、138750、181649、214037）
  - 每次轮询/巡检都会重复携带完整工具 schema，导致输入 token 居高不下

根因归纳：**所有 Agent 使用 `group:plugins` 或继承默认，未按职责缩小工具集，67 个自定义工具 + 其他插件的 schema 一起进入每条请求的 system prompt，造成大量重复 token 消耗与潜在性能负担。**

---

## 二、优化建议（按优先级）

### 2.1 【P0】按 Agent 限定工具白名单（强烈建议）

OpenClaw 支持在 `agents.list[].tools.allow` 中写 **具体工具名**，只把该 Agent 需要的工具放进 prompt，其余插件工具不会注入。

**做法**：为每个 Agent 配置显式 `tools.allow`，只列出该 Agent 实际会调用的 option-trading 工具名（+ 需要的内置/其他插件工具）。

建议清单（按当前 cron / SOUL 使用情况归纳）：

**etf_data_collector_agent**（仅数据采集）：

```json
"tools": {
  "allow": [
    "tool_fetch_index_realtime",
    "tool_fetch_index_historical",
    "tool_fetch_index_minute",
    "tool_fetch_index_opening",
    "tool_fetch_global_index_spot",
    "tool_fetch_etf_realtime",
    "tool_fetch_etf_historical",
    "tool_fetch_etf_minute",
    "tool_fetch_option_realtime",
    "tool_fetch_option_greeks",
    "tool_fetch_option_minute",
    "tool_fetch_a50_data",
    "tool_get_option_contracts",
    "tool_check_trading_status"
  ]
}
```

（若该 Agent 还需读缓存，可加 `tool_read_index_daily` 等；不需要的尽量不加。）

**etf_analysis_agent**（分析 + 研究 + 通知 + 部分数据）：

- 数据：`tool_fetch_etf_realtime`, `tool_fetch_index_realtime`, `tool_fetch_index_opening`, `tool_fetch_global_index_spot`, `tool_read_*` 等按需
- 分析：`tool_analyze_after_close`, `tool_analyze_before_open`, `tool_analyze_opening_market`, `tool_calculate_historical_volatility`, `tool_generate_signals`, `tool_predict_volatility`, `tool_predict_intraday_range`, `tool_detect_market_regime`, `tool_etf_rotation_research`, `tool_backtest_etf_rotation`, `tool_strategy_research`, `tool_get_strategy_research_history`（可选，读策略研究 JSONL 摘要）, `tool_quantitative_screening`
- 涨停/资金：`tool_fetch_limit_up_stocks`, `tool_sector_heat_score`, `tool_write_limit_up_with_sector`, `tool_limit_up_daily_flow`, `tool_dragon_tiger_list`, `tool_capital_flow`, `tool_fetch_northbound_flow`, `tool_fetch_stock_realtime`, `tool_fetch_stock_financials`
- 通知：`tool_send_analysis_report`, `tool_send_feishu_message`, `tool_send_risk_alert` 等
- 其他：`tavily_search`, `web_fetch`, `read`, `exec`, `message` 等按需

**etf_main**（编排 + 巡检 + 子 Agent）：

- 保留 `tavily_search`、`group:plugins` 或改为显式列表（见下）。
- 若希望继续「可调用所有业务工具」，可保留 `group:plugins`，仅对 **data_collector / analysis / notification** 做收口，也能明显降低大部分 cron 的 token。

**etf_notification_agent**（若存在且仅负责通知）：

- 只放：`tool_send_feishu_message`, `tool_send_signal_alert`, `tool_send_analysis_report`, `tool_send_risk_alert`, `tool_send_feishu_card_webhook`, `message` 等。

实施后：**data_collector / analysis 等单次请求的工具 schema 从 67 个降到约 10～25 个**，工具相关 token 可预期明显下降（约一半以上可期）。

---

### 2.2 【P1】缩短工具描述（manifest / 插件）

当前 `config/tools_manifest.yaml` 中多数工具的 `description` 较长，且带「何时用」等说明，会原样进入 LLM 的 system prompt。

**建议**：

- 在 manifest 中为「给 LLM 用」的字段做**简短描述**（一句话，尽量控制在 50 字内），例如：
  - 原：`获取主要指数的实时行情数据（融合Coze get_index_realtime.py）。何时用：盘前/盘中快扫。`
  - 简：`获取指数实时行情，支持多代码逗号分隔。`
- 若希望保留详细说明，可：
  - 在 manifest 中增加 `description_short`（或单独一个字段），插件注册时优先用 short 作为工具的 `description`；
  - 长版仅用于文档或「工具参考手册」。

这样在不改变工具数量的前提下，进一步减少每工具占用的 token。

---

### 2.3 【P1】Cron 任务 payload 瘦身

部分 cron（如信号+风控巡检）的 `payload.message` 极长（多段步骤、口径、涨停回马枪说明等），直接塞进每条 agent turn，会拉高 input token。

**建议**：

- 将「固定步骤与口径」抽到 **Skill 或工作区 Markdown**（如 `~/.openclaw/prompts/research.md` 已有部分），cron 的 `message` 只写一句入口说明 + 「请严格遵循 xx 文档第 n 节」。
- 或：`message` 只写任务类型与时间口径，具体步骤由 Agent 通过 `read` 读取 `research.md` / 某 SOUL 节，避免每次把整份长文本当 user message 发送。

效果：单次 cron 的 user message 变短，整体 input_tokens 下降。

---

### 2.4 【P2】compaction / 记忆与上下文

当前 `openclaw.json` 中已配置 `compaction.mode: "safeguard"`、`memoryFlush`、`reserveTokensFloor: 25000` 等，用于控制上下文与记忆压缩。

**建议**：

- 若单轮对话轮次多、历史很长，可结合「工具白名单 + 短描述」后，再观察是否仍需提高 `reserveTokensFloor` 或调整 `memoryFlush.softThresholdTokens`，避免因工具 schema 占用过多导致有效上下文被压得过狠。
- 一般不建议为「省 token」而过度压缩记忆，优先先做工具与 payload 瘦身。

---

### 2.5 【P2】监控与观测

- 在关键 cron（如盘后分析、信号巡检）的 `delivery` 或日志中保留 `usage.input_tokens` / `usage.total_tokens`（若 OpenClaw 已写入），便于对比「改白名单前/后」和「缩短描述后」的 token 与耗时。
- 可为「工具 schema 总字符数」做简单统计（例如从 session 的 `tools.schemaChars` 或插件加载结果汇总），作为长期监控指标。

---

## 三、实施顺序建议

1. **先做 P0**：在 `~/.openclaw/openclaw.json` 的 `agents.list` 里，为 `etf_data_collector_agent`、`etf_analysis_agent`（及若存在的 `etf_notification_agent`）设置上述 **显式 `tools.allow`**，不改其他逻辑。
2. **观察 1～2 天**：看 cron 的 `input_tokens`、执行时长与成功率是否改善。
3. **再做 P1**：在 `config/tools_manifest.yaml`（及生成 JSON 的逻辑）中增加短描述并让插件采用；同时将最长几条 cron 的 payload 改为「引用 research.md / Skill」。
4. **按需做 P2**：根据监控调整 compaction/记忆参数，并固化 token/字符数监控方式。

---

## 四、openclaw.json 修改示例（仅 P0 片段）

以下仅展示 **etf_data_collector_agent** 和 **etf_analysis_agent** 的 `tools` 修改示例，其余 agent 保持原样或按上表补全 allow 列表。

```json
{
  "agents": {
    "list": [
      {
        "id": "etf_data_collector_agent",
        "name": "etf_data_collector_agent",
        "workspace": "/home/xie/.openclaw/workspaces/etf-options-ai-assistant",
        "agentDir": "/home/xie/.openclaw/agents/etf-options-ai-assistant/data_collector_agent/agent",
        "model": { ... },
        "tools": {
          "allow": [
            "tool_fetch_index_realtime",
            "tool_fetch_index_historical",
            "tool_fetch_index_minute",
            "tool_fetch_index_opening",
            "tool_fetch_global_index_spot",
            "tool_fetch_etf_realtime",
            "tool_fetch_etf_historical",
            "tool_fetch_etf_minute",
            "tool_fetch_option_realtime",
            "tool_fetch_option_greeks",
            "tool_fetch_option_minute",
            "tool_fetch_a50_data",
            "tool_get_option_contracts",
            "tool_check_trading_status"
          ]
        }
      },
      {
        "id": "etf_analysis_agent",
        "name": "etf_analysis_agent",
        "workspace": "/home/xie/.openclaw/workspaces/etf-options-ai-assistant",
        "agentDir": "/home/xie/.openclaw/agents/etf-options-ai-assistant/analysis_agent/agent",
        "model": { ... },
        "tools": {
          "allow": [
            "tavily_search",
            "web_fetch",
            "tool_fetch_index_opening",
            "tool_fetch_index_realtime",
            "tool_fetch_etf_realtime",
            "tool_fetch_global_index_spot",
            "tool_analyze_after_close",
            "tool_analyze_before_open",
            "tool_analyze_opening_market",
            "tool_calculate_historical_volatility",
            "tool_generate_signals",
            "tool_predict_volatility",
            "tool_predict_intraday_range",
            "tool_detect_market_regime",
            "tool_etf_rotation_research",
            "tool_strategy_research",
            "tool_get_strategy_research_history",
            "tool_send_daily_report",
            "tool_send_feishu_message",
            "tool_send_risk_alert",
            "tool_fetch_limit_up_stocks",
            "tool_sector_heat_score",
            "tool_write_limit_up_with_sector",
            "tool_limit_up_daily_flow",
            "tool_dragon_tiger_list",
            "tool_capital_flow",
            "tool_fetch_northbound_flow",
            "tool_quantitative_screening",
            "tool_fetch_stock_realtime",
            "tool_fetch_stock_financials",
            "tool_read_index_daily",
            "tool_read_index_minute",
            "tool_read_etf_daily",
            "tool_read_etf_minute",
            "tool_read_option_minute",
            "tool_read_option_greeks",
            "tool_record_signal_effect"
          ]
        }
      }
    ]
  }
}
```

注意：`allow` 中只写 **工具名**；未列出的 option-trading 工具（如回测、部分通知）该 Agent 将不可见，若后续需要再按需追加。根据 OpenClaw 文档，**仅列出插件工具名时，core 工具（read、exec、message 等）仍会保留**，无需在 allow 中显式写出。

---

## 五、小结

| 问题 | 根因 | 建议 |
|------|------|------|
| 单次请求 input token 过高（10 万～21 万） | 所有相关 Agent 携带全部 67 个自定义工具 + 其他插件 schema | 按 Agent 配置 `tools.allow` 白名单，只暴露该 Agent 需要的工具 |
| 工具描述占用多 | description 过长且带说明性文字 | manifest 增加短描述，注册时用短版给 LLM |
| Cron payload 过长 | 长步骤/口径直接写在 message 里 | 步骤与口径迁到 research.md/Skill，message 只引用 |
| 性能与成本 | 同上，每次请求解析与传输大段 schema | 白名单 + 短描述后，再视情况调 compaction/记忆 |

优先完成 **P0 按 Agent 工具白名单**，即可在不大改业务逻辑的前提下，明显降低 token 消耗与 OpenClaw 负载；再配合 P1/P2 可进一步优化。

---

## 六、P2 实施说明（compaction 与监控）

### 6.1 Compaction / 记忆

当前 `openclaw.json` 中 `agents.defaults.compaction` 已配置：

- `mode: "safeguard"`
- `reserveTokensFloor: 25000`
- `memoryFlush.enabled: true`，`softThresholdTokens: 4000`

实施 P0/P1 后，工具 schema 与 cron message 占用减少，一般无需立刻调高 `reserveTokensFloor`。若单轮对话轮次很多、历史很长，可观察 1～2 周后再视情况将 `reserveTokensFloor` 微调（例如 28000～30000），或略调 `memoryFlush.softThresholdTokens`，避免有效上下文被压得过狠。

### 6.2 Token 与用量监控

- **Cron 用量汇总**：项目内已提供脚本  
  `etf-options-ai-assistant/scripts/check_cron_token_usage.py`  
  读取 `~/.openclaw/cron/runs/*.jsonl` 中近期 `action=finished` 且带 `usage` 的记录，按 `input_tokens` 排序输出，便于对比优化前后。示例：
  ```bash
  python scripts/check_cron_token_usage.py --days 7 --top 20
  ```
- **会话级**：若 OpenClaw 在 session 元数据中写入 `tools.schemaChars` 或类似字段，可定期查看各 Agent 的会话文件，观察工具 schema 总字符数是否随白名单与短描述下降。
