"""
日频全日波动区间预测（全能版）。

与 ``tool_predict_volatility``（日内剩余时段）及 ``tool_predict_intraday_range``（轻量分钟区间）区分：
本工具以 **完整交易日** 为 horizon，基于日 K 多窗口 HV + ATR 融合；交易时段可对区间做有界纠偏。
仅支持指数 / ETF / A 股，不支持单期权合约。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.underlying_resolver import resolve_volatility_underlying


def _format_daily_range_markdown(d: Dict[str, Any]) -> str:
    sym = d.get("symbol", "N/A")
    at = d.get("asset_type", "")
    title = "## 日频波动区间预测（全日）\n\n"
    body = "**标的**\n"
    body += f"- 代码: `{sym}`\n"
    body += f"- 类型: {at}\n\n"
    body += "### 关键指标\n\n"
    body += "| 指标 | 数值 |\n|------|------|\n"
    cp = d.get("current_price")
    if cp is not None:
        body += f"| 锚定/现价 | {float(cp):.4f} |\n"
    lo, up = d.get("lower"), d.get("upper")
    if lo is not None and up is not None:
        body += f"| 预估全日区间 | {float(lo):.4f} - {float(up):.4f} |\n"
    rp = d.get("range_pct")
    if rp is not None:
        body += f"| 全日带宽 (±%) | {float(rp):.2f}% |\n"
    cf = d.get("confidence")
    if cf is not None:
        body += f"| 置信度 | {float(cf):.2f} |\n"
    wins = d.get("windows_used") or []
    win_s = "/".join(str(x) for x in wins) if wins else "5/22/63"
    body += f"| 计算路径 | 日频多周期融合 ({win_s}) + ATR(14) |\n"
    m = d.get("method")
    if m:
        body += f"| 方法说明 | {m} |\n"
    hz = d.get("horizon")
    ts_sess = d.get("target_session")
    if hz or ts_sess:
        body += f"| Horizon | {hz or '1d'} / session={ts_sess or 'current'} |\n"
    body += "\n"
    if d.get("intraday_adjusted"):
        note = d.get("intraday_adjust_note") or ""
        body += f"**盘中纠偏**：已根据最近分钟行情做有界调整。{note}\n\n"
    else:
        body += "**盘中纠偏**：未触发（非连续竞价或分钟数据不可用）。\n\n"
    body += (
        "> 口径说明：本结果为 **全日** 运行区间估计；"
        "``tool_predict_volatility`` 侧重 **日内剩余交易时间**，请勿混用。\n"
    )
    return title + body


def tool_predict_daily_volatility_range(
    underlying: str = "510300",
    symbol: Optional[str] = None,
    asset_type: Optional[str] = None,
    **_: Any,
) -> Dict[str, Any]:
    """
    预测指数/ETF/A 股 **完整交易日** 的价格运行区间。

    Args:
        underlying: 标的代码或简称；歧义时用 ``指数:`` / ``ETF:`` / ``股票:`` 前缀
        symbol: 兼容别名，等价于 underlying
        asset_type: 可选 index / etf / stock
    """
    raw_in = str(symbol or underlying or "510300").strip()
    hint = str(asset_type).strip().lower() if asset_type else None
    if hint == "":
        hint = None

    resolved = resolve_volatility_underlying(raw_in, hint)
    if not resolved.ok:
        return {
            "success": False,
            "message": resolved.error or "标的解析失败",
            "data": {"candidates": resolved.candidates} if resolved.candidates else None,
            "formatted_output": f"❌ {resolved.error or '标的解析失败'}",
        }

    try:
        from src.config_loader import load_system_config
        from src.daily_volatility_range import compute_daily_volatility_range

        cfg = load_system_config(use_cache=True)
        out = compute_daily_volatility_range(resolved.code, resolved.asset_type, cfg)
    except Exception as e:
        return {
            "success": False,
            "message": f"日频区间计算异常: {e}",
            "data": {"error_code": "DAILY_RANGE_RUNTIME_ERROR"},
            "formatted_output": f"❌ 日频区间计算异常: {e}",
        }

    if not out.get("success"):
        msg = out.get("message", "失败")
        return {
            "success": False,
            "message": msg,
            "data": out.get("data"),
            "formatted_output": f"❌ {msg}",
        }

    data = out.get("data") or {}
    return {
        "success": True,
        "message": out.get("message", "日频全日波动区间计算完成"),
        "data": data,
        "formatted_output": _format_daily_range_markdown(data),
        "source": "daily_volatility_range",
    }
