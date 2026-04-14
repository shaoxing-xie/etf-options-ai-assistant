# Cron 任务中 `delivered` / `deliveryStatus` 与钉钉实际投递

OpenClaw `jobs.json` 里若 **`delivery.mode` 为 `none`**（与钉钉自定义机器人长文契约一致），框架**不会**把「会话外」的 HTTP 投递记为 `runs.jsonl` 中的 `delivered=true`。

- **验收口径**：以会话内 **`tool_send_daily_report` / `tool_send_dingtalk_message`** 的 `toolResult`（如钉钉 `errcode=0`）或群内是否收到为准。
- **`delivered=false` / `not-delivered`** 在此模式下**常为预期**，勿单独作为失败判据。
- 详见工作流 `workflows/daily_market_report.yaml` 中「通知要求 / 验收提示」。
