# 功能域 ↔ 代码包 ↔ 配置键（扩展公约）

新增能力时 **先定域**，在同一域下增加 YAML 键；避免在无关域复制同名概念。

| 域 | 职责 | 主要配置键 | 典型代码路径 |
|----|------|----------------|--------------|
| A Reference & Universe | 标的、合约骨架、日历、采集标的清单 | `signal_generation.option_contracts` → 归一化 `option_contracts`、`system.trading_hours`、`data_cache` | `src/config_loader.py`, `src/signal_universe.py`, `src/data_cache.py`, `src/data_cache_universe.py` |
| B Market Data | 多源、熔断、Tick | `data_sources`, `tushare`, `realtime_full_fetch_cache` | `src/data_collector.py`, `tick_client.py` |
| C Analytics & Models | 指标、波动、日频区间、历史面板 | `technical_indicators`, `volatility_engine`, `daily_volatility_range`, `historical_snapshot` | `plugins/analysis/`, `plugins/merged/volatility.py` |
| D Alpha & Signals | 信号、日内、图表告警 | `signal_generation`, `signal_params`, `internal_chart`, `etf_trading` | `src/signal_generator.py`, `src/signal_generation.py`, `src/alerts/` |
| E Risk & Quality | 工具风控、预测质量 | `risk_assessment`, `prediction_quality`, `prediction_monitoring` | `plugins/analysis/risk_assessment.py`, `src/prediction_normalizer.py`, `scripts/prediction_metrics_weekly.py` |
| F Distribution & Narrative | 推送、日报、LLM | `notification`, `trend_analysis_plugin`, `llm_enhancer`, `llm_structured_extract` | `plugins/notification/`, `plugins/analysis/trend_analysis.py` |
| G Platform & Ops | 日志、存储、调度 | `logging`, `system`, `opening_analysis` | `src/logger_config.py`, `scripts/` |

**约定**：OpenClaw 采集插件（`plugins/data_collection` 常为 symlink）**不在此矩阵内改契约**；主项目只读合并后的 `config`。
