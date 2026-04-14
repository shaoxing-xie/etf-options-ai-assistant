# 通知插件（`plugins/notification`）

宽基 ETF / 期权助手相关的 **钉钉** 与 **飞书** 投递实现。OpenClaw / `tool_runner` 暴露的工具 id 以 [`config/tools_manifest.yaml`](../../config/tools_manifest.yaml) 为准；钉钉契约摘要见 [`docs/openclaw/dingtalk_delivery_contract.md`](../../docs/openclaw/dingtalk_delivery_contract.md)。

---

## 1. OpenClaw 工具一览

### 1.1 本目录直接注册（`tool_runner.py` → `TOOL_MAP`）

| 工具 id | 模块 | 作用 |
|---------|------|------|
| `tool_send_dingtalk_message` | `send_dingtalk_message` | 钉钉自定义机器人：Markdown/文本、SEC 加签、关键词、`mode=prod\|test`、可按 `##` 拆条。 |
| `tool_send_signal_risk_inspection` | `send_signal_risk_inspection` | 巡检快报专用发送：接收结构化 `report` 字段，固定模板渲染后再委托钉钉发送。 |
| `tool_run_signal_risk_inspection_and_send` | `run_signal_risk_inspection` | Cron 推荐：进程内拉 000300/399006/000905 + 510300/510500/159915 实时与组合风险快照，组装 `report` 后调用上一行发送。 |
| `tool_send_analysis_report` | `send_analysis_report` | 将 `report_data` 经 `send_daily_report._format_daily_report` 排版后，**委托** `tool_send_dingtalk_message` 发出。 |
| `tool_send_feishu_card_webhook` | `send_feishu_card_webhook` | 飞书 **interactive** 卡片（`msg_type` + `card`），走 webhook。 |

### 1.2 别名入口（实际调用 `merged.send_feishu_notification`）

[`tool_runner.py`](../../tool_runner.py) 中 `ALIASES` 将下列 id 路由到 **`tool_send_feishu_notification`**（实现位于 [`plugins/merged/send_feishu_notification.py`](../merged/send_feishu_notification.py)），**不在本目录重复实现发送 HTTP**：

| 工具 id | `notification_type` | 说明 |
|---------|---------------------|------|
| `tool_send_feishu_message` | `message` | 飞书普通文本类通知。 |
| `tool_send_signal_alert` | `signal_alert` | 飞书信号提醒（manifest 参数多为 `signals` 列表；具体格式化见 merged 与 `send_signal_alert.py` 辅助逻辑）。 |
| `tool_send_risk_alert` | `risk_alert` | 飞书风险预警。 |
| `tool_send_daily_report` | `send_daily_report` | **`tool_runner` 直接调用** `notification.send_daily_report.tool_send_daily_report`（含 prod 门禁）；`tool_send_analysis_report` 内部亦委托同一函数。 |

### 1.3 `send_daily_report.py` 中的 `tool_send_daily_report`

模块内 **`tool_send_daily_report(report_data, ...)`**：排版 → `tool_send_dingtalk_message`。命令行 **`python tool_runner.py tool_send_daily_report '<json>'`** 与 `tool_send_analysis_report` 应对齐（后者委托前者）。

---

## 2. 模块文件说明

| 文件 | 说明 |
|------|------|
| `send_dingtalk_message.py` | 钉钉发送核心：加签 URL、正文截断/拆条、关键词前缀、`mode=test` 干跑。 |
| `send_signal_risk_inspection.py` | 巡检快报专用：结构化字段清洗、固定模板渲染、委托 `tool_send_dingtalk_message` 发送。 |
| `run_signal_risk_inspection.py` | 巡检采集+发送：`build_inspection_report`、`tool_run_signal_risk_inspection_and_send`。 |
| `send_daily_report.py` | 各类 `report_type` 的 Markdown 排版（`_format_daily_report`）；含 `tool_send_daily_report`。 |
| `send_analysis_report.py` | 分析/研究类报告：复用排版函数后调钉钉。 |
| `send_feishu_card_webhook.py` | 飞书 interactive 卡片 webhook。 |
| `send_signal_alert.py` | 信号相关格式化/门槛等 **辅助**（与 merged 通知配合；Runner 不直接指向本文件为 TOOL_MAP 入口）。 |
| `send_feishu_message.py` | 飞书消息相关 **历史/直接调用** 入口；对外工具以 merged 为准。 |
| `notification_cooldown.py` | **非工具**：发送前去重/冷却，由 `merged/send_feishu_notification.py` 引用。 |
| `dingtalk_quota.py` | **非工具**：钉钉条数/窗口配额（当前仓库内 **无发送路径引用**，预留或后续接入）。 |

---

## 3. 配置与环境变量

### 钉钉（定时长文、巡检等）

- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL`
- `OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET`（SEC 加签）
- `DINGTALK_KEYWORD` / `MONITOR_DINGTALK_KEYWORD`（机器人启用关键词时）

进程需能读取 `~/.openclaw/.env`（与 Gateway 一致）。

### 飞书

- 合并后配置 `notification.feishu_webhook`（来源：`config/domains/outbound.yaml`；默认 `${FEISHU_WEBHOOK_URL}`）
- 或环境变量：`FEISHU_WEBHOOK_URL`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`（API 模式见 merged 实现）

---

## 4. 自测与排障

- 盘前/报告类钉钉（JSON 参数文件）：  
  `python3 tool_runner.py tool_send_analysis_report @scripts/examples/before_open_dingtalk_args.test.json`  
  真发前核对 `.env` 后改用 `...prod.json`。
- 脚本：`bash scripts/dingtalk_before_open_smoke.sh test|prod`
- 巡检快报：`bash scripts/dingtalk_signal_inspection_smoke.sh test|prod`（走 `tool_send_signal_risk_inspection`；正文需含「巡检」等关键词时与后台一致）
- 钉钉返回 **310000**：多为 SEC 与机器人后台密钥不一致。

---

## 5. 数据流（简图）

```
分析 / 信号 / 工作流
        │
        ├─► report_data ──► _format_daily_report ──► tool_send_dingtalk_message ──► 钉钉
        │
        ├─► tool_run_signal_risk_inspection_and_send ──► tool_send_signal_risk_inspection ──► tool_send_dingtalk_message ──► 钉钉
        ├─►（手工）report ──► tool_send_signal_risk_inspection ──► tool_send_dingtalk_message ──► 钉钉
        │
        ├─► tool_send_feishu_notification（经别名：消息 / 信号 / 风险）──► 飞书 webhook
        │
        └─► tool_send_feishu_card_webhook ──► 飞书 interactive 卡片
```

---

## 6. 依赖

- 钉钉/飞书 HTTP：标准库 `urllib` 与/或 `requests`（以各实现文件 import 为准）。

---

## 7. 维护提示

- 修改对外工具名或行为后：同步 **`config/tools_manifest.yaml`** 并执行 `python scripts/generate_tools_json.py`。
- 工作流中「仅钉钉 / 禁飞书扇出」等文案以 **`docs/openclaw/dingtalk_delivery_contract.md`** 为权威，YAML 内多为摘要指针。
