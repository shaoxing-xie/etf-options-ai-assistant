"""
策略评分系统插件
评估策略表现，计算策略评分
参考原系统 volatility_weights.py 的逻辑
OpenClaw 插件工具
"""

import sys
import os
from typing import Any, Dict, Optional

# 添加父目录到路径以导入strategy_tracker
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, parent_dir)

try:
    from plugins.analysis.strategy_tracker import get_strategy_performance
    STRATEGY_TRACKER_AVAILABLE = True
except ImportError:
    STRATEGY_TRACKER_AVAILABLE = False


def calculate_wfe_style_metrics(
    strategy: str,
    is_start: str,
    is_end: str,
    oos_start: str,
    oos_end: str,
    trading_costs: Optional[Dict[str, Any]] = None,
    min_closed_is: int = 3,
    min_closed_oos: int = 3,
    wfe_warn_threshold: float = 0.5,
    eps: float = 1e-8,
) -> Dict[str, Any]:
    """
    无参数优化前提下的「务实版」样本外效率指标：用 IS / OOS 两段年化收益代理比衡量衰减。
    非机构完整 Walk-Forward（不含 IS 内寻优）；见 config/strategy_research.yaml 注释说明。
    """
    if not STRATEGY_TRACKER_AVAILABLE:
        return {"success": False, "message": "策略跟踪模块不可用", "data": None}

    is_p = get_strategy_performance(
        strategy=strategy,
        lookback_days=1,
        start_date=is_start,
        end_date=is_end,
        trading_costs=trading_costs,
    )
    oos_p = get_strategy_performance(
        strategy=strategy,
        lookback_days=1,
        start_date=oos_start,
        end_date=oos_end,
        trading_costs=trading_costs,
    )
    if not is_p.get("success") or not oos_p.get("success"):
        return {
            "success": False,
            "message": is_p.get("error") or oos_p.get("error") or "表现查询失败",
            "data": None,
        }

    is_closed = int(is_p.get("closed_signals") or 0)
    oos_closed = int(oos_p.get("closed_signals") or 0)
    if is_closed < min_closed_is or oos_closed < min_closed_oos:
        return {
            "success": True,
            "message": "IS 或 OOS 闭合样本不足，WFE 风格指标记为 N/A",
            "data": {
                "wfe_return_ratio": None,
                "is_annualized_return_proxy": is_p.get("annualized_return_proxy_gross"),
                "oos_annualized_return_proxy": oos_p.get("annualized_return_proxy_gross"),
                "is_gross_sharpe_like": is_p.get("gross_sharpe_like"),
                "oos_gross_sharpe_like": oos_p.get("gross_sharpe_like"),
                "is_closed_signals": is_closed,
                "oos_closed_signals": oos_closed,
                "overfit_warn": None,
                "note": "务实版 WFE：无 IS 内参数优化；比值为 OOS 与 IS 年化收益代理之比。",
            },
        }

    ann_is = float(is_p.get("annualized_return_proxy_gross") or 0.0)
    ann_oos = float(oos_p.get("annualized_return_proxy_gross") or 0.0)
    denom = max(abs(ann_is), eps)
    wfe_ratio = ann_oos / denom if ann_is >= 0 else ann_oos / denom
    overfit_warn = (
        wfe_ratio is not None
        and wfe_ratio < wfe_warn_threshold
        and ann_is > eps
    )

    return {
        "success": True,
        "message": "WFE 风格指标已计算",
        "data": {
            "wfe_return_ratio": float(wfe_ratio),
            "is_annualized_return_proxy": ann_is,
            "oos_annualized_return_proxy": ann_oos,
            "is_gross_sharpe_like": float(is_p.get("gross_sharpe_like") or 0.0),
            "oos_gross_sharpe_like": float(oos_p.get("gross_sharpe_like") or 0.0),
            "is_net_sharpe_like": float(is_p.get("net_sharpe_like") or 0.0),
            "oos_net_sharpe_like": float(oos_p.get("net_sharpe_like") or 0.0),
            "is_closed_signals": is_closed,
            "oos_closed_signals": oos_closed,
            "overfit_warn": bool(overfit_warn),
            "wfe_warn_threshold": wfe_warn_threshold,
            "note": "务实版 WFE：无 IS 内参数优化；完整 Walk-Forward 需参数网格与优化器（见文档）。",
        },
    }


def calculate_strategy_score(
    strategy: str,
    lookback_days: int = 60,
    min_signals: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trading_costs: Optional[Dict[str, Any]] = None,
    param_count: int = 0,
    complexity_penalty_per_param: float = 0.02,
    complexity_penalty_cap: float = 0.30,
    apply_complexity_penalty: bool = True,
) -> Dict[str, Any]:
    """
    计算策略评分

    Args:
        strategy: 策略名称
        lookback_days: 回看天数
        min_signals: 最少信号数（低于此值无法评估）
        start_date / end_date: 可选 YYYYMMDD 区间
        trading_costs: 可选，传入 get_strategy_performance
        param_count: 策略有效参数个数（用于复杂度惩罚）
        complexity_penalty_per_param: 每个参数扣除比例上限的一部分
        complexity_penalty_cap: 惩罚上限（占 base_score 比例）
        apply_complexity_penalty: 是否应用复杂度惩罚

    Returns:
        dict: 评分与各指标
    """
    try:
        if not STRATEGY_TRACKER_AVAILABLE:
            return {
                "success": False,
                "message": "策略跟踪模块不可用",
                "data": None,
            }

        performance = get_strategy_performance(
            strategy=strategy,
            lookback_days=lookback_days,
            start_date=start_date,
            end_date=end_date,
            trading_costs=trading_costs,
        )

        if not performance.get("success"):
            return {
                "success": False,
                "message": performance.get("error", "获取策略表现失败"),
                "data": None,
            }

        total_signals = performance.get("total_signals", 0)
        closed_signals = performance.get("closed_signals", 0)

        if closed_signals < min_signals:
            return {
                "success": True,
                "message": f"信号数不足（{closed_signals} < {min_signals}），无法评估",
                "data": {
                    "score": 50.0,
                    "win_rate": 0.0,
                    "avg_return": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "total_signals": total_signals,
                    "closed_signals": closed_signals,
                },
            }

        win_rate = performance.get("win_rate", 0.0)
        avg_return = performance.get("avg_return", 0.0)
        net_avg = performance.get("avg_return")
        if performance.get("trading_costs_applied"):
            net_avg = float(
                (performance.get("sum_closed_return_net") or 0.0)
                / max(1, closed_signals)
            )

        sharpe_gross = float(performance.get("gross_sharpe_like") or 0.0)
        sharpe_net = float(performance.get("net_sharpe_like") or sharpe_gross)
        sharpe_ratio = sharpe_net

        max_drawdown = abs(min(0.0, net_avg * 0.5))

        score = (
            win_rate * 100 * 0.3
            + min(max(net_avg * 1000, -50), 50) * 0.4
            + min(max(sharpe_ratio * 10, 0), 20) * 0.2
            + (1 - min(max_drawdown, 1.0)) * 100 * 0.1
        )
        score = max(0.0, min(100.0, score))
        base_score = score

        penalty = 0.0
        if apply_complexity_penalty and param_count > 0:
            penalty = min(
                float(param_count) * float(complexity_penalty_per_param),
                float(complexity_penalty_cap),
            )
            score = score * (1.0 - penalty)

        return {
            "success": True,
            "message": "策略评分计算完成",
            "data": {
                "score": float(score),
                "base_score_before_complexity": float(base_score),
                "complexity_penalty": float(penalty),
                "param_count": int(param_count),
                "win_rate": float(win_rate),
                "avg_return": float(avg_return),
                "avg_return_net": float(net_avg) if net_avg is not None else float(avg_return),
                "sharpe_ratio": float(sharpe_ratio),
                "sharpe_ratio_gross": float(sharpe_gross),
                "max_drawdown": float(max_drawdown),
                "total_signals": total_signals,
                "closed_signals": closed_signals,
                "lookback_days": lookback_days,
                "start_date": performance.get("start_date"),
                "end_date": performance.get("end_date"),
                "metrics": {
                    "win_rate_weight": 0.3,
                    "avg_return_weight": 0.4,
                    "sharpe_ratio_weight": 0.2,
                    "max_drawdown_weight": 0.1,
                },
            },
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"计算策略评分失败: {str(e)}",
            "data": None,
        }


def tool_calculate_strategy_score(
    strategy: str,
    lookback_days: int = 60,
    min_signals: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trading_costs: Optional[Dict[str, Any]] = None,
    param_count: int = 0,
    complexity_penalty_per_param: float = 0.02,
    complexity_penalty_cap: float = 0.30,
    apply_complexity_penalty: bool = True,
) -> Dict[str, Any]:
    """OpenClaw 工具：计算策略评分"""
    return calculate_strategy_score(
        strategy=strategy,
        lookback_days=lookback_days,
        min_signals=min_signals,
        start_date=start_date,
        end_date=end_date,
        trading_costs=trading_costs,
        param_count=param_count,
        complexity_penalty_per_param=complexity_penalty_per_param,
        complexity_penalty_cap=complexity_penalty_cap,
        apply_complexity_penalty=apply_complexity_penalty,
    )
