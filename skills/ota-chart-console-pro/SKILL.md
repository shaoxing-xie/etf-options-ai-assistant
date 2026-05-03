---
name: ota_chart_console_pro
description: TradingView 对标二期图表研究台运维与验收规程：启动、健康检查、UI核查、常见报错定位（HEAD 501 / NaN / slice）、回退与冒烟脚本。
---

# OTA：Chart Console Pro（二期）运行规程

## 何时使用

- 用户要求检查或验收 `http://127.0.0.1:8611/` 图表研究台是否可用。
- 出现前端加载异常（白屏、`unknown` 状态灯、顶部红条报错）。
- 需要值班同学快速判断“服务问题 / 数据问题 / 前端脚本问题”。

## 标准启动

```bash
cd <workspace-root>
source .venv/bin/activate
CHART_CONSOLE_PRO_PORT=8611 python apps/chart_console/api/server.py
```

若端口占用：

```bash
lsof -i :8611
kill <PID>
```

## 快速健康检查（顺序固定）

1. `curl -I http://127.0.0.1:8611/` 期望 `200`
2. `curl http://127.0.0.1:8611/api/health` 期望 `{"success": true}`
3. `curl /api/ohlcv` / `curl /api/indicators` / `curl /api/backtest` 至少返回 `success=true`
4. （可选）L4 只读语义：`curl 'http://127.0.0.1:8611/api/semantic/l4_valuation_context?stock_code=600519'`、`curl 'http://127.0.0.1:8611/api/semantic/l4_pe_ttm_percentile?stock_code=600519&window_years=5'` — 首次请求可能触发落盘到 `data/semantic/l4_*`（来源 `tool_l4_*`）；数值以工具 JSON 为准，勿手写复述。

## 二期 UI 验收要点

- 主图 + 第二价格图 + MACD + RSI 都可见。
- 图层开关（`Vol/MACD/RSI/MA`）切换后图形即时变化。
- 回测参数 `fee_bps/slippage_bps` 修改后结果有变化。
- 工作区可保存/加载；模板接口可读。

## 常见错误与处置

- `HEAD 501`：服务未实现 HEAD；应升级为当前 `server.py`（已支持 `do_HEAD`）。
- `Unexpected token ... NaN ... is not valid JSON`：后端序列化未清洗 NaN；应使用 `apps/chart_console/api/serializers.py` 的 NaN->null 修复版本。
- `(macd.dea || []).slice is not a function`：前端对指标返回结构假设过强；应使用 `app.js` 的 `toArrayValues()` 兼容层。
- 图表空白且无报错：优先检查 `lightweight-charts` 版本，固定为 `4.2.0`。

## 发布前脚本

```bash
python scripts/chart_console_phase2_smoke.py
python scripts/check_indicator_consistency.py
```

## 输出纪律

- 对用户反馈“可用/不可用”时，必须附上最少 1 条 API 证据（如 `api/health`）。
- 不要把“端口占用”误判为功能故障；先区分服务冲突与业务错误。
