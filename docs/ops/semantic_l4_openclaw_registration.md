# L4-semantic 工具与 Skill：OpenClaw 注册与验证（运维清单）

## 采集插件（openclaw-data-china-stock）

1. 开发仓合并后：`cd /home/xie/openclaw-data-china-stock && bash scripts/install_plugin_to_runtime.sh`
2. 配置 `OPENCLAW_DATA_CHINA_STOCK_PYTHON`（见 install 脚本输出），写入 `~/.openclaw/.env`（`KEY=VALUE`）。
3. `register_openclaw_dev.py` 会 symlink **插件仓** skills，并将 **`ota-equity-valuation-brief` / `ota-flow-sentiment-brief` / `ota-market-regime-brief`** 从助手仓链入 `~/.openclaw/workspaces/etf-options-ai-assistant/skills/`，且写入对应 agent 的 `skills` 列表。可选环境变量：
   - `OPENCLAW_DATA_CHINA_STOCK_ROOT`：插件根（默认本脚本所在仓库）
   - `OPENCLAW_ETF_OPTIONS_ASSISTANT_ROOT`：助手根（默认 `/home/xie/etf-options-ai-assistant`）
4. 示例：`OPENCLAW_DATA_CHINA_STOCK_ROOT="$HOME/.openclaw/extensions/openclaw-data-china-stock" OPENCLAW_ETF_OPTIONS_ASSISTANT_ROOT="/home/xie/etf-options-ai-assistant" python3 "$OPENCLAW_DATA_CHINA_STOCK_ROOT/scripts/register_openclaw_dev.py"`
5. 重启 OpenClaw Gateway；执行 `openclaw plugins doctor`。

**收尾验收签核**（命令清单与对账脚本）：[`semantic_l4_acceptance_signoff.md`](semantic_l4_acceptance_signoff.md)。

## 交易助手（etf-options-ai-assistant）

1. 修改 `config/tools_manifest.yaml` 后：`python3 scripts/generate_tools_json.py`
2. 新 Skill 位于 `skills/ota-*-brief/SKILL.md`；确保 Agent workspace 指向本仓库（例如 `~/.openclaw/workspaces/etf-options-ai-assistant`）。
3. 验证：`python3 tool_runner.py tool_semantic_equity_valuation_brief '{"symbol":"510300"}'` 输出含 `_meta.data_layer":"L4_semantic"`。

## Chart Console（可选）

- GET：`/api/semantic/equity_valuation_brief?stock_code=600519`
- GET：`/api/semantic/flow_sentiment_brief`
- GET：`/api/semantic/market_regime_brief`
- POST：`/api/semantic/portfolio_concentration_brief`，body JSON：`{"weights":{"600519":0.5,"510300":0.5}}`
