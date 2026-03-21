#!/usr/bin/env python3
"""
期权 / ETF 交易工具网关 - OpenClaw 集成

设计目标：
- 对上：为各个 ETF 相关 Agent 提供统一的 CLI 接口，负责环境探测、风控检查和交易执行入口。
- 对下：后续可以对接真实券商 API、回测框架（KHQuant / Backtrader）或模拟盘，而不影响上层调用协议。

当前实现状态（阶段 1）：
- 保留原有的 `status` / `signal` 行为，避免破坏现有调用。
- 新增：
  - `env`：输出当前券商与数据源能力视图（来自本地配置与推断）。
  - `risk_check`：对下单请求做集中风控评估，仅返回审查结果，不实际下单。
"""

import json
import sys
import os
from datetime import datetime, timezone
from typing import Any, Dict

try:
    from broker_and_data_config import get_runtime_environment_view
except ImportError:
    get_runtime_environment_view = None  # type: ignore[assignment]

try:
    from risk_engine import evaluate_order_request
except ImportError:
    evaluate_order_request = None  # type: ignore[assignment]


def _load_stdin_json() -> Dict[str, Any]:
    """从 stdin 读取 JSON 负载，用于复杂参数传递。"""
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return {}
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "error": "invalid_json",
            "message": f"无法解析 stdin JSON: {exc}",
        }


def handle_status() -> Dict[str, Any]:
    """查询工具网关基础状态。"""
    return {
        "status": "ready",
        "message": "期权 / ETF 交易工具网关已就绪",
        "capabilities": {
            "actions": ["status", "signal", "env", "risk_check"],
            "version": "0.1.0",
        },
    }


def handle_signal() -> Dict[str, Any]:
    """
    查询交易信号占位实现。

    说明：
    - 阶段 1 中，策略信号由上层业务 Agent 根据数据与策略配置生成，
      此处仅保留兼容接口，返回空列表。
    """
    return {"signals": [], "message": "暂无交易信号（由上层策略引擎生成）"}


def handle_env() -> Dict[str, Any]:
    """
    输出当前券商与数据源能力视图。

    行为：
    - 如果存在 `broker_and_data_config.get_runtime_environment_view`，
      则调用其返回结构化环境描述；
    - 否则给出保守的默认视图，假定仅支持本地仿真 / 回测，不直接实盘。
    """
    if get_runtime_environment_view is None:
        return {
            "broker": {
                "name": "unknown",
                "mode": "paper_only",
                "supports_live_trading": False,
            },
            "data_feeds": {
                "etf_510300": {
                    "realtime": False,
                    "minute": False,
                    "tick": False,
                },
                "index_000300": {
                    "realtime": False,
                    "minute": False,
                    "tick": False,
                },
                "options_510300": {
                    "realtime": False,
                    "minute": False,
                    "iv": False,
                },
            },
            "assumptions": [
                "未检测到专用配置模块 broker_and_data_config，使用保守默认值。",
                "假定当前仅用于策略开发、回测与纸面仿真，不直接下真实订单。",
            ],
        }

    return get_runtime_environment_view()


def handle_risk_check(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    对下单请求执行集中风控评估。

    约定输入（stdin JSON）示例：
    {
      "order_request": {
        "strategy_id": "trend_following_510300",
        "instrument_type": "ETF",
        "symbol": "510300",
        "side": "BUY",
        "target_position_pct": 0.02,
        "price": 3.25,
        "time_in_force": "DAY",
        "meta": {
          "timeframe": "1d",
          "signal_confidence": 0.82
        }
      },
      "account_state": {
        "equity": 100000.0,
        "day_pnl_pct": -0.3,
        "positions": [
          {
            "symbol": "510300",
            "instrument_type": "ETF",
            "quantity": 10000,
            "avg_price": 3.1
          }
        ]
      }
    }
    """
    if evaluate_order_request is None:
        return {
            "approved": False,
            "reason": "risk_engine_not_available",
            "message": "未找到 risk_engine 模块，无法执行集中风控检查。",
        }

    if "error" in payload:
        # 来自 _load_stdin_json 的错误
        return payload

    order_request = payload.get("order_request") or {}
    account_state = payload.get("account_state") or {}
    global_risk_config = payload.get("risk_config") or {}

    result = evaluate_order_request(
        order_request=order_request,
        account_state=account_state,
        global_risk_config=global_risk_config,
    )
    _log_risk_check(payload=payload, result=result)
    return result


def _log_risk_check(payload: Dict[str, Any], result: Dict[str, Any]) -> None:
    """
    风控审计日志：将每次 risk_check 的输入摘要与输出结果落地为 JSONL。

    设计：
    - 默认写入 /home/xie/etf-options-ai-assistant/logs/risk_checks_YYYYMMDD.jsonl
    - 仅记录必要字段，避免把大对象/敏感信息写入日志
    """
    try:
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        log_dir = "/home/xie/etf-options-ai-assistant/logs"
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"risk_checks_{date_str}.jsonl")

        order = (payload.get("order_request") or {}) if isinstance(payload, dict) else {}
        account = (payload.get("account_state") or {}) if isinstance(payload, dict) else {}

        record = {
            "ts": now.isoformat(),
            "order_request": {
                "strategy_id": order.get("strategy_id"),
                "instrument_type": order.get("instrument_type"),
                "symbol": order.get("symbol"),
                "side": order.get("side"),
                "target_position_pct": order.get("target_position_pct"),
                "price": order.get("price"),
            },
            "account_state": {
                "equity": account.get("equity"),
                "day_pnl_pct": account.get("day_pnl_pct"),
                "positions_count": len(account.get("positions") or []),
            },
            "result": {
                "approved": result.get("approved"),
                "reasons": result.get("reasons") or result.get("reason"),
                "estimated_slippage_pct": result.get("estimated_slippage_pct"),
                "estimated_fee_pct": result.get("estimated_fee_pct"),
                "total_cost_pct": result.get("total_cost_pct"),
            },
        }

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # 日志失败不应影响交易风控返回
        return


def main() -> None:
    """处理期权 / ETF 交易命令。"""
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "error": "缺少参数",
                    "usage": (
                        "option_trader.py <action> [args...], "
                        "actions: status | signal | env | risk_check"
                    ),
                }
            )
        )
        sys.exit(1)

    action = sys.argv[1]

    if action == "status":
        result = handle_status()
    elif action == "signal":
        result = handle_signal()
    elif action == "env":
        result = handle_env()
    elif action == "risk_check":
        stdin_payload = _load_stdin_json()
        result = handle_risk_check(stdin_payload)
    else:
        result = {
            "error": f"未知操作: {action}",
            "supported_actions": ["status", "signal", "env", "risk_check"],
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
