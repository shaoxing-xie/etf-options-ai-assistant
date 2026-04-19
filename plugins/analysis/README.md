# 分析插件

本目录包含宽基ETF及其期权交易助手的分析相关插件工具，融合了 Coze 插件的核心逻辑。

## 插件列表

### 1. technical_indicators.py - 技术指标计算

**功能说明**：
- 计算技术指标：默认 **MA、MACD、RSI、布林带**；在 `engine=standard` 下可选 **KDJ、CCI、ADX、ATR**（依赖 **`pandas_ta`**，向量化）。
- **`engine=standard`（默认）**：RSI 为 **Wilder**；MACD 柱为 **DIF−DEA**（与 TA-Lib/pandas_ta 一致，**非** 旧版 `2×(DIF−DEA)`）。MA 周期由合并后配置 → `technical_indicators.ma_periods`（域文件：`config/domains/analytics.yaml`）决定，键名为 **`ma{n}`**（如 `ma5`、`ma10`）；仅两条均线时排列文案为「短均在上/下」等。
- **`engine=legacy`**：保留原 Coze **列表实现**（`_calculate_*`），与历史数值对齐；固定 MA5/10/20/60；**不支持** kdj/cci/adx/atr，且**不支持** `timeframe_minutes` / 自定义 `ma_periods`（若指定会自动改用 standard，或缺依赖时报错）。
- **分钟多周期**：`timeframe_minutes ≥ 2` 时先对 OHLCV **重采样**再算指标（如 5m 缓存 → 30m），需数据中带可解析**时间列**。
- **`indicators` 简写**：可写 `MA10`、`RSI14` 等，与 `ma_periods` / `rsi_length` 二选一或组合；规范键名为小写 `ma`、`macd`、`rsi` 等。
- 默认指标列表与全局周期在合并后配置 → `technical_indicators`（域文件：`config/domains/analytics.yaml`）；Skill 口径见 **`ota_technical_indicators_brief`**。

**使用方法**：
```python
from plugins.analysis.technical_indicators import tool_calculate_technical_indicators

# 日线默认四件套（未传 indicators 时用 config 中 default_indicators）
result = tool_calculate_technical_indicators(
    symbol="510300",
    data_type="etf_daily",
    lookback_days=120,
    engine="standard",
)

# 5m 源数据 → 30m，仅 MA10/20 + RSI14（如 etf_510300_intraday_monitor）
result = tool_calculate_technical_indicators(
    symbol="510300",
    data_type="etf_minute",
    period="5",
    lookback_days=7,
    timeframe_minutes=30,
    indicators=["ma", "rsi"],
    ma_periods=[10, 20],
    rsi_length=14,
)
```

**输入参数**：
- `symbol` (str): 标的代码，如 "510300"
- `data_type` (str): `index_daily` / `etf_daily` / `index_minute` / `etf_minute`
- `period` (str, optional): 分钟周期（与缓存一致，如 `"5"`）
- `lookback_days` (int): 回溯自然日；分钟线在内部会放大窗口，默认 120
- `indicators` (List[str], optional): 未传时用 `technical_indicators.default_indicators`
- `engine` (str, optional): `standard` / `legacy`；未传用配置
- `klines_data` (list, optional): 直接传 K 线时**优先于缓存**
- `timeframe_minutes` (int, optional): ≥2 时先重采样再计算（**需安装 pandas_ta**）
- `ma_periods` (List[int], optional): 单次覆盖均线周期（**需 standard + pandas_ta**）
- `rsi_length` (int, optional): 单次覆盖 RSI 周期

**输出格式**（成功时另含 **`message`**：IM 友好 Markdown，供 OpenClaw 直接展示）：
```python
{
    "success": True,
    "message": "✅ 技术指标计算完成 - 510300 ETF\n...",
    "data": {
        "symbol": "510300",
        "current_price": 4.85,
        "engine": "standard",
        "timestamp": "2026-01-15 14:30:00",
        # 可选：重采样 / 本次覆盖参数
        "timeframe_minutes": 30,
        "ma_periods_effective": [10, 20],
        "rsi_length_effective": 14,
        "data_range": "2026-01-05 10:00:00 至 2026-01-06 02:30:00 (34 条)",
        "notes": [],
        "indicators": {
            "ma": {
                "periods": [5, 10, 20, 60],
                "ma5": 4.82,
                "ma10": 4.80,
                "ma20": 4.78,
                "ma60": 4.75,
                "arrangement": "多头排列",
                "cross_signal": "金叉",
                "price_vs_ma20": 0.88,
                "price_vs_ref_period": 20
            },
            "macd": {"dif": 0.02, "dea": 0.01, "macd": 0.02, "signal": "金叉"},
            "rsi": {"rsi": 65.5, "period": 14, "signal": "偏强", "suggestion": "注意风险"},
            "bollinger": {
                "upper": 4.95,
                "middle": 4.78,
                "lower": 4.61,
                "bandwidth": 7.11,
                "percent_b": 0.65,
                "signal": "区间内",
                "suggestion": "正常波动"
            }
        },
        "signal": {
            "signals": ["均线金叉", "MACD金叉"],
            "summary": "均线金叉, MACD金叉"
        }
    },
    "source": "calculated"
}
```

说明：`data.indicators.ma` 中 **`ma{n}` 键与 `periods` 列表**与本次生效的 `ma_periods` 一致（例如仅 `[10, 20]` 时只有 `ma10`、`ma20`）。`timeframe_minutes` / `ma_periods_effective` / `rsi_length_effective` 仅在本次调用使用了对应参数时出现。

**技术实现要点**：
- 数据：`klines_data` 优先，否则 **`read_cache_data`**；列名中英兼容，按时间列升序；OHLCV 提取后计算。
- **standard**：`pandas_ta` 向量计算；结果字典与展示层 **`_format_indicators_message`**、**`_generate_signal`** 对齐。
- **legacy**：原 `_calculate_ma` / `_calculate_macd` / `_calculate_rsi` / `_calculate_bollinger`（列表循环）。
- **缓存**：`@cache_result` TTL **5 分钟**；参数（含 `engine`、`timeframe_minutes`、`ma_periods` 等）参与缓存键。
- **依赖**：`requirements.txt` 含 **`pandas-ta`**；**numpy** 需与 **numba** 兼容（见文件内注释）。未装 `pandas_ta` 且使用重采样/自定义 `ma_periods`/扩展指标时返回 **`success: false`** 并提示安装。

**使用场景**：
- 盘前 / 开盘 / 定时信号：`opening_analysis`、`signal_generation` 等（日线 + 可选 ATR）。
- 盘中：`intraday_analysis`、**`etf_510300_intraday_monitor`**（30m + MA10/20 + RSI14）。
- 工作流内：上一步 K 线可经 **`klines_data`** 传入，减少重复读缓存。

---

### 2. trend_analysis.py - 趋势分析

**功能说明**：
- 封装 `src.trend_analyzer`：`after_close` / `before_open` / `opening_market` 三场景；进程内**不**调用 `llm_enhancer`。自然语言解读由 Gateway 主模型 + Skill：**`ota_trend_analysis_brief`**（三工具契约、`report_meta` / overlay 边界）与 **`ota_openclaw_tool_narration`**（通用工具叙事）等配合。
- **盘后** `tool_analyze_after_close`：在 `analyze_daily_market_after_close` 结果上附加 **`daily_report_overlay`**（北向、全球指数现货、关键位、板块热度、可选 **ADX**，经 `calculate_technical_indicators(..., indicators=["adx"])`）。若 **`trend_analysis_plugin.enabled`** 为 `false`，**不**写 overlay，但仍附加 **`report_meta`**。
- **盘前** `tool_analyze_before_open`：隔夜 **富时 A50 / 纳斯达克中国金龙（HXC）仅在 `analyze_market_before_open` 内拉取**；盘后、开盘与其他工具**不**走此链路。未显式传入盘后 dict 时：**先**自当日起向前最多 **10 个自然日**尝试读落盘 **`after_close_dir` / `{YYYYMMDD}.json`**（覆盖周末后周一等），**再**决定是否现场跑盘后。`report_meta.key_metrics.after_close_basis`：**`passed`**（调用方已传入盘后结果）、**`disk`**（命中落盘）、**`computed`**（现场计算）、**`error`**（读盘或盘后链路失败时的路径）。
- **开盘** `tool_analyze_opening_market`：**取数**优先原系统 `fetch_index_opening_data`，失败则插件 **`fetch_index_opening`**；**分析**优先 **`analyze_opening_market`**；其异常或缺失原系统实现时，若 **`fallback.use_simple_opening`** 为 `true` 则 **`_simple_opening_analysis`**（等权与可选成交量加权情绪、`tool_sector_heat_score` 一行摘要、历史开盘量能对比等）；若为 `false` 则失败返回、不走简版。

**配置**（合并后配置）：
- **`trend_analysis_plugin`**：`enabled`、`overlay`（`northbound_*`、`global_index_codes`、`key_levels_index`、`sector_heat_enabled`、`adx_enabled`、`adx_index`、`adx_lookback_days` 等）、`fallback`（`use_simple_opening`、`simple_opening_include_volume_weighted`）。
- **`system.data_storage.trend_analysis`**：可选逻辑根 **`dir`**、**`after_close_dir`**、**`before_open_dir`**、**`opening_dir`**（开盘 JSON 与盘前分目录，避免同日覆盖）。

**落盘**（`src.data_storage.save_trend_analysis`，文件名多为 **`{YYYYMMDD}.json`**）：
- `after_close` → `after_close_dir`
- `before_open` → `before_open_dir`
- `opening_market` → **`opening_dir`**（默认 `data/trend_analysis/opening`）

**外层返回**（三工具结构一致；失败时 `success: false`，`data` 可能为 `None`）：
```python
{
    "success": True,
    "message": "after_close analysis completed",  # 或 before_open / opening_market
    "data": { ... },   # 各模式字段不同，均含 report_meta；若上游注入 llm_summary 则 llm_enhanced 为 True
    "llm_enhanced": False
}
```

**`data` 内稳定扩展**：
- **`report_meta`**（各模式均有）：`analysis_type`、`timestamp`、`market_sentiment_score`（约 -1～1）、`trend_strength_label`（`strong` / `neutral` / `weak`）、`key_metrics`、`overlay`（与 **`daily_report_overlay`** 内容镜像；无 overlay 时为 `{}`）。
- **`daily_report_overlay`**（仅 **after_close**，且 **`trend_analysis_plugin.enabled`** 为 `true`）：北向、全球现货、`key_levels_{指数}`、`sector_heat`、可选 **`trend_strength`**（ADX：`signal` 等由指标引擎给出，插件不另设硬编码阈值）。
- 盘后/盘前若指数日线滞后，可出现 **`data_stale_warning`**（见 `src.trend_analyzer`）；叙事应说明「基于最近可用交易日」而非断言插件故障。

核心趋势字段仍以 `src.trend_analyzer` 为准（如 `overall_trend`、`final_trend`、`opening_strategy` 等）。

**使用方法**：
```python
from plugins.analysis.trend_analysis import (
    tool_analyze_after_close,
    tool_analyze_before_open,
    tool_analyze_opening_market,
    trend_analysis,  # 程序化：analysis_type="after_close" | "before_open" | "opening_market"
)

result = tool_analyze_after_close()
result = tool_analyze_before_open()
result = tool_analyze_opening_market()
```

**联网冒烟**（仓库根；依赖行情与缓存；`--mode` 默认 `after_close`）：
```bash
python scripts/smoke_trend_analysis.py
python scripts/smoke_trend_analysis.py --mode before_open
python scripts/smoke_trend_analysis.py --mode all --full-json /tmp/trend_smoke.jsonl
```

**单元测试**：`pytest tests/test_trend_analysis_plugin.py`

**相关 Skill 与 Agent 勾选**：`skills/ota-trend-analysis-brief/SKILL.md`；Gateway **`skills`** 片段见 **`config/snippets/openclaw_agents_ota_skills.json`**（`etf_main`、`etf_analysis_agent`、`etf_business_core_agent`、`etf_notification_agent` 等）。

---

### 3. volatility_prediction.py - 波动区间预测

**功能说明**：
- 使用 GARCH 模型预测 ETF 和期权的波动区间
- 融合 Coze `volatility_forecast.py` 的 GARCH/ARIMA 模型
- 支持多标的物、多合约的波动区间预测

**使用方法**：
```python
from plugins.analysis.volatility_prediction import tool_predict_volatility

# 预测波动区间
result = tool_predict_volatility(
    underlying="510300",              # 标的物代码
    contract_codes=["10010891", "10010892"]  # 期权合约代码列表（可选）
)
```

**输入参数**：
- `underlying` (str): 标的物代码，如 "510300"（沪深300ETF）
- `contract_codes` (List[str], optional): 期权合约代码列表
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Volatility prediction completed and saved",
    "data": {
        "underlying": "510300",
        "timestamp": "2025-01-15 14:30:00",
        "date": "20250115",
        "underlyings": {
            "510300": {
                "etf_range": {
                    "lower": 4.75,
                    "upper": 4.95,
                    "current_price": 4.85,
                    "confidence": 0.85
                },
                "call_ranges": [
                    {
                        "contract_code": "10010891",
                        "strike_price": 4.9,
                        "lower": 0.05,
                        "upper": 0.15,
                        "current_price": 0.10
                    }
                ],
                "put_ranges": []
            }
        }
    }
}
```

**技术实现要点**：
- 使用 GARCH 模型预测波动率
- 结合历史波动率（HV）和隐含波动率（IV）
- 支持 IV-HV 对比分析
- 计算置信区间和覆盖率
- 通过 API 保存预测结果到原系统

**使用场景**：
- **9:28首次预测**：基于集合竞价数据预测当天波动区间
- **交易时间内定期更新**：每30分钟更新波动区间预测
- **风险控制**：为交易信号提供波动区间参考
- **期权定价**：为期权交易提供价格区间预测

---

### 4. 交易信号工具（期权 / ETF / A 股）

实现位于 `src/`，插件层 [signal_generation.py](signal_generation.py) 仅转发。监控标的与期权规则集中在合并后配置的 `signal_generation`（域文件：`config/domains/signals.yaml`；加载时归一化到 `option_contracts`、`signal_params`、`intraday_monitor_*`、`etf_trading.short_term` 等，旧代码路径不变）。

| 工具名 | 说明 |
|--------|------|
| `tool_generate_option_trading_signals` | **期权**：按 `option_contracts.underlyings` 的 `underlying` + **`index_symbol`** 拉指数分钟线；可选接波动区间、合约骨架、Greeks 缓存、开盘策略 JSON。 |
| `tool_generate_signals` | 与上一工具**等价**（兼容旧工作流）。 |
| `tool_generate_etf_trading_signals` | **ETF**：`signal_generation.etf` 的 `watchlist` / `default_symbol`，调用 `generate_etf_short_term_signal`。 |
| `tool_generate_stock_trading_signals` | **A 股**：`signal_generation.stock` + `signal_params.stock_short_term`（日线 MA20 + 30m RSI + 量比）；非投资建议。 |

**期权示例**：
```python
from plugins.analysis.signal_generation import tool_generate_option_trading_signals

result = tool_generate_option_trading_signals(underlying="510300")
# data 含：signals、signal_id、signal_type、signal_strength、asset_class="option"、meta.index_symbol
```

**配置要点**：
- `option_contracts.underlyings[]`：`index_symbol`（如 510300→000300，510500→000905）、`enabled`
- `signal_generation.option`：`default_underlying`、`max_contracts_per_side`
- `signal_generation.intraday.by_underlying`：写入后映射为 `signal_params.intraday_monitor_{标的}`
- `signal_generation.option.engine`：与根级 `signal_params` 深度合并（engine 覆盖同名键）

---

### 5. historical_volatility.py - 单窗口历史波动率

**功能**：`tool_calculate_historical_volatility` — 按 **单一** `lookback_days` 窗口计算日线收盘价收益率的年化已实现波动率（**%**）。口径与 `src/realized_vol_panel` / `calculate_historical_volatility` 一致：`pct_change` → 最近 N 期样本标准差 → `sqrt(252)*100`，上限 500%。

**数据源**：`fetch_index_daily_em`（自动识别 ETF → `fetch_etf_daily_em`）。**不适用于 A 股个股**；个股请用 `underlying_historical_snapshot` 并设 `asset_type=stock`。

```python
from plugins.analysis.historical_volatility import tool_calculate_historical_volatility

result = tool_calculate_historical_volatility(
    symbol="510300",
    lookback_days=60,
    start_date=None,  # 可选 YYYYMMDD
    end_date=None,
)
# data: symbol, lookback_days, volatility, annualized_volatility, start_date, end_date, timestamp
```

**参数**：`symbol`，`lookback_days`（默认 60），可选 `start_date` / `end_date`，`data_type` 占位。

---

### 5b. underlying_historical_snapshot.py - 标的历史复合面板

**功能**：`tool_underlying_historical_snapshot`（runner 别名 `tool_historical_snapshot`）— **多标的**、**多窗口** HV、可选 **波动率锥**（min/max/mean/percentile）、可选 **SSE ETF 期权** 近月 ATM IV 与 `iv_eq_30d_pct`。默认项见合并后配置 → `historical_snapshot`（域文件：`config/domains/analytics.yaml`）。

**资产类型**：`asset_type` = `auto` | `stock` | `etf` | `index`。`auto` 先走 `fetch_index_daily_em`，失败再试 `fetch_stock_daily_hist`。**个股务必** `asset_type=stock`。

```python
from plugins.analysis.underlying_historical_snapshot import tool_underlying_historical_snapshot

out = tool_underlying_historical_snapshot(
    symbols="510300,000300",
    windows=[5, 10, 20, 60, 252],  # 可选；默认读 config
    include_vol_cone=False,
    include_iv=False,
    max_symbols=20,
    asset_type="auto",
)
# data.results[]: symbol, success, hv_by_window, data_range, as_of, vol_cone?, iv?
```

**IV**：仅支持上交所 ETF 期权标的（如 510300、510050）；`iv_rank` v1 固定为 `null` 并附说明。`historical_snapshot.enabled=false` 时返回 `success: false` 与说明信息。

**OpenClaw 叙事与勾选**：自研 Skill **`ota_historical_volatility_snapshot`**（`skills/ota-historical-volatility-snapshot/SKILL.md`）；同步见 `scripts/sync_repo_skills_to_openclaw.sh`，勾选片段见 `config/snippets/openclaw_agents_ota_skills.json`。

---

### 6. intraday_range.py - 日内波动区间预测

**功能说明**：
- 指数 / ETF / A 股：优先走 `on_demand_predictor`；若需本模块补算，则**仅使用分钟K线**调用 `calculate_etf_volatility_range_multi_period`。
- **不使用日线数据做区间降级**；分钟数据缺失或上下界无效时返回 `success: false`，`data.error_code` 为 `INTRADAY_MINUTE_DATA_UNAVAILABLE` / `INTRADAY_MINUTE_CALC_INVALID` / `INTRADAY_SPOT_PRICE_UNAVAILABLE`，供工作流分支。
- 输出经 `intraday_monitor_510300.volatility` 的 `range_pct` 夹紧等收敛逻辑（见合并后配置，域文件：`config/domains/signals.yaml`）。

**使用方法**：
```python
from plugins.analysis.intraday_range import tool_predict_intraday_range

# 预测日内波动区间
result = tool_predict_intraday_range(
    symbol="510300",              # ETF代码，默认 "510300"
    current_price=4.85,           # 当前价格（可选）
    confidence_level=0.95          # 置信水平，默认 0.95
)
```

**输入参数**：
- `symbol` (str): 标的代码，如 "510300"（沪深300ETF）或 "000300"（沪深300指数）
- `current_price` (float, optional): 当前价格，如果未提供则使用最新收盘价
- `confidence_level` (float): 置信水平，默认 0.95（支持 0.90, 0.95, 0.99）
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully predicted intraday range",
    "data": {
        "symbol": "510300",
        "current_price": 4.85,
        "confidence_level": 0.95,
        "predicted_range": {
            "expected_high": 4.92,
            "expected_low": 4.78,
            "expected_range_pct": 2.89,
            "max_high": 4.98,
            "max_low": 4.72,
            "max_range_pct": 5.36
        },
        "key_levels": {
            "recent_high": 4.95,
            "recent_low": 4.70,
            "pivot": 4.83
        },
        "timestamp": "2025-01-15 14:30:00"
    }
}
```

**技术实现要点**：
- 通过 `read_cache_data` 从原系统读取历史日线数据
- 计算历史日内波动幅度（(最高价-最低价)/开盘价）
- 使用统计方法（均值+标准差）预测波动区间
- 根据置信水平计算不同概率的波动范围
- 识别近期关键支撑阻力位

**使用场景**：
- **开盘前预测**：预测当天可能的波动区间
- **交易计划**：制定当天的交易策略和止损止盈位
- **风险控制**：评估日内交易的风险水平
- **支撑阻力**：识别关键价格位置

---

### 6b. daily_volatility_range.py - 日频全日波动区间

**功能说明**：
- 与 **`volatility_prediction`**（侧重日内剩余时段）及 **`intraday_range`**（轻量分钟区间）区分：本工具以 **完整交易日** 为 horizon，基于日 K **多窗口 HV + ATR(14)** 融合；连续竞价时段可对区间做有界纠偏。
- 支持指数 / ETF / A 股（经 `resolve_volatility_underlying`）；不支持单期权合约。
- Runner：`tool_predict_daily_volatility_range`（参数别名 `underlying` ↔ `symbol`）。

**使用方法**：
```python
from plugins.analysis.daily_volatility_range import tool_predict_daily_volatility_range

result = tool_predict_daily_volatility_range(underlying="510300", asset_type=None)
# data: symbol, lower, upper, range_pct, confidence, windows_used, intraday_adjusted, message(Markdown) 等
```

---

### 7. risk_assessment.py - 风险评估

**功能说明**：
- 评估 **ETF / 指数 / A 股** 持仓的风险水平（`asset_type` 显式指定时 **缓存优先**，不足则拉日线；`auto` 直接走 `fetch_index_daily_em` / `fetch_stock_daily_hist` 路由，与 `tool_calculate_historical_volatility` 一致）
- 年化波动率使用 **`realized_vol_windows`**（与 `historical_volatility`、标的面板同口径，单位为 **%%**，输出字段 `volatility` 即为百分数，如 `18.5` 表示 18.5%）
- 止损默认：`entry * (1 - (volatility_pct/100) * stop_loss_multiplier)`，`stop_loss_multiplier` 等见合并后配置 → `risk_assessment`（域文件：`config/domains/risk_quality.yaml`）
- 计算仓位比例、风险比例、简化凯利建议、风险等级与中文建议

**使用方法**：
```python
from plugins.analysis.risk_assessment import tool_assess_risk

# ETF（可显式 etf 以走本地 parquet 优先）
result = tool_assess_risk(
    symbol="510300",
    asset_type="etf",
    lookback_trading_days=60,
    position_size=10000,
    entry_price=4.85,
    stop_loss=4.70,                # 可选
    account_value=100000,
)

# A 股个股（示例 600519，需网络/数据源可用）
result = tool_assess_risk(
    symbol="600519",
    asset_type="stock",
    entry_price=1800.0,
    position_size=100,
    account_value=1000000,
)
```

**输入参数**：
- `symbol` (str): 6 位代码，或 `sh600000` / `600000.SH` 形式
- `asset_type` (str, optional): `auto` | `stock` | `etf` | `index`；缺省读合并后配置的 `risk_assessment.default_asset_type`（域文件：`config/domains/risk_quality.yaml`）
- `lookback_trading_days` (int, optional): 波动率窗口（交易日）；缺省读 `risk_assessment.default_lookback_trading_days`（默认 60）
- `position_size` (float): 持仓数量
- `entry_price` (float): 入场价格
- `stop_loss` (float, optional): 止损价格；不传则按波动率与配置系数估算，若无波动率则约为入场价 × 0.97
- `account_value` (float): 账户总值
- `assess_risk` 仍保留 `api_base_url` / `api_key` 形参以兼容旧调用，当前实现不使用

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully assessed risk",
    "data": {
        "symbol": "510300",
        "asset_type": "etf",
        "price_data_source": "cache_then_network",
        "lookback_trading_days": 60,
        "volatility_model": "realized_vol_windows",
        "position_size": 10000,
        "entry_price": 4.85,
        "stop_loss": 4.70,
        "position_value": 48500.0,
        "position_ratio": 48.5,
        "risk_amount": 1500.0,
        "risk_ratio": 1.5,
        "volatility": 18.5,
        "risk_level": "low",
        "kelly_optimal_position": 12.5,
        "recommendations": [
            "仓位比例较高，建议降低仓位"
        ],
        "timestamp": "2026-04-05 14:30:00"
    }
}
```

**技术实现要点**：
- 显式 `etf` / `index` / `stock`：`read_cache_data`（`etf_daily` / `index_daily`）或 `get_cached_stock_daily` 优先；行数不足或缺失则 `fetch_index_daily_em` / `fetch_stock_daily_hist`
- 个股 `fetch_stock_daily_hist`（`src/data_collector.py`）优先走 `plugins/data_collection/stock/fetch_historical.py` 的 **`fetch_single_stock_historical`** 多源链（与 **openclaw-data-china-stock** 采集插件一致：缓存 → mootdx → Baostock → 新浪 → 东财 → 腾讯 → Tushare），全部失败再退回单源东财 `ak.stock_zh_a_hist`
- `auto`：复用 `underlying_historical_snapshot._fetch_daily_em_or_stock`
- `realized_vol_windows` + 收盘列 `_close_column`；止损中 **`volatility_pct / 100`** 再乘系数（避免与 %% 混淆）
- 凯利参数、`stop_loss_multiplier`、风险/波动提示阈值：合并后配置 → `risk_assessment`（域文件：`config/domains/risk_quality.yaml`）

**OpenClaw Skill**：`skills/ota-risk-assessment-brief`（`ota_risk_assessment_brief`），与 `tool_portfolio_risk_snapshot`（组合）区分；同步脚本 `scripts/sync_repo_skills_to_openclaw.sh`。

**使用场景**：
- **仓位管理**：评估当前持仓的风险水平
- **止损设置**：根据波动率自动计算合理的止损位
- **风险控制**：在开仓前评估风险，确保风险在可接受范围内
- **仓位优化**：使用凯利公式计算最优仓位大小

---

## 补充模块（关键位、预测落盘、隔夜校准、涨停情景）

与上表 `tool_*` 并列注册于 `tool_runner.py` / `config/tools_manifest.yaml`，多用于盘前晨报、盘后长文与涨停回马枪专题。

| 模块 | `tool_*` | 说明 |
|------|-----------|------|
| `key_levels.py` | `tool_compute_index_key_levels` | 沪深300 等指数日线近似支撑/压力（MA20、近窗高低、整数关口）。 |
| `accuracy_tracker.py` | `tool_record_before_open_prediction`、`tool_get_yesterday_prediction_review`、`tool_record_limitup_watch_outcome` | 盘前预测写入 `data/prediction_records/`、上一交易日回顾、涨停观察落盘。 |
| `overnight_calibration.py` | `tool_overnight_calibration` | 隔夜信息校准摘要，供 `research.md` 驱动报告与 `limitup_pullback_after_close` 等流程引用。 |
| `scenario_analysis.py` | `tool_build_limitup_scenarios` | 涨停回马枪多情景结构化输出（输入字段来自已采集数据，禁止编造未返回数值）。 |

组合级 VaR/回撤、合规与压力测试占位见 **`plugins/risk/README.md`**（`tool_portfolio_risk_snapshot` 等）。

---

## 其他 analysis 模块（runner / manifest 注册）

与上表并列，下列文件在 `tool_runner.py` / `config/tools_manifest.yaml` 中注册，或作为 **merged 门面** 的底层实现。

| 模块 | 对外 `tool_*`（或门面） | 说明 |
|------|-------------------------|------|
| [`market_regime.py`](market_regime.py) | `tool_detect_market_regime` | 基于指定 ETF 日线缓存：短中期动量、20 日波动、60 日回撤；输出 `regime` ∈ {`trending_up`, `trending_down`, `range`, `high_vol_risk`} 与置信度。 |
| [`etf_rotation_research.py`](etf_rotation_research.py) | `tool_etf_rotation_research` | ETF 轮动研究：本地日线、动量/波动/回撤/趋势 R²/相关性加权排名与 Markdown 摘要；池来自 `etf_pool` 或 `config/rotation_config.yaml` + `symbols.json`。依赖 **[`etf_rotation_core.py`](etf_rotation_core.py)**（管线、历史、池解析，无独立 tool）。 |
| [`etf_trend_tracking.py`](etf_trend_tracking.py) | `tool_check_etf_index_consistency`、`tool_generate_trend_following_signal` | ETF 与指数实时价比对（轻量一致性）；一致时生成简化的趋势跟随信号字段（`signal_type` / `confidence` 等）。 |
| [`equity_factor_screening.py`](equity_factor_screening.py) | `tool_screen_equity_factors` | 主实现见同级 **`openclaw-data-china-stock`** 主仓（本文件动态加载）；震荡模板因子（如 `reversal_5d` / `fund_flow_3d` / `sector_momentum_5d`）、`success` 布尔与 quality/degraded。规程 Skill：**`ota_equity_factor_screening_brief`**（`skills/ota-equity-factor-screening-brief/SKILL.md`）。 |
| [`quantitative_screening.py`](quantitative_screening.py) | ~~`tool_quantitative_screening`~~（已下线） | 历史四因子排序；manifest 已移除。归档叙事见 **`ota_quantitative_screening_brief`**（deprecated）。 |

### 仓位、止盈止损与策略权重（analysis 实现 + merged 门面）

OpenClaw 侧常通过 **`merged`** 单工具调用；实现仍在 `plugins/analysis/`。

| 模块 | 分析层 `tool_*` | 门面（`tool_runner`） |
|------|-----------------|------------------------|
| [`etf_position_manager.py`](etf_position_manager.py) | `tool_calculate_position_size`、`tool_check_position_limit`、`tool_apply_hard_limit` | [`merged/position_limit`](../merged/position_limit.py) → `tool_position_limit` |
| [`etf_risk_manager.py`](etf_risk_manager.py) | `tool_calculate_stop_loss_take_profit`、`tool_check_stop_loss_take_profit` | [`merged/stop_loss_take_profit`](../merged/stop_loss_take_profit.py) → `tool_stop_loss_take_profit` |
| [`strategy_weight_manager.py`](strategy_weight_manager.py) | `tool_get_strategy_weights`、`tool_adjust_strategy_weights` | [`merged/strategy_weights`](../merged/strategy_weights.py) → `tool_strategy_weights`（及 `tool_get_strategy_weights` / `tool_adjust_strategy_weights` 别名映射） |

动态权重合并路径见 **`plugins/strategy_engine/README.md`**、`STRATEGY_FUSION_WEIGHTS_PATH`（`docs/openclaw/跨插件数据契约.md`）。

---

## 策略研究与回放评估（`tool_strategy_research`）

- **实现入口**：[`strategy_research.py`](strategy_research.py) — `tool_strategy_research`、`tool_get_strategy_research_history` 等；与 [`strategy_tracker.py`](strategy_tracker.py)、[`strategy_evaluator.py`](strategy_evaluator.py) 配合。
- **配置**：[`config/strategy_research.yaml`](../../config/strategy_research.yaml) — 样本切分比例、可选交易成本、务实版 WFE 阈值、复杂度惩罚、Holdback 门禁、回测日志路径。
- **数据**：[`plugins/analysis/strategy_tracker.py`](strategy_tracker.py) 从 `data/signal_records/signal_records.db` 聚合；支持 `start_date` / `end_date`（`YYYYMMDD`）、`trading_costs`、`by_regime`（需 `signal_regime_labels` 表为 `signal_id` 提供 `market_regime`）。
- **务实版 WFE**：[`calculate_wfe_style_metrics`](strategy_evaluator.py) 比较 IS 与 OOS 窗口的**年化收益代理**（无样本内参数优化）。机构意义上的完整 Walk-Forward（多窗寻优 + 参数稳定性 CV）**尚未实现**，需后续引入参数网格与优化器后再接 `calculate_wfe_style_metrics` 的语义升级。
- **工具参数**：`enable_split_analysis`、`include_regime_breakdown`（默认读配置）；回测运行摘要追加至 `data/backtest_logs/research_runs.jsonl`（可关）。查询最近记录：`tool_get_strategy_research_history(limit=20)`。

---

## 数据流

```
数据访问工具 (read_cache_data)
    ↓
读取缓存数据（指数、ETF、期权）
    ↓
分析插件计算
    ↓
生成分析结果
    ↓
通过 API 保存到原系统
    ↓
原系统存储（Parquet/JSON）
```

## 依赖包

- `pandas`: 数据处理
- `numpy`: 数值计算
- `arch`: GARCH 模型（波动率预测）
- `statsmodels`: ARIMA 模型（趋势分析）
- `requests`: HTTP 请求（API 调用）

## 环境变量

- `OPENCLAW_API_KEY`: API Key，用于访问原系统 API
- `OPTION_TRADING_ASSISTANT_API_KEY`: 原系统 API Key（如果不同）

## 注意事项

1. **数据依赖**：所有分析插件都依赖原系统的缓存数据，确保数据已采集
2. **API 连接**：确保原系统 API 服务正常运行，且网络可达
3. **计算资源**：GARCH 模型计算较耗时，建议在非交易时间执行
4. **错误处理**：插件包含完整的错误处理，失败时会返回错误信息
5. **数据格式**：确保从缓存读取的数据格式正确，包含必要的列（如 close, high, low, volume）

## Cursor skill

项目内 Cursor Skill（历史波动快照工具选型与配置）：

- [.cursor/skills/etf-options-volatility-snapshot/SKILL.md](../../.cursor/skills/etf-options-volatility-snapshot/SKILL.md)
- [docs/volatility_snapshot_skill.md](../../docs/volatility_snapshot_skill.md)（无法使用 `.cursor/skills` 路径时的短指针）

---

## 迁移说明

- 分析逻辑融合了 Coze 插件的核心计算函数
- 通过数据访问工具从原系统读取数据，保持数据一致性
- 分析结果通过 API 保存到原系统，便于 Web 界面展示
- 插件设计保持独立性，不直接依赖原系统代码
