# Internal Chart Alert Runbook（值班速查）

适用对象：值班同学 / 运维 / oncall  
目标：5-10 分钟内完成“是否正常、哪里异常、如何止损”。

---

## 1. 快速健康检查（1 分钟）

按顺序看 5 件事：

1) 开关是否开启  
- 合并后配置（域文件：`config/domains/analytics.yaml`）:
  - `internal_chart.enabled: true`
  - `internal_chart.mode: observe`（建议值）

2) cron 任务是否存在且启用  
- `~/.openclaw/cron/jobs.json`
  - job id: `internal-alert-scan`
  - `enabled: true`
  - cron: `3-58/5 9-15 * * 1-5`

3) 最近运行状态  
- `jobs.json` 里该 job 的 `state`：
  - `lastRunStatus`
  - `consecutiveErrors`
  - `nextRunAtMs`

4) 是否有事件产物  
- `data/alerts/internal_alert_events.jsonl` 是否存在且有新增行

5) 图表研究台页面健康（两条线择一或都验）  
- **Streamlit（默认 8511）**：`http://localhost:8511/` 可打开；左侧导航含 `Chart Console` / `Backtest & Quality` / `Rules Config` / `Alert Replay`；`Chart Console` 可见数据源状态灯（Data Source + 颜色圆点）。  
- **Chart Console Pro（8611，二期）**：需单独启动 `CHART_CONSOLE_PRO_PORT=8611 python apps/chart_console/api/server.py`；访问 `http://localhost:8611/`；快速探活：`curl -I http://127.0.0.1:8611/` 与 `curl http://127.0.0.1:8611/api/health`。

---

## 2. 常用命令（可直接复制）

```bash
# 0) 启动研究台（默认 8511）
cd /home/xie/etf-options-ai-assistant
./scripts/run_chart_console.sh
```

```bash
# 1) 看任务状态（jobs.json）
python3 - <<'PY'
import json
p='/home/xie/.openclaw/cron/jobs.json'
d=json.load(open(p,encoding='utf-8'))
j=[x for x in d.get('jobs',[]) if str(x.get('id'))=='internal-alert-scan'][0]
print(j['enabled'], j['schedule']['expr'], j['state'])
PY
```

```bash
# 2) 手动触发一次扫描
python3 -c "import sys; sys.path.insert(0,'/home/xie/etf-options-ai-assistant'); from src.alerts.engine import tool_internal_alert_scan; print(tool_internal_alert_scan('510300,510050,510500'))"
```

```bash
# 3) 看最近 20 条事件
python3 - <<'PY'
from pathlib import Path
p=Path('/home/xie/etf-options-ai-assistant/data/alerts/internal_alert_events.jsonl')
if not p.exists():
  print('NO_FILE')
else:
  lines=p.read_text(encoding='utf-8').splitlines()
  for x in lines[-20:]:
    print(x)
PY
```

---

## 3. 故障分级与处置

### P1：连续失败（影响主流程判断）

判定：
- `consecutiveErrors >= 3` 或 `lastRunStatus=error` 持续 15 分钟+

处理：
1. 立即把 `internal_chart.enabled` 改为 `false`（止损）
2. 保持 `providers.internal_chart_alert: false`
3. 排查后再恢复

### P2：任务正常但无事件

判定：
- `lastRunStatus=ok`，但 `events=0` 持续较长

处理：
1. 检查规则阈值是否过严（例如 RSI 30/70）
2. 临时放宽规则做验证（先 observe）
3. 验证后恢复策略阈值

### P2.5：研究台页面异常（白屏/功能缺失）

判定：
- 页面打不开，或缺少关键页面入口/状态灯/回测结果

处理：
1. **Streamlit 线**：重启 `./scripts/run_chart_console.sh`；检查 `streamlit`、`plotly`。
2. **Pro 线（8611）**：确认进程在跑、`curl -I` 非 501、浏览器无顶部红条；API JSON 无 `NaN`；详见 `skills/ota-chart-console-pro/SKILL.md`。
3. 规则侧：用 `config/alerts.yaml` 回退最近变更后再验证（仅影响告警配置与扫描，不修复前端静态资源问题）。

### P3：噪音过高（重复告警）

判定：
- `dedup_skipped` / `cooldown_skipped` 激增

处理：
1. 提高 `cooldown_sec`
2. 下调低优先级规则数量
3. 保持 `observe`，不打开融合

---

## 4. 变更守则（必须）

- 未经过至少 1 周 observe 数据，不得开启：
  - `config/strategy_fusion.yaml -> providers.internal_chart_alert: true`
- 任何规则变更必须记录：
  - 变更人
  - 生效时间
  - 影响标的
  - 回滚方法

---

## 5. 一键回滚清单

如需快速回退到“仅观测/关闭”：

1. 合并后配置（域文件：`config/domains/analytics.yaml`）:
   - `internal_chart.enabled: false`
2. `config/strategy_fusion.yaml`:
   - `providers.internal_chart_alert: false`
3. 保留 `jobs.json` 任务但可临时 `enabled: false`
4. 图表研究台异常时，回退到最小可用能力：
   - 仅使用 `Chart Console + Rules Config`
   - 暂停 `Backtest & Quality` 与 `Alert Replay` 的值班依赖

---

## 6. 交接信息模板

```text
[Internal Chart Alert 值班交接]
时间窗口: YYYY-MM-DD HH:mm ~ HH:mm
任务状态: ok/error, consecutiveErrors=?
事件文件: 有/无，新增约 ? 条
主要问题: ...
已采取措施: ...
是否已止损(关闭enabled): 是/否
建议下一步: ...
```

---

## 7. 值班 10 分钟验收脚本（建议）

1. 打开 `Chart Console`，选择 `510300`，切换 `30m` 周期  
2. 确认主图与副图可见（K线 + MACD + RSI），状态灯显示正常  
3. 新增一个绘图对象并点击保存工作区  
4. 打开 `Backtest & Quality`，执行一次 MA 回测并看到绩效指标  
5. 打开 `Alert Replay`，确认过滤器可用（若无数据，可跳过时间线）

---

## 8. 二期新增值班核查点

1. 图层开关可用：`Vol/MACD/RSI/MA` 开启/关闭后图形立即变化  
2. 多图联动可用：主图拖动缩放后，第二价格图同步  
3. 回测成本参数可用：调整 `fee_bps/slippage_bps` 后回测指标变化  
4. 工作区模板可用：保存工作区后可在模板接口读取  
5. API 冒烟脚本通过：

```bash
cd /home/xie/etf-options-ai-assistant
source .venv/bin/activate
python scripts/chart_console_phase2_smoke.py
```

建议值班 Agent 勾选 Skill：

- `ota_chart_console_pro`（仓库：`skills/ota-chart-console-pro/SKILL.md`；建议挂载 `ops_agent` / `code_maintenance_agent`）

---

## 9. Gateway 看不到 `ota_chart_console_pro`？

仓库里的 Skill **不会**自动出现在 `http://localhost:18789/agents`，须先拷到本机 OpenClaw 技能目录并重启 Gateway：

```bash
cd /home/xie/etf-options-ai-assistant
bash scripts/sync_repo_skills_to_openclaw.sh
```

确认存在 `~/.openclaw/skills/ota-chart-console-pro/SKILL.md` 后，**重启 Gateway**，再在 `/skills` 或 Agent 页勾选 `ota_chart_console_pro` 并 **Save**。合并片段可参考 `config/snippets/openclaw_agents_ota_skills.json` 与 `docs/openclaw/OpenClaw-Agent-ota-skills.md`。

