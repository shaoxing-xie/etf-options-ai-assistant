"""
财务数据采集模块（A 股 PE/PB/ROE/股息率等）

- 封装 AkShare 东方财富财务主要指标接口，供 quantitative_screening 的 valuation 因子使用
- 入参：symbols（支持逗号分隔或列表）, 可选 lookback_report_count
- 出参：financials: [{ symbol, pe_ttm, pb, roe, dividend_yield, report_date, success, error? }]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except Exception:  # noqa: BLE001
    AKSHARE_AVAILABLE = False


def _normalize_symbols(symbols: Any) -> List[str]:
    if isinstance(symbols, str):
        raw = [s.strip() for s in symbols.replace(";", ",").split(",") if s.strip()]
    else:
        raw = [str(s).strip() for s in (symbols or []) if str(s).strip()]
    seen = set()
    result: List[str] = []
    for s in raw:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def _to_em_symbol(code: str) -> str:
    """将 6 位代码转为东方财富 SECUCODE 格式，如 600000.SH, 000001.SZ"""
    clean = code.strip()
    if clean.upper().endswith((".SH", ".SZ", ".BJ")):
        return clean.upper()
    # 去掉前缀 sh/sz
    if clean.lower().startswith("sh"):
        clean = clean[2:].strip()
    elif clean.lower().startswith("sz"):
        clean = clean[2:].strip()
    if len(clean) != 6 or not clean.isdigit():
        return code
    if clean.startswith(("6", "5", "9")):
        return f"{clean}.SH"
    if clean.startswith(("0", "3", "2")):
        return f"{clean}.SZ"
    if clean.startswith(("4", "8")):
        return f"{clean}.BJ"
    return f"{clean}.SH"


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    if v is None:
        return default
    try:
        f = float(v)
        return f if (f == f and abs(f) < 1e15) else default  # noqa: PLR2004
    except (TypeError, ValueError):
        return default


def _fetch_single_financials(symbol: str) -> Dict[str, Any]:
    """
    获取单只股票最新报告期财务指标（PE/PB/ROE/股息率等）。
    东方财富 RPT_F10_FINANCE_MAINFINADATA 返回的列名可能为英文或中文，做兼容映射。
    """
    out: Dict[str, Any] = {
        "symbol": symbol,
        "pe_ttm": None,
        "pb": None,
        "roe": None,
        "dividend_yield": None,
        "report_date": None,
        "success": False,
    }
    if not AKSHARE_AVAILABLE:
        out["error"] = "AkShare 未安装"
        return out

    em_symbol = _to_em_symbol(symbol)
    df = None
    try:
        if hasattr(ak, "stock_financial_analysis_indicator_em"):
            df = ak.stock_financial_analysis_indicator_em(  # type: ignore[attr-defined]
                symbol=em_symbol,
                indicator="按报告期",
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("stock_financial_analysis_indicator_em %s 失败: %s", em_symbol, e)
        out["error"] = str(e)
        return out

    if df is None or df.empty:
        out["error"] = "无财务数据"
        return out

    # 取最新一行（按报告期通常已按时间排序，第一行或最后一行为最新）
    if len(df) == 0:
        out["error"] = "无报告期数据"
        return out

    # 东方财富 RPT_F10_FINANCE_MAINFINADATA 的返回顺序有时不是升序/降序的确定结构。
    # 这里优先按 report_date 最大值选取“最新报告期”，避免取到最旧数据（如 1993 年）。
    row = None
    try:
        import pandas as pd  # local import to keep module import lightweight

        report_date_col = None
        for col in ["REPORT_DATE", "报告期", "REPORT_DATE_CN", "report_date"]:
            if col in df.columns:
                report_date_col = col
                break

        if report_date_col is not None:
            parsed = pd.to_datetime(df[report_date_col], errors="coerce")
            if parsed.notna().any():
                idx = parsed.idxmax()
                row = df.loc[idx]
    except Exception:
        row = None

    # fallback：如果解析/排序失败，退回到最后一行
    if row is None:
        row = df.iloc[-1]

    # 列名可能是英文或中文，做多种可能键的映射
    col_map = {
        "pe_ttm": ["PE_TTM", "市盈率TTM", "市盈率(TTM)", "PE", "市盈率"],
        "pb": ["PB", "市净率", "PB_MRQ"],
        "roe": ["ROE", "净资产收益率", "ROE_WA", "加权平均净资产收益率"],
        "dividend_yield": ["DIVIDEND_YIELD", "股息率", "股息率TTM", "DIV_YIELD"],
        "report_date": ["REPORT_DATE", "报告期", "REPORT_DATE_CN"],
    }
    for out_key, candidates in col_map.items():
        for col in candidates:
            if col in df.columns:
                val = row.get(col)
                if out_key == "report_date":
                    out[out_key] = str(val) if val is not None else None
                else:
                    out[out_key] = _safe_float(val)
                break
        if out.get(out_key) is None and out_key != "report_date":
            out[out_key] = None

    out["success"] = True
    return out


def tool_fetch_stock_financials(
    symbols: Any,
    lookback_report_count: int = 1,
) -> Dict[str, Any]:
    """
    批量获取 A 股个股最新财务指标（PE/PB/ROE/股息率等），供量化选股 valuation 因子使用。

    Args:
        symbols: 股票代码，支持 "600000,000001" 或 ["600000","000001"]。
        lookback_report_count: 保留最近几个报告期（当前仅使用最新一期）。

    Returns:
        {
          "status": "success" | "error",
          "financials": [ { "symbol", "pe_ttm", "pb", "roe", "dividend_yield", "report_date", "success", "error?" }, ... ],
          "error": 可选总体错误信息
        }
    """
    sym_list = _normalize_symbols(symbols)
    if not sym_list:
        return {"status": "error", "error": "symbols 不能为空", "financials": []}

    financials: List[Dict[str, Any]] = []
    for s in sym_list:
        rec = _fetch_single_financials(s)
        financials.append(rec)

    return {
        "status": "success",
        "financials": financials,
        "lookback_report_count": lookback_report_count,
    }
