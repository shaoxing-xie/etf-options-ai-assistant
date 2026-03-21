"""
集中风控引擎协议定义与基础实现。

职责：
- 接收标准化的下单请求（order_request）与账户状态（account_state）；
- 根据全局风控配置与策略局部配置，给出是否允许执行的结论；
- 输出结构化结果，供上层 Agent 与 `option_trader.py` 使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class OrderRequest:
    strategy_id: str
    instrument_type: str  # ETF / INDEX / OPTION / MIXED
    symbol: str
    side: str  # BUY / SELL
    target_position_pct: float  # 目标持仓占权益比例，例如 0.02 表示 2%
    price: Optional[float] = None
    time_in_force: str = "DAY"
    meta: Dict[str, Any] = None  # type: ignore[assignment]


@dataclass
class Position:
    symbol: str
    instrument_type: str
    quantity: float
    avg_price: float


@dataclass
class AccountState:
    equity: float
    day_pnl_pct: float
    positions: List[Position]


def _estimate_costs(
    order: OrderRequest,
    global_risk_config: Dict[str, Any],
) -> Dict[str, float]:
    """
    预估交易成本（用于信号阶段解释与风控审计）。

    说明：
    - 先提供保守默认值；后续可接入真实费率/滑点模型；
    - global_risk_config 可覆盖默认值，例如：
      - slippage_pct_etf / slippage_pct_option / fee_pct_etf / fee_pct_option
    """
    instrument = order.instrument_type

    # 默认（保守）滑点与费用估计
    slippage_defaults = {
        "ETF": 0.0005,    # 0.05%
        "INDEX": 0.0000,  # 指数不直接交易（若用于期货/衍生品，后续扩展）
        "OPTION": 0.0015, # 0.15%
        "MIXED": 0.0008,
    }
    fee_defaults = {
        "ETF": 0.0002,    # 0.02%（佣金等粗估，不含申赎）
        "INDEX": 0.0000,
        "OPTION": 0.0006, # 0.06%（含手续费粗估）
        "MIXED": 0.0003,
    }

    slippage = float(
        global_risk_config.get(f"slippage_pct_{instrument.lower()}", slippage_defaults.get(instrument, 0.0005))
    )
    fee = float(
        global_risk_config.get(f"fee_pct_{instrument.lower()}", fee_defaults.get(instrument, 0.0002))
    )

    total = max(slippage + fee, 0.0)
    return {
        "estimated_slippage_pct": max(slippage, 0.0),
        "estimated_fee_pct": max(fee, 0.0),
        "total_cost_pct": total,
    }


def _parse_order_request(raw: Dict[str, Any]) -> Tuple[Optional[OrderRequest], List[str]]:
    errors: List[str] = []

    try:
        strategy_id = str(raw.get("strategy_id") or "")
        if not strategy_id:
            errors.append("缺少 strategy_id")

        instrument_type = str(raw.get("instrument_type") or "")
        if instrument_type not in {"ETF", "INDEX", "OPTION", "MIXED"}:
            errors.append("instrument_type 必须为 ETF / INDEX / OPTION / MIXED")

        symbol = str(raw.get("symbol") or "")
        if not symbol:
            errors.append("缺少 symbol")

        side = str(raw.get("side") or "")
        if side not in {"BUY", "SELL"}:
            errors.append("side 必须为 BUY / SELL")

        target_position_pct = float(raw.get("target_position_pct", 0.0))
        if target_position_pct <= 0:
            errors.append("target_position_pct 必须为正数")

        price_raw = raw.get("price")
        price = float(price_raw) if price_raw is not None else None

        time_in_force = str(raw.get("time_in_force") or "DAY")
        meta = raw.get("meta") or {}

        if errors:
            return None, errors

        return (
            OrderRequest(
                strategy_id=strategy_id,
                instrument_type=instrument_type,
                symbol=symbol,
                side=side,
                target_position_pct=target_position_pct,
                price=price,
                time_in_force=time_in_force,
                meta=meta,
            ),
            [],
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"解析 order_request 异常: {exc}")
        return None, errors


def _parse_account_state(raw: Dict[str, Any]) -> Tuple[Optional[AccountState], List[str]]:
    errors: List[str] = []
    try:
        equity = float(raw.get("equity", 0.0))
        if equity <= 0:
            errors.append("equity 必须为正数")

        day_pnl_pct = float(raw.get("day_pnl_pct", 0.0))

        positions_raw = raw.get("positions") or []
        positions: List[Position] = []
        for p in positions_raw:
            try:
                positions.append(
                    Position(
                        symbol=str(p.get("symbol") or ""),
                        instrument_type=str(p.get("instrument_type") or "ETF"),
                        quantity=float(p.get("quantity", 0.0)),
                        avg_price=float(p.get("avg_price", 0.0)),
                    )
                )
            except Exception:
                # 忽略单个格式错误的持仓，但记录错误
                errors.append(f"无效持仓记录: {p}")

        if errors:
            return None, errors

        return AccountState(equity=equity, day_pnl_pct=day_pnl_pct, positions=positions), []
    except Exception as exc:  # noqa: BLE001
        errors.append(f"解析 account_state 异常: {exc}")
        return None, errors


def _evaluate_basic_limits(
    order: OrderRequest,
    account: AccountState,
    global_risk_config: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    ok = True

    # 无默认硬锁定：仅当配置中显式设置 per_trade_max_pct 时才限制单笔仓位
    per_trade_max_pct_raw = global_risk_config.get("per_trade_max_pct")
    hard_limit_pct = float(per_trade_max_pct_raw) if per_trade_max_pct_raw is not None else 1.0
    options_leg_max_pct = float(global_risk_config.get("per_option_leg_max_pct", 0.015))
    day_max_loss_pct = float(global_risk_config.get("day_max_loss_pct", -0.015))

    if hard_limit_pct < 1.0 and order.target_position_pct > hard_limit_pct:
        ok = False
        reasons.append(
            f"目标仓位 {order.target_position_pct:.4f} 超过单笔上限 {hard_limit_pct:.4f}"
        )

    if order.instrument_type == "OPTION" and order.target_position_pct > options_leg_max_pct:
        ok = False
        reasons.append(
            f"期权腿目标仓位 {order.target_position_pct:.4f} 超过单腿上限 {options_leg_max_pct:.4f}"
        )

    if account.day_pnl_pct <= day_max_loss_pct:
        ok = False
        reasons.append(
            f"当日浮亏 {account.day_pnl_pct:.4f} 已低于日最大亏损 {day_max_loss_pct:.4f}，"
            "触发全局熔断，禁止新增风险敞口"
        )

    return ok, reasons


def evaluate_order_request(
    order_request: Dict[str, Any],
    account_state: Dict[str, Any],
    global_risk_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    对下单请求执行集中风控检查。

    返回：
    {
      "approved": bool,
      "reasons": [str, ...],
      "suggestions": [str, ...],
      "normalized_order_request": {...}
    }
    """
    global_risk_config = global_risk_config or {}

    order, order_errors = _parse_order_request(order_request)
    account, account_errors = _parse_account_state(account_state)

    reasons: List[str] = []
    reasons.extend(order_errors)
    reasons.extend(account_errors)

    if order is None or account is None:
        return {
            "approved": False,
            "reasons": reasons or ["无效的 order_request 或 account_state"],
            "suggestions": [
                "检查是否包含 strategy_id / symbol / side / target_position_pct / equity 等字段"
            ],
            "normalized_order_request": {},
        }

    ok_basic, basic_reasons = _evaluate_basic_limits(
        order=order,
        account=account,
        global_risk_config=global_risk_config,
    )
    reasons.extend(basic_reasons)

    approved = ok_basic and not reasons
    costs = _estimate_costs(order=order, global_risk_config=global_risk_config)

    return {
        "approved": approved,
        "reasons": reasons,
        "suggestions": [],
        **costs,
        "normalized_order_request": {
            "strategy_id": order.strategy_id,
            "instrument_type": order.instrument_type,
            "symbol": order.symbol,
            "side": order.side,
            "target_position_pct": order.target_position_pct,
            "price": order.price,
            "time_in_force": order.time_in_force,
            "meta": order.meta or {},
        },
    }


__all__ = ["evaluate_order_request"]

