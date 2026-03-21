from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EtfScore:
    symbol: str
    name: Optional[str]
    momentum_20d: float
    momentum_60d: float
    vol_20d: float
    max_drawdown_60d: float
    score: float


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _compute_metrics(df, symbol: str) -> Tuple[float, float, float, float]:
    """
    Compute simple rotation metrics from daily close series:
    - momentum_20d, momentum_60d
    - vol_20d (annualized, sqrt(252))
    - max_drawdown_60d
    """
    import numpy as np
    import pandas as pd

    if df is None or len(df) < 70:
        raise ValueError(f"{symbol}: insufficient daily data (need >= 70 rows)")

    # Normalize column names
    cols = {c.lower(): c for c in df.columns}
    close_col = cols.get("close") or cols.get("收盘") or cols.get("收盘价")
    if not close_col:
        raise ValueError(f"{symbol}: close column not found")

    s = pd.to_numeric(df[close_col], errors="coerce").dropna()
    if len(s) < 70:
        raise ValueError(f"{symbol}: close series insufficient after cleaning")

    # Momentum
    m20 = (s.iloc[-1] / s.iloc[-21]) - 1.0
    m60 = (s.iloc[-1] / s.iloc[-61]) - 1.0

    # Volatility (20d)
    rets = s.pct_change().dropna()
    vol20 = float(rets.iloc[-20:].std(ddof=0) * np.sqrt(252))

    # Max drawdown (60d)
    window = s.iloc[-60:]
    roll_max = window.cummax()
    dd = (window / roll_max) - 1.0
    mdd60 = float(dd.min())

    return float(m20), float(m60), float(vol20), float(mdd60)


def tool_etf_rotation_research(
    *,
    etf_pool: str = "510300,510500,159915,512100,512880,512690",
    lookback_days: int = 120,
    top_k: int = 3,
    mode: str = "prod",
) -> Dict[str, Any]:
    """
    OpenClaw 工具：ETF 轮动研究（研究级）

    - 从本地缓存读取 ETF 日线数据（逐个 symbol 读取）
    - 计算动量/波动/回撤等基础指标
    - 输出排名与 Markdown 研究摘要（兼容研究模式一的结构）

    Args:
        etf_pool: 逗号分隔 ETF 代码列表
        lookback_days: 回看天数（用于读取数据；实际指标窗口固定为 20/60 日）
        top_k: 输出前 K 名
        mode: prod|test（test 可用于离线冒烟）
    """
    from datetime import datetime

    import pandas as pd

    from merged.read_market_data import tool_read_market_data
    try:
        from analysis.market_regime import tool_detect_market_regime
    except Exception:
        tool_detect_market_regime = None  # type: ignore[assignment]

    symbols = [s.strip() for s in (etf_pool or "").split(",") if s.strip()]
    if not symbols:
        return {"success": False, "message": "etf_pool 不能为空", "data": None}

    scores: List[EtfScore] = []
    errors: List[str] = []

    # Read each ETF daily cache and compute metrics
    for sym in symbols:
        out = tool_read_market_data(data_type="etf_daily", symbol=sym)
        if not out.get("success"):
            errors.append(f"{sym}: read failed: {out.get('message')}")
            continue
        data = (out.get("data") or {}).get("data") or (out.get("data") or {}).get("rows") or out.get("data")
        # The cache tool returns different shapes across sources; best-effort.
        try:
            df = pd.DataFrame(data)
            if lookback_days and len(df) > int(lookback_days):
                df = df.iloc[-int(lookback_days) :]
            m20, m60, vol20, mdd60 = _compute_metrics(df, sym)

            # Simple score: reward momentum, penalize volatility and drawdown (drawdown is negative)
            score = 0.45 * m20 + 0.35 * m60 - 0.15 * vol20 + 0.05 * mdd60
            scores.append(
                EtfScore(
                    symbol=sym,
                    name=None,
                    momentum_20d=m20,
                    momentum_60d=m60,
                    vol_20d=vol20,
                    max_drawdown_60d=mdd60,
                    score=float(score),
                )
            )
        except Exception as e:
            errors.append(f"{sym}: compute failed: {e}")

    if not scores:
        return {"success": False, "message": "无法生成轮动评分（无可用ETF数据）", "data": {"errors": errors}}

    scores_sorted = sorted(scores, key=lambda x: x.score, reverse=True)
    top_k = max(1, min(int(top_k), len(scores_sorted)))
    top = scores_sorted[:top_k]

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fmt_pct(x: float) -> str:
        return f"{x*100:.2f}%"

    # 尝试获取当前 Market Regime（研究补充信息）
    regime_info: Dict[str, Any] = {}
    regime_line = ""
    if tool_detect_market_regime is not None:
        try:
            r_out = tool_detect_market_regime(symbol="510300", mode="prod")
            if isinstance(r_out, dict) and r_out.get("success"):
                data = r_out.get("data") or {}
                regime_info = data
                regime = data.get("regime")
                conf = data.get("confidence")
                if regime:
                    regime_line = f"- 当前 Market Regime（基于 510300）: **{regime}**（置信度约 {conf:.2f}，用于理解轮动评分所处的市场环境）。"
        except Exception:
            regime_info = {}
            regime_line = ""

    lines = []
    lines.append("**📊 核心结论**：ETF 轮动研究结果已生成（研究级，不构成交易指令）。")
    lines.append("")
    lines.append("**📉 可执行建议 / 参数方案**：")
    lines.append(f"- 今日轮动候选（Top {top_k}）：{', '.join([t.symbol for t in top])}")
    lines.append("- 建议用途：作为盘前/盘后研究参考，用于判断“相对强弱与风险水平”，不直接替代工作流A的信号与风控结论。")
    lines.append("")
    lines.append("## 📈 市场状态（Market Regime）")
    if regime_line:
        lines.append(regime_line)
    else:
        lines.append("- 当前 Regime 暂未能可靠识别，本次轮动结果仅基于价格与波动因子解读。")
    lines.append("")
    lines.append("## ⚠️ 风险提示")
    lines.append("- 轮动评分基于缓存日线的简单因子（动量/波动/回撤），对突发事件与流动性冲击敏感；极端行情下可能失效。")
    if errors:
        lines.append(f"- 数据缺失/计算失败：{len(errors)} 条（详见 data.errors）。")
    lines.append("")
    lines.append("## 📂 数据与来源")
    lines.append("- 行情数据：本地 ETF 日线缓存（tool_read_market_data → etf_daily），回看窗口约 120 日。")
    lines.append("- 因子口径：20/60 日动量、20 日年化波动率、60 日最大回撤（近似）。")
    lines.append("- 评分公式：0.45 * 20日动量 + 0.35 * 60日动量 - 0.15 * 20日波动 + 0.05 * 60日最大回撤。")
    lines.append("")
    lines.append("## 🧭 下一步行动建议")
    lines.append("- 明日开盘前：再次运行轮动扫描，观察排名是否稳定，以确认当前轮动格局是否持续。")
    lines.append("- 如对排名靠前的 ETF 感兴趣，建议进一步结合分钟级数据、资金流向与板块热度做二次验证。")
    lines.append("")
    lines.append("## 🔍 高密度要点总结")
    lines.append(f"- 时间：{ts}")
    lines.append(f"- Regime：{regime_info.get('regime') or 'unknown'}")
    lines.append(f"- Top{top_k}：{', '.join([t.symbol for t in top])}")
    lines.append("- 用途：研究级 ETF 关注列表，不直接构成建仓指令")
    lines.append("- 评分口径：0.45*m20 + 0.35*m60 - 0.15*vol20 + 0.05*mdd60")

    table = ["| ETF | 20日动量 | 60日动量 | 20日波动(年化) | 60日最大回撤 | Score |", "|---|---:|---:|---:|---:|---:|"]
    for s in scores_sorted[: min(len(scores_sorted), 10)]:
        table.append(
            f"| {s.symbol} | {fmt_pct(s.momentum_20d)} | {fmt_pct(s.momentum_60d)} | {fmt_pct(s.vol_20d)} | {fmt_pct(s.max_drawdown_60d)} | {s.score:.4f} |"
        )

    llm_summary = "\n".join(lines) + "\n\n" + "\n".join(table)

    return {
        "success": True,
        "message": "etf_rotation_research ok",
        "data": {
            "timestamp": ts,
            "etf_pool": symbols,
            "top_k": top_k,
            "ranked": [
                {
                    "symbol": s.symbol,
                    "score": s.score,
                    "momentum_20d": s.momentum_20d,
                    "momentum_60d": s.momentum_60d,
                    "vol_20d": s.vol_20d,
                    "max_drawdown_60d": s.max_drawdown_60d,
                }
                for s in scores_sorted
            ],
            "regime": regime_info,
            "errors": errors,
            "report_data": {
                "report_type": "etf_rotation_research",
                "llm_summary": llm_summary,
                "raw": {
                    "ranked": [s.__dict__ for s in scores_sorted],
                    "errors": errors,
                },
            },
        },
    }

