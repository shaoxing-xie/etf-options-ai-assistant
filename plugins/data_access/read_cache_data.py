"""
读取本地缓存数据的统一入口。

该模块被两类调用方使用：
- 作为 OpenClaw 工具（通过 tool_runner -> merged.read_market_data），要求返回 **JSON 可序列化** 的结果
- 作为分析模块的内部依赖（例如技术指标/风险评估），需要拿到 pandas DataFrame

因此提供 `return_df` 开关：工具侧默认 False，分析侧传 True。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _df_to_records(df) -> list[dict]:
    # 延迟 import，避免工具发现阶段引入 pandas 成本
    import pandas as pd  # type: ignore

    if df is None:
        return []
    if isinstance(df, pd.DataFrame) and df.empty:
        return []

    # 尽量把时间列转成字符串，避免 Timestamp 不可 JSON
    df2 = df.copy()
    for col in df2.columns:
        if pd.api.types.is_datetime64_any_dtype(df2[col]):
            df2[col] = df2[col].astype(str)
    return df2.to_dict(orient="records")


def _try_refill_minute_cache(
    *,
    data_type: str,
    symbol: str,
    period: str,
    start_date: str,
    end_date: str,
) -> Optional["pd.DataFrame"]:
    """
    当检测到分钟级缓存为部分命中或完全缺失时，尝试从数据源补齐并写回缓存。
    仅用于 index_minute / etf_minute。
    优先使用新浪 CN_MarketData.getKLineData（与 Coze 线上实现保持一致），
    如新浪失败再尝试东方财富 / akshare 路线（如果可用）。
    """
    try:
        # 延迟导入，避免在工具发现阶段引入重型依赖
        from src.data_collector import (  # type: ignore
            fetch_index_minute_sina,
            fetch_etf_minute_sina,
            fetch_index_minute_em,
            fetch_etf_minute_em,
        )
        import pandas as pd  # type: ignore
    except Exception:
        return None

    try:
        if data_type == "index_minute":
            # 优先尝试新浪指数分钟接口（与 Coze 成功案例一致，000300 -> sz399300 等映射）
            df: Optional[pd.DataFrame] = fetch_index_minute_sina(  # type: ignore
                symbol=symbol,
                period=str(period),
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or df.empty:  # type: ignore[attr-defined]
                # 新浪不可用时再退回东方财富 / akshare 路径（如果网络允许）
                df = fetch_index_minute_em(  # type: ignore
                    symbol=symbol,
                    period=str(period),
                    start_date=start_date,
                    end_date=end_date,
                )
        elif data_type == "etf_minute":
            # ETF 分钟同样优先使用新浪实现，其次再尝试东方财富 / akshare
            df = fetch_etf_minute_sina(  # type: ignore
                symbol=symbol,
                period=str(period),
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or df.empty:  # type: ignore[attr-defined]
                df = fetch_etf_minute_em(  # type: ignore
                    symbol=symbol,
                    period=str(period),
                    start_date=start_date,
                    end_date=end_date,
                )
        else:
            return None

        if df is None or df.empty:  # type: ignore[attr-defined]
            return None
        return df
    except Exception:
        # 补拉失败时静默降级，由调用方继续按“部分命中”处理
        return None


def _try_refill_daily_cache(
    *,
    data_type: str,
    symbol: str,
    start_date: str,
    end_date: str,
) -> None:
    """
    当检测到日线缓存缺失时，尝试从数据源补齐并写回缓存。
    仅用于 index_daily / etf_daily。
    """
    try:
        from src.data_collector import fetch_index_daily_em, fetch_etf_daily_em  # type: ignore
    except Exception:
        return
    try:
        if data_type == "index_daily":
            fetch_index_daily_em(symbol=symbol, start_date=start_date, end_date=end_date)  # type: ignore
        elif data_type == "etf_daily":
            fetch_etf_daily_em(symbol=symbol, start_date=start_date, end_date=end_date)  # type: ignore
    except Exception:
        return


def read_cache_data(
    *,
    data_type: str,
    symbol: str,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date: Optional[str] = None,
    use_closest: bool = True,
    return_df: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """
    从本地 parquet 缓存读取数据。

    Args:
        data_type: index_daily | index_minute | etf_daily | etf_minute | option_minute | option_greeks
        symbol: 指数/ETF/期权合约代码（统一用 symbol）
        period: 分钟周期（分钟类必须）
        start_date/end_date: 日线/分钟范围（YYYYMMDD）
        date: 期权 minute/greeks 的日期（YYYYMMDD 或 YYYYMMDD hh:mm:ss）
        use_closest: option_greeks 缓存缺失时是否回退到最近缓存日
        return_df: True 返回 pandas.DataFrame；False 返回 records 列表（工具输出更友好）
    """

    from src import data_cache

    dt = data_type
    sym = str(symbol)

    def ok(df=None, *, records=None, message: str = "cache hit", missing_dates=None) -> Dict[str, Any]:
        if return_df:
            return {
                "success": True,
                "message": message,
                "df": df,
                "missing_dates": missing_dates or [],
                "data_type": dt,
                "symbol": sym,
                "period": period,
            }
        recs = records if records is not None else _df_to_records(df)
        return {
            "success": True,
            "message": message,
            "data": {
                "data_type": dt,
                "symbol": sym,
                "period": period,
                "count": len(recs),
                "records": recs,
                "missing_dates": missing_dates or [],
            },
            "source": "cache",
        }

    def fail(message: str, *, missing_dates=None) -> Dict[str, Any]:
        if return_df:
            return {
                "success": False,
                "message": message,
                "df": None,
                "missing_dates": missing_dates or [],
                "data_type": dt,
                "symbol": sym,
                "period": period,
            }
        return {
            "success": False,
            "message": message,
            "data": {"data_type": dt, "symbol": sym, "period": period, "records": [], "count": 0},
            "source": "cache",
        }

    if dt in ("index_daily", "etf_daily"):
        if not start_date or not end_date:
            return fail("缺少 start_date/end_date")
        if dt == "index_daily":
            df, missing = data_cache.get_cached_index_daily(sym, start_date, end_date)
        else:
            df, missing = data_cache.get_cached_etf_daily(sym, start_date, end_date)
        if df is None or missing:
            # 尝试补拉一次（失败则继续按 miss/partial 返回）
            _try_refill_daily_cache(data_type=dt, symbol=sym, start_date=start_date, end_date=end_date)
            if dt == "index_daily":
                df, missing = data_cache.get_cached_index_daily(sym, start_date, end_date)
            else:
                df, missing = data_cache.get_cached_etf_daily(sym, start_date, end_date)
        if df is None:
            return fail(f"Cache miss (missing {len(missing)} dates)", missing_dates=missing)
        if missing:
            # 允许部分命中也返回 success=False，避免误用；同时仍返回已有数据供上层决定
            if return_df:
                return {
                    "success": False,
                    "message": f"Cache miss (missing {len(missing)} dates)",
                    "df": df,
                    "missing_dates": missing,
                    "data_type": dt,
                    "symbol": sym,
                    "period": period,
                }
            recs = _df_to_records(df)
            return {
                "success": False,
                "message": f"Cache miss (missing {len(missing)} dates)",
                "data": {
                    "data_type": dt,
                    "symbol": sym,
                    "period": period,
                    "count": len(recs),
                    "records": recs,
                    "missing_dates": missing,
                },
                "source": "cache_partial",
            }
        return ok(df, message="cache hit")

    if dt in ("index_minute", "etf_minute"):
        if not period:
            return fail("缺少 period（分钟周期）")
        if not start_date or not end_date:
            return fail("缺少 start_date/end_date（分钟数据需日期范围）")
        # 第一次尝试：直接读缓存
        if dt == "index_minute":
            df, missing = data_cache.get_cached_index_minute(sym, str(period), start_date, end_date)
        else:
            df, missing = data_cache.get_cached_etf_minute(sym, str(period), start_date, end_date)

        # 如果存在缺失日期，尝试从数据源补齐并写回缓存，再读一次
        if missing:
            refill_df = _try_refill_minute_cache(
                data_type=dt,
                symbol=sym,
                period=str(period),
                start_date=start_date,
                end_date=end_date,
            )
            if refill_df is not None:
                # 补拉成功后重新评估缓存覆盖情况
                if dt == "index_minute":
                    df2, missing2 = data_cache.get_cached_index_minute(sym, str(period), start_date, end_date)
                else:
                    df2, missing2 = data_cache.get_cached_etf_minute(sym, str(period), start_date, end_date)

                if df2 is not None and not missing2:
                    # 完全补齐，视为成功
                    return ok(df2, message="cache refreshed")

                # 仍然不完整，则回退到后续“部分命中”处理逻辑
                if df2 is not None:
                    df = df2
                # missing2 始终为列表（可能为空），优先采用最新结果
                missing = missing2

        # 经过一次或两次尝试后仍无数据
        if df is None:
            return fail(f"Cache miss (missing {len(missing)} dates)", missing_dates=missing)

        # 仍存在缺失日期：对调用方暴露为部分命中，同时保留已有数据
        if missing:
            if return_df:
                return {
                    "success": False,
                    "message": f"Cache miss (missing {len(missing)} dates) after refill attempt",
                    "df": df,
                    "missing_dates": missing,
                    "data_type": dt,
                    "symbol": sym,
                    "period": period,
                }
            recs = _df_to_records(df)
            return {
                "success": False,
                "message": f"Cache miss (missing {len(missing)} dates) after refill attempt",
                "data": {
                    "data_type": dt,
                    "symbol": sym,
                    "period": period,
                    "count": len(recs),
                    "records": recs,
                    "missing_dates": missing,
                },
                "source": "cache_partial",
            }

        # 分钟级数据缓存已完整命中
        return ok(df, message="cache hit")

    if dt == "option_minute":
        if not date:
            return fail("缺少 date（期权分钟K需指定日期）")
        df = data_cache.get_cached_option_minute(sym, date[:8], period=str(period) if period else None)
        if df is None:
            return fail("Cache miss")
        return ok(df, message="cache hit")

    if dt == "option_greeks":
        if not date:
            return fail("缺少 date（Greeks需指定日期）")
        df = data_cache.get_cached_option_greeks(sym, date, use_closest=use_closest)
        if df is None:
            return fail("Cache miss")
        return ok(df, message="cache hit")

    return fail(f"不支持的数据类型: {dt}")

