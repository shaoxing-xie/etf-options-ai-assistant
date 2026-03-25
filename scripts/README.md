# `scripts/` 运维与辅助脚本

本目录脚本**不属于** OpenClaw 插件日常调用路径，用于发布检查、本地运维、预警轮询、配置生成等。  
在项目根目录执行（`cd` 到仓库根）：

```bash
cd /path/to/etf-options-ai-assistant
```

---

## 发布与质量门禁

| 脚本 | 用途 | 示例 |
|------|------|------|
| `release_safety_gate.py` | 发布前检查：绝对路径泄露、类密钥明文、本机专属硬编码等 | `python3 scripts/release_safety_gate.py` |
| `check_json_syntax.py` | 校验仓库内 `*.json` 语法（排除 `.venv` 等） | `python3 scripts/check_json_syntax.py` |

---

## 配置与清单生成

| 脚本 | 用途 | 示例 |
|------|------|------|
| `generate_tools_json.py` | 从 `config/tools_manifest.yaml` 生成 `config/tools_manifest.json`（插件加载用） | `python3 scripts/generate_tools_json.py`（需 `pip install pyyaml`） |
| `sync_openclaw_model_routes.py` | 同步/校验 OpenClaw 模型路由相关 JSON 配置（与主备模型切换配合） | `python3 scripts/sync_openclaw_model_routes.py` |

---

## OpenClaw / Cron 运维

| 脚本 | 用途 | 示例 |
|------|------|------|
| `cleanup_unused_openclaw_agents.py` | 根据 `openclaw.json` 中已注册 agent，清理未引用的 agent 定义目录（**先备份**） | `python3 scripts/cleanup_unused_openclaw_agents.py` |
| `check_cron_token_usage.py` | 汇总 `~/.openclaw/cron/runs/*.jsonl` 中近期 `finished` 的 token 用量 | `python3 scripts/check_cron_token_usage.py --days 7 --top 20` |
| `test_cron_tools.sh` | 从 `jobs.json` 抽取 `tool_*` 并对 `tool_runner.py` 冒烟（默认跳过 `tool_send_*`） | `./scripts/test_cron_tools.sh --help` |
| `check_third_party_skills.sh` | 检查推荐/可选 OpenClaw 第三方技能是否已安装 | `./scripts/check_third_party_skills.sh` |

---

## 数据库与性能

| 脚本 | 用途 | 示例 |
|------|------|------|
| `optimize_database_indexes.py` | 为 `data/signal_records/`、`data/prediction_records/` 下 SQLite 建索引 | `python3 scripts/optimize_database_indexes.py` |

---

## 波动区间预测评估与回填（宽基ETF巡检快报闭环）

| 脚本 | 用途 | 示例 |
|------|------|------|
| `update_intraday_range_actuals.py` | 收盘后回填 `predictions_{date}.json` 的 `actual_range`，并计算 `hit` | `python3 scripts/update_intraday_range_actuals.py --date 20260325` |
| `generate_intraday_range_weekly_report.py` | 生成覆盖率/区间宽度等周报，落盘到 `data/prediction_reports/` | `python3 scripts/generate_intraday_range_weekly_report.py --week-start 20260324` |
| `monitor_intraday_range_method_metrics.py` | 监控方法分组占比与已验证样本的 `coverage_rate/average_width_pct` | `python3 scripts/monitor_intraday_range_method_metrics.py --days 14` |

---

## 监控与预警（独立小系统）

与 `data/alerts.json`、`data/pending_notifications.json` 等配合，可由 cron 周期性调用：

| 脚本 | 用途 | 示例 |
|------|------|------|
| `monitor_510300_run.py` | 510300 实盘监控逻辑 + webhook（钉钉/飞书），依赖 `ETF_OPTIONS_PROJECT` 指向本项目 | `python3 scripts/monitor_510300_run.py` |
| `alert_engine.py` | 价格预警：读写 `data/alerts.json`、条件判断、钉钉相关 | 通常由 `alert_poll.py` 间接使用 |
| `alert_poll.py` | 轮询活跃预警（如每 10 分钟 cron） | `python3 scripts/alert_poll.py` |
| `alert_notify.py` | 消费 `pending_notifications.json`，输出供 OpenClaw/Agent 发送 | `python3 scripts/alert_notify.py` |
| `fetch_stock_realtime.py` | 供 `alert_engine` 使用的 AkShare 批量实时行情封装 | 一般不作为 CLI 单独使用 |

---

## 与 `tests/` 的区别

- **`scripts/`**：运维、发布、预警、配置生成；可带环境变量与机器路径。
- **`tests/`**：见 `tests/README.md`（`pytest` 冒烟 + `tests/integration/` 长耗时集成脚本）。

更完整的项目结构说明见：`docs/PROJECT_LAYOUT.md`。
