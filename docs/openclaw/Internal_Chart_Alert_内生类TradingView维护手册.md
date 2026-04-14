# Internal Chart Alert（内生类 TradingView）维护手册

本文档用于维护 `etf-options-ai-assistant` 中已落地的“内生类 TradingView”能力，覆盖策略设计、功能边界、配置方法、运行流程、排障与运维建议。

---

## 1. 功能定位与策略边界

### 1.1 目标

- 在不依赖外部 TradingView 的情况下，提供：
  - 图表研究台（K 线 + 指标 + 数据源状态灯 + 多页导航）
  - 规则化告警（扫描、去重、冷却、审计）+ Web 规则配置（启停/阈值/优先级）
  - 与 `tool_strategy_engine` 的可控融合（可开关）
- 保持现有盘前/盘后/盘中主链路稳定，不新增高风险执行通道。

### 1.2 边界（硬约束）

- `internal_chart_alert` 在 `observe` 阶段只做：
  - 扫描、记录、通知、统计
- 不直接触发自动交易。
- 只有在观察数据稳定后，才允许把其纳入融合来源。

---

## 2. 架构与代码落点（二期 Pro）

### 2.1 核心模块

- **Streamlit 多页应用（Legacy / 8511 默认）**：`./scripts/run_chart_console.sh` → `apps/chart_console/app.py` 与 `pages/*`（多页导航：研究台、回测、规则、回放）。
- **Chart Console Pro（二期主入口，8611）**：独立 HTTP 服务 `apps/chart_console/api/server.py` + 静态前端 `apps/chart_console/frontend/`（Lightweight Charts；与 Streamlit 并行存在，验收与排障以本路径为准）。
  - 页面：`pages/backtest.py`、`pages/rules_config.py`、`pages/alert_replay.py` 仅在 Streamlit 壳内使用；Pro 侧等价能力由 `frontend/` + `/api/*` 提供或对齐。
- 数据与指标服务层：
  - `src/services/market_data_service.py`
  - `src/services/indicator_service.py`
  - `src/services/backtest_service.py`
  - `src/services/workspace_service.py`
- 告警引擎：
  - `src/alerts/rules.py`
  - `src/alerts/engine.py`
  - `plugins/analysis/internal_alert_scan.py`（工具包装）
- 融合接入：
  - `plugins/strategy_engine/rule_adapters.py`
  - `plugins/strategy_engine/tool_strategy_engine.py`

### 2.2 配置与工作流

- 主开关：
  - 合并后配置 -> `internal_chart`（域文件：`config/domains/analytics.yaml`）
- 告警配置：
  - `config/alerts.yaml`
- 融合配置：
  - `config/strategy_fusion.yaml`
- 工作流：
  - `workflows/internal_alert_scan.yaml`
  - `workflows/strategy_fusion_routine.yaml`（`sources` 可选参数说明）

---

## 3. 告警策略设计（当前版本）

### 3.1 规则模型

规则结构见：

- `docs/openclaw/internal_alert_contract.md`

当前实现支持的关键字段：

- `rule_id`
- `symbol`
- `timeframe`
- `group`（`technical` / `volatility` / `regime`）
- `priority`（`high` / `medium` / `low`）
- `condition`（`metric/operator/value`）
- `cooldown_sec`
- `ttl_sec`

### 3.2 当前支持的 metric

在 `src/alerts/engine.py` 中当前支持：

- `rsi`
- `current_price`（别名：`close` / `price`）

如需新增 metric（如 `macd`、`bollinger.percent_b`），请扩展 `_extract_metric(...)`。

### 3.3 去重与冷却

- 去重键：
  - `source|symbol|timeframe|rule_id|bar_ts`
- 去重命中：`status=dedup_skipped`
- 冷却命中：`status=cooldown_skipped`

---

## 4. 运行模式与上线策略

### 4.1 模式

合并后配置（域文件：`config/domains/analytics.yaml`）:

```yaml
internal_chart:
  enabled: true
  mode: "observe"  # observe | semi_auto | auto
```

推荐策略：

1. 先 `observe` 跑 1 周
2. 评估噪音比、触发质量、稳定性
3. 再决定是否开启融合来源

### 4.2 融合接入开关

`config/strategy_fusion.yaml`:

```yaml
providers:
  internal_chart_alert: false
```

- `false`：仅记录与观察，不进入融合
- `true`：纳入 `tool_strategy_engine` 来源

---

## 5. 定时任务与调度

系统 cron 任务（OpenClaw）已新增：

- job id: `internal-alert-scan`
- 调度：`3-58/5 9-15 * * 1-5`
- agent：`etf_analysis_agent`
- 目标：每 5 分钟扫描规则并写入审计事件

任务配置文件：

- `~/.openclaw/cron/jobs.json`

---

## 6. 产物与观测

### 6.1 审计事件

- 路径：
  - `data/alerts/internal_alert_events.jsonl`
- 主要字段：
  - `event_id`
  - `rule_id`
  - `symbol`
  - `status`
  - `dedup_key`
  - `trigger_ts`

### 6.2 融合贡献度

`tool_strategy_engine` 返回新增：

- `data.source_contribution`

用于观察各来源（如 `internal_chart_alert`）对融合结论的贡献占比。

### 6.3 周报模板

- `docs/openclaw/internal_alert_weekly_review.md`

---

## 7. 使用说明（运维最小流程）

### 7.1 启动前检查

1. 合并后配置中 `internal_chart.enabled=true`（域文件：`config/domains/analytics.yaml`）
2. `config/alerts.yaml` 已配置真实 `rules`
3. `jobs.json` 存在 `internal-alert-scan` 且 `enabled=true`

### 7.2 图表研究台（本地）

```bash
cd /home/xie/etf-options-ai-assistant
./scripts/run_chart_console.sh
```
### 7.2.0 独立前端（Lightweight Charts + API 聚合）

> 二期技术路线 B 的主入口（独立前端，不依赖 Streamlit 作为主交互容器）：

```bash
cd /home/xie/etf-options-ai-assistant
CHART_CONSOLE_PRO_PORT=8611 python3 apps/chart_console/api/server.py
```

- 浏览器访问：`http://localhost:8611/`
- API 根路径：`/api/*`
- 前端目录：`apps/chart_console/frontend/`
- API 目录：`apps/chart_console/api/`
- OpenClaw 侧验收 Skill 与 Gateway 同步步骤见 **§10.3**。

可选环境变量（覆盖默认端口/监听地址）：

```bash
STREAMLIT_PORT=8512 STREAMLIT_HOST=0.0.0.0 ./scripts/run_chart_console.sh
```

### 7.2.1 图表研究台页面说明（对标 TradingView 风格）

- `Chart Console`
  - 功能：K线主图、Volume/MACD/RSI 副图、BOLL 叠加、多周期选择（5m/15m/30m/1h/1d）
  - 交互：缩放/平移、统一 hover、绘图对象（line/hline/rect/text）添加与清空
  - 工作区：保存/加载/删除（落盘：`data/chart_console/workspaces.json`）
- `Backtest & Quality`
  - 功能：MA 交叉回测、绩效面板（收益/回撤/胜率/交易次数）、交易点标记
- `Rules Config`
  - 功能：可视化编辑告警规则并保存到 `config/alerts.yaml`
- `Alert Replay`
  - 功能：事件状态分布、按 `symbol/status/rule_id` 过滤、时间线回放

### 7.2.2 Web 规则配置（对标 TradingView 的告警面板）

- 入口：图表研究台左侧导航 `Rules Config`
- 页面文件：`apps/chart_console/pages/rules_config.py`
- 能力：
  - 表格化编辑 `rules`（`enabled/rule_id/symbol/timeframe/group/priority/metric/operator/value/cooldown_sec`）
  - `Save to config/alerts.yaml` 一键保存
  - 保存时自动生成备份：`config/alerts.yaml.bak.<timestamp>`
- 使用建议：
  - 先在 `observe` 模式调参，连续观察 3-5 个交易日
  - 避免同一 `symbol+metric+operator` 重复建多条冲突规则
  - 变更后可手动触发一次扫描验证（见 7.3）

### 7.3 手动触发一次扫描

```bash
python3 -c "import sys; sys.path.insert(0,'/home/xie/etf-options-ai-assistant'); from src.alerts.engine import tool_internal_alert_scan; print(tool_internal_alert_scan('510300,510050,510500'))"
```

---

## 8. 二期验收标准（Pro）

必须同时满足：

1. 图表研究主路径在 3 分钟内可完成：选标的 -> 切周期 -> 加指标 -> 画图 -> 保存工作区  
2. 回测页可返回可解释绩效指标，并在图上显示信号点  
3. 告警页可完成“规则配置 -> 扫描触发 -> 回放过滤”闭环  
4. 页面异常时能看到明确失败提示（数据源状态、空数据原因、回退提示）

---

## 9. 常见问题与排障

### Q1: 任务是 idle，不执行？

- 检查 `jobs.json` 的 `nextRunAtMs` 是否已到
- 检查当前是否交易日/交易时段
- 检查 cron 表达式和时区 `Asia/Shanghai`

### Q2: 一直 `events=0`？

- 规则阈值可能过严（例如 RSI 很少到 30/70）
- 先临时放宽阈值做验证，再调回生产阈值

### Q3: 告警很多、噪音高？

- 提高 `cooldown_sec`
- 减少低优先级规则
- 增加 `priority/group` 分层路由

### Q4: 融合结果异常偏向 internal_chart_alert？

- 保持 `providers.internal_chart_alert=false` 继续观察
- 或降低 `strategy_weights.internal_chart_alert`

### Q5: Chart Console Pro（8611）白屏、`curl -I` 返回 501、或控制台报 JSON / `slice`？

- 按固定顺序自检：`curl -I http://127.0.0.1:8611/` → `curl http://127.0.0.1:8611/api/health` → 浏览器是否出现顶部错误条（`bootError`）。
- API 若返回非法 JSON（含 `NaN`/`Infinity`），检查 `apps/chart_console/api/serializers.py` 是否将异常浮点清洗为 `null`。
- 前端 MACD 等副图报 `(…).slice is not a function`：检查 `frontend/app.js` 是否对序列做数组归一（如 `toArrayValues`）；并确认 CDN 使用锁定的 `lightweight-charts` 版本（见 `frontend/index.html`）。
- 发布前：`python scripts/chart_console_phase2_smoke.py`；细则与命令全文见 `skills/ota-chart-console-pro/SKILL.md`。

---

## 10. 维护建议（后续迭代）

- 优先迭代项：
  - 扩展 `metric` 支持（MACD / Bollinger / HV）
  - 把事件存储从 jsonl 升级到 sqlite（便于统计查询）
  - 增加告警规则版本与灰度发布机制
- 变更纪律：
  - 每次改规则都记录版本与生效时间
  - 每周复盘一次噪音比、触发质量、熔断次数

### 10.1 二期（4周）已落地能力

- 前端模块化：
  - `apps/chart_console/frontend/app.js`
  - `apps/chart_console/frontend/api.js`
  - `apps/chart_console/frontend/charts.js`
- 多图联动：
  - 主图与第二价格图联动时间轴（visible range 同步）
  - 跨图光标同步（crosshair）
- 图层管理：
  - `Vol/MACD/RSI/MA` 显隐开关
- 回测增强：
  - 新增手续费与滑点参数（`fee_bps/slippage_bps`）
  - 新增指标：`total_cost/sharpe`
- 工作区升级：
  - `history` 快照（最近 10 次）
  - 指标模板保存（`workspace_templates`）
- API 分层化：
  - `apps/chart_console/api/routes.py`
  - `apps/chart_console/api/services.py`
  - `apps/chart_console/api/serializers.py`
  - 入口仍为 `apps/chart_console/api/server.py`

### 10.2 二期冒烟验证（发布前必跑）

```bash
cd /home/xie/etf-options-ai-assistant
source .venv/bin/activate
python scripts/chart_console_phase2_smoke.py
python scripts/check_indicator_consistency.py
```

### 10.3 OpenClaw Skill：`ota_chart_console_pro`（值班/运维）

- **仓库路径**：`skills/ota-chart-console-pro/`，`SKILL.md`  frontmatter 中 **`name: ota_chart_console_pro`**（下划线；Gateway 列表按此名显示，与目录名 `ota-chart-console-pro` 不同）。
- **建议挂载 Agent**：`ops_agent`、`code_maintenance_agent`（片段见 `config/snippets/openclaw_agents_ota_skills.json`；真源为 `~/.openclaw/openclaw.json` → `agents.defaults.list[].skills`）。
- **同步到本机**（新建或更新仓库内 Skill 后**必须**执行，否则 `http://localhost:18789/skills` 与 `/agents` **不会出现**该技能）：

```bash
cd /home/xie/etf-options-ai-assistant
bash scripts/sync_repo_skills_to_openclaw.sh
```

  目标目录：`~/.openclaw/skills/<技能文件夹>/`（可选同步到 `~/.openclaw/workspaces/shared/skills`，若存在）。

- **Gateway**：执行同步后 **重启 OpenClaw Gateway**，再在浏览器 Agent 页勾选 `ota_chart_console_pro` 并 **Save**。
- **适用场景**：`127.0.0.1:8611` 验收、白屏/端口、HEAD 501、`NaN` JSON、副图 `.slice`、冒烟脚本与回退说明（全文以 `SKILL.md` 为准）。

---

## 11. 相关文档索引

- `docs/openclaw/internal_alert_contract.md`
- `docs/openclaw/internal_alert_weekly_review.md`
- `docs/openclaw/Internal_Chart_Alert_Runbook_值班速查.md`
- `docs/openclaw/LLM_模型分档与路由实施方案.md`
- `docs/openclaw/OpenClaw-Agent-ota-skills.md`
- `docs/openclaw/OpenClaw-Gateway-Agent与Skills勾选指南.md`
