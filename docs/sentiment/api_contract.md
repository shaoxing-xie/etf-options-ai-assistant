# 情绪聚合侧车 JSON（`report_data.sentiment_precheck` / 落盘）

供 `pre_market_sentiment_check`、开盘分析等任务对齐字段名与落盘位置。**不替代**四工具原始 JSON；侧车文件便于下游只读加载与审计。

## 落盘路径（最新快照 + 历史审计）

- **最新快照（UI 读取）**：相对仓库根 `data/sentiment_check/YYYY-MM-DD.json`
- **历史审计（不覆盖，用于对账）**：相对仓库根 `data/sentiment_check/history/YYYY-MM-DD__HHMMSS.json`
- `YYYY-MM-DD`：**交易日**（Asia/Shanghai），与 `tool_check_trading_status` 给出的 `current_time` 日期一致，或与四工具返回的 `date` 一致；不得混用随机历史 `date` 重拉涨停。
- `HHMMSS`：以 `sentiment_meta.generated_at`（Asia/Shanghai）对应的本地时间生成；同一秒多次运行允许在文件名末尾追加 `__r2`、`__r3` 等去重。

## 根对象字段（须齐全）

| 字段 | 类型 | 说明 |
|------|------|------|
| `overall_score` | number | 0–100 综合情绪分 |
| `sentiment_stage` | string | 如：中性 / 偏空 / 高潮期 / 冰点 / 退潮 / `insufficient_evidence` |
| `factor_attribution` | object | 四工具各自贡献摘要（可含子键 `limit_up`、`fund_flow`、`northbound`、`sector`）；北向子键见下节 **北向时间口径** |
| `sentiment_dispersion` | number 或 object | 子项分歧度；若无标准差，至少 `{"spread": max-min}` |
| `data_completeness_ratio` | number | 0–1，成功可用数据源数 / 4 |
| `action_bias` | string | 防御 / 中性 / 略偏多 等（禁止具体买卖价） |
| `risk_counterevidence` | string[] | 与主结论相反或削弱确定性的证据列表 |
| `confidence_band` | string 或 object | 如 `low`/`medium`/`high` 或 `{ "level": "medium", "reason": "..." }` |
| `degraded` | boolean | 任一工具失败或质量闸门未通过则为 `true` |
| `sentiment_meta` | object | 至少 `sentinel_version`（字符串）、`weight_profile`（字符串或对象）、`generated_at`（ISO8601） |
| `cache_ttl_policy` | object | 建议含 `opening_first_hour`（300）、`mid_session`（900）、`closing_hour`（600），单位为秒 |

## 可选

- `status`: 正常省略；证据不足时设为 `insufficient_evidence`。
- `tool_digest`: 各工具 `success` / `quality_score` / `error_code` 摘要，便于对账。
- `openclaw_session_id`: string | null，用于将侧车与 `~/.openclaw/agents/*/sessions/<sessionId>.jsonl` 对账（若运行环境可提供则写入；不可用则省略或置 null）。

## 侧车与 toolResult 一致性（禁止占位杜撰）

- `write` 落盘前，Agent **必须**以**本回合会话中已产生的**对应 `toolResult` 为准填写 `factor_attribution` 各子键；若某工具已成功返回 JSON，则该子键须 `success: true`（或等价），并摘要真实字段（数值、date、`error` 等），**禁止**用下列未经验证的套话占位：
  - `"Tool output not available due to context constraints."`
  - 无插件依据的泛泛 `error_code: "DATA_UNAVAILABLE"`（除非工具返回体中**确实**含相同错误码/信息）。
- 若因上下文过长未保留某工具输出：须**先 `read` 会话或重新调用该工具（仍受「每工具最多 1 次」约束）**，不得编造失败。
- `data_completeness_ratio` 须与四子键实际可用性一致（成功可用源数 / 4），不得在四工具已成功时仍写 `0.25`。

## 采集纪律

- `tool_fetch_limit_up_stocks`、`tool_fetch_a_share_fund_flow`、`tool_fetch_northbound_flow`、`tool_fetch_sector_data`：**各最多成功调用一次**；默认参数见 `workflows/pre_market_sentiment_check.yaml`，**禁止**为「补上下文」擅自改 `date` 重复拉取。

## Cron 与钉钉

- `jobs.json` 中 `delivery.mode: none` 的 **单 Agent 任务**：不执行 yaml 中的 `tool_send_dingtalk_message` 步；钉钉由托管编排或其它已配置投递的任务负责。

## 北向时间口径（`factor_attribution.northbound`）

- `tool_fetch_northbound_flow` 返回的 **`date`** 表示**该条净流入对应的交易日**（Tushare/主源常见为最近已披露、已闭市的交易日）。
- **开盘前**（如 09:10、`tool_check_trading_status` 为 `before_open`）工具 `date` 常为**上一交易日**，与侧车文件名 `data/sentiment_check/YYYY-MM-DD.json` 中的「锚定交易日」**可以不一致**，属**正常**，不是数据错误。
- 侧车中 `factor_attribution.northbound` **必须**包含：
  - `data_date`：字符串，与工具 JSON 顶层的 `date` 对齐（建议规范为 `YYYY-MM-DD`，若工具为 `YYYYMMDD` 则转换）。允许与顶层 `date` 并存，二者须一致。
  - `explanation`：凡 `data_date` 早于锚定交易日、或仍处于开盘前，须使用 **「上一交易日」**、**「截至 data_date」** 等表述；**禁止**使用「今日净流入」等措辞，除非工具 `date` 与锚定交易日一致且语义上确指同一交易日。
- **金额与 signal 文案**：工具返回的 `total_net` 与 `signal.description` 可能因插件内部阈值/量纲与对外展示不一致（例如 description 写「>100亿」而按惯例折算后约为数十亿）。侧车与飞书须 **以 `total_net` 与工具字段含义自洽为准**；若明显矛盾，在 `factor_attribution.northbound` 增加 `narration_note`（或等价说明），**勿**在对外文案中照搬与数值冲突的插件套话。
- 可选：`label`（如 `"上一交易日净流向（亿元）"`）、`total_net_unit`（若工具或 README 明确单位）便于审计。

## 上游数据失败（如北向）

- `tool_fetch_northbound_flow` 失败时：在 `factor_attribution.northbound` 写明 `success:false` 与 `error_code`；`degraded=true`；下调 `data_completeness_ratio`；在 `risk_counterevidence` 中列出「北向不可用」对情绪判断的不确定性。**不得**为凑数重复调用其它日期或静默丢弃失败事实。
