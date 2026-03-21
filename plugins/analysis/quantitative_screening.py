"""
quantitative-screening 技能底层实现：

- 基于已实现的日线行情工具（ETF / 股票）
- 计算简单多因子：动量、波动率、流动性（成交额）
- 按权重合成总分，用于候选标的排序

接口参考《涨停回马枪技能分析.md》：
- 输入：candidates, lookback_days, universe
- 输出：scores（含各因子）、ranked_list、top_picks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from data_collection.etf.fetch_historical import (  # type: ignore[import]
    fetch_single_etf_historical,
)
from data_collection.stock.fetch_historical import (  # type: ignore[import]
    fetch_single_stock_historical,
)
from data_collection.financials import tool_fetch_stock_financials  # type: ignore[import]

logger = logging.getLogger(__name__)


def _normalize_candidates(candidates: Any) -> List[str]:
    if isinstance(candidates, str):
        raw = [s.strip() for s in candidates.replace(";", ",").split(",") if s.strip()]
    else:
        raw = [str(s).strip() for s in (candidates or []) if str(s).strip()]
    seen = set()
    result: List[str] = []
    for s in raw:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def _is_etf_code(symbol: str) -> bool:
    """非常粗略地识别 ETF 代码，用于自动选择数据源。"""
    s = symbol.strip()
    if len(s) != 6 or not s.isdigit():
        return False
    return s.startswith(("5", "1"))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


@dataclass
class FactorValues:
    momentum: float
    volatility: float
    liquidity: float
    valuation: float = 0.0  # 来自财务数据：PE_TTM（越低越好），缺省 999 表示缺失


def _compute_factors_from_df(df: pd.DataFrame) -> Optional[FactorValues]:
    """
    假设 df 至少包含：
    - '收盘'：收盘价
    - '成交额'：成交额
    - '涨跌幅'：日涨跌幅（百分比）
    """
    if df is None or df.empty:
        return None

    closes = df.get("收盘")
    amounts = df.get("成交额")
    pct_chg = df.get("涨跌幅")

    if closes is None or closes.isna().all():
        return None

    closes = closes.astype(float)

    # 动量：区间涨幅（最后一个收盘 / 第一个收盘 - 1）
    try:
        momentum = (closes.iloc[-1] / closes.iloc[0]) - 1.0
    except Exception:
        momentum = 0.0

    # 波动率：日收益率标准差
    if pct_chg is not None and not pct_chg.isna().all():
        returns = pct_chg.astype(float) / 100.0
    else:
        returns = closes.pct_change().fillna(0.0)

    volatility = float(np.std(returns.values)) if len(returns) > 1 else 0.0

    # 流动性：平均成交额
    if amounts is not None and not amounts.isna().all():
        liquidity = float(amounts.astype(float).mean())
    else:
        liquidity = 0.0

    return FactorValues(
        momentum=float(momentum),
        volatility=volatility,
        liquidity=liquidity,
        valuation=999.0,  # 占位，后续由 _merge_valuation_from_financials 覆盖
    )


def _fetch_history_for_symbol(
    symbol: str,
    lookback_days: int,
    universe: Optional[str] = None,
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    根据 symbol + universe 自动选择 ETF / 股票历史数据接口。
    """
    # 这里复用已实现的 fetch_single_*_historical，保持字段统一逻辑。
    if (universe or "").lower() == "etf" or _is_etf_code(symbol):
        df, source = fetch_single_etf_historical(
            etf_code=symbol,
            period="daily",
            start_date=None,
            end_date=None,
        )
    else:
        df, source = fetch_single_stock_historical(
            stock_code=symbol,
            period="daily",
            start_date=None,
            end_date=None,
        )

    if df is None or df.empty:
        return None, source

    # 仅保留最近 lookback_days 行（已在 fetch_* 内部做过时间过滤，这里再保险）
    df = df.sort_values("日期", ascending=True).tail(lookback_days).copy()
    return df, source


def _fetch_valuation_map(symbols: List[str], universe: Optional[str] = None) -> Dict[str, float]:
    """
    批量拉取财务数据，返回 symbol -> valuation_raw。
    valuation_raw 使用 PE_TTM（越低越便宜），缺失或非股票标的用 999.0。
    仅对股票标的请求财务接口，ETF 不请求。
    """
    stock_symbols = [s for s in symbols if not _is_etf_code(s)]
    if (universe or "").lower() == "etf" or not stock_symbols:
        return {s: 999.0 for s in symbols}
    try:
        resp = tool_fetch_stock_financials(symbols=stock_symbols)
        if resp.get("status") != "success":
            return {s: 999.0 for s in symbols}
        out: Dict[str, float] = {}
        for rec in resp.get("financials") or []:
            sym = rec.get("symbol", "")
            pe = rec.get("pe_ttm")
            if pe is not None and isinstance(pe, (int, float)) and pe > 0:
                out[sym] = float(pe)
            else:
                out[sym] = 999.0
        for s in symbols:
            if s not in out:
                out[s] = 999.0
        return out
    except Exception as e:  # noqa: BLE001
        logger.debug("拉取财务估值失败: %s", e)
        return {s: 999.0 for s in symbols}


def _normalize_scores(values: List[float], higher_is_better: bool = True) -> List[float]:
    """
    将一组原始因子值按排名归一到 [0, 1] 区间。
    higher_is_better=True 表示数值越大越好。
    """
    n = len(values)
    if n == 0:
        return []
    # 特殊情况：所有值相等，直接返回 0.5
    if len(set(values)) == 1:
        return [0.5] * n

    # 构造 (index, value) 并排序
    idx_vals = list(enumerate(values))
    idx_vals.sort(key=lambda x: x[1], reverse=higher_is_better)
    scores = [0.0] * n
    for rank, (idx, _) in enumerate(idx_vals):
        if n == 1:
            s = 1.0
        else:
            s = rank / (n - 1)
        # 排名 0 为最差，1 为最好
        scores[idx] = s
    return scores


def tool_quantitative_screening(
    candidates: Any,
    lookback_days: int = 20,
    universe: Optional[str] = None,
    top_k: int = 10,
) -> Dict[str, Any]:
    """
    quantitative-screening 技能入口。

    Args:
        candidates: 候选标的列表，支持 ["510300", "510500"] 或 "510300,510500"。
        lookback_days: 回溯天数（使用最近 N 个交易日的日线数据），默认 20。
        universe: 可选，"etf" / "stock" / None；None 时自动根据代码判断。
        top_k: 返回前多少名作为 top_picks，默认 10。
    """
    symbols = _normalize_candidates(candidates)
    if not symbols:
        return {"status": "error", "error": "candidates 不能为空", "scores": []}

    factor_map: Dict[str, FactorValues] = {}
    failed: Dict[str, str] = {}

    for s in symbols:
        try:
            df, source = _fetch_history_for_symbol(s, lookback_days=lookback_days, universe=universe)
            if df is None or df.empty:
                failed[s] = f"历史行情为空（source={source})"
                continue
            fv = _compute_factors_from_df(df)
            if fv is None:
                failed[s] = "无法从行情中计算因子"
                continue
            factor_map[s] = fv
        except Exception as e:  # noqa: BLE001
            logger.error("计算 %s 因子失败: %s", s, e)
            failed[s] = str(e)

    # 接入财务估值：对股票标的拉取 PE，写入 valuation（越低越好）
    valuation_map = _fetch_valuation_map(list(factor_map.keys()), universe=universe)
    for s, fv in factor_map.items():
        fv.valuation = valuation_map.get(s, 999.0)

    if not factor_map:
        return {
            "status": "error",
            "error": "所有候选标的均无法计算因子",
            "scores": [],
            "failed": failed,
        }

    symbols_ok = list(factor_map.keys())
    momentums = [factor_map[s].momentum for s in symbols_ok]
    volatilities = [factor_map[s].volatility for s in symbols_ok]
    liquidities = [factor_map[s].liquidity for s in symbols_ok]
    valuations = [factor_map[s].valuation for s in symbols_ok]

    # 归一化得分：动量/流动性越大越好，波动率越小越好（先按大为好打分，再取 1-score）
    mom_scores = _normalize_scores(momentums, higher_is_better=True)
    liq_scores = _normalize_scores(liquidities, higher_is_better=True)
    vol_scores_raw = _normalize_scores(volatilities, higher_is_better=False)
    val_scores = _normalize_scores(valuations, higher_is_better=False)

    weights = {
        "momentum": 0.4,
        "volatility": 0.2,
        "liquidity": 0.3,
        "valuation": 0.1,
    }

    score_items: List[Dict[str, Any]] = []
    for idx, sym in enumerate(symbols_ok):
        total = (
            mom_scores[idx] * weights["momentum"]
            + vol_scores_raw[idx] * weights["volatility"]
            + liq_scores[idx] * weights["liquidity"]
            + val_scores[idx] * weights["valuation"]
        )
        score_items.append(
            {
                "symbol": sym,
                "total_score": round(total * 100, 2),
                "factors": {
                    "momentum": {
                        "raw": round(momentums[idx] * 100, 2),
                        "score": round(mom_scores[idx], 3),
                    },
                    "volatility": {
                        "raw": round(volatilities[idx] * 100, 2),
                        "score": round(vol_scores_raw[idx], 3),
                    },
                    "liquidity": {
                        "raw": round(liquidities[idx], 2),
                        "score": round(liq_scores[idx], 3),
                    },
                    "valuation": {
                        "raw": round(valuations[idx], 2),
                        "score": round(val_scores[idx], 3),
                    },
                },
            }
        )

    # 按总分排序
    score_items.sort(key=lambda x: x["total_score"], reverse=True)
    ranked_list = [item["symbol"] for item in score_items]
    top_k = max(1, min(top_k, len(score_items)))
    top_picks = score_items[:top_k]

    return {
        "status": "success",
        "lookback_days": lookback_days,
        "universe": universe,
        "scores": score_items,
        "ranked_list": ranked_list,
        "top_picks": top_picks,
        "failed": failed,
    }


if __name__ == "__main__":
    import json

    demo_result = tool_quantitative_screening(["510300", "510500", "159915"], lookback_days=30, universe="etf")
    print(json.dumps(demo_result, ensure_ascii=False, indent=2))

