"""
策略配置 Schema 与 510300 相关示例策略定义。

核心思想：
- “策略即配置”：上层 Agent 只需要根据这些配置与行情数据，就能生成标准化信号；
- 本文件聚焦于结构与字段约定，不直接做具体指标计算。
"""

from __future__ import annotations

from typing import Any, Dict, List

StrategyConfig = Dict[str, Any]


def base_schema() -> Dict[str, Any]:
    """返回策略配置的字段结构说明（Schema）。"""
    return {
        "id": "唯一策略 ID，如 trend_following_510300",
        "name": "人类可读名称",
        "instrument": {
            "type": "ETF | INDEX | OPTION | MIXED",
            "symbol": "标的代码，如 510300 / 000300",
        },
        "timeframe": "如 1d / 30m / 5m / tick",
        "indicators": [
            {
                "name": "Aroon / MACD / ATR / RSI / VolatilityCone 等",
                "params": {"key": "value"},
            }
        ],
        "triggers": {
            "entry": ["入场条件表达（自然语言描述，供 Agent 解释）"],
            "exit": ["离场条件表达"],
        },
        "positioning": {
            "base_pct": 0.02,
            "max_pct": 0.02,
            "pyramiding": False,
        },
        "risk": {
            "stop_loss": "ATR / 价格百分比 / 波动率阈值等",
            "take_profit": "目标收益 / MA 回归等",
            "day_max_loss_pct": -0.015,
        },
        "meta": {
            "category": "trend / mean_reversion / intraday / options / event",
            "holding_period": "预计持仓周期描述",
        },
    }


def trend_following_510300() -> StrategyConfig:
    """策略 1：趋势跟踪 + ETF/指数一致性增强（波段）。"""
    return {
        "id": "trend_following_510300",
        "name": "510300 趋势跟踪 + 一致性增强",
        "instrument": {"type": "ETF", "symbol": "510300"},
        "benchmark": {"type": "INDEX", "symbol": "000300"},
        "timeframe": "1d",
        "indicators": [
            {
                "name": "Aroon",
                "params": {"period": 25},
            },
            {
                "name": "MACD",
                "params": {"fast": 12, "slow": 26, "signal": 9},
            },
            {
                "name": "PriceBreakout",
                "params": {"lookback": 20},
            },
        ],
        "triggers": {
            "entry": [
                "510300 与 000300 一致性得分 >= 0.7",
                "Aroon 趋势强度 >= 0.6",
                "510300 与指数同向突破 N 日高/低点",
                "5 分钟级别成交量显著放大（用于确认有效突破）",
            ],
            "exit": [
                "价格跌破短期均线且 Aroon 趋势减弱",
                "或 ATR 基础止损被触发",
            ],
        },
        "positioning": {
            "base_pct": 0.02,
            "max_pct": 0.02,
            "pyramiding": False,
        },
        "risk": {
            "stop_loss": {"type": "atr", "multiplier": 1.5},
            "take_profit": {
                "type": "discretionary_band",
                "min_holding_days": 2,
                "max_holding_days": 10,
            },
            "day_max_loss_pct": -0.015,
        },
        "meta": {
            "category": "trend",
            "holding_period": "2-10 个交易日",
        },
    }


def mean_reversion_510300() -> StrategyConfig:
    """策略 2：均值回归 + 波动率锥过滤（短线/波段）。"""
    return {
        "id": "mean_reversion_510300",
        "name": "510300 均值回归 + 波动率锥过滤",
        "instrument": {"type": "ETF", "symbol": "510300"},
        "timeframe": "30m",
        "indicators": [
            {
                "name": "MA",
                "params": {"period": 20},
            },
            {
                "name": "ATR",
                "params": {"period": 14},
            },
            {
                "name": "RSI",
                "params": {"period": 14},
            },
            {
                "name": "VolatilityCone",
                "params": {"lookback_days": 252},
            },
        ],
        "triggers": {
            "entry": [
                "价格相对 MA20 偏离度 > ±1.5×ATR",
                "当前实现波动率处于波动率锥 20-80 分位区间",
                "RSI 进入超卖/超买区间并出现反转迹象",
            ],
            "exit": [
                "价格回归 MA20 附近",
                "或 ATR 止损被触发",
            ],
        },
        "positioning": {
            "base_pct": 0.01,
            "max_pct": 0.02,
            "pyramiding": False,
        },
        "risk": {
            "stop_loss": {"type": "atr", "multiplier": 1.0},
            "take_profit": {"type": "ma_reversion", "target": "MA20"},
            "day_max_loss_pct": -0.015,
        },
        "meta": {
            "category": "mean_reversion",
            "holding_period": "数小时到数日",
        },
    }


def intraday_vol_breakout_510300() -> StrategyConfig:
    """策略 4：日内波动率突破（高频/日内）。"""
    return {
        "id": "intraday_vol_breakout_510300",
        "name": "510300 日内波动率突破",
        "instrument": {"type": "ETF", "symbol": "510300"},
        "benchmark": {"type": "INDEX", "symbol": "000300"},
        "timeframe": "5m",
        "indicators": [
            {
                "name": "IntradayRange",
                "params": {"window_minutes": 30},
            },
            {
                "name": "VolumeSpike",
                "params": {"lookback_bars": 20, "threshold_sigma": 2},
            },
            {
                "name": "Aroon",
                "params": {"period": 20},
            },
        ],
        "triggers": {
            "entry": [
                "9:30-10:00 区间内，5 分钟涨跌幅绝对值 > 0.5%",
                "且成交量显著放大（例如大于近 20 根均值 2 倍）",
                "Aroon 趋势方向与价格突破方向一致",
            ],
            "exit": [
                "持仓时间达到 15-60 分钟窗口上限必须平仓",
                "或日内止损被触发",
            ],
        },
        "positioning": {
            "base_pct": 0.01,
            "max_pct": 0.02,
            "pyramiding": False,
        },
        "risk": {
            "stop_loss": {"type": "percent", "value": 0.0075},
            "take_profit": {"type": "percent", "value": 0.015},
            "day_max_loss_pct": -0.015,
        },
        "meta": {
            "category": "intraday",
            "holding_period": "分钟级，不隔夜",
        },
    }


def event_driven_a50_linked() -> StrategyConfig:
    """策略 5：事件驱动 + A50 期指联动（波段）。"""
    return {
        "id": "event_a50_linked_510300",
        "name": "A50 期指联动 + 510300 事件驱动",
        "instrument": {"type": "ETF", "symbol": "510300"},
        "external_signals": [
            {
                "name": "A50NightSession",
                "params": {"threshold_pct": 0.5},
            },
            {
                "name": "MacroEvents",
                "params": {"events": ["PMI", "CPI", "FOMC"]},
            },
        ],
        "timeframe": "1d",
        "indicators": [],
        "triggers": {
            "entry": [
                "A50 夜盘涨跌幅绝对值 > 0.5%",
                "且方向与 510300 近期趋势一致",
                "宏观事件偏多/偏空与方向相符",
            ],
            "exit": [
                "事件影响兑现，波动回落",
                "或价格跌破关键技术位与日内止损线",
            ],
        },
        "positioning": {
            "base_pct": 0.01,
            "max_pct": 0.02,
            "pyramiding": False,
        },
        "risk": {
            "stop_loss": {"type": "percent", "value": 0.015},
            "take_profit": {"type": "percent_trailing", "value": 0.03},
            "day_max_loss_pct": -0.015,
        },
        "meta": {
            "category": "event",
            "holding_period": "数日到数周",
        },
    }


def options_delta_neutral_510300() -> StrategyConfig:
    """
    策略 3：Delta-Neutral 期权策略（波动率/时间价值收割）。

    说明：
    - 当前阶段主要描述组合结构与风控参数，具体腿的构建与 Greeks 计算
      由后续期权模块结合 tool_fetch_option_* 与 tool_fetch_option_greeks 实现。
    """
    return {
        "id": "delta_neutral_options_510300",
        "name": "510300 Delta-Neutral 期权策略",
        "instrument": {"type": "OPTION", "symbol": "510300"},
        "timeframe": "1d",
        "indicators": [
            {
                "name": "ImpliedVolatility",
                "params": {"lookback_days": 252},
            },
            {
                "name": "HistoricalVolatilityCone",
                "params": {"lookback_days": 252},
            },
        ],
        "triggers": {
            "entry": [
                "当 IV 高于历史 70-80 分位，倾向卖跨式 / 备兑策略",
                "当 IV 低于历史 20-30 分位，倾向买跨式博波动放大",
                "组合 Delta 接近 0，Gamma / Vega / Theta 在可接受区间",
            ],
            "exit": [
                "IV 突破历史 90 分位或回落至中性区间",
                "标的价格触发备兑或保护性止损线",
            ],
        },
        "positioning": {
            "base_pct": 0.015,
            "max_pct": 0.02,
            "pyramiding": False,
        },
        "risk": {
            "stop_loss": {"type": "iv_percentile", "value": 0.9},
            "take_profit": {"type": "theta_capture_window", "days": 5},
            "day_max_loss_pct": -0.015,
            "per_leg_max_pct": 0.015,
            "contract_unit": 10260,
        },
        "meta": {
            "category": "options",
            "holding_period": "数日至到期前",
        },
    }


def multi_strategy_portfolio() -> StrategyConfig:
    """策略 6：多策略组合 + 动态权重调整。"""
    return {
        "id": "multi_strategy_portfolio_510300",
        "name": "510300 多策略组合投资组合",
        "instrument": {"type": "MIXED", "symbol": "510300"},
        "components": [
            {
                "strategy_id": "trend_following_510300",
                "initial_weight": 0.35,
            },
            {
                "strategy_id": "mean_reversion_510300",
                "initial_weight": 0.25,
            },
            {
                "strategy_id": "intraday_vol_breakout_510300",
                "initial_weight": 0.2,
            },
            {
                "strategy_id": "event_a50_linked_510300",
                "initial_weight": 0.1,
            },
            {
                "strategy_id": "delta_neutral_options_510300",
                "initial_weight": 0.1,
            },
        ],
        "rebalance": {
            "frequency_days": 30,
            "min_score": 60,
            "on_score_below_min": "reduce_or_pause",
        },
        "meta": {
            "category": "portfolio",
            "holding_period": "长期，按月动态调权",
        },
    }


def list_all_strategies() -> List[StrategyConfig]:
    """返回所有已定义的 510300 相关策略配置。"""
    return [
        trend_following_510300(),
        mean_reversion_510300(),
        intraday_vol_breakout_510300(),
        event_driven_a50_linked(),
        options_delta_neutral_510300(),
        multi_strategy_portfolio(),
    ]


def get_strategy_config(strategy_id: str) -> StrategyConfig:
    """根据策略 ID 获取配置，不存在则抛出 KeyError。"""
    for cfg in list_all_strategies():
        if cfg.get("id") == strategy_id:
            return cfg
    raise KeyError(f"未知的策略 ID: {strategy_id}")


__all__ = [
    "StrategyConfig",
    "base_schema",
    "trend_following_510300",
    "mean_reversion_510300",
    "intraday_vol_breakout_510300",
    "event_driven_a50_linked",
    "options_delta_neutral_510300",
    "multi_strategy_portfolio",
    "list_all_strategies",
    "get_strategy_config",
]

