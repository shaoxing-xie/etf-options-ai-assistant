"""
合并工具：从缓存读取市场数据
支持 data_type 单类型 或 data_types 多类型一次请求。
data_type 枚举: index_daily | index_minute | etf_daily | etf_minute | option_minute | option_greeks
"""

from typing import Dict, Any, Optional, List


def _since_yyyymmdd(since: Optional[str]) -> Optional[str]:
    if since is None or str(since).strip() == "":
        return None
    s = str(since).strip().replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        return s[:8]
    return None


def _apply_since_floor(since_norm: Optional[str], start: Optional[str]) -> Optional[str]:
    if not since_norm:
        return start
    if not start:
        return since_norm
    return start if start >= since_norm else since_norm


def tool_read_market_data(
    data_type: Optional[str] = None,
    data_types: Optional[List[str]] = None,
    symbol: Optional[str] = None,
    contract_code: Optional[str] = None,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date: Optional[str] = None,
    since: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    从缓存读取市场数据。支持单类型（data_type）或多类型（data_types）一次请求。
    data_type / data_types 枚举: index_daily | index_minute | etf_daily | etf_minute | option_minute | option_greeks
    """
    from data_access.read_cache_data import read_cache_data
    from datetime import datetime, timedelta

    since_norm = _since_yyyymmdd(since)

    # 确定请求类型列表
    if data_types:
        types_to_fetch = list(data_types)
    elif data_type:
        types_to_fetch = [data_type]
    else:
        return {
            "success": False,
            "message": "请提供 data_type 或 data_types",
            "data": None
        }

    # 期权类型用 contract_code，其余用 symbol
    use_symbol = symbol or contract_code
    if not use_symbol and not (data_type in ("index_daily", "index_minute", "etf_daily", "etf_minute") and symbol):
        for t in types_to_fetch:
            if t in ("option_minute", "option_greeks") and not contract_code and not symbol:
                return {"success": False, "message": "option 类型需要 contract_code 或 symbol", "data": None}

    results = {}
    errors = []
    for dt in types_to_fetch:
        if dt in ("option_minute", "option_greeks"):
            sym = contract_code or symbol
            if not sym:
                errors.append(f"{dt}: 缺少 contract_code")
                continue
            if dt == "option_minute":
                out = read_cache_data(
                    data_type=dt,
                    symbol=sym,
                    period=period or "15",
                    date=date,
                    skip_online_refill=True,
                )
            else:
                out = read_cache_data(
                    data_type=dt,
                    symbol=sym,
                    date=date,
                    skip_online_refill=True,
                )
        else:
            if not symbol:
                sym = "000300" if "index" in dt else "510300"
            else:
                sym = symbol

            # 针对分钟级数据，如果未显式提供日期区间，则默认读取最近几天的数据，
            # 避免像 verify_data_pipeline 这类调用在 start_date/end_date 为 None 时直接失败。
            if dt in ("index_minute", "etf_minute"):
                effective_start = start_date
                effective_end = end_date
                if not effective_start and not effective_end and date:
                    effective_start = str(date)
                    effective_end = str(date)
                if not effective_start and not effective_end and not date:
                    today = datetime.now()
                    effective_end = today.strftime("%Y%m%d")
                    effective_start = (today - timedelta(days=5)).strftime("%Y%m%d")
                effective_start = _apply_since_floor(since_norm, effective_start)

                out = read_cache_data(
                    data_type=dt,
                    symbol=sym,
                    period=period or "5",
                    start_date=effective_start,
                    end_date=effective_end,
                    skip_online_refill=True,
                )
            else:
                effective_start = start_date
                effective_end = end_date
                if not effective_start and not effective_end and not date:
                    today = datetime.now()
                    effective_end = today.strftime("%Y%m%d")
                    effective_start = (today - timedelta(days=30)).strftime("%Y%m%d")
                effective_start = _apply_since_floor(since_norm, effective_start)
                out = read_cache_data(
                    data_type=dt,
                    symbol=sym,
                    start_date=effective_start,
                    end_date=effective_end,
                    skip_online_refill=True,
                )
        results[dt] = out
        if not out.get("success"):
            errors.append(f"{dt}: {out.get('message', '')}")

    if len(types_to_fetch) == 1:
        # 单类型：返回与原有工具一致的结构
        key = types_to_fetch[0]
        out = results.get(key, {})
        return out if out else {"success": False, "message": errors[0] if errors else "未知错误", "data": None}

    # 多类型：data 按类型分 key
    return {
        "success": len(errors) < len(types_to_fetch),
        "message": "多类型读取完成" if not errors else "; ".join(errors),
        "data": results
    }
