# 信号+风控巡检：Cron 日志分层排查

## 1. 自动化分类与质量统计

```bash
cd /home/xie/etf-options-ai-assistant
python3 scripts/triage_cron_signal_inspection.py --days 14
```

脚本读取 `~/.openclaw/cron/runs/etf-signal-risk-inspection-(morning|midday|afternoon)-*.jsonl`（文件名前缀仍为 `etf-signal-risk-inspection`），统计：

- **llm-like**：含 `403`、`All models failed`、`timeout`、`quota` 等。
- **dingtalk/delivery-like**：含 `钉钉`、`关键词`、`310000`、`dingtalk` 等。
- **anomaly_summary_ratio**：异常摘要占比（见第 2 节定义）。
- **overlap_skip_count**：同 job in-flight 期间的 `skip(reason=already-running|schedule-due-while-already-running)` 次数。

人工复核时打开对应 `sessionKey` 在 OpenClaw 会话中查看完整轨迹。

## 2. ACK 与异常摘要口径（验收硬定义）

- ACK 必须是单行 JSON，且包含：
  - `run_status`, `run_quality`, `phase`, `degraded`, `run_id`, `ts`
- 异常摘要定义（`anomaly_summary_ratio` 分子）：
  - `summary` 不是 ACK JSON；或
  - 命中伪 tool_call 特征（`<tool_call>`, `<function>`, `toolCall`）；或
  - 命中乱码/异常文本规则（脚本内固定正则）。
- 公式：
  - `anomaly_summary_ratio = anomalous_finished / finished_total`

## 3. LLM 侧缓解（与 OpenClaw 配置）

- 确认 `etf_main` cron 会话使用的 provider/model 可用；出现集中 **403** 时检查 SiliconFlow/OpenRouter 等配额与密钥。
- 巡检工作流约束为 ACK 结构输出，减少无效长文与 token；若仍超时，在网关侧放宽该 cron timeout 或切更快模型（在本机 OpenClaw/Gateway 配置中调整）。
- 与 `llm-health-monitor` 等任务联动：告警出现时先切换 provider 再重试。

## 4. 钉钉侧

- 使用 `bash scripts/dingtalk_signal_inspection_smoke.sh prod` 验证 `errcode=0`。
- 错误码 `310000`：`OPENCLAW_DINGTALK_CUSTOM_ROBOT_SECRET` 与钉钉后台 SEC 不一致。

## 5. 组合风险工具

- `python3 tool_runner.py tool_portfolio_risk_snapshot '{}'`：依赖本地 ETF 日线缓存与 `config/portfolio_weights.json`（可复制 `portfolio_weights.example.json`）。
- 机构占位：`tool_compliance_rules_check`、`tool_stop_loss_lines_check`、`tool_stress_test_linear_scenarios`、`tool_risk_attribution_stub`（见 `config/*.example.yaml`）。

## 6. Cron `payload.message` 模板（`~/.openclaw/cron/jobs.json`）

三档任务仅 `phase` 不同；**唯一必需工具调用**：

- **早盘** `etf-signal-risk-inspection-morning`：`tool_run_signal_risk_inspection_and_send(phase='morning', mode='prod', fetch_mode='production', workflow_profile='cron_balanced', stage_budget_profile='balanced', emit_stage_timing=true, max_concurrency=1)`
- **午间** `etf-signal-risk-inspection-midday`：`tool_run_signal_risk_inspection_and_send(phase='midday', mode='prod', fetch_mode='production', workflow_profile='cron_balanced', stage_budget_profile='balanced', emit_stage_timing=true, max_concurrency=1)`
- **下午** `etf-signal-risk-inspection-afternoon`：`tool_run_signal_risk_inspection_and_send(phase='afternoon', mode='prod', fetch_mode='production', workflow_profile='cron_balanced', stage_budget_profile='balanced', emit_stage_timing=true, max_concurrency=1)`

本地 smoke（不经钉钉）：

```bash
python3 tool_runner.py tool_run_signal_risk_inspection_and_send phase=midday mode=test fetch_mode=production workflow_profile=cron_balanced stage_budget_profile=balanced emit_stage_timing=true max_concurrency=1
```

### 数据不全时排查顺序（与日报类任务一致）

- **禁止**不经逐项核对就归因于“数据采集工具坏了”“网络不稳定”；应先走完字段映射与环境核对，再考虑外网/供应商。
- 采集层单独 `tool_runner` 往往正常；优先查 `report` 字段映射、OpenClaw 多轮 JSON 截断、键名别名。
- 复合工具上线后传送链在进程内，仍应对照 `plugins/notification/run_signal_risk_inspection.py` 与 `send_signal_risk_inspection._REQUIRED_REPORT_KEYS` 逐字段核对。

## 7. Delivery 成功主判据（权威来源）

- 主判据：`tool_send_signal_risk_inspection` 的 `toolResult.delivery`（在 `data.delivery_truth` 镜像）。
- 辅助判据：runs 文件中的 `deliveryStatus` 仅用于历史观测，不作为成功主判据。
- 两者冲突时，以主判据为准并回看对应 `sessionKey`。

## 8. 回滚演练（参数级）

- 目标：验证可随时回退到 legacy/off 档位，不改调度形态。
- 演练命令（本地 test）：

```bash
python3 tool_runner.py tool_run_signal_risk_inspection_and_send phase=midday mode=test fetch_mode=production workflow_profile=legacy stage_budget_profile=off emit_stage_timing=false max_concurrency=1
```

- 期望结果：
  - 仍返回 ACK（`run_status/run_quality/phase/degraded/run_id/ts`）。
  - `data.workflow_profile=legacy`，`data.stage_budget_profile=off`。
  - `data.stage_timing` 不输出（与 off 档位一致）。
