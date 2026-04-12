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
| `link_china_stock_data_collection.sh` | 将 `plugins/data_collection` 链到 **`~/.openclaw/extensions/openclaw-data-china-stock`**（或 `OPENCLAW_EXTENSIONS_DIR`）；否则回退到同级克隆目录；显式覆盖用 `OPENCLAW_DATA_CHINA_STOCK_ROOT` | `./scripts/link_china_stock_data_collection.sh` |
| **`install_china_stock_extension_copy.sh`** | **复制** `openclaw-data-china-stock` 到 `~/.openclaw/extensions/openclaw-data-china-stock`（rsync，排除 `.git`/venv/缓存等）；用于本地对齐发布包或开发仓。完成后执行 `ensure_openclaw_china_stock_plugin.py` + `link_china_stock_data_collection.sh`（脚本末尾有提示） | `./scripts/install_china_stock_extension_copy.sh` 或 `./scripts/install_china_stock_extension_copy.sh /path/to/openclaw-data-china-stock` |
| `ensure_openclaw_china_stock_plugin.py` | 在 `openclaw.json` 中追加 **`openclaw-data-china-stock`** 的 `plugins.allow` 与 `plugins.entries`（`enabled: true`） | `python3 scripts/ensure_openclaw_china_stock_plugin.py --ensure-allow --ensure-entry` |
| **`setup_openclaw_option_trading_assistant.sh`** | **推荐**：写入 `~/.openclaw/openclaw.json` 的 `plugins.load.paths`（extensions + 本仓库绝对路径），可选补全 `allow`/`entries`，并默认移除与仓库重复的 `extensions/option-trading-assistant` 符号链接，避免重复加载与 `plugin not found` | `./scripts/setup_openclaw_option_trading_assistant.sh` |
| `ensure_openclaw_plugin_load_paths.py` | 上述逻辑的 JSON 合并实现；可单独 `--dry-run` / 指定 `--config` | `python3 scripts/ensure_openclaw_plugin_load_paths.py --help` |
| `link_openclaw_extension_option_trading_assistant.sh` | **默认**已改为调用 `setup_openclaw_option_trading_assistant.sh`。仅符号链接旧流程：`OTA_LEGACY_EXTENSION_SYMLINK=1 ./scripts/link_openclaw_extension_option_trading_assistant.sh`（仍会同步 `load.paths`；可能与 symlink 重复扫描） | `./scripts/link_openclaw_extension_option_trading_assistant.sh` |
| `sync_openclaw_model_routes.py` | 同步/校验 OpenClaw 模型路由相关 JSON 配置（与主备模型切换配合） | `python3 scripts/sync_openclaw_model_routes.py` |

---

## OpenClaw / Cron 运维

| 脚本 | 用途 | 示例 |
|------|------|------|
| `cleanup_unused_openclaw_agents.py` | 根据 `openclaw.json` 中已注册 agent，清理未引用的 agent 定义目录（**先备份**） | `python3 scripts/cleanup_unused_openclaw_agents.py` |
| `check_cron_token_usage.py` | 汇总 `~/.openclaw/cron/runs/*.jsonl` 中近期 `finished` 的 token 用量 | `python3 scripts/check_cron_token_usage.py --days 7 --top 20` |
| `test_cron_tools.sh` | 从 `jobs.json` 抽取 `tool_*` 并对 `tool_runner.py` 冒烟（默认跳过 `tool_send_*`） | `./scripts/test_cron_tools.sh --help` |
| `dingtalk_before_open_smoke.sh` | 盘前晨报钉钉冒烟：`tool_send_analysis_report` + JSON 示例（`test` / `prod`） | `bash scripts/dingtalk_before_open_smoke.sh test` |
| `dingtalk_signal_inspection_smoke.sh` | 信号+风控巡检钉钉冒烟（走 `tool_send_signal_risk_inspection` 结构化渲染链路） | `bash scripts/dingtalk_signal_inspection_smoke.sh test` |
| `triage_cron_signal_inspection.py` | 解析 Cron 运行日志，辅助巡检任务分流（配合 `docs/ops/cron_signal_inspection_triage.md`） | `python3 scripts/triage_cron_signal_inspection.py --help` |
| `check_third_party_skills.sh` | 检查推荐/可选 OpenClaw 第三方技能是否已安装 | `./scripts/check_third_party_skills.sh` |
| `sync_repo_skills_to_openclaw.sh` | 将仓库 **`skills/`** 下自研 Skill（子目录含 `SKILL.md`）**rsync** 到 `~/.openclaw/skills/`（及可选 shared skills）；不删除目标目录中其他第三方包 | `./scripts/sync_repo_skills_to_openclaw.sh` |
| `smoke_trend_analysis.py` | 趋势三工具冒烟（盘后/盘前/开盘）；可选 `--date`；见 `plugins/analysis/README.md` | `python scripts/smoke_trend_analysis.py` |

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

## 本地单元测试（推荐）

系统自带的 `python3` / `pytest` 往往**没有**安装 `requirements.txt` 中的 `pandas` 等依赖，直接运行会报 `ModuleNotFoundError`。请使用项目 **`.venv`**：

1. 创建并安装依赖：`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt`
2. 运行测试：优先用仓库内脚本（固定使用 `.venv/bin/python -m pytest`）：

```bash
./scripts/run_tests.sh tests/test_daily_volatility_range_tool.py -m "not integration"
```

或已 `source .venv/bin/activate` 后执行：`python -m pytest ...`（勿用系统全局 `pytest` 调错解释器）。

---

## 与 `tests/` 的区别

- **`scripts/`**：运维、发布、预警、配置生成；可带环境变量与机器路径。
- **`tests/`**：见 `tests/README.md`（`pytest` 冒烟 + `tests/integration/` 长耗时集成脚本）。

## 示例参数（JSON）

`scripts/examples/` 下提供钉钉等工具的 **JSON 参数模板**（含 `before_open_dingtalk_args.*.json`、`signal_inspection_dingtalk_smoke.*.json`）。其中巡检冒烟示例已改为 `report` 结构化对象，供 `python3 tool_runner.py tool_xxx @scripts/examples/....json` 调用，避免 shell 多行 JSON 损坏。

更完整的项目结构说明见：`docs/PROJECT_LAYOUT.md`。
