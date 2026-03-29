# 信号+风控巡检：Cron 日志分层排查

## 1. 自动化分类

```bash
cd /home/xie/etf-options-ai-assistant
python3 scripts/triage_cron_signal_inspection.py --days 14
```

脚本读取 `~/.openclaw/cron/runs/etf-signal-risk-inspection-*.jsonl`，按窗口内 `status=error` 的 `error`+`summary` 文本做启发式分类：

- **llm-like**：含 `403`、`All models failed`、`timeout`、`quota` 等 → 优先检查模型网关、API Key、超时、单轮 token/工具负载。
- **dingtalk/delivery-like**：含 `钉钉`、`关键词`、`310000`、`dingtalk` 等 → 优先检查 `OPENCLAW_DINGTALK_*`、`DINGTALK_KEYWORD` 与机器人后台。

人工复核时打开对应 `sessionKey` 在 OpenClaw 会话中查看完整轨迹。

## 2. LLM 侧缓解（与 OpenClaw 配置）

- 确认 `etf_main` cron 会话使用的 provider/model 可用；出现集中 **403** 时检查 SiliconFlow/OpenRouter 等配额与密钥。
- 巡检工作流已约束为**仅输出模板本体**，减少无效输出与 token；若仍超时，在网关侧放宽该 cron 的 **timeout** 或换用更快模型（需在你本机 OpenClaw/Gateway 配置中调整）。
- 与 `llm-health-monitor` 等任务联动：告警出现时先切换 provider 再重试。

## 3. 钉钉侧

- 使用 `bash scripts/dingtalk_signal_inspection_smoke.sh prod` 验证 **errcode=0**。
- 错误码 **310000**：加签 `OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET` 与钉钉后台 SEC 不一致。

## 4. 组合风险工具

- `python3 tool_runner.py tool_portfolio_risk_snapshot '{}'`：依赖本地 ETF 日线缓存与 `config/portfolio_weights.json`（可复制 `portfolio_weights.example.json`）。
- 机构占位：`tool_compliance_rules_check`、`tool_stop_loss_lines_check`、`tool_stress_test_linear_scenarios`、`tool_risk_attribution_stub`（见 `config/*.example.yaml`）。
