"""
获取指数实时数据
融合 Coze 插件 get_index_realtime.py
OpenClaw 插件工具
"""

import logging
import pandas as pd
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import os
import sys

logger = logging.getLogger(__name__)

# 导入交易日判断工具
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
utils_path = os.path.join(parent_dir, 'utils')
if utils_path not in sys.path:
    sys.path.insert(0, utils_path)

try:
    from plugins.utils.trading_day import check_trading_day_before_operation
    TRADING_DAY_CHECK_AVAILABLE = True
except ImportError:
    TRADING_DAY_CHECK_AVAILABLE = False
    def check_trading_day_before_operation(*args, **kwargs):
        return None

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False

try:
    from mootdx.quotes import Quotes
    MOOTDX_AVAILABLE = True
except Exception:  # noqa: BLE001
    MOOTDX_AVAILABLE = False


def _mootdx_bypass_time_frame_limit() -> None:
    """与股票实时通道一致：尽量绕过 tdxpy 交易时间限制（部分环境返回空与时段相关）。"""
    try:
        import tdxpy.hq as _tdx_hq  # type: ignore

        _tdx_hq.time_frame = lambda: True  # type: ignore[attr-defined]
    except Exception:
        pass


def _normalize_mootdx_code(c: Any) -> str:
    s = str(c).strip()
    if not s:
        return ""
    if "." in s:
        s = s.split(".", 1)[0]
    low = s.lower()
    if low.startswith(("sh", "sz")) and len(s) > 2:
        s = s[2:]
    return s


def _row_float_series(row: Any, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key not in row.index:
            continue
        try:
            v = row[key]
            if v is not None and str(v) != "nan" and str(v) != "":
                return float(v)
        except (TypeError, ValueError):
            continue
    return default


def _mootdx_index_quotes_batch(
    client: Any,
    index_codes: List[str],
) -> Dict[str, Dict[str, Any]]:
    """通达信 quotes：优先用于指数实时快照（列语义与股票实时一致）。"""
    out: Dict[str, Dict[str, Any]] = {}
    if not index_codes:
        return out
    try:
        df = client.quotes(symbol=index_codes)
    except Exception:
        return out
    if df is None or df.empty:
        return out
    code_series = df.get("code")
    if code_series is None:
        return out
    try:
        df_norm = code_series.astype(str).map(_normalize_mootdx_code)
    except Exception:
        return out
    want = set(index_codes)
    for code in index_codes:
        try:
            match = df[df_norm == code]
            if match.empty:
                continue
            row = match.iloc[0]
        except Exception:
            continue
        price = _row_float_series(row, "price", "last", default=0.0)
        open_p = _row_float_series(row, "open", default=0.0)
        high = _row_float_series(row, "high", default=0.0)
        low = _row_float_series(row, "low", default=0.0)
        prev_close = _row_float_series(row, "last_close", "pre_close", default=0.0)
        volume = int(_row_float_series(row, "vol", "volume", default=0.0))
        amount = _row_float_series(row, "amount", default=0.0)
        if price <= 0:
            continue
        change = (price - prev_close) if prev_close else 0.0
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0
        out[code] = {
            "current_price": price,
            "open": open_p,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "change": change,
            "change_percent": change_pct,
            "volume": float(volume),
            "amount": amount,
        }
    # 只返回请求中出现的代码
    return {k: v for k, v in out.items() if k in want}


def _mootdx_index_last_1m_bar(client: Any, index_code: str) -> Optional[Dict[str, Any]]:
    """
    1 分钟 K 最后一根作为盘中近似（frequency=7 与 index fetch_minute 一致）。
    不再使用日 K（frequency=9）充当「实时」。
    """
    try:
        df = client.bars(symbol=index_code, frequency=7, offset=64)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    try:
        last = df.iloc[-1]
    except Exception:
        return None
    close_price = _row_float_series(last, "close", "收盘", default=0.0)
    if close_price <= 0:
        return None
    open_price = _row_float_series(last, "open", "开盘", default=0.0)
    high = _row_float_series(last, "high", "最高", default=0.0)
    low = _row_float_series(last, "low", "最低", default=0.0)
    volume = _row_float_series(last, "vol", "volume", "成交量", default=0.0)
    amount = _row_float_series(last, "amount", "成交额", default=0.0)
    prev_close = 0.0
    if len(df) >= 2:
        prev = df.iloc[-2]
        prev_close = _row_float_series(prev, "close", "收盘", default=0.0)
    change = (close_price - prev_close) if prev_close else 0.0
    change_pct = (change / prev_close * 100.0) if prev_close else 0.0
    return {
        "current_price": close_price,
        "open": open_price,
        "high": high,
        "low": low,
        "prev_close": prev_close,
        "change": change,
        "change_percent": change_pct,
        "volume": volume,
        "amount": amount,
    }


def mootdx_index_quotes_only(index_codes_only: List[str]) -> Dict[str, Dict[str, Any]]:
    """仅 mootdx quotes（批量），不做 1 分钟兜底。"""
    if not MOOTDX_AVAILABLE or not index_codes_only:
        return {}
    _mootdx_bypass_time_frame_limit()
    try:
        client = Quotes.factory(market="std")
    except Exception:
        return {}
    try:
        return _mootdx_index_quotes_batch(client, index_codes_only)
    finally:
        try:
            client.close()
        except Exception:
            pass


def mootdx_index_1m_only(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """仅 mootdx 1 分钟 K 最后一根（在 quotes + AkShare 之后使用）。"""
    if not MOOTDX_AVAILABLE or not codes:
        return {}
    _mootdx_bypass_time_frame_limit()
    out: Dict[str, Dict[str, Any]] = {}
    try:
        client = Quotes.factory(market="std")
    except Exception:
        return {}
    try:
        for code in codes:
            one = _mootdx_index_last_1m_bar(client, code)
            if one is not None:
                out[code] = one
    finally:
        try:
            client.close()
        except Exception:
            pass
    return out


def _fetch_index_spot_df_cached(
    index_codes_only: List[str],
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    全量指数现货快照：新浪 -> 东财多表拼接。
    对单次全量拉取使用 realtime_full_fetch_cache（与 ETF 全量 spot 同级策略）。
    """
    if not AKSHARE_AVAILABLE or not index_codes_only:
        return None, None
    try:
        from src.realtime_full_fetch_cache import get_or_fetch
    except Exception:
        get_or_fetch = None  # type: ignore[assignment]

    def _sina() -> Any:
        return ak.stock_zh_index_spot_sina()

    try:
        df = get_or_fetch("ak.stock_zh_index_spot_sina", _sina) if get_or_fetch else _sina()
        if df is not None and not df.empty:
            return df, "stock_zh_index_spot_sina"
    except Exception:
        pass

    symbols_to_try: set[str] = set()
    for code in index_codes_only:
        if code.startswith("000"):
            symbols_to_try.update(["上证系列指数", "沪深重要指数", "中证系列指数"])
        elif code.startswith("399"):
            symbols_to_try.update(["深证系列指数", "沪深重要指数"])
        else:
            symbols_to_try.update(
                ["沪深重要指数", "上证系列指数", "深证系列指数", "中证系列指数"]
            )

    all_df: Optional[pd.DataFrame] = None
    for sym in sorted(symbols_to_try):

        def _em_fetch(symbol: str = sym) -> Any:
            return ak.stock_zh_index_spot_em(symbol=symbol)

        try:
            if get_or_fetch:
                temp_df = get_or_fetch(f"ak.stock_zh_index_spot_em:{sym}", _em_fetch)
            else:
                temp_df = _em_fetch()
            if temp_df is not None and not temp_df.empty:
                if all_df is None:
                    all_df = temp_df
                else:
                    all_df = pd.concat([all_df, temp_df], ignore_index=True)
        except Exception:
            continue

    if all_df is not None and not all_df.empty:
        return all_df, "stock_zh_index_spot_em"
    return None, None


def _series_safe_get(row: Any, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key not in row.index:
            continue
        try:
            value = row[key]
            if value is not None and str(value) != "nan" and str(value) != "":
                return float(value)
        except (ValueError, TypeError):
            continue
    return default


def _extract_index_snapshots_from_df(
    df: pd.DataFrame,
    codes_needed: List[str],
    index_mapping: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, Any]]:
    """从全量现货表中筛出所需指数，返回与 mootdx 同结构的 snap（不含 code/name）。"""
    code_col = None
    for col in ("代码", "code", "symbol"):
        if col in df.columns:
            code_col = col
            break
    if not code_col:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for index_code_item in codes_needed:
        if index_code_item not in index_mapping:
            continue
        index_info = index_mapping[index_code_item]
        possible_codes = [index_info["symbol"]]
        if index_code_item.startswith("399"):
            possible_codes.extend([f"sz{index_code_item}", index_code_item])
        else:
            possible_codes.extend([f"sh{index_code_item}", index_code_item])

        target_row = None
        for code_pattern in possible_codes:
            try:
                mask = df[code_col].astype(str).str.contains(
                    code_pattern, na=False, regex=False
                )
                if mask.any():
                    target_row = df[mask].iloc[0]
                    break
            except Exception:
                continue

        if target_row is None:
            continue

        row = target_row
        current_price = _series_safe_get(
            row,
            "最新价",
            "close",
            "price",
            "last",
            "当前价",
            "现价",
            default=0.0,
        )
        prev_close = _series_safe_get(
            row, "昨收", "pre_close", "preclose", "昨收价", default=0.0
        )
        change = _series_safe_get(row, "涨跌额", "change", "涨跌", default=0.0)
        change_percent = _series_safe_get(
            row, "涨跌幅", "pct_chg", "涨跌幅%", default=0.0
        )

        if prev_close != 0 and current_price != 0:
            if change == 0:
                change = current_price - prev_close
            if change_percent == 0:
                change_percent = (change / prev_close) * 100 if prev_close else 0.0

        open_price = _series_safe_get(
            row, "今开", "open", "开盘", "开盘价", default=0.0
        )
        high = _series_safe_get(row, "最高", "high", "最高价", default=0.0)
        low = _series_safe_get(row, "最低", "low", "最低价", default=0.0)
        volume = _series_safe_get(row, "成交量", "volume", "vol", default=0.0)
        amount = _series_safe_get(row, "成交额", "amount", "成交金额", default=0.0)

        if current_price <= 0:
            continue

        out[index_code_item] = {
            "current_price": current_price,
            "change": change,
            "change_percent": change_percent,
            "open": open_price,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": volume,
            "amount": amount,
        }
    return out


def fetch_index_realtime(
    index_code: str = "000001",  # 支持单个或多个（用逗号分隔）
    mode: str = "production",
    api_base_url: str = "http://localhost:5000",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取指数实时数据（融合 Coze get_index_realtime.py）
    
    Args:
        index_code: 指数代码，支持单个或多个（用逗号分隔），如 "000001" 或 "000300,000001"
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
        api_base_url: 原系统 API 基础地址
        api_key: API Key（如果未提供，从环境变量获取）
    
    Returns:
        Dict: 包含实时数据的字典
    """
    try:
        # ========== 首先判断是否是交易日 ==========
        if TRADING_DAY_CHECK_AVAILABLE and mode != "test":
            trading_day_check = check_trading_day_before_operation("获取指数实时数据")
            if trading_day_check:
                return trading_day_check
        # ========== 交易日判断结束 ==========
        
        # 解析指数代码（支持单个或多个，用逗号分隔）
        if isinstance(index_code, str):
            index_codes = [code.strip() for code in index_code.split(",") if code.strip()]
        elif isinstance(index_code, list):
            index_codes = [str(code).strip() for code in index_code if str(code).strip()]
        else:
            index_codes = [str(index_code).strip()]
        
        if not index_codes:
            return {
                'success': False,
                'message': '未提供有效的指数代码',
                'data': None
            }
        
        # ========== 自动识别 ETF 代码并调用对应的 ETF 函数 ==========
        # ETF代码通常以5或1开头（如510300, 159915），指数代码通常以000或399开头（如000300, 399001）
        etf_codes = [code for code in index_codes if code.startswith("5") or code.startswith("1")]
        index_codes_only = [code for code in index_codes if code not in etf_codes]
        etf_result = None
        
        if etf_codes:
            # 如果有ETF代码，自动调用ETF函数
            try:
                from plugins.data_collection.etf.fetch_realtime import fetch_etf_realtime
                logger.info(f"检测到 ETF 代码 {', '.join(etf_codes)}，自动调用 fetch_etf_realtime")
                etf_result = fetch_etf_realtime(
                    etf_code=",".join(etf_codes),
                    api_base_url=api_base_url,
                    api_key=api_key
                )
                # 如果只有ETF代码，直接返回ETF结果
                if not index_codes_only:
                    return etf_result
                # 如果还有指数代码，继续处理指数代码，然后合并结果
            except Exception as e:
                logger.warning(f"调用 fetch_etf_realtime 失败: {e}，继续处理指数代码")
                etf_result = None
        # ========== ETF 代码处理结束 ==========
        
        # 如果没有指数代码，直接返回ETF结果（如果有）
        if not index_codes_only:
            if etf_codes and etf_result:
                return etf_result
            else:
                return {
                    'success': False,
                    'message': '未提供有效的指数代码',
                    'data': None
                }
        
        # 指数代码映射（复用 Coze 插件的映射）
        index_mapping = {
            "000001": {"name": "上证指数", "symbol": "sh000001"},
            "399001": {"name": "深证成指", "symbol": "sz399001"},
            "399006": {"name": "创业板指", "symbol": "sz399006"},
            "000300": {"name": "沪深300", "symbol": "sh000300"},
            "000016": {"name": "上证50", "symbol": "sh000016"},
            "000905": {"name": "中证500", "symbol": "sh000905"},
            "000852": {"name": "中证1000", "symbol": "sh000852"},
        }
        
        # 验证所有指数代码
        invalid_codes = []
        for code in index_codes_only:
            if code not in index_mapping:
                invalid_codes.append(code)
        
        if invalid_codes:
            return {
                'success': False,
                'message': f'不支持的指数代码: {", ".join(invalid_codes)}',
                'supported_codes': list(index_mapping.keys()),
                'data': None
            }
        
        # ====== 顺序：mootdx quotes（批量）-> AkShare 全量现货快照（短缓存）-> mootdx 1 分钟 K ======
        if not AKSHARE_AVAILABLE and not MOOTDX_AVAILABLE:
            return {
                "success": False,
                "message": "需要 mootdx 或 akshare 至少其一。请 pip install akshare 与/或 mootdx。",
                "data": None,
            }

        quotes_map: Dict[str, Dict[str, Any]] = (
            mootdx_index_quotes_only(index_codes_only) if MOOTDX_AVAILABLE else {}
        )

        if len(quotes_map) == len(index_codes_only):
            index_rows: List[Dict[str, Any]] = []
            for code in index_codes_only:
                base = index_mapping[code]
                index_rows.append(
                    {
                        "code": code,
                        "name": base["name"],
                        **quotes_map[code],
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            results = index_rows
            if etf_codes and etf_result and etf_result.get("success"):
                etf_data = etf_result.get("data", {})
                if isinstance(etf_data, list):
                    results = results + etf_data
                elif isinstance(etf_data, dict):
                    results = results + [etf_data]
            return {
                "success": True,
                "message": "Successfully fetched index realtime data via mootdx (quotes)",
                "data": results[0] if len(results) == 1 else results,
                "source": "mootdx",
                "count": len(results),
            }

        missing_after_quotes = [c for c in index_codes_only if c not in quotes_map]
        ak_snap: Dict[str, Dict[str, Any]] = {}
        ak_label: Optional[str] = None
        if missing_after_quotes and AKSHARE_AVAILABLE:
            df_ak, ak_label = _fetch_index_spot_df_cached(index_codes_only)
            if df_ak is not None and not df_ak.empty:
                ak_snap = _extract_index_snapshots_from_df(
                    df_ak, missing_after_quotes, index_mapping
                )

        missing_after_ak = [c for c in missing_after_quotes if c not in ak_snap]
        bars_map: Dict[str, Dict[str, Any]] = (
            mootdx_index_1m_only(missing_after_ak)
            if (missing_after_ak and MOOTDX_AVAILABLE)
            else {}
        )

        per_code_sources: List[str] = []
        index_results: List[Dict[str, Any]] = []
        used_fallback = False
        for code in index_codes_only:
            base = index_mapping[code]
            snap: Optional[Dict[str, Any]] = None
            tag: Optional[str] = None
            if code in quotes_map:
                snap = quotes_map[code]
                tag = "mootdx"
            elif code in ak_snap:
                snap = ak_snap[code]
                tag = ak_label or "akshare"
            elif code in bars_map:
                snap = bars_map[code]
                tag = "mootdx_1m"
            else:
                index_results.append(_get_fallback_data(code, index_mapping)["data"])
                per_code_sources.append("fallback")
                used_fallback = True
                continue
            index_results.append(
                {
                    "code": code,
                    "name": base["name"],
                    **snap,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
            per_code_sources.append(tag or "unknown")

        results = index_results
        if etf_codes and etf_result and etf_result.get("success"):
            etf_data = etf_result.get("data", {})
            if isinstance(etf_data, list):
                results = results + etf_data
            elif isinstance(etf_data, dict):
                results = results + [etf_data]

        uniq = sorted(set(per_code_sources))
        source_out = uniq[0] if len(uniq) == 1 else "mixed:" + ",".join(uniq)

        ret: Dict[str, Any] = {
            "success": True,
            "message": "Successfully fetched index realtime data",
            "data": results[0] if len(results) == 1 else results,
            "source": source_out,
            "count": len(results),
        }
        if used_fallback:
            ret["is_fallback"] = True
        return ret
    
    except Exception as e:
        return {
            'success': False,
            'message': f'Error: {str(e)}',
            'data': None
        }


def _get_fallback_data(index_code: str, index_mapping: Dict) -> Dict[str, Any]:
    """返回降级数据"""
    index_info = index_mapping.get(index_code, {"name": "未知指数"})
    
    return {
        "success": True,
        "data": {
            "code": index_code,
            "name": index_info.get('name', '未知'),
            "current_price": 0,
            "change": 0,
            "change_percent": 0,
            "message": "数据暂时不可用，请稍后重试"
        },
        "source": "fallback",
        "is_fallback": True
    }


# OpenClaw 工具函数接口
def tool_fetch_index_realtime(
    index_code: str = "000001",
    mode: str = "production"
) -> Dict[str, Any]:
    """
    OpenClaw 工具：获取指数实时数据
    
    Args:
        index_code: 指数代码，支持单个或多个（用逗号分隔）
        mode: 运行模式，"production"（默认，检查交易日）或 "test"（跳过检查）
    """
    return fetch_index_realtime(index_code=index_code, mode=mode)
