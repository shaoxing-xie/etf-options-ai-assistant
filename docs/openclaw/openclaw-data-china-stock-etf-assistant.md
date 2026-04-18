# openclaw-data-china-stock：安装到运行目录 + 交易助手（etf-options-ai-assistant）配置

本文说明如何把 **采集插件** `openclaw-data-china-stock` 从开发目录同步到 OpenClaw **运行目录**（`~/.openclaw/extensions/…`），并与 **交易助手** workspace（`etf-options-ai-assistant`）对齐：**四情绪工具** + **`market-sentinel` Skill**、插件注册与 Agent 关联。

## 1. 情绪四工具与 market-sentinel（能力边界）

| 类型 | 名称 | 说明 |
|------|------|------|
| 工具 | `tool_fetch_limit_up_stocks` | 涨停生态 |
| 工具 | `tool_fetch_a_share_fund_flow` | A 股资金流向 |
| 工具 | `tool_fetch_northbound_flow` | 北向资金 |
| 工具 | `tool_fetch_sector_data` | 板块结构 |
| Skill | `market-sentinel` | 上述四工具聚合的情绪综合报告（非买卖指令） |

插件侧契约与示例见上游仓库：`docs/sentiment/api_contract.md`、`docs/sentiment/examples.md`。

## 2. 同步插件到运行目录并注册

在 **插件克隆目录**执行（与上游 [`INSTALL.md`](../../../openclaw-data-china-stock/INSTALL.md) 第 7 节一致）：

```bash
cd /path/to/openclaw-data-china-stock
bash scripts/install_plugin_to_runtime.sh
OPENCLAW_DATA_CHINA_STOCK_ROOT="${HOME}/.openclaw/extensions/openclaw-data-china-stock" \
  python3 "${HOME}/.openclaw/extensions/openclaw-data-china-stock/scripts/register_openclaw_dev.py"
```

- 第一条命令：将仓库 `rsync` 到 `~/.openclaw/extensions/openclaw-data-china-stock`（可用 `OPENCLAW_DATA_CHINA_STOCK_RUNTIME` 改目标路径）。
- 第二条命令：更新 `~/.openclaw/openclaw.json` 中插件 `openclaw-data-china-stock` 的 `scriptPath` / `manifestPath`，并把插件路径加入 `plugins.load.paths`；为 workspace **`…/etf-options-ai-assistant`** 的各 Agent **幂等追加**插件自带 Skill 列表（含 `market-sentinel`）；在 `~/.openclaw/workspaces/etf-options-ai-assistant/skills/` 下为每个 Skill 建立指向插件内 `skills/<name>/` 的**符号链接**。

固定 Python 解释器（避免 Gateway 与 CLI 口径不一致）：

```bash
export OPENCLAW_DATA_CHINA_STOCK_PYTHON="/path/to/openclaw-data-china-stock/.venv/bin/python"
# 若仅使用运行目录副本，可改为：
# export OPENCLAW_DATA_CHINA_STOCK_PYTHON="${HOME}/.openclaw/extensions/openclaw-data-china-stock/.venv/bin/python"
```

然后 **重启 Gateway**（见 [`docs/publish/service-ops.md`](../publish/service-ops.md)）。

## 3. 交易助手侧：工具白名单（数据采集 Agent）

Gateway 实际可调用的工具以插件 manifest 为准；本仓库 **数据采集 Agent** 白名单须显式包含四情绪工具（含北向），见：

- [`agents/data_collector_agent.yaml`](../../agents/data_collector_agent.yaml)

已包含：`tool_fetch_limit_up_stocks`、`tool_fetch_sector_data`、`tool_fetch_a_share_fund_flow`、**`tool_fetch_northbound_flow`**。

若你维护了其它 Agent 的 tool 白名单，请同步增加上述四个 id。

## 4. Agent 与 `market-sentinel` Skill

OpenClaw 主配置 `~/.openclaw/openclaw.json` 中，`workspace` 以 `etf-options-ai-assistant` 结尾的 Agent，其 `skills` 数组应由 `register_openclaw_dev.py` 自动追加 `china-macro-analyst`、`technical-analyst`、`market-scanner`、**`market-sentinel`**、`fund-flow-analyst` 等。

若某 Agent 仍缺少 `market-sentinel`，可手动在对应条目的 `skills` 中加入字符串 **`market-sentinel`** 后重启 Gateway。

参考片段（与本机 OTA 技能并列，以你环境为准）：

- `config/snippets/openclaw_agents_ota_skills.json`（仅作维护参考；**以 `openclaw.json` 为准**。）

## 5. 验收

```bash
openclaw doctor
# 或
openclaw plugins list | grep -i china-stock
```

在会话中验证：能触发 `market-sentinel` 相关叙事，且四工具可被 `tool_runner` / Gateway 调用（见插件仓库 `tests/` 与 `docs/sentiment/examples.md` 第 5 节典型问法）。

## 6. 仍用开发目录而不复制到 extensions

若 `openclaw.json` 中插件 `scriptPath` / `manifestPath` 已指向 **开发克隆**（例如 `/home/xie/openclaw-data-china-stock`），只需在开发目录执行：

```bash
python3 scripts/register_openclaw_dev.py
```

无需 `install_plugin_to_runtime.sh`；运行时解释器仍建议设置 `OPENCLAW_DATA_CHINA_STOCK_PYTHON`。
