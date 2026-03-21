# 分析插件

本目录包含宽基ETF及其期权交易助手的分析相关插件工具，融合了 Coze 插件的核心逻辑。

## 插件列表

### 1. technical_indicators.py - 技术指标计算

**功能说明**：
- 计算多种技术指标：移动平均线（MA）、MACD、RSI、布林带
- 融合 Coze `technical_indicators.py` 的所有计算函数
- 支持 ETF 和指数数据的技术指标分析

**使用方法**：
```python
from plugins.analysis.technical_indicators import tool_calculate_technical_indicators

# 计算技术指标
result = tool_calculate_technical_indicators(
    symbol="510300",              # ETF代码，默认 "510300"
    data_type="etf_daily",        # 数据类型："index_daily", "etf_daily", "index_minute", "etf_minute"
    period=None,                  # 周期（用于分钟数据）
    indicators=["ma", "macd", "rsi", "bollinger"]  # 需要计算的指标列表
)
```

**输入参数**：
- `symbol` (str): 标的代码，如 "510300"（沪深300ETF）
- `data_type` (str): 数据类型，可选 "index_daily", "etf_daily", "index_minute", "etf_minute"
- `period` (str, optional): 周期（用于分钟数据），如 "5m", "15m", "30m"
- `indicators` (List[str], optional): 需要计算的指标列表，默认全部计算

**输出格式**：
```python
{
    "success": True,
    "data": {
        "symbol": "510300",
        "current_price": 4.85,
        "indicators": {
            "ma": {
                "ma5": 4.82,
                "ma10": 4.80,
                "ma20": 4.78,
                "ma60": 4.75,
                "arrangement": "多头排列",
                "cross_signal": "金叉",
                "price_vs_ma20": 0.88
            },
            "macd": {
                "dif": 0.02,
                "dea": 0.01,
                "macd": 0.02,
                "signal": "金叉"
            },
            "rsi": {
                "rsi": 65.5,
                "period": 14,
                "signal": "偏强",
                "suggestion": "注意风险"
            },
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
        },
        "timestamp": "2025-01-15 14:30:00"
    },
    "source": "calculated"
}
```

**技术实现要点**：
- 通过 `read_cache_data` 从原系统读取历史数据
- 提取收盘价序列进行计算
- 复用 Coze 插件的核心计算函数（`_calculate_ma`, `_calculate_macd`, `_calculate_rsi`, `_calculate_bollinger`）
- 生成综合信号，汇总各指标信号

**使用场景**：
- 盘前分析：计算前一交易日技术指标，判断趋势
- 盘中监控：实时计算技术指标，识别交易机会
- 信号生成：作为信号生成的基础数据
- 趋势判断：结合多个指标判断市场趋势

---

### 2. trend_analysis.py - 趋势分析

**功能说明**：
- 执行盘后、盘前、开盘三种类型的趋势分析
- 融合 Coze `trend_analysis.py` 的逻辑
- 支持多时间框架趋势判断

**使用方法**：
```python
from plugins.analysis.trend_analysis import (
    tool_analyze_after_close,
    tool_analyze_before_open,
    tool_analyze_opening_market
)

# 盘后分析（15:30执行）
result = tool_analyze_after_close()

# 盘前分析（9:15执行）
result = tool_analyze_before_open()

# 开盘分析（9:28执行）
result = tool_analyze_opening_market()
```

**输入参数**：
- `analysis_type` (str): 分析类型，可选 "after_close", "before_open", "opening_market"
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key，从环境变量 `OPENCLAW_API_KEY` 获取

**输出格式**：
```python
{
    "success": True,
    "message": "Trend analysis completed and saved",
    "data": {
        "analysis_type": "after_close",
        "timestamp": "2025-01-15 15:30:00",
        "trend": "up",           # "up", "down", "neutral"
        "strength": 0.75,        # 趋势强度 0-1
        "details": {
            "index_trend": "up",
            "etf_trend": "up",
            "consistency": True,
            "confidence": 0.80
        }
    }
}
```

**技术实现要点**：
- 通过数据访问工具读取指数和ETF历史数据
- 使用ARIMA模型进行趋势预测
- 结合技术指标判断趋势方向
- 计算趋势强度和置信度
- 通过 API 保存分析结果到原系统

**使用场景**：
- **盘后分析（15:30）**：分析当天市场，预测下一交易日趋势
- **盘前分析（9:15）**：基于前一交易日盘后结论 + 外盘/A50数据，给出当天开盘策略建议
- **开盘分析（9:28）**：基于集合竞价数据，给出当天更贴近开盘现实的趋势判断

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

### 4. signal_generation.py - 交易信号生成

**功能说明**：
- 生成 ETF 和期权的交易信号
- 融合 Coze `signal_generator.py` 的核心逻辑
- 支持多种策略：趋势跟踪、均值回归、突破
- 支持回测功能和 IV 调整

**使用方法**：
```python
from plugins.analysis.signal_generation import tool_generate_signals

# 生成交易信号
result = tool_generate_signals(
    underlying="510300",              # 标的物代码
    contract_codes=["10010891", "10010892"]  # 期权合约代码列表（可选）
)
```

**输入参数**：
- `underlying` (str): 标的物代码，如 "510300"
- `contract_codes` (List[str], optional): 期权合约代码列表
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Generated 2 signals and saved",
    "data": {
        "signals": [
            {
                "signal_type": "call",        # "call", "put", "etf_buy", "etf_sell"
                "underlying": "510300",
                "contract_code": "10010891",
                "signal_strength": 0.75,      # 信号强度 0-1
                "strategy": "trend_following", # "trend_following", "mean_reversion", "breakout"
                "risk_level": "medium",       # "low", "medium", "high"
                "expected_return": 0.05,
                "risk_reward_ratio": 2.5,
                "timestamp": "2025-01-15 14:30:00",
                "reason": "ETF短期K线转折 + Greeks确认"
            }
        ],
        "count": 2
    }
}
```

**技术实现要点**：
- 结合技术指标、趋势分析、波动率预测生成信号
- 支持多种策略：趋势跟踪、均值回归、突破
- 信号强度分级：强信号（≥0.75）、中等信号（0.55-0.75）、弱信号（0.45-0.55）
- 支持回测功能验证信号效果
- 支持 IV 调整，在高 IV 环境下调整策略权重
- 通过 API 保存信号到原系统

**使用场景**：
- **日内交易**：生成 ETF 和期权的日内交易信号
- **趋势跟踪**：在趋势明确时生成顺势信号
- **均值回归**：在价格偏离均值时生成回归信号
- **突破策略**：在价格突破关键位置时生成信号
- **信号通知**：通过通知插件发送信号提醒

---

### 5. historical_volatility.py - 历史波动率计算

**功能说明**：
- 计算多个时间窗口的历史波动率（HV）
- 融合 Coze `historical_volatility.py` 的计算逻辑
- 支持日线和分钟级数据
- 计算波动率锥（Volatility Cone）

**使用方法**：
```python
from plugins.analysis.historical_volatility import tool_calculate_historical_volatility

# 计算历史波动率
result = tool_calculate_historical_volatility(
    symbol="510300",              # ETF代码，默认 "510300"
    windows=[5, 10, 20, 60, 120]  # 计算窗口列表（可选）
)
```

**输入参数**：
- `symbol` (str): 标的代码，如 "510300"（沪深300ETF）或 "000300"（沪深300指数）
- `windows` (List[int], optional): 计算窗口列表，默认 [5, 10, 20, 60, 120]
- `data_period` (str): 数据频率，默认 "daily"
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully calculated historical volatility",
    "data": {
        "symbol": "510300",
        "data_frequency": "daily",
        "volatilities": {
            "hv_5": {
                "window": 5,
                "volatility": 0.1523,
                "volatility_percent": 15.23
            },
            "hv_10": {
                "window": 10,
                "volatility": 0.1845,
                "volatility_percent": 18.45
            },
            "hv_20": {
                "window": 20,
                "volatility": 0.2012,
                "volatility_percent": 20.12
            },
            "hv_60": {
                "window": 60,
                "volatility": 0.1956,
                "volatility_percent": 19.56
            },
            "hv_120": {
                "window": 120,
                "volatility": 0.1898,
                "volatility_percent": 18.98
            }
        },
        "volatility_cone": {
            "window_5": {
                "min": 0.1066,
                "max": 0.1980,
                "mean": 0.1523
            },
            "window_20": {
                "min": 0.1408,
                "max": 0.2616,
                "mean": 0.2012
            }
        },
        "current_hv20": 0.2012,
        "current_hv20_percent": 20.12,
        "data_points": 250,
        "timestamp": "2025-01-15 14:30:00"
    }
}
```

**技术实现要点**：
- 通过 `read_cache_data` 从原系统读取历史数据
- 计算对数收益率序列
- 使用标准差方法计算历史波动率
- 年化波动率计算（日线数据：252个交易日，分钟数据：252*240）
- 生成波动率锥，用于判断当前波动率水平

**使用场景**：
- **波动率分析**：评估标的物的历史波动水平
- **IV-HV对比**：与隐含波动率（IV）对比，判断期权定价合理性
- **风险度量**：作为风险评估的输入参数
- **策略优化**：根据历史波动率调整交易策略参数

---

### 6. intraday_range.py - 日内波动区间预测

**功能说明**：
- 基于历史日内波动数据预测当天价格波动区间
- 融合 Coze `intraday_range.py` 的预测逻辑
- 计算不同置信水平的波动区间
- 识别关键支撑阻力位

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

### 7. risk_assessment.py - 风险评估

**功能说明**：
- 评估 ETF 持仓的风险水平
- 融合 Coze `risk_assessment.py` 的风险计算逻辑
- 计算仓位比例、风险比例、最优仓位
- 提供风险等级和建议

**使用方法**：
```python
from plugins.analysis.risk_assessment import tool_assess_risk

# 风险评估
result = tool_assess_risk(
    symbol="510300",              # ETF代码，默认 "510300"
    position_size=10000,           # 持仓数量
    entry_price=4.85,              # 入场价格
    stop_loss=4.70,                # 止损价格（可选）
    account_value=100000           # 账户总值
)
```

**输入参数**：
- `symbol` (str): ETF代码，如 "510300"（沪深300ETF），必须是上海ETF（51xxxx）或深圳ETF（159xxx）
- `position_size` (float): 持仓数量，默认 10000
- `entry_price` (float): 入场价格，默认 4.0
- `stop_loss` (float, optional): 止损价格，如果未提供则根据波动率自动计算
- `account_value` (float): 账户总值，默认 100000
- `api_base_url` (str): 原系统 API 基础地址，默认 "http://localhost:5000"
- `api_key` (str, optional): API Key

**输出格式**：
```python
{
    "success": True,
    "message": "Successfully assessed risk",
    "data": {
        "symbol": "510300",
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
        "timestamp": "2025-01-15 14:30:00"
    }
}
```

**技术实现要点**：
- 通过 `read_cache_data` 从原系统读取历史数据计算波动率
- 计算仓位比例（持仓价值/账户总值）
- 计算风险金额和风险比例（止损金额/账户总值）
- 使用凯利公式计算最优仓位比例
- 根据风险比例评估风险等级（low/medium/high）
- 生成风险控制建议

**使用场景**：
- **仓位管理**：评估当前持仓的风险水平
- **止损设置**：根据波动率自动计算合理的止损位
- **风险控制**：在开仓前评估风险，确保风险在可接受范围内
- **仓位优化**：使用凯利公式计算最优仓位大小

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

## 迁移说明

- 分析逻辑融合了 Coze 插件的核心计算函数
- 通过数据访问工具从原系统读取数据，保持数据一致性
- 分析结果通过 API 保存到原系统，便于 Web 界面展示
- 插件设计保持独立性，不直接依赖原系统代码
