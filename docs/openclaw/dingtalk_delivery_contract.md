# 钉钉长文投递契约（权威摘要）

工作流 YAML 中多处 `structured_message` 曾重复同一套「仅钉钉、禁飞书扇出」条款。本文档为 **单一锚点**；各 `workflows/*.yaml` 内仅保留短摘要并指向本节。

**环境变量（Gateway / OpenClaw 进程须加载 `~/.openclaw/.env`）**

- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL`
- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET`

**研究口径路径**：以本机 `~/.openclaw/prompts/research.md` 为准（第十节各专题）。

---

## 标准长文（`tool_send_daily_report` / `tool_send_dingtalk_message`）

适用于：`daily_market_report`、`after_close_analysis_enhanced`、`etf_rotation_research_agent`、`strategy_research_playback` 等与 **完整 Markdown 报告** 相关的定时任务。

1. **cron `delivery=none`**：禁止依赖调度器「代为发送」；须通过工具推到钉钉自定义机器人。
2. **优先** `tool_send_daily_report`（`report_data` 与 `research.md` 第十节对应小节一致；本工作区映射为钉钉 webhook，非飞书）。若不便拼装 `report_data`，则用 `tool_send_dingtalk_message`：`message`=完整 Markdown 正文，`title` 可选，**`mode` 必须为 `prod`**（禁止用 `test` 当作已发送）。
3. **禁止**：`tool_send_feishu_message`、飞书 webhook 扇出同一份长文、message 类工具做多通道/飞书投递（避免与「仅钉钉」任务冲突）。
4. 群备注（示例）：`cid0dqwAYvqu94+QEoODXL1uw==`（实际落群以 webhook 绑定为准）。
5. 失败勿令任务以 **error** 结束；在输出末尾记录原因与重试建议（可重试 1 次）。
6. **通知要求**：`delivery.mode` 保持 `none`。
7. **代码合并约定**：凡修改 `plugins/notification/**` 的 PR，**须在 PR 描述或首条评论写明** `AUTOFIX_ALLOWED=false`（与 `config/evolver_scope.yaml` → `denied_paths`、`docs/research/daily_market_report_web_benchmark.md` §3、`.github/pull_request_template.md` 一致）。

---

## 涨停回马枪盘后（`tool_send_analysis_report` 等）

适用于：`limitup_pullback_after_close.yaml`。

1. **cron `delivery=none`**：须工具推送钉钉自定义机器人；`tool_send_analysis_report(..., mode=prod, split_markdown_sections=true)`（以该工作流 `structured_message` 为准）。
2. 环境变量同上。
3. **禁止**：`tool_send_feishu_message` 对同一份长文扇出。
4. 失败勿令任务 error；输出末尾记原因与重试建议（可重试 1 次）。
5. **`delivery.mode`** 保持 `none`。

---

## 巡检快报（`tool_send_dingtalk_message` 专用）

适用于：`signal_risk_inspection.yaml`（早盘 / 上午 / 下午三套模板，仅 `phase` 不同）。

1. **cron `delivery.mode=none`**：**推荐**单次 **`tool_run_signal_risk_inspection_and_send`**（`phase=morning|midday|afternoon`，`mode=prod`），进程内组装模板并委托发送；与手工路径等价于填充后调用 **`tool_send_signal_risk_inspection`** → **`tool_send_dingtalk_message`**（`message`=模板正文，**`mode` 必须为 `prod`**）。依赖上述 `OPENCLAW_DINGTALK_*`。
2. **关键词**：首行已含「巡检」。若机器人报关键词不匹配，将 `DINGTALK_KEYWORD`（或 `MONITOR_DINGTALK_KEYWORD`）设为与钉钉后台**完全一致**；工具可自动前置关键词（见 `plugins/notification/send_dingtalk_message.py`）。
3. **禁止**：`send_feishu_webhook`、`tool_send_feishu_message` 或任何飞书渠道投递本快报。
4. 正文过长时工具可能截断：可拆成 2 次 `tool_send_dingtalk_message`（前半/后半）或压缩表格；第二次注明「（续）」。
5. 发送失败可重试 1 次；勿令任务 error。`INSPECTION_RUN_STATUS`：`ok`｜`dingtalk_fail`｜`partial`（定义见工作流内模板）。
6. 冒烟：`bash scripts/dingtalk_signal_inspection_smoke.sh test|prod`（仓库内）。

---

## 与质量巡检的交叉引用

- 单次巡检运行内 **最多 1 次** `tool_send_dingtalk_message` 等同文重复投递等约束，见 `workflows/quality_backstop_audit.yaml` 与 `docs/openclaw/hybrid_trigger_mapping.md`。
