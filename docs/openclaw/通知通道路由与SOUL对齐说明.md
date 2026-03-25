# 通知通道路由与 SOUL 对齐说明

## 背景

早期文档与部分 cron `payload.message` 中写的是 **「统一通知扇出（双通道）」**：同一份 Markdown **同时**发飞书群 + 钉钉群。

当前生产约定已调整为 **分通道路由**（与钉钉自定义机器人、飞书运维群分工一致）：

| 类型 | 主渠道 | 典型工具 / 别名 |
|------|--------|------------------|
| 研究 / 分析类长报告 | **钉钉** | `tool_send_dingtalk_message` / `send_dingtalk_message`（Webhook + 加签） |
| 运维 / 巡检 / 快报 | **飞书** | `send_feishu_webhook` / `tool_send_feishu_message` |

## SOUL 已更新的位置（本机 OpenClaw Agent）

以下文件中的 **「统一通知扇出（双通道）」** 已改为 **「统一通知路由规范（分通道）」**：

- `~/.openclaw/agents/etf-options-ai-assistant/analysis_agent/agent/SOUL.md`（`etf_analysis_agent`）
- `~/.openclaw/agents/etf-options-ai-assistant/main/agent/SOUL.md`（`etf_main`）

## 与 `jobs.json` 的关系

- **最高优先级**：单条任务的 `payload.message`。
- **已对齐（本机）**：`~/.openclaw/cron/jobs.json` 中下列分析类任务已改为 **仅钉钉**（不再要求「双通道同时发飞书+钉钉」）：开盘行情分析、每日市场分析报告、ETF 轮动研究、策略研究与回放、盘后/盘前增强版、涨停回马枪盘后；`etf-510300-intraday-monitor` 改为 **仅钉钉**（可 `tool_send_dingtalk_message` 或 `message→钉钉`）；`策略引擎与信号融合` 改为 **默认静默**，仅在强信号场景允许 **简短** 钉钉摘要。
- **巡检类**（信号+风控三档）仍为 **仅飞书**（`send_feishu_webhook`），与 SOUL 一致。

## 同步到其它机器

若在新环境部署，请将上述两份 `SOUL.md` 与 `~/.openclaw/cron/jobs.json` 一并校对后复制到对应路径。
