"""
机构向风控占位：合规规则展示、止损线配置、线性压力情景、归因占位。

与真实账户/行业数据对接前，输出以配置与说明为主，避免误当作实盘指令。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Optional[str], default_name: str) -> Dict[str, Any]:
    p = Path(path).expanduser() if path else _root() / "config" / default_name
    if not p.is_file():
        ex = _root() / "config" / default_name.replace(".yaml", ".example.yaml")
        p = ex if ex.is_file() else p
    if not p.is_file():
        return {}
    if yaml is None:
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def tool_compliance_rules_check(rules_path: Optional[str] = None) -> Dict[str, Any]:
    """读取合规规则 YAML，返回规则内容与占位状态（无持仓明细时不判违规）。"""
    data = _load_yaml(rules_path, "compliance_rules.yaml")
    return {
        "success": True,
        "message": "compliance rules loaded",
        "data": {
            "rules": data,
            "violations": [],
            "status": "rules_only",
            "note": "未接入持仓与行业分布时仅展示规则，不输出违规结论。",
        },
    }


def tool_stop_loss_lines_check(
    lines_path: Optional[str] = None,
) -> Dict[str, Any]:
    """读取止损线配置，计算止损价；现价需由上层用行情工具另行填入。"""
    data = _load_yaml(lines_path, "stop_loss_lines.yaml")
    pos = data.get("positions") or []
    rows: List[Dict[str, Any]] = []
    for p in pos:
        sym = p.get("symbol")
        cost = float(p.get("cost") or 0)
        pct = float(p.get("stop_loss_pct") or 0)
        if not sym or cost <= 0:
            continue
        stop_px = round(cost * (1.0 - pct / 100.0), 4)
        rows.append(
            {
                "symbol": sym,
                "cost": cost,
                "stop_loss_pct": pct,
                "stop_price": stop_px,
                "note": "现价请用 tool_fetch_etf_realtime 比对后再填 triggered",
            }
        )
    return {
        "success": True,
        "message": "stop loss lines",
        "data": {"positions": rows},
    }


def tool_stress_test_linear_scenarios(
    index_shocks_pct: Optional[List[float]] = None,
    portfolio_config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    简单线性冲击：假设组合与宽基同步变动，估算组合 NAV 近似变动（%）。
    shocks 默认 [-5, -10, -20] 表示指数跌 5%/10%/20% 时组合同向近似。
    """
    shocks = index_shocks_pct if index_shocks_pct is not None else [-5.0, -10.0, -20.0]
    cfg_path = portfolio_config_path
    cfg_file = Path(cfg_path).expanduser() if cfg_path else _root() / "config" / "portfolio_weights.json"
    if not cfg_file.is_file():
        cfg_file = _root() / "config" / "portfolio_weights.example.json"
    weights: Dict[str, float] = {"510300": 0.34, "510500": 0.33, "159915": 0.33}
    if cfg_file.is_file():
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            weights = {str(k): float(v) for k, v in (cfg.get("weights") or weights).items()}
        except Exception:
            pass
    wsum = sum(weights.values()) or 1.0
    weights = {k: v / wsum for k, v in weights.items()}
    scenarios = []
    for shock in shocks:
        # 近似：组合日收益 ~= 指数冲击 * 1（beta=1）；展示为百分比
        est = shock * 1.0
        scenarios.append(
            {
                "scenario": f"同步冲击 {shock}%",
                "estimated_portfolio_move_pct": round(est, 4),
                "weights_used": weights,
            }
        )
    return {
        "success": True,
        "message": "linear stress (beta=1 placeholder)",
        "data": {"scenarios": scenarios, "disclaimer": "线性近似，未含期权凸性与相关性。"},
    }


def tool_risk_attribution_stub() -> Dict[str, Any]:
    """占位：因子风险归因需可靠收益与因子暴露，当前返回说明与示例结构。"""
    return {
        "success": True,
        "message": "stub",
        "data": {
            "market_factor_pct": None,
            "industry_factor_pct": None,
            "idiosyncratic_pct": None,
            "note": "接入多因子收益与持仓暴露后再计算；当前不输出数值以免误导。",
        },
    }
