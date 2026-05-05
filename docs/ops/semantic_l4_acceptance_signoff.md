# L4-semantic 全面收尾验收签核

本文档记录**可自动化**与**须人工**的验收项；自动化命令应在助手仓库根目录执行，Python 使用 `/home/xie/etf-options-ai-assistant/.venv/bin/python`。

## 执行记录（自动化，2026-05-05）

- 助手：`pytest tests/test_semantic_context_tools.py tests/test_smoke_tool_runner.py tests/test_l4_report_attachment.py` — **21 passed**（约 50s）。
- 插件：`pytest tests/test_l4_data_tools_contract.py tests/test_entity_tools_contract.py` — **10 passed**。
- `~/.openclaw/.env`：`OPENCLAW_DATA_CHINA_STOCK_PYTHON` — **已配置**（仅检查键存在）。
- `python3 /home/xie/openclaw-data-china-stock/scripts/register_openclaw_dev.py` — **成功**；`openclaw.json` 中 etf workspace agent 的 `skills` 已包含三个 `ota-*-brief`；工作区 skills 若原为**实体目录**则脚本**不会覆盖**（与 symlink 并存策略一致），以助手仓 git 为准时请自行改为 symlink 或同步目录内容。
- `scripts/semantic_l4_acceptance_e2e.py 600519` — **exit 0**（本环境 PE 分位双端均为 `null`，走「双缺失跳过数值对账」分支）。
- `tool_runner.py tool_semantic_equity_valuation_brief` — JSON 含 `_meta.data_layer=L4_semantic`。
- `openclaw plugins doctor` — **No plugin issues**；若出现 `duplicate plugin id` 配置警告，与团队既有双入口注册有关，非本方案引入。
- `bash scripts/install_plugin_to_runtime.sh`（插件仓）— **已成功 rsync** 至 `~/.openclaw/extensions/openclaw-data-china-stock`；并以运行时根执行 `register_openclaw_dev.py`（`OPENCLAW_DATA_CHINA_STOCK_ROOT` 指向扩展目录）— **成功**。

## 1. 助手仓测试（必跑）

```bash
cd /home/xie/etf-options-ai-assistant
.venv/bin/python -m pytest tests/test_semantic_context_tools.py tests/test_smoke_tool_runner.py tests/test_l4_report_attachment.py -q
```

## 2. 插件仓约定子集（阶段一回归）

```bash
cd /home/xie/openclaw-data-china-stock
.venv/bin/python -m pytest tests/test_l4_data_tools_contract.py tests/test_entity_tools_contract.py -q
```

## 3. 语义工具 CLI 冒烟

```bash
cd /home/xie/etf-options-ai-assistant
.venv/bin/python tool_runner.py tool_semantic_equity_valuation_brief '{"symbol":"510300"}' | head -c 2000
```

确认 JSON 中含 `"_meta"` 且 `"data_layer":"L4_semantic"`。

## 4. 阶段三估值数值对账（路径 A vs B）

```bash
cd /home/xie/etf-options-ai-assistant
set -a; source /home/xie/.openclaw/.env || true; set +a
.venv/bin/python scripts/semantic_l4_acceptance_e2e.py 600519
```

期望：`ok: true` 且 `delta` 极小（同一 `tool_l4_pe_ttm_percentile` 链）。

## 5. OpenClaw 注册与 Agent 技能绑定

安装插件并注册后，须将助手侧三个 brief Skill **写入 agent `skills` 列表**并（可选）在工作区 skills 目录建立指向助手仓的 symlink：

```bash
OPENCLAW_DATA_CHINA_STOCK_ROOT="${OPENCLAW_DATA_CHINA_STOCK_ROOT:-$HOME/.openclaw/extensions/openclaw-data-china-stock}" \
  OPENCLAW_ETF_OPTIONS_ASSISTANT_ROOT="/home/xie/etf-options-ai-assistant" \
  python3 "$OPENCLAW_DATA_CHINA_STOCK_ROOT/scripts/register_openclaw_dev.py"
```

说明：`register_openclaw_dev.py` 已扩展为同时处理 `ASSISTANT_BRIEF_SKILL_NAMES`；若你仍从**开发仓**运行脚本，请改为：

```bash
python3 /home/xie/openclaw-data-china-stock/scripts/register_openclaw_dev.py
```

（开发仓脚本与运行时同步后，以 `install_plugin_to_runtime.sh` 为准。）

**人工**：检查 `~/.openclaw/openclaw.json` 中 `workspace` 以 `etf-options-ai-assistant` 结尾的 agent，其 `skills` 是否包含 `ota-equity-valuation-brief`、`ota-flow-sentiment-brief`、`ota-market-regime-brief`；新开 Agent 会话后核对 `skillsSnapshot`。

## 6. 环境变量（仅检查键名，勿打印密钥）

```bash
grep -E '^OPENCLAW_DATA_CHINA_STOCK_PYTHON=' /home/xie/.openclaw/.env >/dev/null && echo "OPENCLAW_DATA_CHINA_STOCK_PYTHON: present" || echo "OPENCLAW_DATA_CHINA_STOCK_PYTHON: absent"
```

## 7. 插件健康

```bash
openclaw plugins doctor
```

## 8. Chart Console（服务已启动时）

见 [`semantic_l4_openclaw_registration.md`](semantic_l4_openclaw_registration.md) 中 curl 路径；与 `tool_runner` 字段对齐为人工抽检。

## 9. Agent NL 抽检

清单：[`../semantic_l4_nl_smoke_checklist.md`](../semantic_l4_nl_smoke_checklist.md)（≥10 条；执行记录由团队自行归档）。

## 附录：与方案附录的差异（设计留痕）

- **资金流**：助手 manifest 无 `tool_fetch_northbound_flow`，brief 仅编排 `tool_fetch_a_share_fund_flow`（与实现对账一致即可）。
- **市场 regime**：实现为 `tool_detect_market_regime` + `tool_fetch_index_data` + 可选 `tool_sector_heat_score`，与方案表格中部分示例 tool id 不完全同名，以 manifest 为准。
- **组合**：无 `tool_batch_resolve_symbol`，使用 `tool_l4_portfolio_valuation_context` 与逐标的 `tool_l4_pe_ttm_percentile`。
