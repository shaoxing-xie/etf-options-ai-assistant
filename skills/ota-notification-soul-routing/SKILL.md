---
name: ota_notification_soul_routing
description: 钉钉/飞书通道、tool_runner 别名与 merged 入口、与工作流 structured_message 对齐；凭证来自合并后配置占位与进程环境变量。
---

# OTA：通知通道路由与 SOUL 对齐

## 何时使用

- 选择通知类 `tool_*`（长文、快报、信号、风险、卡片）或核对「是否允许多通道扇出」。
- 对照 **`workflows/*.yaml`** 与本机 **cron/jobs.json**，检查 Agent **SOUL / WORKFLOW** 是否仍写旧约定（例如双通道同时发）。

## 实现分层（与 `plugins/notification` 一致）

### 钉钉（`plugins/notification` 直连 `TOOL_MAP`）

| 工具 id | 说明 |
|---------|------|
| `tool_send_dingtalk_message` | 自定义机器人：Markdown/文本、SEC 加签、关键词、`mode=prod\|test`、可按 `##` 拆条。 |
| `tool_send_analysis_report` | `report_data` → 与日报同源排版 → **委托** `tool_send_dingtalk_message`。 |

**路由**：`tool_runner` 中 **`tool_send_daily_report`** 与 **`tool_send_analysis_report`** 均落到 `send_daily_report.tool_send_daily_report`（分析类报告入口委托日报实现，共用 prod 门禁与钉钉投递）。

### 飞书（经别名进入 `merged.send_feishu_notification`）

| 工具 id | 实际 | 说明 |
|---------|------|------|
| `tool_send_feishu_message` | `tool_send_feishu_notification` + `notification_type=message` | 普通文本类。 |
| `tool_send_signal_alert` | 同上 + `signal_alert` | 信号提醒（参数常为 `signals` 等，见 manifest）。 |
| `tool_send_risk_alert` | 同上 + `risk_alert` | 风险预警。 |

发送前去重/冷却可能经 **`notification.notification_cooldown`**（由 merged 引用）。

### 飞书卡片（本目录直连）

| 工具 id | 说明 |
|---------|------|
| `tool_send_feishu_card_webhook` | `msg_type: interactive` 卡片 JSON。 |

**细表与维护**：[`plugins/notification/README.md`](../../plugins/notification/README.md)。

## 规程

1. **凭证**：不写死密钥；钉钉用 `OPENCLAW_DINGTALK_CUSTOM_ROBOT_WEBHOOK_URL` / `SECRET` / 关键词 env；飞书用 合并后配置 → `notification.*`（域文件：`config/domains/outbound.yaml`）或 `FEISHU_*`。
2. **通道**：**以任务绑定的 YAML 为准**。研究/盘前/盘后/日报等长文契约多为 **仅钉钉**（详见 **`docs/openclaw/dingtalk_delivery_contract.md`**）；**禁止**在契约写「仅钉钉」时对同一份长文再发飞书。
3. **巡检快报**：以 **`workflows/signal_risk_inspection.yaml`** 为准——**Cron 推荐** **`tool_run_signal_risk_inspection_and_send`（mode=prod）**；手工/排障可 **`tool_send_signal_risk_inspection`** → **`tool_send_dingtalk_message`（mode=prod）**；细则见钉钉契约 **§巡检快报**。
4. **生产**：定时任务 **禁止** 用 `mode=test` 当作已投递。
5. **失败**：按各 tool 返回处理；勿在无证下静默丢弃风控类告警。

## 钉钉群 @ 交互（必须遵守）

- 当**当前会话渠道为钉钉群聊**且用户**@机器人触发**时：必须在钉钉群内给出**可见回复**（至少 1 条短回复/摘要/“结果已投递到××”确认）。
- **禁止**在钉钉群 @ 交互中以 `NO_REPLY` 结束，或仅转发到飞书而不回钉钉。
- 若确因策略需要“正文走飞书”，钉钉群内也必须回一条：说明**已投递飞书**并附上**最关键 1–2 行结论**（例如区间上下界、置信度、时间戳）。
- 若历史记忆中出现“避免钉钉回复/禁止 `tool_send_dingtalk_message`”等旧偏好，与本节冲突时，必须忽略旧偏好，以本节同源回复规则为准。

## 权威文档

- [`plugins/notification/README.md`](../../plugins/notification/README.md)
- [`docs/openclaw/dingtalk_delivery_contract.md`](../../docs/openclaw/dingtalk_delivery_contract.md)
- [`docs/openclaw/通知通道路由与SOUL对齐说明.md`](../../docs/openclaw/通知通道路由与SOUL对齐说明.md)（若与 YAML 冲突，**以仓库工作流与 jobs 真源为准**并回写 SOUL）
- [`config/tools_manifest.yaml`](../../config/tools_manifest.yaml)、[`docs/openclaw/能力地图.md`](../../docs/openclaw/能力地图.md)
